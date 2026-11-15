# Workstation clients

The coding-agent side of the stack (`docs/stack-design.md` §7): OpenCode configured against the
LiteLLM gateway on TrueNAS, the owner's working style as agents and commands, a guard plugin,
the MCP tools, the SSH tool, Claude Code as a second path, and project-memory templates.

**Nothing here runs full time.** Every service of the stack runs as a container on TrueNAS.
On a workstation, OpenCode is only the command you start, the way you start Claude Code today:
`install.sh` turns off OpenCode's shared background service (`opencode service set disabled
true`), so each `opencode` runs its own server and stops it when it exits. The SSH tool,
`ssh-mcp`, is a stdio child process that OpenCode starts for a session and stops with it. No
`opencode serve`, no systemd unit, no launchd agent, no `opencode pair`.

| Path | What it is | Installed as |
|---|---|---|
| `opencode/opencode.jsonc` | provider `local`, models, limits, policies, permissions, MCP servers | link `~/.config/opencode/opencode.jsonc` |
| `opencode/agents/*.md` | `coordinator` (default), `researcher`, `builder`, `reviewer` | links in `~/.config/opencode/agents/` |
| `opencode/commands/*.md` | `/plan`, `/issue`, `/pr`, `/check` | links in `~/.config/opencode/commands/` |
| `opencode/plugins/guard.ts` | refuses pushes to main, secrets in files, wiping commands | link `~/.config/opencode/plugins/guard.ts` |
| `ssh-mcp/config.example.toml` | deny-by-default SSH policy, one example host | copied once to the ssh-mcp config path |
| `ssh-mcp/ssh-mcp-stdio` | how OpenCode starts ssh-mcp (strict host keys, audit log) | link `~/.local/bin/ssh-mcp-stdio` |
| `claude-code/settings.json` | Claude Code settings for the local gateway | read by `claude-local` only |
| `claude-code/claude-local` | runs `claude --settings ...` for one session | link `~/.local/bin/claude-local` |
| `templates/AGENTS.md`, `templates/CLAUDE.md` | project memory for a new repository | copy by hand |
| `install.sh` | installs and links all of the above | run from the clone |

Pinned: OpenCode **2.3.0** (sha512 per platform in `install.sh`), ssh-mcp **2.26.0**.

## Install (c4dev and the Mac)

1. Clone this repository. The links point into the clone, so keep it where it is.
2. Preview, then install:

   ```sh
   clients/install.sh --dry-run
   clients/install.sh
   ```

   It installs OpenCode into `~/.opencode/bin` (the npm package and location the official
   installer uses, checked against a pinned sha512), disables the background service, links the
   files above, creates `~/.config/local-agent-stack/client.env` (mode 600) once, installs ssh-mcp
   if Node.js 20.6+ is present, and adds a marked block to `~/.bashrc` or `~/.zshrc` that loads
   `client.env` and puts `~/.opencode/bin` and `~/.local/bin` on `PATH`. Any file of yours it
   would replace is kept as `<name>.bak.<time>`. Options: `--no-shell-rc`, `--no-opencode`,
   `--no-ssh-mcp`. Running it again changes nothing that is already right.
3. Put your values into `~/.config/local-agent-stack/client.env`:

   ```sh
   LAB_DOMAIN=lab.example.com         # your domain: OpenCode uses https://llm.$LAB_DOMAIN/v1
   LOCAL_LLM_KEY=sk-local-...         # a LiteLLM virtual key for this user
   MCP_HUB_TOKEN=...                  # the MCP hub token (web.env on the NAS)
   ```

   The shell block exports these to every process of your shell; OpenCode reads them with
   `{env:...}`. Use a LiteLLM virtual key with a budget, never the master key.
4. Open a new terminal and verify:

   ```sh
   opencode --version                          # opencode v2.3.0
   opencode service get disabled               # true
   cd ~/projects/some-repo && opencode models  # local/local-coder, local/local-coder-moe, local/local-fast only
   curl -s -H "Authorization: Bearer $LOCAL_LLM_KEY" https://llm.$LAB_DOMAIN/v1/models | head -c 300
   opencode mcp list                           # searxng, fetch, kb connected; ssh disabled
   opencode run "Reply with the word OK."      # OK, from local-coder
   ```

**The Mac** runs its own OpenCode CLI against `https://llm.<your domain>` with the same
install (the script handles macOS), or you `ssh c4dev` and run `opencode` there. On either
machine nothing of OpenCode keeps running after you exit it.

## What the configuration does

- **One provider.** `local` (`@opencode/ai/providers/openai-compatible`) at
  `https://llm.{env:LAB_DOMAIN}/v1`, key `{env:LOCAL_LLM_KEY}`. Models `local-coder` (default,
  64K context), `local-fast` (same model, thinking off: session titles), `local-coder-moe`
  (swaps the GPU model; use it for a whole session). A policy denies every other provider, and
  `websearch: false` plus a `websearch.use` policy remove the paid search tool.
- **No phone-home.** `update: "disable"`, `share: "disabled"`, and the shell block sets
  `OPENCODE_DISABLE_MODELS_FETCH=1` (no models.dev download) and `OPENCODE_DISABLE_FREE_MODELS=1`.
- **Agents.** `coordinator` is the default: it plans, writes the contract, starts at most 2-3
  subagents, integrates, runs the checks and is the only one that commits or pushes.
  `builder` edits only the files its brief names and cannot run git or gh. `researcher` reads
  code, docs and the web and can write only under `docs/`. `reviewer` cannot edit. One GPU serves
  every agent, so the coordinator runs at most 2 at a time (3 for short research). An agent's
  Markdown body replaces OpenCode's base system prompt for that agent, so each body restates the
  few harness rules that matter (read before edit, exact old text).
- **Commands.** `/plan` (read-only plan with the `plan` agent), `/issue N` (read the issue,
  branch, contract), `/pr` (checks, changelog line, push the branch by name, open the PR),
  `/check` (run `tools/check.sh`). `/issue` and `/check` put your arguments into a shell line
  that runs before the prompt; type only issue numbers and check names there.
- **Guard and policies.** `guard.ts` refuses: pushing to main or master, `--all`/`--mirror`, and
  any push that does not name its branch; writing `.env`, key and credential files or text that
  contains a private key or token; `rm -r` of `/`, `~`, system, home or pool directories or the
  whole working tree, `--no-preserve-root`, `mkfs`, `dd` onto a device, fork bombs. The model sees
  the reason and what to do instead. The `policies` in `opencode.jsonc` repeat the simplest forms;
  global policies cannot be loosened by a project's config, while a project could disable the
  plugin. Permissions ask before any shell command except read-only git and gh, deny `sudo`, deny
  reading `.env` files, ask before touching paths outside the project, and turn off Code Mode so
  MCP tools are plain tools.
- **MCP.** `searxng`, `fetch` and `kb` from the hub at
  `https://mcp.{env:LAB_DOMAIN}/servers/<name>/mcp` with `Authorization: Bearer {env:MCP_HUB_TOKEN}`
  (no OAuth). `ssh` is configured but disabled until you set it up (below).

## The SSH tool

ssh-mcp reaches only the hosts listed in its policy file and refuses every call until that file
exists; destructive and privileged commands need your approval, which OpenCode shows as a form
(MCP elicitation). Never list the TrueNAS host itself.

1. Make a key only for the agent: `ssh-keygen -t ed25519 -f ~/.ssh/agent_ed25519 -C agent@c4dev`.
   OpenCode starts ssh-mcp without a terminal, so it cannot ask for a passphrase; restrict the key
   on each host instead (`restrict,from="192.0.2.20"` in `authorized_keys`, a non-root `agent`
   user, see `docs/research/d-gui-rag-search.md` D5). To use an agent socket that holds only this
   key, set `SSH_MCP_AUTH_SOCK`; `ssh-mcp-stdio` never passes your own `SSH_AUTH_SOCK` on.
2. Edit the policy (`~/.config/ssh-mcp/config.toml`, on macOS
   `~/Library/Application Support/ssh-mcp/config.toml`): host, user, `keyRef`, and pin the host key
   with `trustedHostKey` from `ssh-keyscan -t ed25519 <host> | ssh-keygen -lf -`. The launcher runs
   `--hostKeyMode=strict`, so an unpinned key is refused.
3. Enable the server in the project that needs it, in its `opencode.jsonc` (a project entry
   replaces the whole global entry, so repeat every field):

   ```jsonc
   { "mcp": { "servers": { "ssh": {
     "type": "local", "command": ["{env:HOME}/.local/bin/ssh-mcp-stdio"], "codemode": false
   } } } }
   ```

4. Verify: `opencode mcp list` shows `ssh` connected; ask the agent to run `list-connections`.
   The audit log is `~/.local/share/ssh-mcp/` (hash-chained).

## Claude Code against the local gateway

`claude-local` runs Claude Code for one session with `clients/claude-code/settings.json` (your
`LAB_DOMAIN` put in place of `lab.example.com`, passed with `claude --settings`). Your normal
`claude` and `~/.claude/settings.json` stay on Anthropic. The settings point `ANTHROPIC_BASE_URL`
at `https://llm.<domain>` (LiteLLM serves `/v1/messages`), map the opus, sonnet and haiku aliases to
`local-opus`, `local-sonnet` and `local-haiku`, declare the 64K window
(`CLAUDE_CODE_MAX_CONTEXT_TOKENS`; otherwise Claude Code assumes 1M for unknown model IDs), cap
output at 16384 tokens, turn off nonessential traffic and telemetry, skip the WebFetch preflight
to api.anthropic.com, and get the key from `client.env` through `apiKeyHelper`.

Limits (`docs/research/b-inference.md` §4.4): Anthropic does not support Claude Code on non-Claude
models; WebSearch, Remote Control and fast mode do not work; tool use is weaker than on Claude;
expect frequent compaction at 64K. Pin the Claude Code version you tested.

## New projects

Copy `templates/AGENTS.md` (and `templates/CLAUDE.md` if you also use Claude Code) to the root
of the repository and fill in the capitalised placeholders. Keep `AGENTS.md` under 150 lines: it
is sent with every request. OpenCode reads `AGENTS.md`; `CLAUDE.md` imports it with `@AGENTS.md`.

## Security notes

- OpenCode has no sandbox: its shell runs with your user's rights. The guard, the policies and
  the `ask` rules are the fence; for untrusted code use a separate user or a container.
- OpenCode runs any `.opencode/plugins/*.ts` in a repository it opens. Read a repository's
  `.opencode/` before you run OpenCode in it.
- The certificate for `*.<domain>` comes from Let's Encrypt (DNS-01), so no private CA needs
  trusting on clients.

## Updating

Change `OPENCODE_VERSION` (and every sha512 from `https://registry.npmjs.org/@opencode/cli-<target>/<version>`,
field `dist.integrity`) or `SSH_MCP_VERSION` in `install.sh`, re-check the config keys against the
release notes, and run `install.sh` again. `opencode upgrade` is not used: `update` is disabled.
