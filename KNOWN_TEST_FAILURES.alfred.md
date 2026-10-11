# Known test failures in Alfred (vs. upstream Hermes Agent)

Alfred is generated from upstream by `alfred-build`. The upstream pytest suite (~45k tests) runs on
every generated tree; the files below fail only because of the rebrand and are accepted as-is.
Everything else that fails on an Alfred tree also fails on the pristine upstream tag in the same
environment (network, Docker, macOS-specific launchers, WhatsApp bridge, git update rehearsals).

| Test file | Why it fails | Status |
|---|---|---|
| `tests/scripts/test_release_tags.py` | fixture remaps `https://github.com/NousResearch/` with `pushInsteadOf`; the rebrand rewrites the full repo URL but not the owner-only prefix | upstream release plumbing, not used by Alfred |
| `tests/scripts/test_termux_build_driver.py` | Termux (Android) release driver expects the upstream repository and release assets | Termux builds are not shipped by Alfred |
| `tests/scripts/test_icon_flavors.py::test_layered_macos_icon_mono_layer_and_flavor_stays_in_the_fill` | the placeholder top-hat artwork has no grayscale mono layer tones | fixed by real Alfred artwork (`alfred-build/overlays/assets/`) |

Removed from the tree (they test the upstream GitHub workflows or the docs site, both replaced):
`tests/ci/`, `tests/website/`, `tests/scripts/test_dispatch_log.py`.
