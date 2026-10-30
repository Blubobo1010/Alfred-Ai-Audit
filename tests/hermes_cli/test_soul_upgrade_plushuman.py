"""+Human: an untouched earlier default SOUL.md upgrades to the +Human persona; a customised one never changes
(overlay from alfred-build)."""

import pytest
from hermes_cli.config import _ensure_default_soul_md
from hermes_cli.default_soul import _HERMES_LEGACY_SOULS, DEFAULT_SOUL_MD, is_legacy_template_soul

EARLIER_DEFAULTS = [t for t in _HERMES_LEGACY_SOULS if t.startswith("You are Alfred, built by Ai-Audit")]


def test_earlier_brand_defaults_are_recorded():
    assert EARLIER_DEFAULTS, "the Alfred-era defaults must stay upgradeable"
    for text in EARLIER_DEFAULTS:
        assert is_legacy_template_soul(text)
        assert is_legacy_template_soul(text.replace("—", "--"))


def test_current_default_is_the_plushuman_persona():
    assert DEFAULT_SOUL_MD.startswith("You are the +Human assistant, an AI assistant built by Ai-Audit")
    assert "Never claim or imply to be human" in DEFAULT_SOUL_MD  # AI Act art. 50(1)
    assert "Alfred" not in DEFAULT_SOUL_MD


@pytest.mark.parametrize("dashes", ["—", "--"])
def test_untouched_earlier_default_upgrades(tmp_path, dashes):
    (tmp_path / "SOUL.md").write_text(EARLIER_DEFAULTS[-1].replace("—", dashes), encoding="utf-8")
    _ensure_default_soul_md(tmp_path)
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == DEFAULT_SOUL_MD


def test_customised_soul_is_never_touched(tmp_path):
    custom = "Ti chiami Jarvis e lavori per Luca.\n" + EARLIER_DEFAULTS[-1]
    (tmp_path / "SOUL.md").write_text(custom, encoding="utf-8")
    _ensure_default_soul_md(tmp_path)
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == custom
