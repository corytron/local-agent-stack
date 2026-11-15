title: References
kind: appendix

# References

This appendix lists the primary sources behind the guide: vendor documentation, release notes,
source repositories and model cards that the research notes under `docs/research/` cite. Each note
names the exact page and the date it was read (all in November 2026); when the guide and a source
disagree with a newer release, the source and the release notes win.

## TrueNAS SCALE documentation

- [TrueNAS SCALE 25.10 version notes](https://www.truenas.com/docs/scale/25.10/gettingstarted/versionnotes/)
- [TrueNAS SCALE 25.10.0 release notes](https://update.freenas.org/scale/TrueNAS-SCALE-Goldeye/TrueNAS-SCALE-25.10.0.release-notes.txt)
- [Apps screens (25.10)](https://www.truenas.com/docs/scale/25.10/scaleuireference/apps/)
- [Install Custom App screens (25.10)](https://www.truenas.com/docs/scale/25.10/scaleuireference/apps/installcustomappscreens/)
- [Installing custom apps](https://apps.truenas.com/managing-apps/installing-custom-apps/)
- [Managing GPUs (25.10)](https://www.truenas.com/docs/scale/25.10/scaletutorials/systemsettings/advanced/managegpuscale/)
- [Advanced settings tutorials (25.10)](https://www.truenas.com/docs/scale/25.10/scaletutorials/systemsettings/advanced/)
- [Advanced Settings screen (25.10)](https://www.truenas.com/docs/scale/25.10/scaleuireference/systemsettings/advancedsettingsscreen/)
- [General Settings screens (25.10)](https://www.truenas.com/docs/scale/25.10/scaleuireference/systemsettings/generalsettingsscreens/)
- [Datasets (25.10)](https://www.truenas.com/docs/scale/25.10/scaletutorials/datasets/datasetsscale/)
- [Dataset permissions (25.10)](https://www.truenas.com/docs/scale/25.10/scaletutorials/datasets/permissionsscale/)
- [SMB shares (25.10)](https://www.truenas.com/docs/scale/25.10/scaletutorials/shares/smb/)
- [Periodic snapshot tasks (25.10)](https://www.truenas.com/docs/scale/25.10/scaletutorials/dataprotection/periodicsnapshottasksscale/)
- [Setting up backups (25.10)](https://www.truenas.com/docs/scale/25.10/gettingstarted/configure/setupbackupscale/)
- [TrueNAS API documentation](https://www.truenas.com/docs/scale/api/)
- [TrueNAS API v25.10 reference](https://api.truenas.com/v25.10/)
- [TrueNAS API client (`midclt` and Python client)](https://github.com/truenas/api_client)
- [TrueNAS apps catalog source](https://github.com/truenas/apps)
- [TrueNAS 26 deprecations](https://www.truenas.com/docs/scale/26/gettingstarted/deprecations/)
- [OpenZFS workload tuning](https://openzfs.github.io/openzfs-docs/Performance%20and%20Tuning/Workload%20Tuning.html)

## NVIDIA, CUDA and the host CPU

- [CUDA Toolkit release notes (driver compatibility tables)](https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html)
- [NVIDIA Container Toolkit: specialized configurations with Docker](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html)
- [NVIDIA driver persistence](https://docs.nvidia.com/deploy/driver-persistence/)
- [GeForce RTX 4080 product page](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4080/)
- [`nvidia/cuda` container images](https://hub.docker.com/r/nvidia/cuda)
- [NVIDIA GPU exporter for Prometheus](https://github.com/utkuozdemir/nvidia_gpu_exporter)
- [Intel Xeon W-3400 and W-2400 quick reference guide](https://cdrdv2-public.intel.com/751438/Intel%20Xeon_W-3400_and_Xeon_W-2400_QuickRefGuide.pdf)
- [Intel Xeon w5-3435X specifications](https://www.intel.com/content/www/us/en/products/sku/233421/intel-xeon-w53435x-processor-45m-cache-3-10-ghz/specifications.html)

## llama.cpp sources

- [llama.cpp repository](https://github.com/ggml-org/llama.cpp)
- [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)
- [llama.cpp container images](https://github.com/ggml-org/llama.cpp/pkgs/container/llama.cpp)
- [llama-server README (flags and endpoints)](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama-bench README](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md)
- [Function calling in llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
- [Speculative decoding in llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
- [llama.cpp Docker documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md)
- [llama.cpp CUDA Dockerfile](https://github.com/ggml-org/llama.cpp/blob/master/.devops/cuda.Dockerfile)

## llama-swap sources

- [llama-swap repository and README](https://github.com/mostlygeek/llama-swap)
- [llama-swap configuration reference](https://github.com/mostlygeek/llama-swap/blob/main/docs/config.example.yaml)
- [llama-swap container build](https://github.com/mostlygeek/llama-swap/blob/main/docker/llama-swap.Containerfile)
- [llama-swap unified image](https://github.com/mostlygeek/llama-swap/blob/main/docker/unified/README.md)

## LiteLLM documentation

- [LiteLLM releases](https://github.com/BerriAI/litellm/releases)
- [Docker quick start](https://docs.litellm.ai/docs/proxy/docker_quick_start)
- [Configuration settings](https://docs.litellm.ai/docs/proxy/config_settings)
- [Virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys)
- [Users and budgets](https://docs.litellm.ai/docs/proxy/users)
- [Custom pricing](https://docs.litellm.ai/docs/proxy/custom_pricing)
- [Prometheus metrics](https://docs.litellm.ai/docs/proxy/prometheus)
- [Health checks](https://docs.litellm.ai/docs/proxy/health)
- [Anthropic `/v1/messages` endpoint](https://docs.litellm.ai/docs/anthropic_unified)
- [Anthropic provider](https://docs.litellm.ai/docs/providers/anthropic)
- [OpenAI-compatible providers](https://docs.litellm.ai/docs/providers/openai_compatible)
- [Rerank](https://docs.litellm.ai/docs/rerank)
- [Claude Code with non-Anthropic models](https://docs.litellm.ai/docs/tutorials/claude_non_anthropic_models)
- [Web search interception](https://docs.litellm.ai/docs/integrations/websearch_interception)
- [LiteLLM PyPI and Docker compromise, October 2026 (Datadog Security Labs)](https://securitylabs.datadoghq.com/articles/litellm-compromised-pypi-docker/)

## Open WebUI documentation

- [Open WebUI releases](https://github.com/open-webui/open-webui/releases)
- [Open WebUI licence](https://docs.openwebui.com/license/)
- [Quick start (image tags)](https://docs.openwebui.com/getting-started/quick-start)
- [Environment variable reference](https://docs.openwebui.com/reference/env-configuration)
- [Retrieval-augmented generation](https://docs.openwebui.com/features/chat-conversations/rag)
- [Knowledge](https://docs.openwebui.com/features/workspace/knowledge)
- [Knowledge base sync (oikb)](https://docs.openwebui.com/ecosystem/knowledge-base-sync)
- [oikb daemon](https://docs.openwebui.com/ecosystem/knowledge-base-sync/daemon)
- [oikb repository](https://github.com/open-webui/oikb)
- [MCP support](https://docs.openwebui.com/features/extensibility/mcp)
- [SearXNG web search provider](https://docs.openwebui.com/features/chat-conversations/web-search/providers/searxng)
- [Agentic search and fetch](https://docs.openwebui.com/features/chat-conversations/web-search/agentic-search)
- [Docling document extraction](https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/docling)
- [Open WebUI with llama.cpp](https://docs.openwebui.com/alternatives/llama-cpp)

## SearXNG documentation

- [Installation with containers](https://docs.searxng.org/admin/installation-docker.html)
- [Settings and `use_default_settings`](https://docs.searxng.org/admin/settings/settings.html)
- [Container files and environment](https://github.com/searxng/searxng/tree/master/container)
- [Default settings](https://github.com/searxng/searxng/blob/master/searx/settings.yml)
- [Default limiter configuration](https://github.com/searxng/searxng/blob/master/searx/limiter.toml)

## Docling sources

- [docling-serve repository](https://github.com/docling-project/docling-serve)
- [docling-serve configuration](https://github.com/docling-project/docling-serve/blob/main/docs/configuration.md)
- [docling-mcp repository](https://github.com/docling-project/docling-mcp)

## MCP server sources

- [MCP reference servers (fetch, filesystem, git)](https://github.com/modelcontextprotocol/servers)
- [`mcp-server-fetch` on PyPI](https://pypi.org/project/mcp-server-fetch/)
- [mcp-proxy (the MCP hub)](https://github.com/sparfenyuk/mcp-proxy)
- [mcp-searxng](https://github.com/ihor-sokoliuk/mcp-searxng)
- [Open WebUI knowledge MCP server](https://github.com/RonasIT/open-webui-mcp-server)
- [ssh-mcp](https://github.com/tufantunc/ssh-mcp)
- [OpenSSH `sshd` manual (authorized_keys format)](https://man.openbsd.org/sshd.8)
- [OpenSSH `sshd_config` manual](https://man.openbsd.org/sshd_config.5)

## Caddy and certificates

- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Caddyfile `tls` directive](https://caddyserver.com/docs/caddyfile/directives/tls)
- [Running Caddy](https://caddyserver.com/docs/running)
- [caddy-dns provider modules](https://github.com/caddy-dns)

## OpenCode documentation

- [OpenCode documentation index](https://opencode.ai/docs/llms.txt)
- [Configuration](https://opencode.ai/docs/config.md)
- [Agents](https://opencode.ai/docs/agents.md)
- [Models (local models, compatibility)](https://opencode.ai/docs/models.md)
- [Providers](https://opencode.ai/docs/providers.md)
- [Permissions](https://opencode.ai/docs/permissions.md)
- [Policies](https://opencode.ai/docs/policies.md)
- [MCP servers](https://opencode.ai/docs/mcp-servers.md)
- [Plugins](https://opencode.ai/docs/plugins.md)
- [Plugin server API (hooks)](https://opencode.ai/docs/build/plugins/server.md)
- [Tools (Code Mode, subagent, shell)](https://opencode.ai/docs/tools.md)
- [Instructions (AGENTS.md)](https://opencode.ai/docs/instructions.md)
- [Skills](https://opencode.ai/docs/skills.md)
- [CLI](https://opencode.ai/docs/cli.md)
- [CLI commands](https://opencode.ai/docs/cli/commands.md)
- [Web and server](https://opencode.ai/docs/cli/web.md)
- [Network](https://opencode.ai/docs/network.md)
- [Migrating from V1](https://opencode.ai/docs/migrate-v1.md)
- [OpenCode repository and releases](https://github.com/anomalyco/opencode)

## Claude Code documentation

- [Memory (CLAUDE.md, AGENTS.md, imports)](https://code.claude.com/docs/en/memory)
- [LLM gateways](https://code.claude.com/docs/en/llm-gateway)
- [Gateway protocol compatibility](https://code.claude.com/docs/en/llm-gateway-protocol)
- [Connect to a gateway](https://code.claude.com/docs/en/llm-gateway-connect)
- [Model configuration](https://code.claude.com/docs/en/model-config)
- [Environment variables](https://code.claude.com/docs/en/env-vars)
- [Data usage and telemetry](https://code.claude.com/docs/en/data-usage)
- [Network configuration](https://code.claude.com/docs/en/network-config)
- [Feature availability](https://code.claude.com/docs/en/feature-availability)
- [Tools reference](https://code.claude.com/docs/en/tools-reference)
- [Subagents](https://code.claude.com/docs/en/sub-agents)
- [Permissions](https://code.claude.com/docs/en/permissions)
- [Sandboxing](https://code.claude.com/docs/en/sandboxing)
- [Headless mode](https://code.claude.com/docs/en/headless)
- [MCP](https://code.claude.com/docs/en/mcp)
- [Claude Code licence](https://github.com/anthropics/claude-code/blob/HEAD/LICENSE.md)

## Other coding agents

- [Qwen Code repository and README](https://github.com/QwenLM/qwen-code)
- [Qwen Code settings reference](https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/configuration/settings.md)
- [Qwen Code model providers](https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/configuration/model-providers.md)
- [Qwen Code hooks](https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/hooks.md)
- [Qwen Code approval modes](https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/approval-mode.md)
- [Qwen Code sandbox](https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/sandbox.md)
- [Qwen Code subagents](https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/sub-agents.md)
- [Qwen Code MCP](https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/mcp.md)
- [Qwen Code resident context cost](https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/features/context-cost.md)
- [Qwen Code terms and privacy](https://github.com/QwenLM/qwen-code/blob/HEAD/docs/users/support/tos-privacy.md)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference.md)
- [Codex advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced.md)
- [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md.md)
- [Codex releases](https://github.com/openai/codex/releases)
- [Pi repository](https://github.com/earendil-works/pi)
- [Goose releases](https://github.com/aaif-goose/goose/releases)
- [AGENTS.md format](https://agents.md/)

## Model cards and model files

- [Qwen3.8-27B model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- [Qwen3.8-27B GSQ-RCO GGUF files (IST-DASLab)](https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF)
- [Qwen3.8-27B GGUF files (Unsloth)](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF)
- [Qwen3.8-27B guide (Unsloth)](https://unsloth.ai/docs/models/qwen3.8-27b)
- [Qwen3.6-35B-A3B model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
- [Qwen3.6-35B-A3B GGUF files (Unsloth)](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF)
- [Qwen3-Embedding-0.6B GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF)
- [Qwen3-Reranker-0.6B Q8_0 GGUF (ggml-org)](https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF)
- [Qwen3.8-Flash-Next model card and licence](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)
- [Qwen3.8-Flash-Next GGUF files (Unsloth)](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF)
- [gpt-oss-120b GGUF (ggml-org)](https://huggingface.co/ggml-org/gpt-oss-120b-GGUF)
- [Artificial Analysis model leaderboard](https://artificialanalysis.ai/leaderboards/models)
- [Berkeley Function Calling Leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html)

## GitHub and project tooling

- [GitHub CLI manual](https://cli.github.com/manual)
- [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [REST API: repository rules](https://docs.github.com/en/rest/repos/rules)
- [REST API: code scanning](https://docs.github.com/en/rest/code-scanning/code-scanning)
- [About code scanning](https://docs.github.com/en/code-security/code-scanning/introduction-to-code-scanning/about-code-scanning)
- [About secret scanning](https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning)
- [Secure use reference (self-hosted runners)](https://docs.github.com/en/actions/reference/security/secure-use)
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub-hosted runner images](https://github.com/actions/runner-images)
- [Renovate Docker documentation](https://docs.renovatebot.com/docker/)
- [Dependabot supported ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories)
- [actionlint](https://github.com/rhysd/actionlint)
- [zizmor](https://github.com/zizmorcore/zizmor)
- [ShellCheck](https://github.com/koalaman/shellcheck)
- [yamllint](https://github.com/adrienverge/yamllint)
- [markdownlint-cli2](https://github.com/DavidAnson/markdownlint-cli2)
- [gitleaks](https://github.com/gitleaks/gitleaks)
- [Harbor (agent benchmarks)](https://github.com/laude-institute/harbor)
- [Berkeley Function Calling Leaderboard tooling](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard)
- [ragas](https://github.com/explodinggradients/ragas)

## Getting help

For a problem with this guide or the files it installs, open an issue in the project's repository,
[github.com/corytron/local-agent-stack](https://github.com/corytron/local-agent-stack). Search the
existing issues and Discussions first. For a problem in a component, ask where its maintainers
answer:

- [TrueNAS Community Forums](https://forums.truenas.com/)
- [llama.cpp Discussions](https://github.com/ggml-org/llama.cpp/discussions)
- [llama-swap issues](https://github.com/mostlygeek/llama-swap/issues)
- [LiteLLM issues](https://github.com/BerriAI/litellm/issues)
- [Open WebUI issues](https://github.com/open-webui/open-webui/issues)
- [OpenCode issues](https://github.com/anomalyco/opencode/issues)

Include in every report:

- The TrueNAS release (`midclt call system.version` in **System > Shell**) and the release tag
  of the stack you installed.
- The output of `nvidia-smi` on the server.
- The log of the failing container: `sudo docker logs <container>`, where `<container>` is the
  fixed name from the stack's compose file, for example `llama-swap` or `litellm`. TrueNAS writes
  compose errors to `/var/log/app_lifecycle.log`.
- What you ran and what you expected, with every address, domain, key and name replaced by the
  placeholders this guide uses (`192.0.2.10`, `lab.example.com`, `sk-local-...`).

!!! warning
    Logs and configuration files can contain API keys and tokens. Read every line before you post
    it in a public issue or forum.
