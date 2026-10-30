# Known test failures in +Human (vs. upstream Hermes Agent)

+Human (formerly Alfred) is generated from upstream by `alfred-build`. The upstream pytest suite (~45k tests) runs on
every generated tree; the files below fail only because of the rebrand and are accepted as-is.
Everything else that fails on a +Human tree also fails on the pristine upstream tag in the same
environment (network, Docker, macOS-specific launchers, WhatsApp bridge, git update rehearsals).

| Test file | Why it fails | Status |
|---|---|---|
| `tests/scripts/test_release_tags.py` | fixture remaps `https://github.com/NousResearch/` with `pushInsteadOf`; the rebrand rewrites the full repo URL but not the owner-only prefix | upstream release plumbing, not used by +Human |
| `tests/scripts/test_termux_build_driver.py` | Termux (Android) release driver expects the upstream repository and release assets | Termux builds are not shipped by +Human |

Skipped by a codemod (`neutralise_brand_fixtures`), not failing: in
`tests/hermes_cli/test_source_release_channels.py`, `test_selected_draft_never_falls_back_to_other_tags` and
`test_origin_tag_cannot_substitute_a_fork_commit` assume the official repository publishes a release
pointer on hermes-assets; +Human publishes none and resolves its stable release from GitHub's latest.

Removed from the tree (they test the upstream GitHub workflows or the docs site, both replaced):
`tests/ci/`, `tests/website/`, `tests/scripts/test_dispatch_log.py`.
