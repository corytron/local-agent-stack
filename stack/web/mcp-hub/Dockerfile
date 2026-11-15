# mcp-hub: sparfenyuk/mcp-proxy 0.15.0 serving three stdio MCP servers as Streamable HTTP at
# /servers/<name>/mcp behind one bearer token (docs/stack-design.md §1-§3):
#   searxng  mcp-searxng 2.10.1                    web search + URL reader through SearXNG
#   fetch    mcp-server-fetch 2026.11.11 (Python)  official fetch server, page to Markdown
#   kb       open-webui-knowledge-mcp-server 0.2.0 Open WebUI knowledge bases (same index as the GUI)
#
# Build: docker build -t local-agent-stack-mcp-hub stack/web/mcp-hub
# Every dependency is pinned: the base image by digest, the Node.js tree by package-lock.json
# (npm ci), the Python tree by requirements-fetch.txt with hashes (--require-hashes). Both lock
# files were resolved with nothing newer than 2026-11-12; regenerate them as README.md shows.

FROM ghcr.io/sparfenyuk/mcp-proxy:v0.15.0-debian-node@sha256:29265b23ef7517a095083714d582fcf47803287a3c3d66513e2a661d4b9ce3e9

LABEL org.opencontainers.image.title="local-agent-stack-mcp-hub" \
      org.opencontainers.image.description="mcp-proxy 0.15.0 with the searxng, fetch and kb MCP servers" \
      org.opencontainers.image.source="https://github.com/corytron/local-agent-stack" \
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /opt/mcp-hub

# Node.js servers. No package in the lock file has an install script, so scripts stay off.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund \
    && npm cache clean --force

# Python fetch server in its own virtual environment, every distribution checked by hash.
COPY requirements-fetch.txt ./
RUN uv venv --no-cache --python /usr/local/bin/python3 /opt/mcp-hub/fetch \
    && uv pip install --no-cache --python /opt/mcp-hub/fetch/bin/python \
       --require-hashes --no-deps -r requirements-fetch.txt

COPY console-to-stderr.cjs ./
COPY servers.json /etc/mcp-hub/servers.json
COPY healthcheck.py /usr/local/bin/mcp-hub-healthcheck

# Run as an unprivileged user; the servers need no host files and no writable paths but $HOME.
RUN chmod 0755 /usr/local/bin/mcp-hub-healthcheck \
    && groupadd --gid 10001 mcp \
    && useradd --uid 10001 --gid mcp --create-home --home-dir /home/mcp \
       --shell /usr/sbin/nologin mcp

USER mcp:mcp
WORKDIR /home/mcp
EXPOSE 8096

# ENTRYPOINT is the base image's: /usr/bin/catatonit -- mcp-proxy. The flags (host, port,
# --named-server-config /etc/mcp-hub/servers.json, --allowed-host) are set in compose.yaml.
