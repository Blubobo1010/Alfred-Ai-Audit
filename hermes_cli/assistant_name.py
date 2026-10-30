"""The assistant's own name, chosen by each customer; +Human is the product.

`display.assistant_name` in config.yaml (or HERMES_ASSISTANT_NAME) names the assistant: it introduces itself with
that name, the default skin's labels use it and WhatsApp replies are signed with it. Empty keeps the product name.
SOUL.md is never written here, so an untouched default persona keeps upgrading in place.
"""

from __future__ import annotations

import os
import unicodedata

PRODUCT = "+Human"
VENDOR = "Ai-Audit"
ENV = "HERMES_ASSISTANT_NAME"
MAX_LEN = 40
RULE = "────────────"


def _clean(value: object) -> str:
    """One line of letters, digits, spaces and `+ . ' -`, cut to MAX_LEN; any other character means no name: the
    name lands in the prompt, in labels and inside WhatsApp's bold prefix (the brain plugin applies the same rule)."""
    text = " ".join(unicodedata.normalize("NFC", str(value or "")).split())
    if not all(ch.isalnum() or ch in " +.'-" for ch in text):
        return ""
    return text[:MAX_LEN].rstrip()


def configured() -> str:
    """The configured name, or "" when none is set. Never raises: a broken config means no name."""
    env = _clean(os.environ.get(ENV, ""))
    if env:
        return env
    try:
        from hermes_cli.config import load_config

        display = load_config().get("display") or {}
    except Exception:  # naming is cosmetic; a config error must not break startup
        return ""
    return _clean(display.get("assistant_name", "")) if isinstance(display, dict) else ""


def name() -> str:
    """The name the assistant goes by: the configured one, else the product name."""
    return configured() or PRODUCT


def personalize_branding(branding: dict[str, str]) -> dict[str, str]:
    """The default skin speaks with the assistant's name; skins with a persona of their own keep it."""
    own = configured()
    if not own or branding.get("agent_name") != PRODUCT:
        return branding
    out = dict(branding)
    for key in ("agent_name", "welcome", "response_label"):
        if isinstance(out.get(key), str):
            out[key] = out[key].replace(PRODUCT, own)
    return out


def identity_line(soul: str | None = None) -> str:
    """The prompt line that names the assistant and says it is an AI (AI Act art. 50(1)), or "" when the identity
    already says so: no name and either upstream's fallback identity (`soul` None) or the product's default SOUL.md.
    A customised SOUL.md may say neither, so it always gets the line."""
    own = configured()
    if own:
        return (f"Your name is {own}: the user chose it, so introduce yourself as {own}, an AI assistant, and never "
                f"claim to be human. {PRODUCT} is the product you are part of, built by {VENDOR}.")
    if not soul or _is_default_soul(soul):
        return ""
    return (f"You are an AI assistant ({PRODUCT}, built by {VENDOR}): say so plainly when you introduce yourself, "
            "and never claim to be human.")


def _is_default_soul(soul: str) -> bool:
    try:
        from hermes_cli.default_soul import DEFAULT_SOUL_MD
    except Exception:  # no default to compare with: say it
        return False
    return " ".join(soul.split()) == " ".join(DEFAULT_SOUL_MD.split())


def reply_prefix() -> str:
    """WhatsApp reply prefix signed with the assistant's name, or "" when no name is set."""
    own = configured()
    return f"*{own}*\n{RULE}\n" if own else ""


def setup_assistant_name(config: dict) -> None:
    """Setup step: ask the customer what the assistant is called (Enter keeps the current answer)."""
    from hermes_cli.config import save_config
    from hermes_cli.setup import _info, print_header, print_success, prompt

    print_header("Assistant Name")
    display = config.setdefault("display", {})
    current = _clean(display.get("assistant_name", ""))
    _info("Give your assistant a name: it introduces itself with it and signs WhatsApp replies with it.",
          f"{PRODUCT} is the product. Leave it empty and the assistant presents itself as the {PRODUCT} assistant.")
    answer = _clean(prompt("Assistant name", current))
    display["assistant_name"] = answer
    save_config(config)
    print_success(f"Assistant name: {answer}" if answer else f"No name set: the assistant uses {PRODUCT}")
