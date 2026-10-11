# Alfred

Alfred is a personal AI agent that runs the same core across a CLI, a terminal UI, a native
macOS desktop app and messaging gateways (Telegram, WhatsApp, Discord, Slack and more). It
learns across sessions, delegates to sub-agents, runs scheduled jobs and is extended through
plugins and skills.

Alfred is a white-label build of [Hermes Agent](https://github.com/NousResearch/hermes-agent)
by Nous Research (MIT). Every release of Alfred is generated from an upstream Hermes release;
the upstream tag and commit are recorded in each Alfred commit message and release notes.

## Install

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Blubobo1010/Alfred-Ai-Audit/main/scripts/install.sh | bash
```

Add `--include-desktop` to also build the desktop app from source. Windows (PowerShell):

```powershell
iex (irm https://raw.githubusercontent.com/Blubobo1010/Alfred-Ai-Audit/main/scripts/install.ps1)
```

Then run `alfred` (or `alfred setup` for the guided setup). Every `hermes <command>` from the
Hermes documentation is available as `alfred <command>`; the `hermes` command keeps working as
an alias.

### macOS desktop app

Signed and notarized builds are published on the
[Releases](https://github.com/Blubobo1010/Alfred-Ai-Audit/releases) page as
`AlfredBundled-<version>-mac-arm64.dmg`. The app updates itself from the same releases; the backend
updates with `alfred update`.

### Switching an existing Hermes install to Alfred

Re-run the installer with the repository pointed at Alfred; the checkout keeps its data and
simply changes origin:

```bash
HERMES_REPO_URL=https://github.com/Blubobo1010/Alfred-Ai-Audit.git \
  bash <(curl -fsSL https://raw.githubusercontent.com/Blubobo1010/Alfred-Ai-Audit/main/scripts/install.sh)
```

## Plugins

Alfred installs plugins straight from git:

```bash
alfred plugins install Blubobo1010/alfred-odoo --enable   # Odoo CRM, read-only
```

## Documentation

The [Hermes documentation](https://hermes-agent.nousresearch.com/docs) applies to Alfred
unchanged (configuration, gateways, plugins, skills). Alfred-specific issues go to
[this repository's issue tracker](https://github.com/Blubobo1010/Alfred-Ai-Audit/issues).

## License

MIT. Copyright (c) 2025 Nous Research for the Hermes Agent code; see `LICENSE`.
Alfred branding © 2026 Ai-Audit. Based on Hermes Agent.
