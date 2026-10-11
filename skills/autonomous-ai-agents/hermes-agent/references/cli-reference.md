# Alfred CLI Reference

Live sources when anything looks stale: `alfred --help`, `hermes <command> --help`,
https://hermes-agent.nousresearch.com/docs/reference/cli-commands

### Global Flags

```
hermes [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
alfred chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
alfred setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
alfred model                Interactive model/provider picker
alfred fallback [add|remove|list]  Fallback provider chain
alfred config [show|edit|get|set|unset|path|env-path|check|migrate]
alfred login / logout       OAuth sign-in / clear stored auth
alfred doctor [--fix]       Check dependencies and config
alfred status [--full]      Component summary (--full: every section)
```

### Tools & Skills

```
alfred tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

alfred skills list|browse|search QUERY|inspect ID
alfred skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
alfred skills config        Enable/disable skills per platform
alfred skills check|update|uninstall|publish PATH
alfred skills tap add REPO  Add a GitHub repo as a skill source
alfred bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
alfred mcp add NAME (--url or --command) | remove | list | test NAME
alfred mcp catalog | install NAME     Curated catalog install
alfred mcp configure NAME             Toggle tool selection
alfred mcp serve                      Run Alfred as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
alfred gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `hermes photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
alfred sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
alfred cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
alfred webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
alfred profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
alfred profile rename A B | alias NAME | export NAME | import FILE
alfred profile migrate-identity A B   Retry a completed rename's session/routing identity migration
```

### Credentials & Pools

```
alfred auth                 Interactive credential manager
alfred auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
alfred auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
alfred desktop / gui        Native desktop app
alfred dashboard            Web admin panel + embedded chat (--stop / --status)
alfred proxy                OpenAI-compatible local proxy backed by an OAuth provider
alfred portal               Quick setup / sign in via Nous Portal
alfred kanban <verb>        Multi-agent work-queue board
alfred project              Named multi-folder workspaces
alfred skin list|use|set    Switch/tweak skins (see references/themes.md)
alfred pets <verb>          Pet mascots (see references/petdex.md)
alfred memory setup|status|off|reset   Memory provider
alfred secrets bitwarden|onepassword   External secret stores
alfred moa                  Mixture-of-Agents slots
alfred hooks / security / backup / import / checkpoints / console
alfred logs [-f] [errors]   View agent/error logs
alfred send                 One-off message through a gateway platform
alfred pairing / plugins / insights / journey / computer-use
alfred acp                  ACP server (IDE integration)
alfred completion bash|zsh|fish
alfred update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `hermes photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `alfred config edit` · [Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| Tools / toolsets | `alfred tools list` · [Tools reference](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| Skills catalog | `alfred skills browse` · [Skills catalog](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `alfred model` · [Providers guide](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| Env variables | `alfred config env-path` · [Env vars reference](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| Gateway logs | `~/.hermes/logs/gateway.log` (or `alfred logs`) |
| Sessions | `alfred sessions browse` (reads state.db) |
