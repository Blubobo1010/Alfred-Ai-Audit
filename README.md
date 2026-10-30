# +Human

+Human is a personal AI assistant for owners and professionals. The same core runs across a CLI, a
terminal UI, a native macOS desktop app and messaging gateways (Telegram, WhatsApp, Discord, Slack and
more). It learns across sessions, delegates to sub-agents, runs scheduled jobs and is extended through
plugins and skills. Each customer gives the assistant its own name.

+Human is a white-label build of [Hermes Agent](https://github.com/NousResearch/hermes-agent)
by Nous Research (MIT). Every +Human release is generated from an upstream Hermes release;
the upstream tag and commit are recorded in each commit message and in the release notes.

## Install

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Blubobo1010/Alfred-Ai-Audit/main/scripts/install.sh | bash
```

Add `--include-desktop` to also build the desktop app from source. Windows (PowerShell):

```powershell
iex (irm https://raw.githubusercontent.com/Blubobo1010/Alfred-Ai-Audit/main/scripts/install.ps1)
```

Then run `plushuman` (or `plushuman setup` for the guided setup). Every `hermes <command>` from the
Hermes documentation is available as `plushuman <command>`; the `hermes` command keeps working as
an alias, and so does `alfred`, the command of earlier releases.

### macOS desktop app

Signed and notarized builds are published on the
[Releases](https://github.com/Blubobo1010/Alfred-Ai-Audit/releases) page as
`AlfredBundled-<version>-mac-arm64.dmg` (the file name predates the +Human name and stays, so existing
installs keep updating). The app updates itself from the same releases; the backend updates with
`plushuman update`.

### Switching an existing Hermes install to +Human

Re-run the installer with the repository pointed at this one; the checkout keeps its data and
simply changes origin:

```bash
HERMES_REPO_URL=https://github.com/Blubobo1010/Alfred-Ai-Audit.git \
  bash <(curl -fsSL https://raw.githubusercontent.com/Blubobo1010/Alfred-Ai-Audit/main/scripts/install.sh)
```

## Plugins

+Human's own plugins (second brain, Microsoft 365, Odoo CRM) are provided to customers with their
installation and are kept at the reviewed version by `plushuman update`.

## Documentation

The [Hermes documentation](https://hermes-agent.nousresearch.com/docs) applies to +Human
unchanged (configuration, gateways, plugins, skills). +Human-specific issues go to
[this repository's issue tracker](https://github.com/Blubobo1010/Alfred-Ai-Audit/issues).

## License

MIT. Copyright (c) 2025 Nous Research for the Hermes Agent code; see `LICENSE`.
+Human branding © 2026 Ai-Audit. Based on Hermes Agent.
