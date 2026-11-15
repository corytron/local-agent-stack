# Agent harnesses that play Claude Code's role on local models

Status: research, 2026-11-15. Author: research agent C.

## Summary

- **Primary harness: OpenCode V2 (2.3.0, MIT)**, on both c4dev and the Mac. It has the
  smallest prompt of the full-featured harnesses: 5.3k tokens measured for the first request,
  against 9.4k to 11.4k for Codex, Qwen Code and Claude Code. It talks plain OpenAI Chat
  Completions to a custom provider with declared context limits. It covers almost every Claude
  Code feature natively: per-agent models and permission rules, background subagents, a plan
  agent, commands, skills, MCP over stdio and HTTP, worktrees, compaction, headless `opencode run`,
  and a client/server design. That design lets the Mac's TUI, web UI or desktop app drive
  sessions that run on c4dev.
- **Secondary harness: Qwen Code (0.27.4, Apache-2.0).** It is the closest open clone of Claude
  Code. Its hooks use Claude Code's JSON protocol and accept Claude tool names. Its subagent
  Markdown matches Claude Code's (`model: fast`, `tools`, `approvalMode`, background by default).
  It also has a bubblewrap/Landlock shell sandbox, `--worktree`, a GitHub Action and a `fastModel`.
  Use it where Claude-format hooks must run unchanged, or where an OS sandbox is wanted. It
  costs more prompt (9.7k tokens measured) and sends usage statistics until you turn them off.
- **Claude Code against the local endpoint works but is not recommended as primary.** It works
  through LiteLLM's Anthropic `/v1/messages` route: in v2.1.325, `claude -p` finished a turn
  against a fake endpoint. Anthropic's own gateway docs say it does not support routing Claude
  Code to non-Claude models. It sends Anthropic-only request fields (`thinking`,
  `context_management`, `output_config`). It assumes a 1M-token window for unknown model IDs
  unless you set `CLAUDE_CODE_MAX_CONTEXT_TOKENS`. WebSearch needs LiteLLM's search interception,
  and Remote Control is disabled behind a non-Anthropic base URL. Keep it as a fallback that
  reuses the existing `.claude/` setup unchanged.
- **Codex CLI (0.169.0, Apache-2.0)** has a strong sandbox and Claude-compatible hooks, but it
  speaks only the Responses API (`wire_api = "responses"` is the only value). It also sends
  OpenAI-only tool types: a `namespace` tool group and a hosted `web_search` tool. So it depends
  on LiteLLM translating those correctly for a local model, which is a third-choice risk.
- **For very weak models, Pi (1.5.2, MIT) is the minimal fallback:** 1.3k-token first request,
  4 tools, MCP built in. It has no subagents, plan mode or permission system. **Goose (1.59.1)**
  has a "tool shim" for models that emit text tool calls.
- **Dead or stale; do not adopt:** Roo Code (repo archived 2026-05-15), Continue (acquired by
  Cursor, last release June 2026), OpenHands CLI (README says no longer maintained), Plandex
  (cloud wound down, last release July 2025), legacy Kimi CLI (archived). Aider (last release
  0.86.2, 2026-02-12) is stable but frozen and has no agent loop, MCP or subagents.
- **Prompt budget matters more than harness choice.** The owner's current memory files total
  about 33 KB, roughly 8k tokens, more than any harness's own prompt. They are re-sent on every
  request and every parallel subagent. Trim `AGENTS.md` to always-true rules and move the rest
  into skills.
- **Working style transfers with adjustments:**
  - Contracts in `docs/`, a coordinator, and background workers with read-only researchers map
    directly onto OpenCode subagents plus permission rules.
  - The PreToolUse rule hook becomes a small OpenCode plugin. It calls the same shell script.
  - "Parallel by default" must be capped at 2 to 3 concurrent agents, because all of them share
    one 16 GB GPU.
- **Security:**
  - OpenCode has no OS sandbox, so run it as an unprivileged user or in its official container
    (`ghcr.io/anomalyco/opencode:2.3.0`).
  - Add hard-deny `policies` and permission rules on top.
  - OpenCode documents no telemetry: turn off updates and the models.dev catalog fetch.
  - Qwen Code, Codex and Claude Code each need an explicit telemetry opt-out, listed below.

## Recommendation

**Install OpenCode V2 as the primary harness on c4dev**, configured against the OpenAI-compatible
endpoint `http://192.0.2.10:4000/v1`:

- One custom provider `local`, with models `local-coder` (main) and `local-fast` (title
  generation, read-only scouts).
- Real context limits declared on both models.
- Built-in web search off. Search goes through the SearXNG MCP server, and fetch uses the
  built-in `webfetch` tool.
- Provider policy locked to `local`.
- Updates and the models.dev catalog fetch disabled.
- Project rules in `AGENTS.md`.
- Custom agents in `.opencode/agents/`.
- A plugin that bridges the existing PreToolUse shell script into OpenCode's permission hook.

On the Mac, choose one of two setups:

- Install OpenCode and SSH into c4dev to run it there, which is closest to today's habit.
- Or run the OpenCode service on c4dev and attach the Mac's TUI, browser or desktop app through
  an SSH tunnel.

The Mac can also run OpenCode locally against the same endpoint for Mac-side work.

**Install Qwen Code as the secondary harness** on c4dev, for three uses:

1. CI and scripted runs where the Claude-format hook script must run unchanged.
2. Work that should run inside its bubblewrap sandbox.
3. A second opinion with a Qwen-tuned prompt, if agent A picks a Qwen-family model.

Keep **Claude Code** pointed at the local endpoint only as a compatibility fallback. Do not build
the guide around it.

Reasoning, weighted for weak local models:

- **Prompt size:** see the measured table in Details. Every token of fixed prefix is
  prefilled on each cache miss and for every new subagent context. One home-lab write-up
  measured 360 to 624 prefill tokens per second for Qwen3.6-27B on a 22 GB card, so a 17k-token
  tool block cost 28 to 48 s per miss [S41]. OpenCode is about half the prefix of Qwen Code,
  Codex and Claude Code, and keeps the feature set; Pi is smaller but has no subagents or
  permissions.
- **Wire format:**
  - OpenCode, Qwen Code, Pi, Goose, Crush and Cline use Chat Completions, which every local
    server and LiteLLM serve natively.
  - Codex needs `/v1/responses` and Claude Code needs `/v1/messages`. Both rely on LiteLLM
    translation and on it dropping provider-specific fields.
- **Tool-call robustness:**
  - All the candidates rely on native tool calling.
  - OpenCode and Qwen Code let you declare per-model capabilities. OpenCode has
    `compatibility.reasoningField` for `reasoning_content` streams. Both let you cut the declared
    tool set: OpenCode by permission rules and turning off Code Mode, Qwen Code through
    `tools.eager` and `tools.disabled`.
  - Edit format is exact-match `oldString`/`newString` in OpenCode, Qwen Code, Pi and Claude
    Code. Codex uses an `apply_patch` grammar, which weak models break more often (assumed from
    the format, not tested).
- **Licence and control:** OpenCode is MIT and runs as a documented server with an official
  container image. Claude Code is proprietary and its gateway use with non-Claude models is
  explicitly unsupported.

## Options compared

| Option | What it is | Fit for this hardware (16 GB GPU, local models) | Maturity (2026-11-15) | Licence | Verdict |
|---|---|---|---|---|---|
| OpenCode V2 | Terminal/web/desktop agent with a background server; custom agents, plugins, MCP | Best: 5.3k-token first request; Chat Completions; declares context and tool capability per model | v2.3.0 released 2026-11-13; V2 since Oct 2026 (new major, some churn); ~227k stars | MIT | **Primary** |
| Qwen Code | Fork of Gemini CLI, now a near-complete Claude Code clone | Good: 9.7k tokens; Qwen-tuned; deferred tools via `tool_search`/`tool_call` bridge (may confuse weak models) | v0.27.4 released 2026-11-15; very fast release cadence | Apache-2.0 | **Secondary** |
| Claude Code via LiteLLM | The original, with `ANTHROPIC_BASE_URL` pointed at the gateway | Workable: 11.4k tokens headless (third-party interactive figure about 33k); 1M assumed window unless overridden; Anthropic-only request fields | v2.1.325; non-Claude routing unsupported by vendor | Proprietary | Fallback only |
| Codex CLI | OpenAI's Rust agent | Workable via LiteLLM `/v1/responses`; 9.4k tokens; GPT-tuned prompt and tools | v0.169.0 released 2026-11-13 | Apache-2.0 | Not chosen (Responses-only) |
| Pi | Minimal agent: 4 tools, extensions, MCP | Best for very weak models (1.3k tokens) | v1.5.2 released 2026-11-10 | MIT | Optional tool for quick tasks |
| Goose | MCP-first agent from AAIF (Linux Foundation) | Good; tool shim for text-format tool calls; telemetry off by default | v1.59.1 released 2026-11-14 | Apache-2.0 | Alternative |
| Crush | Charm's TUI agent; LSP; Claude-compatible hooks; background subagents | Good; `litellm` and `llamacpp` provider types | v0.101.0 released 2026-11-12 | FSL-1.1-MIT (source-available, not OSI) | Alternative (licence) |
| Kilo Code CLI | Fork of OpenCode inside the Kilo platform, plus VS Code/JetBrains | As OpenCode | v7.8.27 released 2026-11-05 | MIT | Only for the VS Code/JetBrains need |
| Cline (CLI, VS Code, Desktop) | IDE-first agent with CLI and SDK; Desktop over SSH | Fair; "Compact Prompt" for local models disables MCP | CLI tag v4.1.26 (2026-10-26) | Apache-2.0 | IDE option |
| Hermes Agent | General personal agent (messaging gateway, cron, SSH/Docker terminal backends) | Not a coding-first harness | v0.23.1 released 2026-11-10 | MIT | Out of scope; noted for SSH backends |
| Mistral Vibe | Mistral's CLI | Not evaluated in depth | v3.1.2 released 2026-11-10 | Apache-2.0 | Not chosen |
| Aider | Pair programmer with text edit formats | Robust edit formats for tiny models, but no agent loop, MCP or subagents | 0.86.2 (2026-02-12); no release since | Apache-2.0 | Not chosen |
| Gemini CLI | Google's CLI | Google-model-centric; its fork Qwen Code is the relevant one | v0.68.0 | Apache-2.0 | Not chosen |
| OpenHands CLI | OpenHands terminal client | README: "no longer actively maintained"; OpenHands moved to Agent Canvas (web) | 1.16.0 (2026-05-08) | MIT | Dead (Canvas is agent D's topic) |
| Roo Code | VS Code agent | Repo archived 2026-05-15 | Dead | Apache-2.0 | Do not use |
| Continue | VS Code agent and `cn` CLI | Acquired by Cursor; last release v2.1.0 (2026-06-19) | Dead | Apache-2.0 | Do not use |
| Plandex | Planning agent with a server | Cloud wound down 2025-10-03; last release 2025-07-16 | Dormant | MIT | Do not use |

## Details

### 1. Feature matrix

Legend:

- **N**: native.
- **P**: via plugin, extension, MCP server or a documented workaround.
- **M**: missing.
- **?**: not verified.
- **(a)**: assumed from secondary sources or from a fork's parent.

The OpenCode, Qwen Code, Codex and Claude Code columns were checked against their current docs
or source. The Goose, Crush, Pi, Cline, Kilo and Aider columns were checked against READMEs and
documentation indexes only.

| Feature (Claude Code reference) | Claude Code (local) | OpenCode V2 | Qwen Code | Codex CLI | Goose | Crush | Pi | Cline CLI | Kilo CLI | Aider |
|---|---|---|---|---|---|---|---|---|---|---|
| Project memory file, hierarchy | N (CLAUDE.md tree; reads AGENTS.md from v2.1.277) | N (AGENTS.md global, upward and nested; CLAUDE.md only via `instructions`) | N (QWEN.md + AGENTS.md; `context.fileName`) | N (AGENTS.md root to cwd, 32 KiB cap) | N (AGENTS.md, .goosehints, nested) | N (CRUSH.md, AGENTS.md) | N (context files) | N (.clinerules, AGENTS.md) | N (a) | P (`--read` files) (a) |
| Custom subagents with own model and tools | N | N (`model`, `permissions`, `steps`, `system`) | N (`model: inherit/fast/id`, `tools`, `approvalMode`) | N (TOML: model, effort, instructions; not provider, sandbox or MCP) | N (name, description, model only) | P (model and read/write access chosen at dispatch) | M | ? | N (a) | M |
| Parallel / background agents | N | N (always background; report on idle) | N (background default, forks) | N (`spawn_agent`/`wait_agent`, thread cap) | N | N (`agent_dispatch`) | M | P (Kanban with worktrees) | N (a) | M |
| Hooks (PreToolUse etc.) | N (shell, many events) | P (TypeScript plugin: `permission` evaluate, `tool` execute.before/after, `shell` create.before) | N (Claude-compatible JSON, command and HTTP hooks) | N (Claude-compatible; trust review) | N (Open Plugins hooks; PreToolUse can block) | N ("largely Claude Code-compatible", marked preliminary) | P (extension events) | P (SDK plugins) | P (a) | M |
| Slash commands | N | N (`.opencode/commands/*.md`, `!` shell blocks) | N | N (built-in; custom via skills) | N (map to recipes) | N (user-invocable skills) | N (prompt templates) | ? | N (a) | N (built-in only) |
| Skills (SKILL.md) | N | N (also reads `.claude/skills`) | N | N | N | N (also reads `.claude/skills`) | N | N | N (a) | M |
| MCP client: stdio / HTTP | N / N | N / N (Code Mode by default) | N / N (+SSE) | N / N | N / N (a) | N / N (+SSE) | N / N | N / ? | N (a) | M |
| Permission modes, allow-lists | N (6 modes + rules) | N (ordered allow/ask/deny rules, hard-deny `policies`, `run --auto`) | N (plan, default, auto-edit, auto, yolo + rules) | N (approval policy × sandbox mode + rules) | N (auto, approve, smart_approve, chat) | N (allow list, yolo) | M | N (a) | N (a) | P |
| Plan mode | N | N (`plan` agent) | N | N (`/plan`) | ? | N (a) (plan template in source) | M (deliberately) | N (Plan & Act) | N (a) | P (`/architect`, `/ask`) (a) |
| Headless / CI (`-p`) | N (`-p`, `--bare`) | N (`run`, `--format json`, `--auto`) | N (`-p`, `--output-format json`) | N (`exec`) | N | ? | N (`-p`, JSON, RPC) | N (`--json`) | N (a) | N (a) |
| GitHub Actions app (gh CLI works in all via shell) | N (`anthropics/claude-code-action@v1`) | P (`opencode run --standalone` step) | N (`QwenLM/qwen-code-action`) | N (`openai/codex-action@v1`) | ? | ? | M | P (CLI samples) | ? | M |
| Web search | P (server tool: needs LiteLLM `websearch_interception` with SearXNG, or MCP) | P (built-in only Exa, Firecrawl, Parallel, Tavily, TinyFish; SearXNG via MCP) | P (DashScope only; MCP) | P (OpenAI-hosted only; MCP) | P (MCP) | P (a) | P (MCP) | ? | P (a) | M |
| Web fetch | N (pre-flight check to api.anthropic.com unless `skipWebFetchPreflight`) | N (`webfetch`) | N (`web_fetch`) | P (MCP) (a) | P (MCP) (a) | N (`fetch`, `agentic_fetch`) | P | ? | N (a) | N (`/web`) (a) |
| Image / PDF reading | N / N | N / N (model must accept them) | N / N (vision bridge) | N / ? | ? | ? | N / ? | N / ? | N (a) | N / M (a) |
| Todo list | N | P (`experimental.todo`) | ? | P (goals, `/plan`) | ? | N (`todos`) | M | N (a) | ? | M |
| Session resume | N | N (`--continue`, `--session`) | N (`--continue`, `--resume`) | N (`codex resume`, `fork`) | N | N (a) | N (session tree) | N (a) | N (a) | P |
| Context compaction | N (set the window for unknown IDs) | N (`compaction.keep`, `buffer`; uses `limit.context`) | N (`contextWindowSize`) | N (`/compact`, `model_auto_compact_token_limit`) | N | N | N | N (a) | N (a) | P |
| Git worktrees | N (`-w`, `isolation`) | N (`worktree` config, `worktree_create`) | N (`--worktree`, `isolation`) | N (`exec --worktree`, `/worktree`) | ? | ? | M | N (Kanban) | N (a) | M |
| Remote use: run on a host, attach clients | P (plain SSH or tmux; Remote Control disabled behind a non-Anthropic base URL) | N (server + TUI/web/desktop clients; SSH tunnel; `pair`) | N (`qwen serve`, Web Shell) (a) | P (`--remote` app-server) | ? | N (shared workspace across clients) (a) | P (RPC mode) | N (Desktop over SSH) | N (a) | M |
| Operating on another host over SSH | P (ssh-mcp) | P (ssh-mcp) | P (ssh-mcp) | P (ssh-mcp) | P (ssh-mcp) | P (ssh-mcp) | P (ssh-mcp) | P | P | M |
| IDE integration | N (VS Code, JetBrains) | P (ACP clients such as Zed; desktop app) | N (VS Code, JetBrains, Zed) | N (closed-source IDE extension) | P (ACP) | ? | ? | N (VS Code, JetBrains, ACP) | N (VS Code, JetBrains) | P (a) |
| Main model + small fast model | N (`ANTHROPIC_MODEL` + `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`) | N (`model` + `agents.title.model` + per-agent `model`) | N (`model.name` + `fastModel`; agent `model: fast`) | P (`model` + `agents.default_subagent_model`) | P (`GOOSE_SUBAGENT_MODEL`) | ? | P | N (a) | N (a) | N (`--weak-model`) (a) |
| OS sandbox for shell commands | N (bubblewrap + socat; Seatbelt on macOS) | M (use a container) | N (bwrap or Landlock; Docker/Podman) | N (bwrap) | ? | ? | M (containerization guide) | ? | M (a) | M |
| Licence | Proprietary | MIT | Apache-2.0 | Apache-2.0 | Apache-2.0 | FSL-1.1-MIT | MIT | Apache-2.0 | MIT | Apache-2.0 |
| Telemetry default, and how to turn it off | On; `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` | None documented; OTLP export only if `OTEL_EXPORTER_OTLP_ENDPOINT` is set | On; `privacy.usageStatisticsEnabled: false` | On (Statsig); `[analytics] enabled = false` | Off (`GOOSE_TELEMETRY_ENABLED`) | On; `CRUSH_DISABLE_METRICS=1` or `DO_NOT_TRACK=1` | ? | ? | ? | ? |
| Measured first request (tokens, headless) | 11,375 (`--bare`: 1,200) | 5,340 | 9,695 | 9,427 | not measured | not measured | 1,322 | not measured | not measured | not measured |
| API the endpoint must serve | Anthropic Messages | Chat Completions | Chat Completions (or Responses) | Responses only | Chat Completions (a) | Chat Completions (`completions`, `litellm` types) | Chat Completions | Chat Completions | Chat Completions | Chat Completions (a) |

### 2. Measured prompt overhead (my measurement, 2026-11-15)

**Method.** Each harness ran once in a throwaway `node:22-bookworm` container on c4dev:

- It was pointed at a fake endpoint that records the request body and answers "OK", with the
  prompt "Reply with the single word OK." in an empty git repository.
- There was no AGENTS.md or CLAUDE.md, no MCP servers and default settings, in headless mode:
  `opencode run`, `qwen -p`, `codex exec`, `claude -p`, `pi -p`.
- Counts use tiktoken `o200k_base`. Qwen- or Gemma-family tokenizers will differ somewhat
  (assumed ±15 %).
- Interactive TUI sessions may declare more tools than headless runs.

| Harness, version | Tools declared | System prompt | Tool schemas | First user message | Whole request |
|---|---|---|---|---|---|
| OpenCode 2.3.0 | 11 (`edit, glob, grep, question, read, shell, skill, subagent, webfetch, write, execute`) | 1,960 | 3,090 | 7 | **5,340** |
| Qwen Code 0.27.4 | 6 (`glob, grep_search, read_file, skill, tool_call, tool_search`; others deferred) | 4,281 | 2,182 | 2,668 (bundled skill list, environment) | **9,695** |
| Codex CLI 0.169.0 | 9 (incl. `multi_agent_v1` namespace, hosted `web_search`, goal tools) | 4,061 | 4,038 | 113 | **9,427** |
| Claude Code 2.1.325, `-p` | 12 (incl. `ToolSearch`, deferred-tool placeholder) | 3,309 | 7,335 | 254 | **11,375** |
| Claude Code 2.1.325, `--bare -p` | 3 (`Bash, Edit, Read`) | 58 | 887 | 7 | **1,200** |
| Pi 1.5.2 | 4 (`read, bash, edit, write`) | 501 | 714 | 7 | **1,322** |

Notes:

- OpenCode's second request was title generation on `local-fast` (509 tokens, no tools). That
  confirms `agents.title.model` routes background work to the small model.
- Claude Code sent `max_tokens: 32000`, `thinking: {type: adaptive}`, `context_management` and
  `output_config`, and warned that it assumes a 1M window for `local-coder`.
- Codex's request carries OpenAI-specific tool types: `namespace`, and `web_search` with
  `external_web_access: false`. The gateway must translate or drop these for a local model.
  Test this before relying on Codex.
- Older third-party figures, for comparison:
  - Claude Code about 32.8k against OpenCode V1 about 6.9k (Systima, July 2026, interactive,
    Claude Sonnet) [S38].
  - Codex v0.114.0 about 8.5k minimal; v0.121.0 about 25.4k with MCP schemas included [S39, S40].
  - Pi under 1k [S39].
- The owner's existing memory files, about 33 KB together, would add roughly 8k tokens to every
  request in any harness. Codex truncates project docs at 32 KiB (`project_doc_max_bytes`).

### 3. Endpoint requirements (what the gateway at `192.0.2.10:4000` must serve)

- `/v1/chat/completions` with tool calling, and `/v1/models`, for OpenCode, Qwen Code, Pi,
  Goose, Crush and Cline. Model IDs `local-coder` and `local-fast` must be exposed as the
  gateway's model names.
- `/v1/messages` (Anthropic format) only if Claude Code is used. LiteLLM serves it for any
  backend [S20].
- `/v1/responses` only if Codex is used. LiteLLM serves `/v1/responses` and translates for
  non-OpenAI model groups (search-result summary of LiteLLM's Codex page, not read in full)
  [S22].
- If the local model is a reasoning model whose server streams `reasoning_content`, set
  OpenCode's `compatibility.reasoningField` (see the config below).
- Every harness needs the **real** context window declared (`limit.context`,
  `contextWindowSize`, `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `model_context_window`). The fallbacks
  are 200k (OpenCode), 1M (Claude Code) and 128k (Pi), so compaction would start too late and
  requests would overflow. The values below use 65,536 and 32,768 as placeholders: replace them
  with what agent B's server actually runs (`llama-server -c`, `vllm --max-model-len`).

### 4. Install and configure OpenCode V2 (primary)

**Install on c4dev (Linux)** [S1, S17]:

```bash
# Option A: install script (installs to ~/.opencode/bin)
curl -fsSL https://opencode.ai/v2/install | bash
# Option B: npm (Node 22+ from the distribution or nvm)
npm i -g @opencode/cli@2.3.0
# Option C: Homebrew on Linux or macOS
brew install anomalyco/tap/opencode-v2
```

**Install on the Mac:**

- CLI: `brew install anomalyco/tap/opencode-v2`.
- Optional desktop app: `brew install --cask opencode-desktop` [S17].

**Container option:** `ghcr.io/anomalyco/opencode:2.3.0` is a multi-arch image (amd64, arm64),
Alpine and musl, with `ENTRYPOINT ["opencode"]` and only `opencode` and `ripgrep` inside. It
needs no GPU or CUDA build because the harness never touches the GPU [S18].

- Build a derived image with the project toolchain added (git, gh, the project's linters).
- Mount only the repository.

**Environment (c4dev and Mac shell profile).** The variable names on the left are the owner's
choice; the `OPENCODE_*` names are OpenCode's:

```bash
export LOCAL_LLM_API_KEY='<LiteLLM virtual key>'      # read by {env:LOCAL_LLM_API_KEY}
export SEARXNG_URL='http://192.0.2.10:<searxng-port>' # from agent D's file
export OPENCODE_DISABLE_MODELS_FETCH=1                # no models.dev download (verified in source, not docs)
export OPENCODE_DISABLE_FREE_MODELS=1                 # hide hosted free models (docs)
```

For the background service, persist them with `opencode service set env NAME value`
[S6, S16].

**Global config `~/.config/opencode/opencode.jsonc`** (keys verified in the V2 docs unless
marked):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "local/local-coder",
  "default_agent": "build",
  "update": "disable",                 // global-only key; "notify" | "auto" | "disable"
  "share": "disabled",                 // in the config schema source, not in the docs pages
  "websearch": false,                  // removes the built-in (paid-provider) search tool
  "policies": [                        // hard limits that project config cannot loosen
    { "action": "provider.use", "resource": "*", "effect": "deny" },
    { "action": "provider.use", "resource": "local", "effect": "allow" },
    { "action": "tool.use", "resource": "shell:git push --force*", "effect": "deny" },
    { "action": "tool.use", "resource": "edit:*.env", "effect": "deny" }
  ],
  "providers": {
    "local": {
      "name": "Local stack",
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "http://192.0.2.10:4000/v1",
        "apiKey": "{env:LOCAL_LLM_API_KEY}"
      },
      "models": {
        "local-coder": {
          "name": "Local coder",
          "capabilities": { "tools": true, "input": ["text"], "output": ["text"] },
          "limit": { "context": 65536, "output": 8192 }
          // for a reasoning model streaming reasoning_content, add:
          // "compatibility": { "reasoningField": "reasoning_content" }
        },
        "local-fast": {
          "name": "Local fast",
          "capabilities": { "tools": true, "input": ["text"], "output": ["text"] },
          "limit": { "context": 32768, "output": 4096 }
        }
      }
    }
  },
  "agents": {
    "title": { "model": "local/local-fast" }   // V2 replacement for V1 small_model
  },
  "compaction": { "auto": true, "keep": { "tokens": 8000 }, "buffer": "20%" },
  "experimental": { "todo": true },
  "permissions": [
    { "action": "shell", "resource": "*", "effect": "ask" },
    { "action": "shell", "resource": "git status *", "effect": "allow" },
    { "action": "shell", "resource": "git diff *", "effect": "allow" },
    { "action": "shell", "resource": "git log *", "effect": "allow" },
    { "action": "shell", "resource": "gh issue view *", "effect": "allow" },
    { "action": "shell", "resource": "gh pr view *", "effect": "allow" },
    { "action": "external_directory", "resource": "*", "effect": "ask" },
    { "action": "read", "resource": "*.env", "effect": "deny" },
    // weak local models: turn off Code Mode so MCP tools are plain tools (see the MCP note)
    { "action": "execute", "resource": "*", "effect": "deny" }
  ],
  "mcp": {
    "servers": {
      "searxng": {
        "type": "local",
        "command": ["npx", "-y", "mcp-searxng@2.10.1"],
        "environment": { "SEARXNG_URL": "{env:SEARXNG_URL}" },
        "codemode": false
      },
      "ssh": {
        "type": "local",
        "command": ["ssh-mcp"],
        "codemode": false,
        "disabled": true                 // enable per project; config in ~/.config/ssh-mcp/config.toml
      }
    }
  }
}
```

Notes on that config:

- **Rule order.** The last matching permission rule wins. `"git status *"` also matches bare
  `git status`. Agent rules are appended after global rules. With no matching rule, the default
  is `ask` [S6].
- **Code Mode.** By default MCP tools are reached through the `execute` tool, where the model
  writes JavaScript that calls `tools.<server>.<tool>()`. Denying `execute` lists those tools
  directly instead [S9]. That is easier for weak models but costs one schema per tool in every
  request. Measure both with the eval set from agent F before fixing the choice.
- **Fetch.** The built-in `webfetch` covers fetching, so the fetch MCP server
  (`uvx mcp-server-fetch`, PyPI `mcp-server-fetch` 2026.11.11) is optional. The filesystem MCP
  server (`@modelcontextprotocol/server-filesystem` 2.3.0) is redundant with the built-in file
  tools. Add it only to expose a fixed outside directory, and prefer OpenCode's `references`
  for that.
- **SearXNG.** It must have JSON output enabled for `mcp-searxng` [S35].
- **SSH host access.** `ssh-mcp` (npm 2.26.0) is policy-gated and audited. It refuses every call
  until `~/.config/ssh-mcp/config.toml` defines profiles; set `approvalMode = "ask-destructive"`
  [S36]. Install it with `npm install -g ssh-mcp`.

**Project files (in each repository):**

```text
AGENTS.md                       # project memory (canonical; Claude Code v2.1.277+ also reads it)
opencode.jsonc                  # project overrides; optionally "instructions": ["docs/rules/*.md"]
.opencode/agents/worker.md      # subagents (Markdown + YAML frontmatter)
.opencode/agents/scout.md
.opencode/agents/reviewer.md
.opencode/commands/issue.md     # slash commands (/issue)
.opencode/skills/<id>/SKILL.md  # skills (also discovered: .claude/skills, .agents/skills)
.opencode/plugins/rules-hook.ts # PreToolUse bridge (section 7)
```

- OpenCode V2 reads only `AGENTS.md`. To keep an existing `CLAUDE.md` as the source, add
  `"instructions": ["CLAUDE.md"]` to the project `opencode.jsonc`. Relative entries are searched
  from the workspace up to the project root [S10].
- The global memory file is `~/.config/opencode/AGENTS.md`.

**Subagent definitions** (frontmatter keys verified: `description`, `mode`, `model`,
`permissions`, `steps`, `hidden`, `color`, `disabled`; body = system prompt) [S3]:

```markdown
---
description: Implements one brief. Edits only the files the brief names. Never runs git or gh.
mode: subagent
model: local/local-coder
steps: 60
permissions:
  - action: shell
    resource: "git *"
    effect: deny
  - action: shell
    resource: "gh *"
    effect: deny
---
You are a worker. Read the contract in docs/ that the brief names, change only the files the
brief lists, run the verification commands the brief gives, and report the files you changed.
```

```markdown
---
description: Read-only research. Searches code, docs and the web; writes nothing.
mode: subagent
model: local/local-fast
permissions:
  - action: edit
    resource: "*"
    effect: deny
  - action: shell
    resource: "*"
    effect: deny
---
Answer the question with file paths, line references and source URLs. Do not edit anything.
```

How subagents behave:

- They always run in the background. The parent gets a `<subagent>` report when each child goes
  idle.
- Nesting depth defaults to 1; set `experimental.subagent_depth` to change it.
- To control which agents the coordinator may launch, use the `subagent` permission action with
  an agent ID as the resource [S3, S9].

**Slash command example** `.opencode/commands/issue.md` (the `!` shell-block syntax and
`$ARGUMENTS` are verified [S12]):

```markdown
---
description: Start work on a GitHub issue
agent: build
---
Issue to work on:
!`gh issue view $1 --json number,title,body,labels`
Create a branch named after the issue number, write or update the contract under docs/, then
plan the split into disjoint file sets before spawning workers.
```

**Mac usage, three choices** (all verified in the web and CLI docs [S15]):

1. `ssh c4dev`, then `opencode` in the repository. This is the simplest.
2. On c4dev: `opencode service start` (it listens on 127.0.0.1:49374 by default on Linux), then
   `opencode pair`. On the Mac: `ssh -L 49374:127.0.0.1:49374 c4dev` and open the printed link
   in a browser or the desktop app.
3. On the Mac: `OPENCODE_PASSWORD=... opencode --server http://127.0.0.1:49374` through the same
   tunnel, after `opencode service set password ...` on c4dev.

Do **not** use `opencode pair --remote`, which exposes the server through an internet tunnel.
That conflicts with the local-only rule.

### 5. Install and configure Qwen Code (secondary)

**Install:**

- `npm install -g @qwen-code/qwen-code@0.27.4` (needs Node 22+).
- Or `brew install qwen-code`.

The vendor's one-line installer downloads from an Alibaba OSS bucket; prefer npm [S29].

**User config `~/.qwen/settings.json`** (keys verified in the settings and providers docs
[S24, S25]):

```json
{
  "modelProviders": {
    "openai": [
      { "id": "local-coder", "name": "Local coder", "envKey": "LOCAL_LLM_API_KEY",
        "baseUrl": "http://192.0.2.10:4000/v1",
        "generationConfig": { "contextWindowSize": 65536, "timeout": 300000,
                              "samplingParams": { "max_tokens": 8192 } } },
      { "id": "local-fast", "name": "Local fast", "envKey": "LOCAL_LLM_API_KEY",
        "baseUrl": "http://192.0.2.10:4000/v1",
        "generationConfig": { "contextWindowSize": 32768 } }
    ]
  },
  "security": { "auth": { "selectedType": "openai" } },
  "model": { "name": "local-coder", "catalogRefresh": false },
  "fastModel": "local-fast",
  "privacy": { "usageStatisticsEnabled": false },
  "context": { "fileName": ["AGENTS.md", "QWEN.md"] },
  "tools": {
    "approvalMode": "default",
    "webSearch": { "enabled": false },
    "executionSandbox": { "backend": "bwrap", "filesystem": "workspace-write", "network": "open" }
  },
  "mcpServers": {
    "searxng": { "command": "npx", "args": ["-y", "mcp-searxng@2.10.1"],
                 "env": { "SEARXNG_URL": "$SEARXNG_URL" } }
  }
}
```

Notes:

- **Approval mode.** The out-of-the-box mode is `auto`, where an LLM classifier approves or
  blocks each action [S26]. With a weak local model that classifier is the weakest link, so set
  `"default"` (ask) or `"auto-edit"` and rely on hooks.
- **Sandbox.** `executionSandbox` needs `/usr/bin/bwrap`. `network: "closed"` would block `gh`,
  `npm` and the like inside tool commands [S27].
- **Telemetry.** `QWEN_USAGE_STATISTICS_ENABLED=false` overrides the setting.
- **Hooks.** These go in `.qwen/settings.json` and are Claude-compatible. The matcher accepts
  `"Bash"` and `"Write|Edit"`. `CLAUDE_PROJECT_DIR` is set for command hooks. Project hooks run
  only after you approve that exact configuration or trust the folder [S23].

  ```json
  { "hooks": { "PreToolUse": [ { "matcher": "Bash|Edit|Write", "hooks": [
      { "type": "command", "command": "\"$QWEN_PROJECT_DIR/tools/hooks/pretooluse.sh\"",
        "name": "project-rules", "timeout": 10 } ] } ] } }
  ```

- **Subagents.** Define them in `.qwen/agents/<name>.md` with `name`, `description`,
  `model: inherit|fast|<id>`, `approvalMode`, `tools` and `disallowedTools` [S28].
- **Prompt size.** Run `/context detail` on the first turn to read the actual cost. Use
  `tools.eager` and `tools.disabled` to keep only the tools you need declared [S30].

### 6. Claude Code against the local endpoint (fallback only)

Verified variables and settings [S11–S14]:

```bash
export ANTHROPIC_BASE_URL=http://192.0.2.10:4000      # LiteLLM serves /v1/messages
export ANTHROPIC_AUTH_TOKEN='<LiteLLM key>'           # sent as Authorization: Bearer
export ANTHROPIC_MODEL=local-coder
export ANTHROPIC_DEFAULT_HAIKU_MODEL=local-fast       # background tasks and titles
export CLAUDE_CODE_SUBAGENT_MODEL=local-coder
export CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536           # otherwise it assumes 1M for unknown IDs
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192             # unknown IDs default to 32000
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1     # telemetry, error reports, updates, surveys
```

Add `"skipWebFetchPreflight": true` to `~/.claude/settings.json`. The WebFetch domain check
otherwise calls api.anthropic.com regardless of provider.

Limits:

- **Web search.** WebSearch is a server-side tool. With a local model it works only if LiteLLM
  runs the `websearch_interception` callback with a `searxng` search tool (`SEARXNG_API_BASE`)
  [S21]. Otherwise use the SearXNG MCP server.
- **Remote Control** is disabled behind a non-Anthropic base URL [S12].
- **Gateway translation.** LiteLLM must drop or translate `thinking`, `context_management` and
  `output_config` for the local backend. That was not tested here.
- **Unsupported by the vendor.** Anthropic does not support non-Claude models behind a gateway
  [S11].

### 7. Reproducing the owner's working style in OpenCode

| Practice | How in OpenCode V2 | Gap or workaround |
|---|---|---|
| Contract docs in `docs/` before spawning | Coordinator writes them; `AGENTS.md` states the rule; an `/issue` command starts the flow | None |
| Parallel background agents | `subagent` tool; children always run in the background and report on idle; follow-ups via the returned `sessionID` | One 16 GB GPU serves all agents. Cap at 2 to 3 concurrent workers (match the server's parallel slots, agent B). Use `local-fast` for scouts |
| Each agent owns disjoint files | The brief lists the files; a plugin permission hook enforces it (below); or one worktree per worker via the `worktree` config and `worktree_create` | Static agent permissions cannot express per-brief file lists, so the enforcing plugin has not been tested |
| One coordinator integrates; no agent runs git | Worker and scout agents deny `shell` on `git *` and `gh *`; only `build` (the coordinator) may | None |
| Issue → branch → PR | `gh` through the shell with allow rules for read commands and `ask` for writes; `.opencode/commands/` templates with `!` shell blocks; branch protection on GitHub | CI agent runs need a **self-hosted runner on the LAN** to reach the endpoint. Run `opencode run --standalone --auto` there |
| PreToolUse hook enforcing rules | Plugin with `ctx.permission.hook("evaluate")`; hard rules in `policies` | Hooks are TypeScript, not shell. The bridge below reuses the shell script |
| Model rule enforced by hook | `policies` with `provider.use` deny `*`, allow `local`; each agent's `model` field | None |
| Plan first | `plan` agent (Tab to switch) | None |
| Memory across sessions (Claude's auto memory) | Missing as a built-in | A maintained `instructions` file or a memory MCP server |

**PreToolUse bridge plugin.** This is a sketch that has **not been executed**. The API calls are
the documented ones in [S8]: `Plugin.define`, `ctx.permission.hook("evaluate")`, and the event
fields `action`, `resources`, `sessionID`, `effect` and `message`. It sends the project's
existing Claude-format hook script a PreToolUse payload and maps exit code 2 to a denial.

```ts
// .opencode/plugins/rules-hook.ts  (auto-discovered from .opencode/plugins/)
import { Plugin } from "@opencode/plugin"            // resolution for local files: UNVERIFIED
import { spawnSync } from "node:child_process"

const toolName = (a: string) => (a === "shell" ? "Bash" : a === "edit" ? "Edit" : a === "read" ? "Read" : a)

export default Plugin.define({
  id: "rules-hook",
  async setup(ctx) {
    await ctx.permission.hook("evaluate", async (event) => {
      const input = event.action === "shell"
        ? { command: event.resources.join(" && ") }
        : { file_path: event.resources[0], resources: event.resources }
      const r = spawnSync("tools/hooks/pretooluse.sh", {
        input: JSON.stringify({ hook_event_name: "PreToolUse", session_id: event.sessionID,
                                tool_name: toolName(event.action), tool_input: input }),
        encoding: "utf8", timeout: 10_000,
      })
      if (r.status === 2) {
        event.effect = "deny"
        event.message = (r.stderr || "Blocked by project rule").trim()
      }
    })
  },
})
```

- **Behaviour.** Permission hooks run for `allow` and `ask` decisions. An explicit configured
  `deny` is final and skips the hook.
- **Per-brief file ownership.** The same hook can enforce it. Read the child session's first
  prompt with `ctx.session.context({ sessionID })`, which is documented in the same example.
  Parse a "Files you may edit:" block from it and deny `edit` resources outside that list.

### 8. Security

- **Shell sandboxing:**
  - OpenCode has none. Its shell tool "has the host user's filesystem, process, and network
    authority". The built-in `build` agent allows access outside the workspace by default.
    Mitigations, from cheapest:
    1. Permission rules: `external_directory` set to `ask`, `.env` reads denied, plus `policies`
       hard denies.
    2. Run OpenCode as a dedicated unprivileged user on c4dev, with only the repositories and a
       GitHub token scoped to them.
    3. Run the OpenCode service in a container built from `ghcr.io/anomalyco/opencode:2.3.0`,
       with the repository bind-mounted and no host Docker socket.
  - Qwen Code: `tools.executionSandbox` (bwrap or Landlock), or Docker/Podman for the whole CLI.
  - Codex: bwrap with `workspace-write`.
  - Claude Code: `/sandbox` (bubblewrap + socat).
- **Telemetry and phone-home:**
  - OpenCode:
    - No telemetry is documented. OTLP export starts only when `OTEL_EXPORTER_OTLP_ENDPOINT` is
      set (source).
    - Set `update: "disable"` and `OPENCODE_DISABLE_MODELS_FETCH=1` (models.dev catalog,
      source-verified).
    - Never run `pair --remote`.
    - The `policies` provider lock stops accidental use of hosted providers.
  - Qwen Code: `privacy.usageStatisticsEnabled: false` and `model.catalogRefresh: false`.
    Statistics go to an Alibaba Cloud endpoint by default [S31].
  - Codex: `[analytics] enabled = false`, `check_for_update_on_startup = false`,
    `feedback.enabled = false`.
  - Claude Code: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` plus `skipWebFetchPreflight`.
  - Crush: `CRUSH_DISABLE_METRICS=1`. Goose: telemetry is off by default. Mistral Vibe:
    `enable_telemetry = false`.
- **Untrusted repository content:**
  - OpenCode loads `.opencode/plugins/*.ts` from a repository automatically. That is code
    execution at startup, so review a repository's `.opencode/` before running OpenCode in it.
  - Qwen Code and Codex hold project hooks until you approve them; OpenCode has no such review
    step for plugins (assumed from the docs, which describe none).

### 9. Known problems and fixes

- **Tool calls fail on a local model.** Check, in order:
  1. The server's real context: Ollama defaults to 4k.
  2. llama.cpp started with `--jinja`.
  3. vLLM started with `--enable-auto-tool-choice --tool-call-parser ...`.
  4. Reasoning arriving in `reasoning_content`: set `compatibility.reasoningField`.

  Points 1 to 3 come from secondary sources [S42]; the vLLM flags are also stated in OpenCode's
  docs [S4].
- **vLLM models discovered by OpenCode have tools disabled.** Declare the model under a custom
  provider with `capabilities.tools: true` [S4].
- **Compaction never triggers, then requests overflow.** Declare the real window; see section 3.
- **A Qwen Code subagent cannot find a tool.** Tools outside `tools.eager` are deferred behind
  `tool_search`. Add the core tools to `tools.eager`, and do not disable the bridge [S30].

## Fit with Claude Code features

The recommended option is OpenCode V2; where it falls short, Qwen Code is named.

| Claude Code feature | OpenCode V2 match | What is lost |
|---|---|---|
| CLAUDE.md hierarchy | AGENTS.md global + upward + lazily loaded nested files; edits picked up mid-session | No CLAUDE.md fallback (use `instructions`); no `@import` syntax; no auto memory |
| Subagents with own model and tools | Markdown agents with `model`, `permissions`, `steps` | Tools restricted by permission rules, not a tool list; no per-agent MCP set or per-agent hooks |
| Background and parallel agents | Native, always background | No "agent teams" or cross-session messaging equivalent; GPU-bound concurrency |
| Hooks | Plugin hooks: permission evaluate, tool before/after, shell before, session prompt/context | Not shell-configured; Qwen Code matches Claude's format exactly |
| Slash commands, skills | Native; also reads `.claude/skills` | None material |
| MCP stdio/HTTP, OAuth | Native; Code Mode by default | Code Mode may need turning off for weak models |
| Permission modes | Ordered allow/ask/deny rules + `policies`; `plan` agent; `run --auto` | No named mode cycle like acceptEdits or auto-classifier |
| Plan mode | `plan` agent | Equivalent |
| Headless `-p` | `opencode run`, JSON output | Equivalent |
| GitHub integration | `gh` via the shell; `opencode run` in Actions | No first-party Action in V2 docs; needs a LAN self-hosted runner |
| Web search / fetch | `webfetch` native; search via SearXNG MCP | Built-in search supports paid providers only |
| Images / PDFs | `read` passes PNG/JPEG/GIF/WebP/PDF | Only useful if the local model is multimodal (agent A) |
| Todo list | `experimental.todo` | Experimental flag |
| Resume, compaction, worktrees | Native | None material |
| Remote use | Server + TUI/web/desktop clients over an SSH tunnel | Better than Claude Code's local-endpoint case |
| IDE | ACP (Zed and other ACP clients), desktop app | No first-party VS Code extension in V2 docs |
| Main + small model | Per-agent `model`; `agents.title.model` | Compaction and summary agents' model override not verified |
| Sandbox | None | Use a container or user isolation; Qwen Code has bwrap |
| Licence / telemetry | MIT; none documented | None |

## Verified vs assumed

**Verified** (primary sources or my measurement, 2026-11-15):

- OpenCode versions and docs:
  - Version 2.3.0 (2026-11-13), MIT, npm `@opencode/cli`; image `ghcr.io/anomalyco/opencode:2.3.0`
    exists.
  - All config keys shown: `providers.<id>.package`, `settings.baseURL`, `apiKey`,
    `models.<id>.capabilities`, `limit`, `modelID`, `compatibility.reasoningField`,
    `agents.title.model`, `permissions`, `policies`, `mcp.servers.*`, `codemode`, `websearch`,
    `update`, `compaction`, `experimental.todo`, `experimental.subagent_depth`, `instructions`,
    `worktree`, `plugins`.
  - AGENTS.md-only discovery.
  - Background subagents, the plugin hook API, server, pair, tunnel and ports.
- OpenCode source: `share` key in the config schema; `OPENCODE_DISABLE_MODELS_FETCH`; OTLP only
  when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- Qwen Code: 0.27.4, Apache-2.0, Node 22+; all settings keys shown; Claude-compatible hooks;
  subagent frontmatter; approval modes with `auto` as the default; sandbox; usage statistics
  default on, and the opt-out.
- Codex: 0.169.0, Apache-2.0; `wire_api` accepts only `responses`; OSS mode supports only
  ollama and lmstudio; custom agent TOML schema; hooks shape; `analytics.enabled`; AGENTS.md
  32 KiB cap; `exec`, `resume` and `--worktree`; `openai/codex-action@v1`.
- Claude Code: 2.1.325, proprietary licence text; all environment variables shown; gateway API
  formats; "doesn't support routing to non-Claude models"; 1M assumed window; Remote Control
  disabled behind a non-Anthropic base URL; telemetry variables; AGENTS.md support from
  v2.1.277; subagent frontmatter fields; sandbox via bubblewrap and socat.
- Ecosystem facts from GitHub/npm/PyPI metadata and project pages:
  - Roo Code archived (GitHub API).
  - Continue acquired by Cursor (its homepage).
  - OpenHands CLI unmaintained (its README).
  - Plandex cloud wound down (its README).
  - Aider 0.86.2 on PyPI, 2026-02-12.
  - Kilo CLI is an OpenCode fork (its README).
  - Crush licence, metrics opt-out and hook compatibility claim (its README).
  - Pi: no subagents, plan mode or permissions, and MCP support (its README and docs).
- MCP server packages: `mcp-searxng` 2.10.1 with `SEARXNG_URL`; `ssh-mcp` 2.26.0 with its config
  path; `mcp-server-fetch` 2026.11.11; `@modelcontextprotocol/server-filesystem` 2.3.0.
- The prompt-size table in Details section 2, by my own measurement.

**Assumed or unverified:**

- Every cell marked "(a)" or "?" in the matrix, especially the Goose, Crush, Cline, Kilo and Aider
  columns.
- How well LiteLLM translates Codex's `namespace` and hosted `web_search` tools, and Claude Code's
  `thinking`, `context_management` and `output_config` fields, for a local backend. Not tested.
- The OpenCode plugin sketch: that `@opencode/plugin` resolves for a bare `.opencode/plugins/*.ts`
  file without a `package.json`, and that `spawnSync` works under OpenCode's runtime.
- Whether `agents.summary.model` or `agents.compaction.model` overrides work as they do for
  `title`. Not tested.
- The ±15 % tokenizer difference between o200k and Qwen or Gemma tokenizers.
- Interactive TUI prompt sizes, which may exceed the headless numbers measured.
- Third-party figures: Systima's 33k against 7k, Vaughan's Codex and Pi numbers, and the
  2080 Ti prefill rates. These are secondary sources, each from a single measurement.
- That edit formats based on exact-match `oldString` fail less often on weak models than Codex's
  `apply_patch`. This is a reasoned guess, not measured.

## Open questions for the owner

1. **Hook format trade-off.** Should the primary harness be OpenCode, whose hooks are TypeScript
   plugins calling the existing shell script, or Qwen Code, which runs Claude-format hook
   scripts unchanged but needs a bigger prompt and a telemetry opt-out? This file recommends
   OpenCode.
2. **Concurrency limit.** "Parallel by default" on one 16 GB GPU means 2 to 3 concurrent agents
   at most, with slower turns. Accept that cap, or have parallel work run serially through one
   worker?
3. **Isolation level on c4dev.** Choose one: permission rules only, a dedicated unprivileged
   user, or the OpenCode container.
4. **CI with local models.** Agent-driven GitHub Actions jobs need a self-hosted runner on the
   LAN. Is that acceptable? If the repository is public, self-hosted runners combined with
   outside pull requests are a known risk.
5. **Memory trimming.** Agree to cut the always-loaded memory files (about 8k tokens today) to
   a short `AGENTS.md`, with the rest moved into skills and docs loaded on demand?
6. **Claude Code in the cloud.** Keep it available alongside the local stack for hard tasks, or
   retire it on this VM entirely?

## Sources

All read 2026-11-15.

1. OpenCode V2 docs index — https://opencode.ai/docs/llms.txt
2. OpenCode Config — https://opencode.ai/docs/config.md
3. OpenCode Agents — https://opencode.ai/docs/agents.md
4. OpenCode Models (local, compatibility, aliases) — https://opencode.ai/docs/models.md
5. OpenCode Providers — https://opencode.ai/docs/providers.md
6. OpenCode Permissions — https://opencode.ai/docs/permissions.md ; Policies — https://opencode.ai/docs/policies.md
7. OpenCode MCP servers — https://opencode.ai/docs/mcp-servers.md
8. OpenCode Plugins — https://opencode.ai/docs/plugins.md ; plugin server API (hooks) — https://opencode.ai/docs/build/plugins/server.md
9. OpenCode Tools (Code Mode, subagent, shell) — https://opencode.ai/docs/tools.md
10. OpenCode Instructions (AGENTS.md) — https://opencode.ai/docs/instructions.md ; Skills — https://opencode.ai/docs/skills.md ; Web search — https://opencode.ai/docs/websearch.md
11. Claude Code: Other LLM gateways — https://code.claude.com/docs/en/llm-gateway.md ; gateway compatibility guide — https://code.claude.com/docs/en/llm-gateway-protocol.md
12. Claude Code: connect to a gateway — https://code.claude.com/docs/en/llm-gateway-connect.md
13. Claude Code: model configuration — https://code.claude.com/docs/en/model-config.md ; environment variables — https://code.claude.com/docs/en/env-vars.md
14. Claude Code: data usage and telemetry — https://code.claude.com/docs/en/data-usage.md ; sub-agents — https://code.claude.com/docs/en/sub-agents.md ; memory — https://code.claude.com/docs/en/memory.md ; permissions — https://code.claude.com/docs/en/permissions.md ; sandboxing — https://code.claude.com/docs/en/sandboxing.md ; headless — https://code.claude.com/docs/en/headless.md ; CLI reference — https://code.claude.com/docs/en/cli-reference.md ; GitHub Actions — https://code.claude.com/docs/en/github-actions.md ; MCP — https://code.claude.com/docs/en/mcp.md
15. OpenCode CLI intro, commands, web/server, ACP — https://opencode.ai/docs/cli.md , https://opencode.ai/docs/cli/commands.md , https://opencode.ai/docs/cli/web.md , https://opencode.ai/docs/cli/acp.md
16. OpenCode Migrate from V1 (small_model, CLAUDE.md fallback) — https://opencode.ai/docs/migrate-v1.md ; Network — https://opencode.ai/docs/network.md
17. OpenCode repository: README, release v2.3.0 notes, `packages/schema/src/config.ts`, `packages/cli/src/server-process.ts`, `packages/util/src/observability.ts`, `packages/core/src/session/runner/prompt/system.txt` — https://github.com/anomalyco/opencode
18. OpenCode container publish script and registry manifest — https://github.com/anomalyco/opencode/blob/HEAD/.github/release/publish-docker.sh ; https://ghcr.io/v2/anomalyco/opencode/manifests/2.3.0
19. Claude Code licence — https://github.com/anthropics/claude-code/blob/HEAD/LICENSE.md ; npm `@anthropic-ai/claude-code` 2.1.325 — https://registry.npmjs.org/@anthropic-ai/claude-code/latest
20. LiteLLM: Claude Code with non-Anthropic models — https://docs.litellm.ai/docs/tutorials/claude_non_anthropic_models
21. LiteLLM: web search interception (SearXNG backend) — https://docs.litellm.ai/docs/integrations/websearch_interception
22. LiteLLM: Codex CLI client setup (seen as a search-result summary only) — https://docs.litellm.ai/docs/proxy/client_setup/codex_cli
23. Qwen Code hooks — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/hooks.md
24. Qwen Code settings reference — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/configuration/settings.md
25. Qwen Code model providers — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/configuration/model-providers.md
26. Qwen Code approval modes — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/approval-mode.md
27. Qwen Code sandbox — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/sandbox.md
28. Qwen Code sub-agents — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/sub-agents.md ; memory — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/memory.md ; worktrees — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/worktree.md ; headless — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/headless.md ; MCP — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/mcp.md ; GitHub Action — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/integration-github-action.md ; web search — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/developers/tools/web-search.md
29. Qwen Code README — https://github.com/QwenLM/qwen-code ; releases — https://github.com/QwenLM/qwen-code/releases
30. Qwen Code resident context cost — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/context-cost.md
31. Qwen Code terms and privacy (usage statistics) — https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/support/tos-privacy.md
32. Codex docs: advanced config — https://learn.chatgpt.com/docs/config-file/config-advanced.md ; config reference — https://learn.chatgpt.com/docs/config-file/config-reference.md ; subagents — https://learn.chatgpt.com/docs/agent-configuration/subagents.md ; hooks — https://learn.chatgpt.com/docs/hooks.md ; AGENTS.md — https://learn.chatgpt.com/docs/agent-configuration/agents-md.md ; sandboxing — https://learn.chatgpt.com/docs/sandboxing.md ; CLI commands — https://learn.chatgpt.com/docs/developer-commands.md?surface=cli ; GitHub Action — https://learn.chatgpt.com/docs/github-action.md ; open source — https://learn.chatgpt.com/docs/open-source.md ; releases — https://github.com/openai/codex/releases
33. Goose docs (hooks, custom agents, config files, goosehints, environment variables) — https://github.com/aaif-goose/goose/tree/HEAD/documentation/docs/guides ; releases — https://github.com/aaif-goose/goose/releases
34. Crush README and hooks guide — https://github.com/charmbracelet/crush ; https://github.com/charmbracelet/crush/blob/HEAD/docs/hooks/README.md ; subagent dispatch tool text — https://github.com/charmbracelet/crush/blob/HEAD/internal/agent/templates/agent_dispatch_tool.md
35. mcp-searxng README and npm 2.10.1 — https://github.com/ihor-sokoliuk/mcp-searxng ; https://registry.npmjs.org/mcp-searxng/latest
36. ssh-mcp README and npm 2.26.0 — https://github.com/tufantunc/ssh-mcp ; PyPI mcp-server-fetch — https://pypi.org/project/mcp-server-fetch/ ; npm @modelcontextprotocol/server-filesystem — https://registry.npmjs.org/@modelcontextprotocol/server-filesystem/latest
37. Pi README and docs (MCP, how Pi works, models configuration, NVIDIA RTX with llama.cpp) — https://github.com/earendil-works/pi ; https://github.com/earendil-works/pi/tree/HEAD/packages/coding-agent/docs
38. Systima measurement, via secondary coverage (July 2026) — https://www.edenai.co/post/claude-code-vs-opencode-the-33k-token-overhead-gap ; https://www.drweb.de/claude-code-sendet-33-000-token-vor-dem-ersten-prompt-opencode-nur-7-000/
39. D. Vaughan, "System prompts compared" (2026-04-19, updated 2026-11-15) — https://codex.danielvaughan.com/2026/04/19/system-prompts-compared-codex-gemini-claude-code/
40. D. Vaughan, "Does Pi outperform Codex CLI for local models?" (2026-04-19, updated 2026-11-15) — https://codex.danielvaughan.com/2026/04/19/does-pi-outperform-codex-cli-for-local-models/
41. "Tool definition tax" on a 22 GB 2080 Ti (2026-06-27) — https://ai-muninn.com/en/blog/tool-definition-tax-17k-context-economics
42. "Best agent harness for local LLMs" (2026-10-20, secondary) — https://llmconfigurator.com/en/blog/best-agent-harness-for-local-llms ; "Every AI coding harness compared" (2026-10-25, secondary) — https://tech.grahammiranda.com/ai-coding-harness-comparison/
43. Project status pages:
    - Roo Code repository (archived 2026-05-15) — https://github.com/RooCodeInc/Roo-Code
    - Continue homepage (joined Cursor) — https://continue.dev/
    - OpenHands CLI README (unmaintained) — https://github.com/OpenHands/OpenHands-CLI
    - OpenHands local LLMs — https://docs.openhands.dev/openhands/usage/llms/local-llms.md
    - Plandex README — https://github.com/plandex-ai/plandex
    - Aider on PyPI — https://pypi.org/project/aider-chat/
    - Kimi CLI (archived) — https://github.com/MoonshotAI/kimi-cli
    - Kilo Code README — https://github.com/Kilo-Org/kilocode
    - Cline README and docs index — https://github.com/cline/cline ; https://docs.cline.bot/llms.txt
    - Hermes Agent README — https://github.com/NousResearch/hermes-agent
    - Mistral Vibe README — https://github.com/mistralai/mistral-vibe
    - Gemini CLI releases — https://github.com/google-gemini/gemini-cli/releases
