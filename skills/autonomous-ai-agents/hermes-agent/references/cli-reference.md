# +Human CLI Reference

Live sources when anything looks stale: `plushuman --help`, `plushuman <command> --help`,
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
plushuman chat [flags]
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
plushuman setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
plushuman model                Interactive model/provider picker
plushuman fallback [add|remove|list]  Fallback provider chain
plushuman config [show|edit|get|set|unset|path|env-path|check|migrate]
plushuman login / logout       OAuth sign-in / clear stored auth
plushuman doctor [--fix]       Check dependencies and config
plushuman status [--full]      Component summary (--full: every section)
```

### Tools & Skills

```
plushuman tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

plushuman skills list|browse|search QUERY|inspect ID
plushuman skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
plushuman skills config        Enable/disable skills per platform
plushuman skills check|update|uninstall|publish PATH
plushuman skills tap add REPO  Add a GitHub repo as a skill source
plushuman bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
plushuman mcp add NAME (--url or --command) | remove | list | test NAME
plushuman mcp catalog | install NAME     Curated catalog install
plushuman mcp configure NAME             Toggle tool selection
plushuman mcp serve                      Run +Human as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
plushuman gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `hermes photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
plushuman sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
plushuman cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
plushuman webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
plushuman profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
plushuman profile rename A B | alias NAME | export NAME | import FILE
plushuman profile migrate-identity A B   Retry a completed rename's session/routing identity migration
```

### Credentials & Pools

```
plushuman auth                 Interactive credential manager
plushuman auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
plushuman auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
plushuman desktop / gui        Native desktop app
plushuman dashboard            Web admin panel + embedded chat (--stop / --status)
plushuman proxy                OpenAI-compatible local proxy backed by an OAuth provider
plushuman portal               Quick setup / sign in via Nous Portal
plushuman kanban <verb>        Multi-agent work-queue board
plushuman project              Named multi-folder workspaces
plushuman skin list|use|set    Switch/tweak skins (see references/themes.md)
plushuman pets <verb>          Pet mascots (see references/petdex.md)
plushuman memory setup|status|off|reset   Memory provider
plushuman secrets bitwarden|onepassword   External secret stores
plushuman moa                  Mixture-of-Agents slots
plushuman hooks / security / backup / import / checkpoints / console
plushuman logs [-f] [errors]   View agent/error logs
plushuman send                 One-off message through a gateway platform
plushuman pairing / plugins / insights / journey / computer-use
plushuman acp                  ACP server (IDE integration)
plushuman completion bash|zsh|fish
plushuman update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `hermes photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `plushuman config edit` · [Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| Tools / toolsets | `plushuman tools list` · [Tools reference](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| Skills catalog | `plushuman skills browse` · [Skills catalog](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `plushuman model` · [Providers guide](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| Env variables | `plushuman config env-path` · [Env vars reference](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| Gateway logs | `~/.hermes/logs/gateway.log` (or `plushuman logs`) |
| Sessions | `plushuman sessions browse` (reads state.db) |
