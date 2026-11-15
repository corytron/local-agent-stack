title: Configuration file reference
kind: appendix

# Configuration file reference

This appendix prints every file that the deployment installs or that you copy and edit, exactly as it ships in release 1.0 of the repository. The chapters quote the parts they need; this appendix is the complete text, for review and for recovery without network access. Files that contain only lock data (package hashes) are not printed; they are in the repository next to the files below.

## Inference app files

These files belong to the `ai-inference` TrueNAS app. On the server they are under `/mnt/tank/ai/stacks/local-agent-stack/`; the `.env.example` file is the template for the secrets file that lives outside the repository.

Table: Inference app files

| File | Purpose |
|---|---|
| `stack/inference/compose.yaml` | The ai-inference compose project: llama-swap, LiteLLM and its PostgreSQL. |
| `stack/inference/llama-swap/config.yaml` | Models llama-swap serves, their llama-server flags and groups. |
| `stack/inference/litellm/config.yaml` | Client-facing model names and how LiteLLM routes them. |
| `stack/inference/inference.env.example` | Variables for /mnt/tank/ai/secrets/inference.env. |

### inference/compose.yaml

The ai-inference compose project: llama-swap, LiteLLM and its PostgreSQL.

{{ include stack/inference/compose.yaml }}

### inference/llama-swap/config.yaml

Models llama-swap serves, their llama-server flags and groups.

{{ include stack/inference/llama-swap/config.yaml }}

### inference/litellm/config.yaml

Client-facing model names and how LiteLLM routes them.

{{ include stack/inference/litellm/config.yaml }}

### inference/inference.env.example

Variables for /mnt/tank/ai/secrets/inference.env.

{{ include stack/inference/inference.env.example }}

## RAG app files

These files belong to the `ai-rag` TrueNAS app. On the server they are under `/mnt/tank/ai/stacks/local-agent-stack/`; the `.env.example` file is the template for the secrets file that lives outside the repository.

Table: RAG app files

| File | Purpose |
|---|---|
| `stack/rag/compose.yaml` | The ai-rag compose project: pgvector, docling and oikb. |
| `stack/rag/oikb/oikb.yaml` | The document-share sync configuration. |
| `stack/rag/rag.env.example` | Variables for /mnt/tank/ai/secrets/rag.env. |

### rag/compose.yaml

The ai-rag compose project: pgvector, docling and oikb.

{{ include stack/rag/compose.yaml }}

### rag/oikb/oikb.yaml

The document-share sync configuration.

{{ include stack/rag/oikb/oikb.yaml }}

### rag/rag.env.example

Variables for /mnt/tank/ai/secrets/rag.env.

{{ include stack/rag/rag.env.example }}

## Web app files

These files belong to the `ai-web` TrueNAS app. On the server they are under `/mnt/tank/ai/stacks/local-agent-stack/`; the `.env.example` file is the template for the secrets file that lives outside the repository.

Table: Web app files

| File | Purpose |
|---|---|
| `stack/web/compose.yaml` | The ai-web compose project: Open WebUI, SearXNG and the MCP hub. |
| `stack/web/searxng/settings.yml` | SearXNG settings. |
| `stack/web/searxng/limiter.toml` | SearXNG limiter settings. |
| `stack/web/mcp-hub/Dockerfile` | How the MCP hub image is built. |
| `stack/web/mcp-hub/servers.json` | The tool servers the MCP hub serves. |
| `stack/web/web.env.example` | Variables for /mnt/tank/ai/secrets/web.env. |

### web/compose.yaml

The ai-web compose project: Open WebUI, SearXNG and the MCP hub.

{{ include stack/web/compose.yaml }}

### web/searxng/settings.yml

SearXNG settings.

{{ include stack/web/searxng/settings.yml }}

### web/searxng/limiter.toml

SearXNG limiter settings.

{{ include stack/web/searxng/limiter.toml }}

### web/mcp-hub/Dockerfile

How the MCP hub image is built.

{{ include stack/web/mcp-hub/Dockerfile }}

### web/mcp-hub/servers.json

The tool servers the MCP hub serves.

{{ include stack/web/mcp-hub/servers.json }}

### web/web.env.example

Variables for /mnt/tank/ai/secrets/web.env.

{{ include stack/web/web.env.example }}

## Edge app files

These files belong to the `ai-edge` TrueNAS app. On the server they are under `/mnt/tank/ai/stacks/local-agent-stack/`; the `.env.example` file is the template for the secrets file that lives outside the repository.

Table: Edge app files

| File | Purpose |
|---|---|
| `stack/edge/compose.yaml` | The ai-edge compose project: Caddy and the GPU exporter. |
| `stack/edge/Caddyfile` | Host names, TLS and reverse-proxy rules. |
| `stack/edge/Dockerfile` | How the Caddy image with DNS provider modules is built. |
| `stack/edge/edge.env.example` | Variables for /mnt/tank/ai/secrets/edge.env. |

### edge/compose.yaml

The ai-edge compose project: Caddy and the GPU exporter.

{{ include stack/edge/compose.yaml }}

### edge/Caddyfile

Host names, TLS and reverse-proxy rules.

{{ include stack/edge/Caddyfile }}

### edge/Dockerfile

How the Caddy image with DNS provider modules is built.

{{ include stack/edge/Dockerfile }}

### edge/edge.env.example

Variables for /mnt/tank/ai/secrets/edge.env.

{{ include stack/edge/edge.env.example }}

## Workstation files

Table: Workstation files

| File | Purpose |
|---|---|
| `clients/opencode/opencode.jsonc` | OpenCode configuration: provider, models, MCP servers, permissions. |
| `clients/opencode/agents/coordinator.md` | The coordinator agent. |
| `clients/opencode/agents/researcher.md` | The researcher agent. |
| `clients/opencode/agents/builder.md` | The builder agent. |
| `clients/opencode/agents/reviewer.md` | The reviewer agent. |
| `clients/opencode/commands/plan.md` | The /plan command. |
| `clients/opencode/commands/issue.md` | The /issue command. |
| `clients/opencode/commands/pr.md` | The /pr command. |
| `clients/opencode/commands/check.md` | The /check command. |
| `clients/opencode/plugins/guard.ts` | The guard plugin (rules enforced on every tool call). |
| `clients/claude-code/settings.json` | Claude Code settings for the local gateway. |
| `clients/ssh-mcp/config.example.toml` | SSH tool policy example. |
| `clients/templates/AGENTS.md` | Project memory template. |
| `clients/templates/CLAUDE.md` | Claude Code memory template that imports AGENTS.md. |
| `clients/install.sh` | Installs OpenCode and links these files on a workstation. |
| `clients/claude-code/claude-local` | Starts Claude Code against the local gateway. |
| `clients/ssh-mcp/ssh-mcp-stdio` | Launches the SSH tool as a stdio child of the agent. |

### clients/opencode/opencode.jsonc

OpenCode configuration: provider, models, MCP servers, permissions.

{{ include clients/opencode/opencode.jsonc }}

### clients/opencode/agents/coordinator.md

The coordinator agent.

{{ include clients/opencode/agents/coordinator.md }}

### clients/opencode/agents/researcher.md

The researcher agent.

{{ include clients/opencode/agents/researcher.md }}

### clients/opencode/agents/builder.md

The builder agent.

{{ include clients/opencode/agents/builder.md }}

### clients/opencode/agents/reviewer.md

The reviewer agent.

{{ include clients/opencode/agents/reviewer.md }}

### clients/opencode/commands/plan.md

The /plan command.

{{ include clients/opencode/commands/plan.md }}

### clients/opencode/commands/issue.md

The /issue command.

{{ include clients/opencode/commands/issue.md }}

### clients/opencode/commands/pr.md

The /pr command.

{{ include clients/opencode/commands/pr.md }}

### clients/opencode/commands/check.md

The /check command.

{{ include clients/opencode/commands/check.md }}

### clients/opencode/plugins/guard.ts

The guard plugin (rules enforced on every tool call).

{{ include clients/opencode/plugins/guard.ts }}

### clients/claude-code/settings.json

Claude Code settings for the local gateway.

{{ include clients/claude-code/settings.json }}

### clients/ssh-mcp/config.example.toml

SSH tool policy example.

{{ include clients/ssh-mcp/config.example.toml }}

### clients/templates/AGENTS.md

Project memory template.

{{ include clients/templates/AGENTS.md }}

### clients/templates/CLAUDE.md

Claude Code memory template that imports AGENTS.md.

{{ include clients/templates/CLAUDE.md }}

### clients/install.sh

Installs OpenCode and links these files on a workstation.

{{ include clients/install.sh }}

### clients/claude-code/claude-local

Starts Claude Code against the local gateway.

{{ include clients/claude-code/claude-local }}

### clients/ssh-mcp/ssh-mcp-stdio

Launches the SSH tool as a stdio child of the agent.

{{ include clients/ssh-mcp/ssh-mcp-stdio }}

## Deployment state file

Table: Deployment state file

| File | Purpose |
|---|---|
| `deploy/truenas.toml` | The desired state tools/deploy.py applies and checks. |

### deploy/truenas.toml

The desired state tools/deploy.py applies and checks.

{{ include deploy/truenas.toml }}
