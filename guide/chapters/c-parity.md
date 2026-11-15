title: Feature parity with Claude Code
kind: appendix

# Feature parity with Claude Code

This appendix compares Claude Code, as documented in November 2026, with the stack's primary path:
OpenCode 2.3.0 on the workstation, the local models behind LiteLLM, and the stack's tool servers. It
then describes what changes when Claude Code itself runs against the gateway, and where the local
models fall short of Claude together with the mitigations the stack builds in.

Each comparison rates the parity of a feature on three levels.

Table: Parity levels

| Level | Meaning |
|---|---|
| Full | The stack provides the feature with equivalent behavior. The model behind it can still be weaker; see [Where local models fall short](#where-local-models-fall-short). |
| Partial | The stack provides the feature with limits, or through a workaround that the Notes column describes. |
| None | The stack does not provide the feature. |

## Parity by feature area

### Agent loop and context window

Table: Parity of the agent loop and context

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Agent loop with read, edit, search and shell tools | OpenCode built-in tools: `read`, `edit`, `write`, `glob`, `grep`, `shell`, `webfetch`, `subagent`, `skill` | Full | The local model loses the plan more often on long, multi-step tasks |
| Context window of 200,000 tokens or more | 65,536 tokens on `coder`, declared in `opencode.jsonc` | Partial | Compaction starts much earlier; long files and tool results fill the window quickly |
| Automatic compaction | OpenCode `compaction` settings | Full | Works from the declared context limit |
| Session resume | OpenCode `--continue` and `--session` | Full | |
| Todo list | OpenCode `experimental.todo` | Partial | Behind an experimental flag |
| Extended thinking and effort levels | Qwen3.8 reasoning effort (`low`, `medium`, `xhigh`); `local-fast` turns thinking off | Partial | No adaptive reasoning; `medium` is the recommended level for agents |
| Prompt caching | llama.cpp prefix cache and prompt cache in host RAM | Partial | `cache_control` has no effect. Editing earlier history makes the hybrid model process the whole prompt again |
| Parallel tool calls in one turn | `llama-server` tool calling | Partial | On the OpenAI route, llama.cpp makes parallel calls only when the request sets `"parallel_tool_calls": true`; on the Anthropic route the default follows the chat template. Local models make them less reliably than Claude. Whether OpenCode and Claude Code ask for them was not verified. If an agent's parallel calls arrive broken or duplicated, tell it to make one tool call per turn; the evaluation suites test parallel calls on the OpenAI route ([Evaluation suites](#evaluation-suites)) |

### Project memory parity

Table: Parity of project memory files

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| `CLAUDE.md` files at user, project and folder level | `AGENTS.md` at global (`~/.config/opencode/AGENTS.md`), project and folder level; templates in `clients/templates/` | Partial | OpenCode reads `CLAUDE.md` only when it is listed under `instructions`. No `@import` syntax. Edits are picked up during a session |
| Auto memory across sessions | None in the coding agents; Open WebUI's Memory in the web GUI | None | Keep a maintained instructions file, or add a memory MCP server. Open WebUI keeps each user's memories across its chats ([Memory levels in Open WebUI](#memory-levels-in-open-webui)), but OpenCode and Claude Code do not see them |

### Sub-agents and parallel agents

Table: Parity of sub-agents

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Custom sub-agents with their own prompt, model and tools | `clients/opencode/agents/`: `coordinator`, `researcher`, `builder`, `reviewer` (`description`, `mode`, `model`, `permissions`, `steps`) | Partial | Tools are limited through permission rules, not a tool list. No per-agent MCP servers or hooks |
| Background and parallel sub-agents | OpenCode sub-agents always run in the background and report when idle | Partial | Every agent shares one GPU. Run two to three at a time, and use `local-fast` for read-only scouts |
| A different model per sub-agent | The `model` field of each agent | Partial | Only one agent model fits on the GPU. An agent on `local-coder-moe` swaps the GPU model, which takes seconds |
| Agent teams and messaging between sessions | None | None | |

### Hooks and guard rules

Table: Parity of hooks

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Shell hooks on tool events, such as `PreToolUse` | OpenCode plugin `clients/opencode/plugins/guard.ts` (permission evaluation, before and after tool calls, before shell commands) | Partial | Written in TypeScript, not configured as shell commands. Qwen Code runs Claude-format hook scripts unchanged, if that matters more |
| Deny rules that project settings cannot loosen | OpenCode `policies` | Full | Hard limits that a project's configuration cannot override |

### Slash commands and skills

Table: Parity of commands and skills

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Custom slash commands | `clients/opencode/commands/`: `/plan`, `/issue`, `/pr`, `/check` | Full | Command files support `!` shell blocks and `$ARGUMENTS` |
| Skills (`SKILL.md`) | OpenCode skills | Full | OpenCode also reads skills from `.claude/skills` |

### MCP tool servers

Table: Parity of MCP support

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| MCP client for stdio and HTTP servers | OpenCode MCP client | Full | |
| Shared MCP servers for several clients | MCP hub (`mcp-proxy` v0.15.0) with `searxng`, `fetch` and `kb` at `https://mcp.lab.example.com/servers/<name>/mcp` | Full | One bearer token for every client; the hub has no per-user identity |
| Tool search, which keeps large tool sets out of the prompt | OpenCode Code Mode, which reaches MCP tools through one `execute` tool | Partial | Code Mode is harder for weak models; turned off, each tool's schema costs context in every request. Expose few tools to each agent |

### Permissions and sandboxing

Table: Parity of permissions and sandboxing

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Permission modes with allow, ask and deny rules | Ordered allow, ask and deny rules; `policies`; `opencode run --auto` | Partial | No named mode cycle such as `acceptEdits`, and no automatic approval classifier |
| Operating-system sandbox for shell commands | None in OpenCode | None | Run OpenCode as a dedicated unprivileged user ([Using gh from agents](#using-gh-from-agents)). This guide runs no container on a workstation, so it does not cover OpenCode's container image. Qwen Code has a bubblewrap sandbox (Appendix B) |
| Telemetry opt-out | OpenCode documents no telemetry; updates and the models.dev catalog download are turned off | Full | |

### Plan mode

Table: Parity of plan mode

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Plan mode | OpenCode `plan` agent (Tab switches agents); the `/plan` command | Full | Local models drift on long plans: keep the plan in a file |

### Web search and web fetch

Table: Parity of web search and fetch

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| WebSearch (a server tool run by Anthropic) | SearXNG through `mcp-searxng` on the MCP hub | Partial | Result quality depends on the upstream engines, which SearXNG suspends after CAPTCHAs. The model must refine its queries itself |
| WebFetch | OpenCode `webfetch`; the hub's `fetch` server and `web_url_read` | Partial | The hub's tools return the page text without a summary by a second model, so long pages fill the context. Keep their length limits |

### Documents and retrieval

Table: Parity of document retrieval

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Reads files in the workspace; no index of your documents | Open WebUI knowledge bases (pgvector hybrid search, Qwen3 embedding and reranking), synced from the `rag-docs` share by `oikb`; the `kb` tool on the MCP hub | Full | A capability that Claude Code does not have. The web GUI and the coding agent query the same index |

### Images and PDF reading

Table: Parity of image and PDF reading

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Reading images and screenshots | The vision projectors of `coder` and `coder-moe`, on the CPU; images attached in OpenCode, pasted or dragged into Claude Code, or dropped into an Open WebUI chat ([Images on the chat models](#images-on-the-chat-models)) | Partial | The 64K context stays, because the projector uses no VRAM, but each image takes about 11 seconds to encode on the CPU (estimate), more for a large one, and up to 4,096 tokens of the window (a 1920 x 1080 screenshot about 2,000). Not verified on the reference server: how well the model reads text in images with the Q8_0 projector ([Run the vision evaluation](#run-the-vision-evaluation)) |
| Reading PDF files, including their pages as images | Text and tables extracted by docling into the knowledge bases, or into a chat's own collection when you drop the PDF into an Open WebUI chat; `web_url_read` for remote PDFs | Partial | No visual reading of figures; scanned pages depend on OCR quality. A PDF sent to the model directly does not reach it: `llama-server` rejects a PDF part on the OpenAI route and drops a PDF block on the Anthropic route without an error, so a PDF that Claude Code reads is lost, and OpenCode tells the model that it cannot read the file |

### SSH and remote sessions

Table: Parity of SSH and remote use

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Commands on remote hosts through `ssh` in the shell tool, with permission prompts | `ssh-mcp` 2.26.0 on the workstation (stdio): policy, host-key pinning, approval prompts, audit log | Full | Stricter than plain `ssh`. Approval prompts need MCP elicitation in the harness; without it, `ssh-mcp` refuses destructive commands |
| Remote Control: driving a session from another device | `ssh c4dev` and OpenCode in that terminal, resumed with `opencode --continue` after a dropped connection; or OpenCode installed on the other device (Linux or macOS) against the same gateway | Partial | No background service: `clients/install.sh` keeps OpenCode's service disabled, because nothing of the stack runs on a workstation full time, so a session lives only as long as its terminal. Never run `opencode pair --remote`: it exposes the session's server through an internet tunnel. Claude Code's Remote Control is turned off when it uses a non-Anthropic base URL |

### GitHub integration

Table: Parity of GitHub integration

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| `git` and `gh` through the shell tool | The same commands, with allow rules for read-only `gh` commands | Full | |
| GitHub Actions integration (`anthropics/claude-code-action`) | `opencode run` in a workflow step | Partial | No first-party action. The runner must reach the gateway, so it has to be a self-hosted runner on the LAN; on a public repository that accepts outside pull requests, such a runner is a known risk |

### Headless runs and CI

Table: Parity of headless runs

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Headless mode (`claude -p`) with JSON output | `opencode run` with `--format json` and `--auto` | Full | |

### IDE integration

Table: Parity of IDE integration

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Extensions for VS Code and JetBrains IDEs | Editors that speak the Agent Client Protocol (ACP), such as Zed; the OpenCode desktop app | Partial | The OpenCode V2 documentation lists no first-party VS Code extension. Kilo Code, a fork of OpenCode, offers VS Code and JetBrains extensions |

### Models and model roles

Table: Parity of models and model roles

| Claude Code | This stack (component) | Parity | Notes |
|---|---|---|---|
| Main model (Opus, Sonnet) | Qwen3.8-27B as `local-coder` (`local-opus` and `local-sonnet` for Claude Code) | Partial | Artificial Analysis Intelligence Index 20, against 59 for Opus 5.5 and 55 for Sonnet 5.5 |
| Small, fast model (Haiku) | The same model with thinking off: `local-fast` (`local-haiku` for Claude Code) | Partial | Uses no extra VRAM, but shares the GPU with the main model instead of running beside it |
| Choosing a model per task (`/model`) | `local-coder-moe` (Qwen3.6-35B-A3B) as a faster profile | Partial | Switching swaps the GPU model. All Claude roles map to one model on a 16 GB GPU |
| Usage and cost reporting (`/cost`) | LiteLLM usage logs per key; Prometheus metrics | Partial | Tokens and durations per client; there is no money cost to report |
| Fast mode and Advisor | None | None | Claude-only features |

## Using Claude Code against the stack

Claude Code itself can use the gateway at `https://llm.lab.example.com` through LiteLLM's Anthropic
route `/v1/messages`, with the model names `local-opus`, `local-sonnet` and `local-haiku`. This path
keeps an existing `.claude/` setup unchanged. Anthropic does not support routing Claude Code to
non-Claude models through a gateway, so treat it as a compatibility path. Chapter 7 configures it
([Use Claude Code against the local gateway](#use-claude-code-against-the-local-gateway)).

Table: Claude Code with the local gateway

| Item | Behavior with the local gateway |
|---|---|
| Model aliases `opus`, `sonnet`, `haiku` | `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL` map them to the local names; all three reach the same model |
| Context window | Set `CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536`. Without it, Claude Code assumes a 1,000,000-token window for a model name it does not know, and compacts far too late |
| Output length | Set `CLAUDE_CODE_MAX_OUTPUT_TOKENS`. The default for unknown model names is 32,000 tokens, half of the window |
| Prompt cache | Set `CLAUDE_CODE_ATTRIBUTION_HEADER=0` so that the system prompt starts identically in every request |
| WebSearch | Not available: it is an Anthropic server tool. Use the SearXNG MCP server |
| WebFetch | Works with `"skipWebFetchPreflight": true` in `settings.json`; otherwise its domain check calls `api.anthropic.com` |
| Images and PDFs | A pasted, dragged or named image reaches the model as an image block (assumed; Claude Code's source is not public). A PDF block is dropped by `llama-server` without an error |
| Remote Control, fast mode, Advisor | Not available with a non-Anthropic base URL |
| `/cost` | Meaningless; use the LiteLLM usage logs |
| Prompt overhead | 11,375 tokens in the first request of `claude -p`, against 5,340 for `opencode run` (measured in November 2026) |
| Upgrades | New Claude Code releases can send request fields that the gateway rejects. Pin the version and test after each upgrade; set `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` if requests fail with "Extra inputs are not permitted" |

## Where local models fall short

The harness features above transfer almost completely. The models do not. Plan your work for a
model that is reliable at single, short tool calls and weaker at long, multi-step work.

### Measured gap to Claude

Table: Artificial Analysis Intelligence Index (v5.0.1, read 15 November 2026)

| Model | Index | Note |
|---|---|---|
| Claude Opus 5.5 (Max) | 59 | |
| Claude Sonnet 5.5 (Max) | 55 | |
| Claude Haiku 5.5 (Max) | 36 | |
| Qwen3.8-Flash-Next | 29 | Needs more system memory than the reference system has (Appendix B) |
| Qwen3.8-27B, reasoning effort `xhigh` | 20 | The stack's main model. 17 at `medium`, 10 with thinking off |

On agentic work, a model of this size is roughly at the level of last year's Haiku for single,
short tool calls, and well below Haiku 5.5 on long, multi-step work. Vendor benchmarks are less
useful as a guide: they are run at full precision with a 256,000-token context, while the stack
runs the model at about 3.5 bits per weight with 64K context. Do not read the vendor's claim that
Qwen3.8-27B beats Opus 4.6 on SWE-bench Pro as a statement about this deployment.

### Failure modes and mitigations

Table: Failure modes of local models and their mitigations

| Failure mode | What you see | Mitigation |
|---|---|---|
| Long multi-step tool loops | The agent repeats itself, loses the plan or retries a failing call | Give each agent a small, scoped task. Write the plan to a file (plan mode). Limit the steps per agent (`steps`). Stop and re-plan when the same tool call repeats |
| Context length | 64K tokens instead of 200,000 or more; accuracy drops at long context, most with thinking off | Keep thinking on at `medium`. Compact at 60 to 70 percent of the window. Let sub-agents with fresh contexts do the searching and reading, and return summaries |
| Prompt processing time | A 30,000-token first prompt takes 20 to 35 seconds; editing earlier history makes the model process the whole prompt again | Keep the system prompt and the tool list stable, append to the history instead of rewriting it, and keep llama.cpp's context checkpoints on |
| Instruction following with a long memory file | Rules in a long `AGENTS.md` are followed less reliably as the context grows | Keep `AGENTS.md` short, under about 2,000 to 3,000 tokens. Move hard rules into the guard plugin and `policies`, which apply deterministically |
| Too many tools | Each tool schema costs context and lowers the accuracy of tool choice | Expose few tools to each agent, with short descriptions and enumerated arguments |
| Malformed tool calls | Calls with broken arguments, or a call written inside the thinking block | llama.cpp constrains tool-call output with a grammar. Validate arguments and retry once in the harness. Pin the llama.cpp build and the chat template, and run the evaluations with their tool-calling suite after every change ([Evaluations and the regression gate](#evaluations-and-the-regression-gate)) |
| Latency of thinking | Long reasoning before every answer; Qwen3.8-27B used 128 million output tokens on the index at `xhigh`, against a median of 77.7 million | Use reasoning effort `medium` for the main loop, and `local-fast` (thinking off) for titles, summaries and scouts |
| Quantization loss over long runs | Quality studies of the quantized files cover single-turn tasks only | Prefer the 3.5-bit file or a larger one to smaller files. Repeat the evaluations after changing a model file |
| KV cache precision | Tool calling degrades with a `q4_0` KV cache | Keep the KV cache at `q8_0` |
| One GPU for every agent | Parallel agents wait for each other | Run two to three agents at a time |

### Narrowing the gap

The largest single improvement on the reference system is memory bandwidth. Two more matched
32 GB RDIMMs (four channels, 128 GB) make Qwen3.8-Flash-Next, which scores 29 on the index above,
usable at an estimated 25 to 35 tokens per second, with its experts in system memory. Appendix B
describes that profile and the memory upgrade.
