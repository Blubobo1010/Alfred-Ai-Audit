"""+Human: the plugin catalog ships with the release and upstream's removal list never reaches the plugins the
release pins (overlay from alfred-build, codemod C0191)."""

import json

import pytest
from hermes_cli import plugin_catalog as pc
from hermes_cli import plushuman_plugins as pp
from hermes_cli.plugin_catalog import RemovedEntry

OURS = [
    {"dir": "brain", "repo": "Blubobo1010/alfred-brain", "sha": "a" * 40},
    {"dir": "alfred-m365", "repo": "Blubobo1010/alfred-m365", "sha": "b" * 40},
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def off(monkeypatch):
    """The shipped default; the suite's conftest opts every other test in."""
    monkeypatch.delenv("HERMES_LIVE_PLUGIN_CATALOG", raising=False)
    monkeypatch.setattr(pc, "_live_fetch_failed_until", 0.0)


@pytest.fixture
def no_network(monkeypatch):
    import httpx

    def refuse(*_args, **_kwargs):
        raise AssertionError("the live plugin catalog was requested")

    monkeypatch.setattr(httpx, "get", refuse)


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setattr(pp, "load_manifest", lambda *_args, **_kwargs: list(OURS))


def _catalog_dir(tmp_path, monkeypatch, removed):
    """An in-tree catalog holding only a removal list."""
    root = tmp_path / "plugin-catalog"
    root.mkdir()
    (root / "removed.yaml").write_text(json.dumps({"removed": removed}), encoding="utf-8")  # JSON is YAML
    monkeypatch.setattr(pc, "get_catalog_dir", lambda: root)
    return root


# ------------------------------------------------------------------ the live catalog is off


def test_live_catalog_is_not_fetched(home, off, no_network):
    assert pc.fetch_live_catalog() is None
    assert pc.fetch_live_catalog(force=True) is None
    assert pc.live_removed_list() == []
    assert [e.name for e in pc.load_catalog_live()] == [e.name for e in pc.load_catalog()]


def test_an_earlier_cache_is_not_read(home, off, no_network, tmp_path, monkeypatch):
    _catalog_dir(tmp_path, monkeypatch, [])
    cache = home / "cache" / "plugin-catalog.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"entries": [], "removed": [{"name": "left-by-an-older-build"}]}), encoding="utf-8")
    assert pc.fetch_live_catalog() is None
    assert pc.cached_removed_entries() == []
    assert pc.resolved_removed_entries() == []


def test_opting_in_reads_the_published_document(home, monkeypatch):
    import httpx

    class Response:
        content = b"{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"entries": [], "removed": [{"name": "recalled"}]}

    monkeypatch.setenv("HERMES_LIVE_PLUGIN_CATALOG", "1")
    monkeypatch.setattr(pc, "_live_fetch_failed_until", 0.0)
    monkeypatch.setattr(httpx, "get", lambda *_args, **_kwargs: Response())
    assert [r.name for r in pc.live_removed_list()] == ["recalled"]


# ------------------------------------------------------------------ the removal list and the pinned plugins


def test_spare_drops_an_entry_for_a_pinned_repository():
    removed = [RemovedEntry(name="anything", repo="git@github.com:Blubobo1010/alfred-brain.git"),
               RemovedEntry(name="other", repo="https://github.com/someone/other")]
    assert [r.name for r in pp.spare_release_plugins(removed, OURS)] == ["other"]


def test_spare_keeps_a_namesake_by_repository_only():
    removed = [RemovedEntry(name="brain", repo="https://github.com/someone/brain", reason="malware")]
    kept = pp.spare_release_plugins(removed, OURS)
    assert [(r.name, r.repo, r.reason) for r in kept] == [
        ("brain (https://github.com/someone/brain)", "https://github.com/someone/brain", "malware")]
    assert pc.match_removed("brain", kept) is None
    assert pc.match_removed("https://github.com/Someone/brain.git", kept) is not None


def test_spare_drops_a_namesake_without_a_repository():
    for name in ("brain", "alfred-m365", "alfred-brain"):
        assert pp.spare_release_plugins([RemovedEntry(name=name)], OURS) == []


def test_spare_leaves_the_list_alone_without_pins():
    removed = [RemovedEntry(name="brain")]
    assert pp.spare_release_plugins(removed, []) == removed


def test_an_upstream_removal_named_like_our_plugin_does_not_reach_it(home, off, pinned, tmp_path, monkeypatch):
    from hermes_cli.plugins_cmd_catalog import installed_plugin_removal

    _catalog_dir(tmp_path, monkeypatch, [
        {"name": "brain", "repo": "https://github.com/someone/brain", "reason": "recalled upstream"},
        {"name": "flowcanvas", "reason": "recalled upstream"}])
    ours = home / "plugins" / "brain"
    ours.mkdir(parents=True)
    (ours / "plugin.yaml").write_text("name: brain\nversion: 0.6.1\n", encoding="utf-8")
    other = home / "plugins" / "flowcanvas"
    other.mkdir()

    assert installed_plugin_removal("brain", ours) is None
    assert pc.find_removed("brain") is None
    assert pc.find_removed("https://github.com/someone/brain") is not None
    assert installed_plugin_removal("flowcanvas", other).reason == "recalled upstream"
