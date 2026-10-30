"""+Human: keep the product's own plugins at the revision this release was tested with.

`plushuman_plugins.json` (written next to this module by alfred-build from brand.toml [[plugins]]) lists +Human's
plugins with the exact commit each release ships. Every INSTALLED one is moved to its pin and its setup runs once
there; plugins a home never installed are left alone. Three triggers, none of which can fail or hang its caller:
- `plushuman update` (maintenance tail): every profile home, each in a worker process with a timeout;
- the first launch after an update (post_update HOME_STEPS, desktop-only installs too): the active home, same way;
- any later launch once an earlier attempt failed and RETRY_DELAY has passed: a detached worker, nothing waits.
The worker (`python -m hermes_cli.plushuman_plugins --home PATH`, also the manual retry) holds a per-home lock and
never reads stdin. The repos are private: git reads them with the GitHub credential in the macOS Keychain
(osxkeychain helper), never with a prompt. Re-pinning goes through the installer's regular update path: user files
are carried over, edits to tracked files are kept under plugins-backup/, and a plugin installed from another source
is left as it is.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST = Path(__file__).with_name("plushuman_plugins.json")
STATE_FILE = "plushuman-plugins.json"
LOCK_FILE = "plushuman-plugins.lock"
RETRY_KEY = "_retry_after"  # state key; plugin names start with a letter or digit
WORKER_ENV = "PLUSHUMAN_PLUGINS_WORKER"  # set in the worker and its children: no nested retries
GROUP_ENV = "PLUSHUMAN_PLUGINS_OWN_GROUP"  # set only by the spawns below, which give the worker a group of its own
SETUP_TIMEOUT = 240  # seconds for one plugin's setup command (below BOOT_TIMEOUT: it ends with its own error)
BOOT_TIMEOUT = 300  # seconds the first launch after an update waits for its home
UPDATE_TIMEOUT = 1200  # seconds `update` waits for each profile home
RETRY_DELAY = timedelta(hours=6)
GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "credential.https://github.com.helper",
    "GIT_CONFIG_VALUE_0": "osxkeychain" if sys.platform == "darwin" else "cache",
}


def load_manifest(path: Path = MANIFEST) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("plugins", []) if isinstance(data, dict) else []
    return [e for e in entries if isinstance(e, dict) and e.get("dir") and e.get("repo")
            and isinstance(e.get("sha"), str) and len(e["sha"]) == 40]


def _state_path(home: Path) -> Path:
    return home / STATE_FILE


def _read_state(home: Path) -> dict:
    try:
        data = json.loads(_state_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(home: Path, state: dict) -> None:
    """Atomic replace through a temp file of its own (callers hold the home lock: see _home_lock)."""
    fd, tmp = tempfile.mkstemp(prefix=".plushuman-plugins.", suffix=".tmp", dir=home)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, _state_path(home))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _now() -> datetime:
    return datetime.now(UTC)


def _mark_retry(home: Path) -> None:
    """From outside a worker: schedule a retry, unless a worker holds the home (it records its own outcome)."""
    with _home_lock(home) as held:
        if held:
            state = _read_state(home)
            state[RETRY_KEY] = (_now() + RETRY_DELAY).isoformat(timespec="seconds")
            _write_state(home, state)


def _child_env(home: Path, *, own_group: bool = False) -> dict[str, str]:
    """This process's environment for a child acting on `home` (secrets kept: git and setup run as the user would).
    `own_group` tells a worker it leads a process group of its own (see main)."""
    from tools.environments.local import build_subprocess_env

    extra = {"HERMES_HOME": str(home), WORKER_ENV: "1"}
    if own_group:
        extra[GROUP_ENV] = "1"
    return build_subprocess_env(scrub_secrets=False, inherit_profile_home=False, extra=extra)


def _run_bounded(cmd: list[str], *, timeout: int, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run `cmd` without stdin in a process group of its own; past `timeout` the whole group is killed (a child it
    left in the background included) and TimeoutExpired is raised."""
    with subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=env, start_new_session=True) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.wait()
            raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def installed_revision(plugin_dir: Path) -> str | None:
    """HEAD of a git-installed plugin, else None (not installed or not a checkout)."""
    if not (plugin_dir / ".git").exists():
        return None
    r = subprocess.run(["git", "-C", str(plugin_dir), "rev-parse", "HEAD"], capture_output=True, text=True,
                       check=False, stdin=subprocess.DEVNULL)
    return r.stdout.strip() if r.returncode == 0 else None


def pending(home: Path, manifest: list[dict] | None = None) -> list[dict]:
    """Manifest entries installed in `home` that are off their pin or whose setup has not run at the pin."""
    state = _read_state(home)
    todo = []
    for entry in manifest if manifest is not None else load_manifest():
        plugin_dir = home / "plugins" / entry["dir"]
        if not plugin_dir.is_dir():
            continue
        revision = installed_revision(plugin_dir)
        done = state.get(entry["dir"], {})
        if revision != entry["sha"] or (entry.get("setup") and done.get("setup_sha") != entry["sha"]):
            todo.append(entry)
    return todo


def _installed_from_elsewhere(name: str, repo: str) -> str | None:
    """The recorded source of installed plugin `name` when it is not `repo`, else None. Only a plugin installed from
    the pinned repo is re-pinned: the installer carries user files over only for a reinstall of the same source."""
    from hermes_cli import plugins_cmd

    git_url, subdir = plugins_cmd._resolve_git_url(repo)
    prior = plugins_cmd._read_install_metadata().get(name)
    found = prior.get("source") if isinstance(prior, dict) else None
    return None if found == plugins_cmd._canonical_source(git_url, subdir) else (found or "an unrecorded source")


def apply_active_home(say: Callable[[str], None] = print) -> list[str]:
    """Re-pin and set up every pending plugin of the ACTIVE home (HERMES_HOME). Returns problems; any problem
    schedules a retry after RETRY_DELAY, a clean run cancels it."""
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    problems: list[str] = []
    entries = pending(home)
    if entries:
        os.environ.update(GIT_ENV)
    for entry in entries:
        name, sha = entry["dir"], entry["sha"]
        target = home / "plugins" / name
        try:
            if installed_revision(target) != sha:
                elsewhere = _installed_from_elsewhere(name, entry["repo"])
                if elsewhere:
                    raise RuntimeError(f"installed from {elsewhere}, not {entry['repo']}: left as it is")
                from hermes_cli import plugins_cmd

                # +Human's own pinned plugins: their dependencies are part of the release, so the publication
                # gate gets the consent a headless run cannot ask for.
                plugins_cmd._install_plugin_core(entry["repo"], force=True, ref=sha, assume_deps_consent=True)
                say(f"  +Human plugin {name} -> {entry.get('version') or sha[:8]}")
            if entry.get("setup"):
                cmd = [sys.executable, "-m", "hermes_cli.main", *entry["setup"]]
                r = _run_bounded(cmd, timeout=SETUP_TIMEOUT, env=_child_env(home))
                if r.returncode != 0:
                    raise RuntimeError(f"setup failed: {(r.stderr or r.stdout).strip()[-300:]}")
            state = _read_state(home)
            state[name] = {"sha": sha, "setup_sha": sha if entry.get("setup") else None,
                           "at": _now().isoformat(timespec="seconds")}
            _write_state(home, state)
        except subprocess.TimeoutExpired:
            problems.append(f"{name}: setup still running after {SETUP_TIMEOUT} s")
            say(f"  ⚠ +Human plugin {name}: setup stopped after {SETUP_TIMEOUT} s; retried later")
        except Exception as exc:  # never fail the update; a later launch retries
            problems.append(f"{name}: {exc}")
            say(f"  ⚠ +Human plugin {name} not updated: {exc}")
    state = _read_state(home)
    if problems:
        state[RETRY_KEY] = (_now() + RETRY_DELAY).isoformat(timespec="seconds")
        _write_state(home, state)
    elif state.pop(RETRY_KEY, None) is not None:
        _write_state(home, state)
    return problems


def _run_worker(home: Path, timeout: int, say: Callable[[str], None]) -> bool:
    """One home in its own process group, so nothing it starts (git, dependency installs, setup) can outlive the
    timeout or hang the caller. Any failure schedules a retry, also a worker that died before recording one."""
    cmd = [sys.executable, "-m", "hermes_cli.plushuman_plugins", "--home", str(home)]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=_child_env(home, own_group=True), start_new_session=True)
    except OSError as exc:
        say(f"  ⚠ +Human plugins in {home}: worker not started ({exc}); retried later")
        _mark_retry(home)
        return False
    with proc:
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.wait()
            say(f"  ⚠ +Human plugins in {home}: stopped after {timeout} s; retried later")
            _mark_retry(home)
            return False
    for line in (out or "").splitlines():
        if line.strip():
            say(line)
    if proc.returncode != 0:
        _mark_retry(home)
        return False
    return True


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # the worker leads its own group (start_new_session)
    except (AttributeError, OSError):  # no process groups here, or already gone
        proc.kill()


def step() -> dict:
    """post_update HOME_STEPS entry, once per revision (desktop-only installs included): the active home. Logs,
    never prints: it runs inside whatever command started first after the update."""
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    if not pending(home):
        return {"ok": True}
    ok = _run_worker(home, BOOT_TIMEOUT, say=logger.info)
    return {"ok": ok} if ok else {"ok": False, "error": "a +Human plugin was not updated; retried later"}


def retry_due() -> None:
    """Every launch: when an earlier attempt failed and its retry time has come, start a detached worker for the
    active home. The usual case reads one small file and returns; never waits, never raises."""
    if os.environ.get(WORKER_ENV):
        return
    try:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home())
        if not _retry_is_due(_read_state(home)):
            return
        with _home_lock(home) as held:
            if not held:  # a worker is already on it
                return
            state = _read_state(home)
            if not _retry_is_due(state):  # another launch claimed it first
                return
            state[RETRY_KEY] = (_now() + RETRY_DELAY).isoformat(timespec="seconds")  # claimed; a clean run clears it
            _write_state(home, state)
        subprocess.Popen(  # this interpreter, this module; the worker takes the lock itself
            [sys.executable, "-m", "hermes_cli.plushuman_plugins", "--home", str(home)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            env=_child_env(home, own_group=True))
    except Exception as exc:  # a retry problem must never reach the command being launched
        logger.debug("+Human plugin retry not started: %s", exc)


def _retry_is_due(state: dict) -> bool:
    due = state.get(RETRY_KEY)
    try:
        return isinstance(due, str) and datetime.fromisoformat(due) <= _now()
    except ValueError:
        return True  # an unreadable time is overdue


def update_all_homes(say: Callable[[str], None] = print) -> None:
    """`plushuman update` maintenance tail: every profile home sharing this venv, each in its own worker."""
    try:
        from pm.plugins_state import dependency_homes

        homes = dependency_homes()
    except Exception as exc:  # the listing is best effort
        say(f"  ⚠ +Human plugins: profile homes not listed ({exc}); the next launch retries")
        return
    manifest = load_manifest()
    for home in homes:
        if pending(Path(home), manifest):
            _run_worker(Path(home), UPDATE_TIMEOUT, say)


@contextmanager
def _home_lock(home: Path) -> Iterator[bool]:
    """Yields False when another worker holds this home (one re-pin at a time); no locking where fcntl is missing."""
    try:
        import fcntl
    except ImportError:
        yield True
        return
    home.mkdir(parents=True, exist_ok=True)
    with open(home / LOCK_FILE, "a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m hermes_cli.plushuman_plugins")
    parser.add_argument("--home", help="profile home (default: the active HERMES_HOME)")
    args = parser.parse_args(argv)
    if args.home:
        os.environ["HERMES_HOME"] = args.home
    os.environ[WORKER_ENV] = "1"
    from hermes_constants import get_hermes_home

    # A worker we started in a group of its own (detached retry, supervised worker) never outlives the longest wait
    # anyone has for it: past UPDATE_TIMEOUT it ends with everything it started. A manual run (a shell pipeline may
    # share its group) never arms this.
    armed = (hasattr(signal, "SIGALRM") and os.environ.pop(GROUP_ENV, "") == "1"
             and os.getpgrp() == os.getpid())
    if armed:
        previous = signal.signal(signal.SIGALRM, lambda *_: os.killpg(os.getpgrp(), signal.SIGKILL))
        signal.alarm(UPDATE_TIMEOUT)
    try:
        with _home_lock(Path(get_hermes_home())) as held:
            if not held:
                print("  +Human plugins: another worker is updating this home")
                return 0
            return 1 if apply_active_home() else 0
    finally:
        if armed:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)


if __name__ == "__main__":
    sys.exit(main())
