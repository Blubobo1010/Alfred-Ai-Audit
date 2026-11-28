"""Outlook draft approval over Telegram: every new draft in one mailbox waits for a human tap.

A ``no_agent`` cron job runs ``poll`` every minute. Each new draft in the mailbox's Drafts folder,
whoever created it, gets a Telegram preview with three buttons:

- ``✅ Invia``   -> ``gt:send:<ref>``    -> ``scripts/gmail-triage/send-draft.sh <ref>`` -> ``send``
- ``🗑 Scarta``  -> ``gt:archive:<ref>`` -> ``scripts/gmail-triage/archive.sh <ref>``    -> ``discard``
- ``✏️ Modifica in Outlook`` -> the draft's ``webLink`` (a URL button, no callback)

The ``gt:`` callbacks are the Telegram adapter's existing script-dispatch buttons
(``plugins/platforms/telegram/adapter.py::_GT_VERB_DISPATCH``): the adapter checks that the tapper is an
authorized bot user, runs the script, and on exit 0 appends the outcome and strips the keyboard. That is
why this plugin needs no core change. Mail sent any other way (cron follow-ups via ``sendMail``) never
lands in Drafts and is not affected.

Invariant: the button sends exactly the version the preview showed. ``send`` refuses when the draft's
``lastModifiedDateTime`` differs from the one rendered, refreshes the preview, and asks for a new tap.

Run as a script (``python drafts.py poll|send REF|discard REF|status``) by the cron job and the button
scripts, whose environment is scrubbed of secrets: credentials come from ``$HERMES_HOME/.env``.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import quote

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TELEGRAM_BASE = "https://api.telegram.org"
# Immutable ids survive edits and folder moves, so a ref stays valid for the life of the draft.
PREFER_IMMUTABLE = 'IdType="ImmutableId"'
PREFER_TEXT_BODY = 'outlook.body-content-type="text"'
LIST_FIELDS = "id,subject,toRecipients,ccRecipients,bccRecipients,lastModifiedDateTime,webLink"
CALLBACK_SEND, CALLBACK_DISCARD = "gt:send:", "gt:archive:"
TELEGRAM_TEXT_LIMIT = 4096
SENDING_STALE_SECONDS = 300
PRUNE_AFTER_SECONDS = 30 * 86400
STATE_VERSION = 1

# User-visible copy (the customer works in Italian). Button-script failures surface as a Telegram toast
# showing the last stderr line cut to 80 chars, so every FAIL_* message stays under that.
TEXT = {
    "header": "📝 Bozza da approvare · #{ref}",
    "updated": "🔄 Aggiornata: ricontrolla prima di inviare.",
    "updated_by_agent": "✏️ Modificata su tua richiesta: ricontrolla prima di inviare.",
    "to": "A", "cc": "Cc", "bcc": "Ccn", "subject": "Oggetto",
    "no_subject": "(senza oggetto)", "no_recipients": "(nessun destinatario)", "no_body": "(testo vuoto)",
    "truncated": "… (testo completo in Outlook)",
    "edit_hint": "✏️ Per modificarla aprila in Outlook, oppure rispondi a questo messaggio dicendo cosa cambiare.",
    "gone": "📭 Bozza #{ref} «{subject}» non è più tra le bozze di Outlook (inviata o eliminata da lì).",
    "btn_send": "✅ Invia", "btn_discard": "🗑 Scarta", "btn_edit": "✏️ Modifica in Outlook",
    "FAIL_unknown": "Bozza #{ref} sconosciuta",
    "FAIL_done": "Bozza #{ref} già gestita ({status})",
    "FAIL_gone": "La bozza non esiste più in Outlook",
    "FAIL_changed": "Bozza cambiata: anteprima aggiornata, ricontrolla e premi Invia",
    "FAIL_no_recipients": "La bozza non ha destinatari: aggiungili in Outlook",
    "FAIL_send": "Invio non riuscito: {detail}",
    "FAIL_discard": "Eliminazione non riuscita: {detail}",
}


class DraftsError(RuntimeError):
    """Expected failure with a user-facing message (printed to stderr, exit 1)."""


class ConfigError(DraftsError):
    pass


class GraphError(DraftsError):
    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status

    @property
    def ambiguous(self) -> bool:
        """The request may have been applied (transport failure or server error)."""
        return self.status is None or self.status >= 500


class TelegramError(DraftsError):
    pass


# --------------------------------------------------------------------------------------------- config


@dataclass(frozen=True)
class Settings:
    mailbox: str
    chat_id: str
    thread_id: str | None = None
    settle_seconds: int = 120
    max_body_chars: int = 1500
    announce_existing: bool = False
    certificate_dir: str = ""


# alfred-m365 (the Outlook plugin) owns the Entra app and its certificate: same app, same files, no second login.
M365_PLUGIN = "alfred-m365"
CERT_KEY_FILE, CERT_FILE = "alfred-m365-key.pem", "alfred-m365.cer"


def _m365_settings(config: dict[str, Any]) -> dict[str, Any]:
    entry = ((config.get("plugins") or {}).get("entries") or {}).get(M365_PLUGIN) or {}
    return entry.get("settings") or {}


def load_settings(config: dict[str, Any] | None = None) -> Settings:
    """``outlook_drafts:`` section of config.yaml (behaviour lives there, secrets in .env)."""
    if config is None:
        from hermes_cli.config import load_config_readonly
        config = load_config_readonly()
    section, m365 = config.get("outlook_drafts") or {}, _m365_settings(config)
    mailbox = str(section.get("mailbox") or m365.get("mailbox") or "").strip()
    chat_id = str(section.get("telegram_chat_id") or "").strip()
    if not mailbox or not chat_id:
        raise ConfigError("Set outlook_drafts.telegram_chat_id (and the mailbox, here or in alfred-m365) in config.yaml")
    thread_id = str(section.get("telegram_thread_id") or "").strip() or None
    return Settings(
        mailbox=mailbox, chat_id=chat_id, thread_id=thread_id,
        settle_seconds=max(0, int(section.get("settle_seconds", 120))),
        max_body_chars=min(3000, max(200, int(section.get("max_body_chars", 1500)))),
        announce_existing=bool(section.get("announce_existing", False)),
        certificate_dir=str(section.get("certificate_dir") or m365.get("certificate_dir") or "").strip())


def read_secret(name: str) -> str:
    from hermes_cli.config import get_env_value_prefer_dotenv
    return (get_env_value_prefer_dotenv(name) or "").strip()


def hermes_home() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home())


@dataclass(frozen=True)
class Credentials:
    """App-only Entra credential: the certificate made by ``alfred outlook keygen`` (preferred: IT holds only
    the public .cer) or, as a fallback, ``MSGRAPH_CLIENT_SECRET``."""

    tenant_id: str
    client_id: str
    client_secret: str = ""
    certificate_dir: Path | None = None
    authority_url: str = "https://login.microsoftonline.com"
    scope: str = "https://graph.microsoft.com/.default"

    @property
    def token_url(self) -> str:
        return f"{self.authority_url.rstrip('/')}/{quote(self.tenant_id, safe='')}/oauth2/v2.0/token"

    def token_fields(self) -> dict[str, str]:
        fields = {"grant_type": "client_credentials", "client_id": self.client_id, "scope": self.scope}
        if self.client_secret:
            fields["client_secret"] = self.client_secret
        else:
            fields["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            fields["client_assertion"] = client_assertion(self.certificate_dir, self.client_id, self.token_url)
        return fields


def certificate_dir(settings: Settings) -> Path:
    return Path(settings.certificate_dir).expanduser() if settings.certificate_dir else hermes_home() / M365_PLUGIN


def load_credentials(settings: Settings) -> Credentials:
    tenant, client = read_secret("MSGRAPH_TENANT_ID"), read_secret("MSGRAPH_CLIENT_ID")
    if not tenant or not client:
        raise ConfigError("MSGRAPH_TENANT_ID and MSGRAPH_CLIENT_ID are not set")
    secret, certs = read_secret("MSGRAPH_CLIENT_SECRET"), certificate_dir(settings)
    if not secret and not ((certs / CERT_KEY_FILE).is_file() and (certs / CERT_FILE).is_file()):
        raise ConfigError(f"no MSGRAPH_CLIENT_SECRET and no certificate in {certs} (run `plushuman outlook keygen`)")
    return Credentials(tenant_id=tenant, client_id=client, client_secret=secret, certificate_dir=certs,
                       authority_url=read_secret("MSGRAPH_AUTHORITY_URL") or Credentials.authority_url,
                       scope=read_secret("MSGRAPH_SCOPE") or Credentials.scope)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def client_assertion(directory: Path | None, client_id: str, token_url: str) -> str:
    """RS256 JWT (RFC 7523) signed with the alfred-m365 key: aud = token URL, iss = sub = client id, 10 minutes.
    Same construction as alfred-m365's ``certauth.client_assertion`` (Entra matches ``x5t`` to the uploaded .cer)."""
    import uuid

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    if directory is None:
        raise ConfigError("no certificate directory")
    try:
        key = serialization.load_pem_private_key((directory / CERT_KEY_FILE).read_bytes(), password=None)
        der = x509.load_pem_x509_certificate((directory / CERT_FILE).read_bytes()).public_bytes(serialization.Encoding.DER)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read the certificate in {directory}: {type(exc).__name__}") from None
    header = {"alg": "RS256", "typ": "JWT", "x5t": _b64url(hashlib.sha1(der).digest()),  # SHA-1: Entra's x5t
              "x5t#S256": _b64url(hashlib.sha256(der).digest())}
    now = int(time.time())
    claims = {"aud": token_url, "iss": client_id, "sub": client_id, "jti": str(uuid.uuid4()),
              "nbf": now - 60, "iat": now, "exp": now + 600}
    signing_input = ".".join(_b64url(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims))
    signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


# ---------------------------------------------------------------------------------------------- state


class Store:
    """``$HERMES_HOME/outlook_drafts/state.json`` under an exclusive file lock.

    Every command holds the lock for its whole run, so a poll and a button tap (or two taps) never
    interleave: a draft is announced once and sent at most once."""

    def __init__(self, root: Path) -> None:
        self.dir = root / "outlook_drafts"
        self.path = self.dir / "state.json"
        self.lock_path = self.dir / ".lock"

    @contextlib.contextmanager
    def locked(self) -> Iterator[dict[str, Any]]:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+") as lock_file:
            _lock_file(lock_file)
            state = self._read()
            try:
                yield state
            finally:
                # Saved on failure too: a refreshed preview or a "gone" mark must not be repeated.
                self.save(state)

    def _read(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            state = {}
        state.setdefault("version", STATE_VERSION)
        state.setdefault("baseline_done", False)
        state.setdefault("drafts", {})
        return state

    def save(self, state: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


def _lock_file(handle) -> None:
    try:
        import fcntl
    except ImportError:  # Windows: msvcrt locks a byte range of the lock file.
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def make_ref(graph_id: str, taken: dict[str, Any]) -> str:
    """Short, stable reference for a draft: fits Telegram's 64-byte callback_data and is easy to say."""
    digest = base64.b32encode(hashlib.sha256(graph_id.encode("utf-8")).digest()).decode("ascii")
    for length in (6, 8, 10, 12):
        ref = digest[:length]
        if ref not in taken or taken[ref].get("graph_id") == graph_id:
            return ref
    raise DraftsError("could not allocate a draft reference")


def normalize_ref(ref: str) -> str:
    return str(ref or "").strip().lstrip("#").upper()


# ---------------------------------------------------------------------------------------------- Graph


class Graph:
    """Minimal synchronous Microsoft Graph client for one mailbox (app-only credentials)."""

    def __init__(self, mailbox: str, *, credentials: Credentials, transport: httpx.BaseTransport | None = None,
                 timeout: float = 30.0, sleep: Callable[[float], None] = time.sleep) -> None:
        self.mailbox = mailbox
        self._credentials = credentials
        self._client = httpx.Client(timeout=timeout, transport=transport)
        self._sleep = sleep
        self._token: tuple[str, float] | None = None

    def _access_token(self, *, refresh: bool = False) -> str:
        if self._token and not refresh and self._token[1] - 120 > time.time():
            return self._token[0]
        creds = self._credentials
        try:
            response = self._client.post(creds.token_url, data=creds.token_fields())
        except httpx.HTTPError as exc:
            raise GraphError(None, f"token request failed: {exc}") from exc
        if response.status_code >= 400:
            raise GraphError(response.status_code, f"token request failed: HTTP {response.status_code} "
                                                   f"{_token_error_code(response)}".rstrip())
        payload = response.json()
        self._token = (payload["access_token"], time.time() + int(payload.get("expires_in", 3600)))
        return self._token[0]

    def _user_path(self, suffix: str) -> str:
        return f"{GRAPH_BASE}/users/{quote(self.mailbox, safe='')}{suffix}"

    def _message_path(self, message_id: str, suffix: str = "") -> str:
        return self._user_path(f"/messages/{quote(message_id, safe='')}{suffix}")

    def request(self, method: str, url: str, *, params: dict | None = None, json_body: Any = None,
                prefer: tuple[str, ...] = (PREFER_IMMUTABLE,), idempotent: bool = True) -> httpx.Response:
        """One Graph call. 401 refreshes the token and 429 waits ``Retry-After``: neither was applied.
        A 5xx or transport error is retried only for idempotent calls: a non-idempotent call
        (``send``) must never be replayed blindly, or the recipient gets the mail twice."""
        refreshed = False
        for attempt in range(4):
            headers = {"Authorization": f"Bearer {self._access_token(refresh=refreshed)}"}
            if prefer:
                headers["Prefer"] = ", ".join(prefer)
            try:
                response = self._client.request(method, url, params=params, json=json_body, headers=headers)
            except httpx.HTTPError as exc:
                if idempotent and attempt < 3:
                    self._sleep(2 ** attempt)
                    continue
                raise GraphError(None, f"Graph {method} failed: {exc}") from exc
            status = response.status_code
            if status < 400:
                return response
            if status == 401 and not refreshed:
                refreshed = True
                continue
            if attempt < 3 and (status == 429 or (idempotent and status >= 500)):
                self._sleep(min(10.0, _retry_after(response, attempt)))
                continue
            raise GraphError(status, _graph_error_detail(response))
        raise GraphError(None, f"Graph {method} exhausted retries")

    def list_drafts(self) -> list[dict[str, Any]]:
        url: str | None = self._user_path("/mailFolders/drafts/messages")
        params: dict | None = {"$select": LIST_FIELDS, "$top": "50"}
        items: list[dict[str, Any]] = []
        while url:
            payload = self.request("GET", url, params=params).json()
            items.extend(payload.get("value") or [])
            url, params = payload.get("@odata.nextLink"), None
        return items

    def get_draft(self, message_id: str) -> dict[str, Any] | None:
        """Full draft with a plain-text body, or None when it no longer exists or is no longer a draft."""
        try:
            message = self.request("GET", self._message_path(message_id),
                                   params={"$select": LIST_FIELDS + ",body,isDraft"},
                                   prefer=(PREFER_IMMUTABLE, PREFER_TEXT_BODY)).json()
        except GraphError as exc:
            if exc.status == 404:
                return None
            raise
        return message if message.get("isDraft", True) else None

    def update_draft(self, message_id: str, patch: dict[str, Any]) -> None:
        self.request("PATCH", self._message_path(message_id), json_body=patch)

    def send_draft(self, message_id: str) -> None:
        self.request("POST", self._message_path(message_id, "/send"), idempotent=False)

    def delete_draft(self, message_id: str) -> None:
        """Moves the draft to Deleted Items (recoverable from Outlook)."""
        try:
            self.request("DELETE", self._message_path(message_id))
        except GraphError as exc:
            if exc.status != 404:
                raise


def _token_error_code(response: httpx.Response) -> str:
    """Entra's AADSTS code (e.g. AADSTS700027 = certificate not uploaded): never the description, which echoes input."""
    try:
        codes = response.json().get("error_codes") or []
    except ValueError:
        return ""
    return f"AADSTS{codes[0]}" if codes else ""


def _retry_after(response: httpx.Response, attempt: int) -> float:
    try:
        return float(response.headers.get("Retry-After", ""))
    except ValueError:
        return float(2 ** attempt)


def _graph_error_detail(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
        detail = error.get("code") or error.get("message")
    except ValueError:
        detail = None
    return f"HTTP {response.status_code}" + (f" {detail}" if detail else "")


# ------------------------------------------------------------------------------------------- Telegram


class Telegram:
    def __init__(self, token: str, chat_id: str, thread_id: str | None = None, *,
                 transport: httpx.BaseTransport | None = None, timeout: float = 20.0) -> None:
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN is not set")
        self._base = f"{TELEGRAM_BASE}/bot{token}"
        self.chat_id, self.thread_id = chat_id, thread_id
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(f"{self._base}/{method}", json=payload)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(f"Telegram {method} failed: {type(exc).__name__}") from exc
        if not body.get("ok"):
            description = str(body.get("description") or "")
            if "message is not modified" in description:
                return {}
            raise TelegramError(f"Telegram {method} failed: {description[:120]}")
        return body.get("result") or {}

    def send(self, text: str, markup: dict[str, Any]) -> int:
        payload = {"chat_id": self.chat_id, "text": text, "reply_markup": markup,
                   "link_preview_options": {"is_disabled": True}}
        if self.thread_id:
            payload["message_thread_id"] = int(self.thread_id)
        return int(self._call("sendMessage", payload)["message_id"])

    def edit(self, message_id: int, text: str, markup: dict[str, Any] | None) -> None:
        self._call("editMessageText", {
            "chat_id": self.chat_id, "message_id": message_id, "text": text,
            "reply_markup": markup or {"inline_keyboard": []},
            "link_preview_options": {"is_disabled": True}})


# -------------------------------------------------------------------------------------------- render


def _addresses(recipients: list[dict[str, Any]] | None) -> str:
    parts = []
    for recipient in recipients or []:
        email = recipient.get("emailAddress") or {}
        address, name = (email.get("address") or "").strip(), (email.get("name") or "").strip()
        parts.append(f"{name} <{address}>" if name and name != address else address or name)
    return ", ".join(p for p in parts if p)


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_card(draft: dict[str, Any], ref: str, settings: Settings, *, note: str = "") -> str:
    lines = [TEXT["header"].format(ref=ref)]
    if note:
        lines.append(note)
    lines.append("")
    lines.append(f"{TEXT['to']}: {_cap(_addresses(draft.get('toRecipients')) or TEXT['no_recipients'], 400)}")
    for key, field in (("cc", "ccRecipients"), ("bcc", "bccRecipients")):
        if value := _addresses(draft.get(field)):
            lines.append(f"{TEXT[key]}: {_cap(value, 400)}")
    lines.append(f"{TEXT['subject']}: {_cap((draft.get('subject') or '').strip() or TEXT['no_subject'], 300)}")
    body = re.sub(r"\n{3,}", "\n\n", ((draft.get("body") or {}).get("content") or "").replace("\r\n", "\n")).strip()
    if len(body) > settings.max_body_chars:
        body = body[: settings.max_body_chars].rstrip() + "\n" + TEXT["truncated"]
    lines += ["", body or TEXT["no_body"], "", TEXT["edit_hint"]]
    return _cap("\n".join(lines), TELEGRAM_TEXT_LIMIT)


def keyboard(ref: str, web_link: str | None) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = [[
        {"text": TEXT["btn_send"], "callback_data": CALLBACK_SEND + ref},
        {"text": TEXT["btn_discard"], "callback_data": CALLBACK_DISCARD + ref}]]
    if web_link and web_link.startswith("https://"):
        rows.append([{"text": TEXT["btn_edit"], "url": web_link}])
    return {"inline_keyboard": rows}


# ---------------------------------------------------------------------------------------------- logic


def _parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp()


def _settled(draft: dict[str, Any], settings: Settings, now: float) -> bool:
    """Outlook autosaves a draft while someone is still typing it: wait until it stops changing."""
    modified = _parse_time(draft.get("lastModifiedDateTime"))
    return modified is None or now - modified >= settings.settle_seconds


@dataclass
class Drafts:
    """The commands, over injected collaborators (tests pass fakes, ``from_runtime`` the real ones)."""

    store: Store
    graph: Graph
    telegram: Telegram
    settings: Settings
    clock: Callable[[], float] = time.time

    @classmethod
    def from_runtime(cls) -> Drafts:
        settings = load_settings()
        return cls(store=Store(hermes_home()), graph=Graph(settings.mailbox, credentials=load_credentials(settings)),
                   telegram=Telegram(read_secret("TELEGRAM_BOT_TOKEN"), settings.chat_id, settings.thread_id),
                   settings=settings)

    # --- poll

    def poll(self) -> dict[str, int]:
        counts = {"announced": 0, "updated": 0, "gone": 0}
        with self.store.locked() as state:
            now, entries = self.clock(), state["drafts"]
            drafts = {d["id"]: d for d in self.graph.list_drafts() if d.get("id")}
            if not state["baseline_done"]:
                state["baseline_done"] = True
                if not self.settings.announce_existing:
                    # Drafts already sitting in the folder at install time are not flooded into the chat.
                    for graph_id, draft in drafts.items():
                        entries[make_ref(graph_id, entries)] = {
                            "graph_id": graph_id, "status": "ignored",
                            "last_modified": draft.get("lastModifiedDateTime"), "updated_at": now}
                    return counts
            by_graph_id = {entry["graph_id"]: ref for ref, entry in entries.items()}
            for graph_id, listed in drafts.items():
                ref = by_graph_id.get(graph_id)
                entry = entries.get(ref) if ref else None
                changed = entry is not None and entry.get("last_modified") != listed.get("lastModifiedDateTime")
                if entry is not None and entry["status"] == "sending" and now - entry.get("updated_at", 0) > SENDING_STALE_SECONDS:
                    entry["status"] = "pending"  # a send that crashed mid-way and left the draft in place
                if entry is None or (entry["status"] == "ignored" and changed):
                    if _settled(listed, self.settings, now) and self._announce(entries, graph_id, now):
                        counts["announced"] += 1
                elif entry["status"] == "pending" and changed and _settled(listed, self.settings, now):
                    if self._refresh(ref, entry, TEXT["updated"], now):
                        counts["updated"] += 1
            for ref, entry in entries.items():
                if entry["status"] in ("pending", "sending") and entry["graph_id"] not in drafts:
                    self._mark_gone(ref, entry, now)
                    counts["gone"] += 1
            self._prune(entries, drafts, now)
        return counts

    def _announce(self, entries: dict[str, Any], graph_id: str, now: float) -> bool:
        draft = self.graph.get_draft(graph_id)
        if draft is None:
            return False
        ref = make_ref(graph_id, entries)
        message_id = self.telegram.send(render_card(draft, ref, self.settings), keyboard(ref, draft.get("webLink")))
        entries[ref] = {"graph_id": graph_id, "status": "pending", "message_id": message_id,
                        "last_modified": draft.get("lastModifiedDateTime"), "web_link": draft.get("webLink"),
                        "subject": (draft.get("subject") or "")[:200], "announced_at": now, "updated_at": now}
        return True

    def _refresh(self, ref: str, entry: dict[str, Any], note: str, now: float) -> dict[str, Any] | None:
        """Re-render the preview from Graph's current version; returns the draft, None if it is gone."""
        draft = self.graph.get_draft(entry["graph_id"])
        if draft is None:
            self._mark_gone(ref, entry, now)
            return None
        self.telegram.edit(entry["message_id"], render_card(draft, ref, self.settings, note=note),
                           keyboard(ref, draft.get("webLink")))
        entry.update(last_modified=draft.get("lastModifiedDateTime"), subject=(draft.get("subject") or "")[:200],
                     updated_at=now)
        return draft

    def _mark_gone(self, ref: str, entry: dict[str, Any], now: float) -> None:
        entry.update(status="gone", updated_at=now)
        if entry.get("message_id"):
            with contextlib.suppress(TelegramError):
                self.telegram.edit(entry["message_id"], TEXT["gone"].format(
                    ref=ref, subject=entry.get("subject") or TEXT["no_subject"]), None)

    @staticmethod
    def _prune(entries: dict[str, Any], drafts: dict[str, Any], now: float) -> None:
        for ref in list(entries):
            entry = entries[ref]
            vanished = entry["status"] == "ignored" and entry["graph_id"] not in drafts
            expired = (entry["status"] in ("sent", "discarded", "gone")
                       and now - entry.get("updated_at", now) > PRUNE_AFTER_SECONDS)
            if vanished or expired:
                del entries[ref]

    # --- button actions

    def _pending_entry(self, state: dict[str, Any], ref: str) -> dict[str, Any]:
        entry = state["drafts"].get(ref)
        if entry is None:
            raise DraftsError(TEXT["FAIL_unknown"].format(ref=ref))
        if entry["status"] != "pending":
            raise DraftsError(TEXT["FAIL_done"].format(ref=ref, status=entry["status"]))
        return entry

    def send(self, ref: str) -> None:
        ref = normalize_ref(ref)
        with self.store.locked() as state:
            entry, now = self._pending_entry(state, ref), self.clock()
            draft = self.graph.get_draft(entry["graph_id"])
            if draft is None:
                self._mark_gone(ref, entry, now)
                raise DraftsError(TEXT["FAIL_gone"])
            if draft.get("lastModifiedDateTime") != entry.get("last_modified"):
                self._refresh(ref, entry, TEXT["updated"], now)
                raise DraftsError(TEXT["FAIL_changed"])
            if not any(draft.get(f) for f in ("toRecipients", "ccRecipients", "bccRecipients")):
                raise DraftsError(TEXT["FAIL_no_recipients"])
            entry.update(status="sending", updated_at=now)
            self.store.save(state)
            try:
                self.graph.send_draft(entry["graph_id"])
            except GraphError as exc:
                # Ambiguous outcome: a draft that left the Drafts folder was sent; never resend blindly.
                if exc.ambiguous and self.graph.get_draft(entry["graph_id"]) is None:
                    entry.update(status="sent", updated_at=self.clock())
                    return
                entry.update(status="pending", updated_at=self.clock())
                raise DraftsError(TEXT["FAIL_send"].format(detail=str(exc)[:40])) from exc
            entry.update(status="sent", updated_at=self.clock())

    def discard(self, ref: str) -> None:
        ref = normalize_ref(ref)
        with self.store.locked() as state:
            entry = self._pending_entry(state, ref)
            try:
                self.graph.delete_draft(entry["graph_id"])
            except GraphError as exc:
                raise DraftsError(TEXT["FAIL_discard"].format(detail=str(exc)[:40])) from exc
            entry.update(status="discarded", updated_at=self.clock())

    # --- agent tool

    def list_pending(self) -> list[dict[str, Any]]:
        with self.store.locked() as state:
            return [{"ref": ref, "subject": e.get("subject", ""), "status": e["status"]}
                    for ref, e in state["drafts"].items() if e["status"] == "pending"]

    def read(self, ref: str, *, body_limit: int = 8000) -> dict[str, Any]:
        ref = normalize_ref(ref)
        with self.store.locked() as state:
            entry = self._pending_entry(state, ref)
            draft = self.graph.get_draft(entry["graph_id"])
            if draft is None:
                self._mark_gone(ref, entry, self.clock())
                raise DraftsError(TEXT["FAIL_gone"])
        return {"ref": ref, "to": _addresses(draft.get("toRecipients")), "cc": _addresses(draft.get("ccRecipients")),
                "bcc": _addresses(draft.get("bccRecipients")), "subject": draft.get("subject") or "",
                "body": ((draft.get("body") or {}).get("content") or "")[:body_limit]}

    def update(self, ref: str, *, subject: str | None = None, body: str | None = None, body_html: str | None = None,
               to: list[str] | None = None, cc: list[str] | None = None, bcc: list[str] | None = None) -> dict[str, Any]:
        """Edit a pending draft and refresh its preview. Never sends: only the human's button does."""
        ref = normalize_ref(ref)
        patch: dict[str, Any] = {}
        if subject is not None:
            patch["subject"] = subject
        if body_html is not None:
            patch["body"] = {"contentType": "HTML", "content": body_html}
        elif body is not None:
            escaped = html.escape(body).replace("\r\n", "\n").replace("\n", "<br>\n")
            patch["body"] = {"contentType": "HTML", "content": f"<html><body>{escaped}</body></html>"}
        for field, values in (("toRecipients", to), ("ccRecipients", cc), ("bccRecipients", bcc)):
            if values is not None:
                patch[field] = [{"emailAddress": {"address": str(v).strip()}} for v in values if str(v).strip()]
        if not patch:
            raise DraftsError("nothing to update: pass subject, body, body_html, to, cc or bcc")
        with self.store.locked() as state:
            entry = self._pending_entry(state, ref)
            self.graph.update_draft(entry["graph_id"], patch)
            if self._refresh(ref, entry, TEXT["updated_by_agent"], self.clock()) is None:
                raise DraftsError(TEXT["FAIL_gone"])
        return {"ref": ref, "updated": sorted(patch), "preview_refreshed": True}

    def status(self) -> dict[str, Any]:
        with self.store.locked() as state:
            counts: dict[str, int] = {}
            for entry in state["drafts"].values():
                counts[entry["status"]] = counts.get(entry["status"], 0) + 1
            return {"mailbox": self.settings.mailbox, "baseline_done": state["baseline_done"], "drafts": counts}


# ------------------------------------------------------------------------------------------------ CLI


def run_command(argv: list[str], factory: Callable[[], Drafts] = Drafts.from_runtime) -> int:
    parser = argparse.ArgumentParser(prog="outlook-drafts")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("poll", help="Announce new drafts, refresh edited ones (run every minute)")
    for name in ("send", "discard"):
        sub.add_parser(name).add_argument("ref")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.command == "poll":
        return _run_poll(factory)
    try:
        drafts = factory()
        if args.command == "send":
            drafts.send(args.ref)
        elif args.command == "discard":
            drafts.discard(args.ref)
        else:
            print(json.dumps(drafts.status(), indent=2))
    except DraftsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


POLL_FAILURE_REPORT_EVERY = 60


def _run_poll(factory: Callable[[], Drafts]) -> int:
    """Silent on success (a no_agent cron job delivers stdout and reports a failing exit). A Graph or
    Telegram outage would otherwise page the chat every minute: report the first failure of a streak,
    then once an hour, and say when it recovers."""
    streak_file = hermes_home() / "outlook_drafts" / "poll_failures"
    try:
        streak = int(streak_file.read_text(encoding="utf-8-sig").strip() or 0)
    except (FileNotFoundError, ValueError):
        streak = 0
    try:
        factory().poll()
    except DraftsError as exc:
        streak += 1
        streak_file.parent.mkdir(parents=True, exist_ok=True)
        streak_file.write_text(str(streak), encoding="utf-8")
        if streak == 1 or streak % POLL_FAILURE_REPORT_EVERY == 0:
            print(f"Controllo bozze Outlook non riuscito ({streak}° tentativo di fila): {exc}", file=sys.stderr)
            return 1
        return 0
    if streak:
        streak_file.unlink(missing_ok=True)
        if streak > 1:
            print(f"Controllo bozze Outlook di nuovo attivo dopo {streak} tentativi falliti.")
    return 0


if __name__ == "__main__":
    sys.exit(run_command(sys.argv[1:]))
