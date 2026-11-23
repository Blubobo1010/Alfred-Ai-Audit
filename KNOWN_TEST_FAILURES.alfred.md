# Known test failures in +Human (vs. upstream Hermes Agent)

+Human (formerly Alfred) is generated from upstream by `alfred-build`. Upstream's suites run on the generated
tree next to pristine upstream at the same tag (`python -m rebrand trial`, workflows in `ops/trial/` of
alfred-build); what fails on the +Human tree only is either fixed in the generator or listed here with its reason.

Last compared: upstream v0.23.3 (about 92,000 Python tests, 2,480 JS test files), 2026-11-23.

## Python suite

`alfred-ci.yml` with `full-suite` reads this table (`scripts/alfred/known_failures.py`): a slice fails on a test
file without a row, or with more failing tests than its row says. Keep one row per file, the path in backticks.

| Test file | Failing | Why it fails |
|---|---|---|
| `tests/gateway/test_multiplex_api_server_routing.py` | 4 | the fixture spells the default profile's handle `Hermes` (handle `hermes`, kept); the rebrand turns the spelling into the product name |
| `tests/hermes_cli/test_peer_cmd.py` | 2 | same `Hermes` handle spelling, in peer targets (`box/Hermes`) |
| `tests/gateway/test_command_caption_document_text.py` | 1 | the Feishu fixture names the bot after the product; upstream renders a mention markdown-escaped (`@\+Human`) but strips it by the raw name, so a bot name with a markdown character is not recognised (upstream bug, any such name) |
| `tests/gateway/test_restart_drain.py` | 1 | the detached restart runs the `hermes` launcher (kept, always installed); the test expects the product CLI |
| `tests/hermes_cli/test_gateway_runtime_ensure.py` | 1 | same: the gateway child is started through the `hermes` launcher |
| `tests/tools/test_bot_mode_dm.py` | 6 | same: deliveries run the `hermes` launcher, the expected argv lists were rewritten to the product CLI |
| `tests/hermes_cli/test_plugin_manifest_v2.py` | 1 | the message now reads `requires plushuman >=…`; the test pins `requires hermes >=…` |
| `tests/hermes_cli/test_update_fetch_failure_classifier.py` | 1 | pins upstream's installer URL; +Human points at its own installer |
| `tests/gateway/test_estop_interactive_turns.py` | 1 | reads the docs site (`website/`, kept pristine and not shipped) for a `plushuman pause` row |
| `tests/hermes_cli/test_gateway_command_parity.py` | 1 | compares a page generated from rebranded sources with its pristine copy under `website/` |
| `tests/hermes_cli/test_plugin_validate_private_imports.py` | 1 | same, for the plugin API page |
| `tests/tools/test_skills_hub.py` | 2 | bundled skills keep upstream's repository as their source (skills.sh namespace); the fixtures were rewritten to the fork |
| `tests/tools/test_skills_upstream_provenance.py` | 1 | same |
| `tests/scripts/test_release_artifacts.py` | 3 | reads upstream's release workflows, which +Human replaces with its own |
| `tests/scripts/test_termux_build_driver.py` | 2 | Termux (Android) release driver: reads the same workflows; Termux builds are not shipped |
| `tests/scripts/test_release_tags.py` | 1 | fixture remaps `https://github.com/NousResearch/` with `pushInsteadOf`; the rebrand rewrites the full repo URL but not the owner-only prefix |
| `tests/hermes_cli/test_session_recovery_lost_and_found.py` | 1 | fails on pristine upstream too on GitHub's runners (their `sqlite3` CLI) |
| `tests/tools/test_approval_windows.py` | 2 | fails on pristine upstream too on GitHub's 4-core runners (a linear-time bound) |

Adjusted by a codemod instead of failing:
- `tests/hermes_cli/test_source_release_channels.py`: `test_selected_draft_never_falls_back_to_other_tags` and
  `test_origin_tag_cannot_substitute_a_fork_commit` are skipped. They assume the official repository publishes a
  release pointer on hermes-assets; +Human publishes none and resolves its stable release from GitHub's latest.
- `tests/gateway/test_journey_compress_restart_fifo.py`: compression budget 13000 instead of 12000 tokens. The
  journey is tuned to the size of upstream's prompt; +Human's persona is longer.
- Fixtures that only happen to spell the product name or the launcher: see `neutralise_brand_fixtures` in
  alfred-build's `rebrand/codemods.py`.

Removed from the tree (they test upstream's GitHub workflows, its release plumbing or the docs site, all
replaced): `tests/ci/`, `tests/website/`, `tests/scripts/test_dispatch_log.py`,
`tests/scripts/test_termux_commit_identity.py`, `tests/scripts/test_commit_bundle_entrypoints.py`,
`tests/scripts/test_desktop_build_cache.py`, `tests-js/setup-pm-cache.test.mjs`.

On macOS a few more files fail on any tree, pristine included (no `/proc`, launchd fixtures): judge on Linux.
