"""+Human: the product's own plugins follow the release (overlay from alfred-build)."""

import json
import subprocess
from datetime import timedelta

import pytest
from hermes_cli import plushuman_plugins as pp


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv(pp.WORKER_ENV, raising=False)
    return tmp_path


@pytest.fixture
def plugin_repo(home):
    """An installed git plugin `brain` with two commits; returns (dir, first_sha, second_sha)."""
    d = home / "plugins" / "brain"
    d.mkdir(parents=True)
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@example.com")
    _git(d, "config", "user.name", "t")
    (d / "plugin.yaml").write_text("name: brain\nversion: 0.6.0\n", encoding="utf-8")
    _git(d, "add", "-A")
    _git(d, "commit", "-qm", "one")
    first = _git(d, "rev-parse", "HEAD")
    (d / "plugin.yaml").write_text("name: brain\nversion: 0.6.1\n", encoding="utf-8")
    _git(d, "commit", "-qam", "two")
    second = _git(d, "rev-parse", "HEAD")
    _git(d, "checkout", "-q", first)
    return d, first, second


@pytest.fixture
def same_source(monkeypatch):
    monkeypatch.setattr(pp, "_installed_from_elsewhere", lambda _name, _repo: None)


def _manifest(tmp_path, entries):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"plugins": entries}), encoding="utf-8")
    return path


def _state(home):
    return json.loads((home / pp.STATE_FILE).read_text(encoding="utf-8"))


def test_manifest_keeps_only_exact_pins(tmp_path):
    good = {"dir": "brain", "repo": "https://example.com/brain.git", "sha": "a" * 40}
    bad = [{"dir": "x", "repo": "r", "sha": "main"}, {"repo": "r", "sha": "b" * 40}, "nope"]
    assert pp.load_manifest(_manifest(tmp_path, [good, *bad])) == [good]
    assert pp.load_manifest(tmp_path / "missing.json") == []


def test_not_installed_plugins_are_left_alone(home):
    entry = {"dir": "alfred-odoo", "repo": "https://example.com/o.git", "sha": "c" * 40}
    assert pp.pending(home, [entry]) == []


def test_off_pin_plugin_moves_to_its_pin_through_the_regular_update_path(home, plugin_repo, same_source, monkeypatch):
    d, _first, second = plugin_repo
    entry = {"dir": "brain", "repo": "https://example.com/brain.git", "sha": second, "version": "0.6.1"}
    assert pp.pending(home, [entry]) == [entry]
    calls = []

    def fake_install(identifier, **kwargs):
        calls.append((identifier, kwargs))
        _git(d, "checkout", "-q", kwargs["ref"])
        return d, {}, "brain"

    from hermes_cli import plugins_cmd
    monkeypatch.setattr(plugins_cmd, "_install_plugin_core", fake_install)
    monkeypatch.setattr(pp, "load_manifest", lambda path=pp.MANIFEST: [entry])
    said = []
    assert pp.apply_active_home(say=said.append) == []
    # no before_swap: the installer itself carries user files and backs up tracked edits; dependency consent is given
    assert calls == [("https://example.com/brain.git", {"force": True, "ref": second, "assume_deps_consent": True})]
    assert pp.installed_revision(d) == second
    assert pp.pending(home, [entry]) == []
    assert _state(home)["brain"]["sha"] == second
    assert pp.RETRY_KEY not in _state(home)
    assert any("0.6.1" in line for line in said)


def test_a_plugin_installed_from_another_source_is_left_alone(home, plugin_repo, monkeypatch):
    _d, first, second = plugin_repo
    entry = {"dir": "brain", "repo": "https://example.com/brain.git", "sha": second}
    from hermes_cli import plugins_cmd
    monkeypatch.setattr(plugins_cmd, "_install_plugin_core", lambda *_a, **_k: pytest.fail("must not reinstall"))
    monkeypatch.setattr(pp, "_installed_from_elsewhere", lambda _name, _repo: "https://example.com/fork.git")
    monkeypatch.setattr(pp, "load_manifest", lambda path=pp.MANIFEST: [entry])
    problems = pp.apply_active_home(say=lambda _m: None)
    assert problems and "fork.git" in problems[0]
    assert pp.installed_revision(_d) == first


def test_setup_runs_once_at_the_pin_bounded(home, plugin_repo, monkeypatch):
    _d, first, _second = plugin_repo
    entry = {"dir": "brain", "repo": "https://example.com/brain.git", "sha": first, "setup": ["brain", "setup"]}
    assert pp.pending(home, [entry]) == [entry]  # at the pin, but setup never ran there
    setups = []

    def bounded(cmd, *, timeout, env):
        setups.append((cmd[1:], timeout, env["HERMES_HOME"]))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pp, "_run_bounded", bounded)
    monkeypatch.setattr(pp, "load_manifest", lambda path=pp.MANIFEST: [entry])
    assert pp.apply_active_home(say=lambda _m: None) == []
    assert setups == [(["-m", "hermes_cli.main", "brain", "setup"], pp.SETUP_TIMEOUT, str(home))]
    assert pp.pending(home, [entry]) == []
    assert pp.SETUP_TIMEOUT < pp.BOOT_TIMEOUT  # a slow setup ends with its own error inside the worker


def test_a_hanging_setup_is_stopped_and_retried_later(home, plugin_repo, monkeypatch):
    _d, first, _second = plugin_repo
    entry = {"dir": "brain", "repo": "https://example.com/brain.git", "sha": first, "setup": ["brain", "setup"]}

    def bounded(cmd, *, timeout, env):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(pp, "_run_bounded", bounded)
    monkeypatch.setattr(pp, "load_manifest", lambda path=pp.MANIFEST: [entry])
    problems = pp.apply_active_home(say=lambda _m: None)
    assert problems and "still running" in problems[0]
    assert pp.RETRY_KEY in _state(home)
    assert pp.pending(home, [entry]) == [entry]


def test_run_bounded_closes_stdin_and_returns_the_output(tmp_path):
    import os
    import sys

    r = pp._run_bounded([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], timeout=30,
                        env=dict(os.environ))
    assert r.returncode == 0 and r.stdout.strip() == "''"


@pytest.mark.skipif(not hasattr(__import__("os"), "killpg"), reason="process groups are POSIX")
def test_run_bounded_kills_what_the_command_left_running(tmp_path):
    import os
    import time

    marker = tmp_path / "survivor"
    cmd = ["sh", "-c", f"(sleep 2; touch {marker}) > /dev/null 2>&1 < /dev/null & sleep 30"]
    with pytest.raises(subprocess.TimeoutExpired):
        pp._run_bounded(cmd, timeout=1, env=dict(os.environ))
    time.sleep(2.5)
    assert not marker.exists()


def test_failures_never_raise_and_schedule_a_retry(home, plugin_repo, same_source, monkeypatch):
    _d, _first, second = plugin_repo
    entry = {"dir": "brain", "repo": "https://example.com/brain.git", "sha": second}

    def boom(*_a, **_k):
        raise RuntimeError("no credential")

    from hermes_cli import plugins_cmd
    monkeypatch.setattr(plugins_cmd, "_install_plugin_core", boom)
    monkeypatch.setattr(pp, "load_manifest", lambda path=pp.MANIFEST: [entry])
    said = []
    problems = pp.apply_active_home(say=said.append)
    assert problems and "no credential" in problems[0]
    assert any("not updated" in line for line in said)
    assert pp.RETRY_KEY in _state(home)


def test_boot_step_uses_a_worker_and_prints_nothing(home, plugin_repo, monkeypatch, capsys):
    _d, _first, second = plugin_repo
    entry = {"dir": "brain", "repo": "https://example.com/brain.git", "sha": second}
    monkeypatch.setattr(pp, "load_manifest", lambda path=pp.MANIFEST: [entry])
    runs = []

    def worker(h, timeout, say):
        runs.append((h, timeout))
        say("  +Human plugin brain -> 0.6.1")
        return False

    monkeypatch.setattr(pp, "_run_worker", worker)
    assert pp.step()["ok"] is False
    assert runs == [(home, pp.BOOT_TIMEOUT)]
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(pp, "load_manifest", lambda path=pp.MANIFEST: [])
    assert pp.step() == {"ok": True}
    assert len(runs) == 1


class _FakeWorker:
    """Stands in for the worker process: `communicate` hangs (timeout) or returns `out` with `code`."""

    pid = 4242

    def __init__(self, *, hang=False, out="", code=0):
        self.hang, self.out, self.code, self.returncode = hang, out, code, None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def communicate(self, timeout=None):
        if self.hang:
            raise subprocess.TimeoutExpired("worker", timeout)
        self.returncode = self.code
        return self.out, None

    def wait(self):
        self.returncode = -9
        return -9


def test_a_stuck_worker_is_stopped_with_its_group_and_retried_later(home, monkeypatch):
    killed = []
    monkeypatch.setattr(pp.subprocess, "Popen", lambda *_a, **_k: _FakeWorker(hang=True))
    monkeypatch.setattr(pp, "_kill_group", lambda proc: killed.append(proc.pid))
    said = []
    assert pp._run_worker(home, 5, said.append) is False
    assert killed == [4242]
    assert said and "stopped after 5 s" in said[0]
    assert pp.RETRY_KEY in _state(home)


def test_a_worker_that_died_without_recording_still_gets_a_retry(home, monkeypatch):
    monkeypatch.setattr(pp.subprocess, "Popen", lambda *_a, **_k: _FakeWorker(out="Traceback: boom\n", code=1))
    said = []
    assert pp._run_worker(home, 5, said.append) is False
    assert said == ["Traceback: boom"]
    assert pp.RETRY_KEY in _state(home)


def test_the_worker_runs_in_its_own_process_group(home, monkeypatch):
    seen = {}

    def popen(cmd, **kwargs):
        seen.update(kwargs)
        return _FakeWorker()

    monkeypatch.setattr(pp.subprocess, "Popen", popen)
    assert pp._run_worker(home, 5, lambda _m: None) is True
    assert seen["start_new_session"] is True and seen["stdin"] == subprocess.DEVNULL
    assert seen["env"]["HERMES_HOME"] == str(home) and seen["env"][pp.WORKER_ENV] == "1"
    assert not (home / pp.STATE_FILE).exists()  # success leaves no retry behind


@pytest.mark.skipif(not hasattr(__import__("os"), "killpg"), reason="process groups are POSIX")
def test_kill_group_also_stops_what_the_worker_started():
    import os
    import time

    proc = subprocess.Popen(["sh", "-c", "sleep 30 & sleep 30"], start_new_session=True)
    time.sleep(0.2)
    pp._kill_group(proc)
    proc.wait(timeout=5)
    for _ in range(50):  # the orphaned grandchild is reaped by init shortly after the kill
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    pytest.fail("a process of the worker's group survived")


def test_mark_retry_leaves_a_busy_home_to_its_worker(home):
    with pp._home_lock(home) as held:
        assert held
        pp._mark_retry(home)
    assert not (home / pp.STATE_FILE).exists()


def test_retry_starts_a_detached_worker_only_when_due(home, monkeypatch):
    started = []
    monkeypatch.setattr(pp.subprocess, "Popen", lambda cmd, **kwargs: started.append((cmd, kwargs)))
    pp.retry_due()  # nothing failed: no state, no worker
    assert started == []
    pp._write_state(home, {pp.RETRY_KEY: (pp._now() + timedelta(hours=1)).isoformat()})
    pp.retry_due()
    assert started == []
    pp._write_state(home, {pp.RETRY_KEY: (pp._now() - timedelta(minutes=1)).isoformat()})
    pp.retry_due()
    assert len(started) == 1
    cmd, kwargs = started[0]
    assert cmd[1:] == ["-m", "hermes_cli.plushuman_plugins", "--home", str(home)]
    assert kwargs["start_new_session"] is True and kwargs["stdin"] == subprocess.DEVNULL
    assert pp._read_state(home)[pp.RETRY_KEY] > pp._now().isoformat()  # claimed: the next launch does not start another
    pp.retry_due()
    assert len(started) == 1


def test_no_retry_while_a_worker_holds_the_home(home, monkeypatch):
    monkeypatch.setattr(pp.subprocess, "Popen", lambda *_a, **_k: pytest.fail("the running worker is enough"))
    pp._write_state(home, {pp.RETRY_KEY: (pp._now() - timedelta(minutes=1)).isoformat()})
    with pp._home_lock(home) as held:
        assert held
        pp.retry_due()


def test_no_retry_from_inside_a_worker(home, monkeypatch):
    monkeypatch.setenv(pp.WORKER_ENV, "1")
    monkeypatch.setattr(pp.subprocess, "Popen", lambda *_a, **_k: pytest.fail("nested worker"))
    pp._write_state(home, {pp.RETRY_KEY: (pp._now() - timedelta(minutes=1)).isoformat()})
    pp.retry_due()


def test_only_a_worker_we_started_in_its_own_group_arms_the_alarm(home, monkeypatch):
    import os

    alarms = []
    monkeypatch.setattr(pp.signal, "alarm", alarms.append)
    monkeypatch.setattr(pp.signal, "signal", lambda *_a: None)
    monkeypatch.setattr(pp, "apply_active_home", lambda say=print: [])
    monkeypatch.setattr(os, "getpgrp", os.getpid)  # as if this process led its group
    monkeypatch.delenv(pp.GROUP_ENV, raising=False)
    assert pp.main(["--home", str(home)]) == 0  # manual run: a shell pipeline may share the group
    assert alarms == []
    monkeypatch.setenv(pp.GROUP_ENV, "1")
    assert pp.main(["--home", str(home)]) == 0
    assert alarms == [pp.UPDATE_TIMEOUT, 0]  # armed for the run, disarmed on return
    assert pp.GROUP_ENV not in os.environ  # setup children do not inherit it


def test_one_worker_per_home(home, monkeypatch):
    monkeypatch.setattr(pp, "apply_active_home", lambda say=print: pytest.fail("must wait for the other worker"))
    with pp._home_lock(home) as held:
        assert held
        assert pp.main(["--home", str(home)]) == 0
