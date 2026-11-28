"""Behaviour contracts for the Outlook draft approval flow (fake Graph + fake Telegram, temp HERMES_HOME)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "outlook-drafts"


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        "outlook_drafts_under_test", PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


plugin = _load_plugin()
drafts = plugin.drafts

NOW = 1_800_000_000.0


def iso(ts: float) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGraph:
    def __init__(self):
        self.drafts: dict[str, dict] = {}
        self.sent: list[str] = []
        self.deleted: list[str] = []
        self.send_error: drafts.GraphError | None = None
        self.send_removes_on_error = False

    def add(self, graph_id, *, modified, subject="Offerta", to=("cliente@example.com",), body="Buongiorno,\nin allegato."):
        self.drafts[graph_id] = {
            "id": graph_id, "subject": subject, "lastModifiedDateTime": iso(modified),
            "toRecipients": [{"emailAddress": {"address": a, "name": a}} for a in to],
            "ccRecipients": [], "bccRecipients": [], "webLink": f"https://outlook.office365.com/owa/?ItemID={graph_id}",
            "body": {"contentType": "text", "content": body}, "isDraft": True}

    def touch(self, graph_id, modified, **changes):
        self.drafts[graph_id].update(lastModifiedDateTime=iso(modified), **changes)

    def list_drafts(self):
        return [{k: v for k, v in d.items() if k != "body"} for d in self.drafts.values()]

    def get_draft(self, graph_id):
        draft = self.drafts.get(graph_id)
        return json.loads(json.dumps(draft)) if draft else None

    def update_draft(self, graph_id, patch):
        self.drafts[graph_id].update(patch)
        self.drafts[graph_id]["lastModifiedDateTime"] = iso(NOW + 999)
        if "body" in patch:
            self.drafts[graph_id]["body"] = {"contentType": "text", "content": "updated body"}

    def send_draft(self, graph_id):
        if self.send_error:
            if self.send_removes_on_error:
                self.drafts.pop(graph_id)
            raise self.send_error
        self.sent.append(graph_id)
        self.drafts.pop(graph_id)

    def delete_draft(self, graph_id):
        self.deleted.append(graph_id)
        self.drafts.pop(graph_id, None)


class FakeTelegram:
    def __init__(self):
        self.messages: dict[int, dict] = {}
        self._next = 100

    def send(self, text, markup):
        self._next += 1
        self.messages[self._next] = {"text": text, "markup": markup, "edits": 0}
        return self._next

    def edit(self, message_id, text, markup):
        self.messages[message_id].update(text=text, markup=markup)
        self.messages[message_id]["edits"] += 1


SETTINGS = drafts.Settings(mailbox="luca@example.com", chat_id="42", settle_seconds=120)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    clock = {"now": NOW}
    graph, telegram = FakeGraph(), FakeTelegram()
    service = drafts.Drafts(store=drafts.Store(tmp_path), graph=graph, telegram=telegram, settings=SETTINGS,
                            clock=lambda: clock["now"])
    return service, graph, telegram, clock


def buttons(message):
    return [b for row in message["markup"]["inline_keyboard"] for b in row] if message["markup"] else []


def ref_of(telegram, message_id=None):
    message = telegram.messages[message_id or max(telegram.messages)]
    send = next(b for b in buttons(message) if b.get("callback_data", "").startswith("gt:send:"))
    return send["callback_data"].removeprefix("gt:send:")


def test_first_poll_ignores_existing_drafts_and_announces_new_ones_once(world):
    service, graph, telegram, _clock = world
    graph.add("old", modified=NOW - 3600)
    service.poll()
    assert telegram.messages == {}

    graph.add("new", modified=NOW - 600, subject="Preventivo")
    service.poll()
    service.poll()
    assert len(telegram.messages) == 1
    message = next(iter(telegram.messages.values()))
    assert "Preventivo" in message["text"] and "cliente@example.com" in message["text"]
    callbacks = [b["callback_data"] for b in buttons(message) if "callback_data" in b]
    assert callbacks == [f"gt:send:{ref_of(telegram)}", f"gt:archive:{ref_of(telegram)}"]
    assert all(len(c.encode()) <= 64 for c in callbacks)
    assert any(b.get("url", "").startswith("https://outlook.office365.com/") for b in buttons(message))


def test_draft_still_being_written_waits_until_it_settles(world):
    service, graph, telegram, clock = world
    service.poll()  # baseline (empty folder)
    graph.add("typing", modified=NOW - 10)
    service.poll()
    assert telegram.messages == {}
    clock["now"] = NOW + 200
    service.poll()
    assert len(telegram.messages) == 1


def test_send_sends_exactly_once(world):
    service, graph, telegram, _clock = world
    service.poll()
    graph.add("d1", modified=NOW - 600)
    service.poll()
    ref = ref_of(telegram)
    service.send(ref)
    assert graph.sent == ["d1"]
    with pytest.raises(drafts.DraftsError, match="già gestita"):
        service.send(ref)
    assert graph.sent == ["d1"]


def test_send_refuses_a_version_the_preview_did_not_show(world):
    service, graph, telegram, _clock = world
    service.poll()
    graph.add("d1", modified=NOW - 600, body="versione uno")
    service.poll()
    ref, message_id = ref_of(telegram), max(telegram.messages)
    graph.touch("d1", NOW - 5, body={"contentType": "text", "content": "versione due"})

    with pytest.raises(drafts.DraftsError, match="anteprima aggiornata"):
        service.send(ref)
    assert graph.sent == []
    assert "versione due" in telegram.messages[message_id]["text"]

    service.send(ref)  # the second tap approves what is now on screen
    assert graph.sent == ["d1"]


def test_draft_sent_or_deleted_from_outlook_closes_its_preview(world):
    service, graph, telegram, _clock = world
    service.poll()
    graph.add("d1", modified=NOW - 600, subject="Riunione")
    service.poll()
    message_id = max(telegram.messages)
    del graph.drafts["d1"]
    service.poll()
    message = telegram.messages[message_id]
    assert "non è più tra le bozze" in message["text"] and "Riunione" in message["text"]
    assert buttons(message) == []


def test_ambiguous_send_failure_is_never_retried_blindly(world):
    service, graph, telegram, _clock = world
    service.poll()
    graph.add("d1", modified=NOW - 600)
    graph.add("d2", modified=NOW - 600)
    service.poll()
    assert len(telegram.messages) == 2

    graph.send_error = drafts.GraphError(503, "HTTP 503")
    graph.send_removes_on_error = True  # Graph applied it but answered 503
    service.send(drafts.make_ref("d1", {}))
    assert service.status()["drafts"].get("sent") == 1

    graph.send_removes_on_error = False  # really failed: the draft is still there
    second = drafts.make_ref("d2", {})
    with pytest.raises(drafts.DraftsError, match="Invio non riuscito"):
        service.send(second)
    assert [p["ref"] for p in service.list_pending()] == [second]


def test_discard_deletes_the_draft(world):
    service, graph, telegram, _clock = world
    service.poll()
    graph.add("d1", modified=NOW - 600)
    service.poll()
    service.discard("#" + ref_of(telegram).lower())
    assert graph.deleted == ["d1"] and graph.sent == []


def test_agent_edit_refreshes_the_preview_and_never_sends(world):
    service, graph, telegram, _clock = world
    service.poll()
    graph.add("d1", modified=NOW - 600)
    service.poll()
    ref, message_id = ref_of(telegram), max(telegram.messages)
    result = service.update(ref, subject="Nuovo oggetto", body="Gentile cliente,\nconfermo.")
    assert result["updated"] == ["body", "subject"]
    assert graph.sent == []
    assert "Nuovo oggetto" in telegram.messages[message_id]["text"]
    assert "Modificata su tua richiesta" in telegram.messages[message_id]["text"]
    service.poll()  # the edit is already reflected: no second refresh
    assert telegram.messages[message_id]["edits"] == 1
    service.send(ref)
    assert graph.sent == ["d1"]


def test_graph_send_is_not_replayed_on_server_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in request.url.path:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        calls.append((request.method, request.url.raw_path.decode()))
        return httpx.Response(502, json={"error": {"code": "BadGateway"}})

    creds = type("C", (), {"token_url": "https://login.example/x/oauth2/v2.0/token", "client_id": "c",
                           "client_secret": "s", "scope": "x"})()
    graph = drafts.Graph("luca@example.com", credentials=creds, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(drafts.GraphError) as err:
        graph.send_draft("AAMk/1=")
    assert err.value.ambiguous
    assert calls == [("POST", "/v1.0/users/luca%40example.com/messages/AAMk%2F1%3D/send")]

    calls.clear()
    with pytest.raises(drafts.GraphError):
        graph.update_draft("AAMk", {"subject": "x"})
    assert len(calls) == 4  # idempotent calls retry


def test_install_writes_executable_scripts_and_keeps_foreign_ones(tmp_path):
    foreign = tmp_path / "scripts" / "gmail-triage" / "send-draft.sh"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(drafts.DraftsError, match="refusing to overwrite"):
        plugin.install_scripts(tmp_path)
    assert foreign.read_text() == "#!/bin/sh\necho mine\n"

    paths = plugin.install_scripts(tmp_path, force=True)
    assert {p.name for p in paths} == {"send-draft.sh", "archive.sh", "outlook-drafts-poll.sh"}
    for path in paths:
        assert os.access(path, os.X_OK)
    assert plugin.install_scripts(tmp_path)  # re-install over its own scripts needs no --force


def test_button_script_runs_the_command_with_a_scrubbed_env(tmp_path):
    """The adapter runs the script with secrets scrubbed; it must still reach the command and fail
    cleanly (one stderr line for the toast) when the draft is unknown."""
    (tmp_path / "config.yaml").write_text("outlook_drafts:\n  mailbox: luca@example.com\n  telegram_chat_id: '42'\n")
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=123:abc\nMSGRAPH_TENANT_ID=t\nMSGRAPH_CLIENT_ID=c\nMSGRAPH_CLIENT_SECRET=s\n")
    plugin.install_scripts(tmp_path)
    script = tmp_path / "scripts" / "gmail-triage" / "send-draft.sh"
    proc = subprocess.run([str(script), "ZZZZZZ"], capture_output=True, text=True, timeout=120, check=False,
                          env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})
    assert proc.returncode == 1, proc.stderr
    assert proc.stderr.strip().splitlines()[-1] == "Bozza #ZZZZZZ sconosciuta"


def test_poll_failures_are_reported_once_per_streak(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    class Broken:
        def poll(self):
            raise drafts.GraphError(503, "HTTP 503")

    codes = [drafts.run_command(["poll"], factory=Broken) for _ in range(3)]
    assert codes == [1, 0, 0]
    assert capsys.readouterr().err.count("non riuscito") == 1

    class Healthy:
        def poll(self):
            return {}

    assert drafts.run_command(["poll"], factory=Healthy) == 0
    assert "di nuovo attivo" in capsys.readouterr().out
