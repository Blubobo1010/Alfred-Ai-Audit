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

## No page of upstream's site inside the app (since 0.21.712)

The Plugins tab, the Skills tab and Bot Mode embedded pages of upstream's documentation site as one-click
catalogues. +Human lists what is installed; the embedded pages and their tests are gone:
- removed: `apps/desktop/src/plugins/hermes-bots/skills-hub-picker.test.tsx`;
- skipped by a codemod: four tests of the catalogue pane in
  `apps/desktop/src/app/capabilities/plugins/plugins-tab.test.tsx` and the two hub picker tests in
  `apps/desktop/src/app/capabilities/index.test.tsx`;
- adjusted: `apps/desktop/src/plugins/hermes-bots/profile-config-capabilities.test.tsx` expects no hub section.

The plugin catalog is the one in the tree: upstream's published document is not fetched unless
`HERMES_LIVE_PLUGIN_CATALOG=1`. `tests/conftest.py` sets it, so upstream's tests of that path still run;
`tests/hermes_cli/test_plugin_catalog_plushuman.py` covers the shipped default.
