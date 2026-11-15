# Local Agent Stack

A self-hosted, local-model take on Claude Code's feature set: open-weight models on a TrueNAS SCALE
server with one NVIDIA RTX 4080, a terminal coding agent, a web GUI, RAG over your documents, web
search through SearXNG, and SSH tools for remote hosts.

**Documents:** [Deployment guide sources](guide/) · [Guide style](docs/guide-style.md) · [Research](docs/research/) · [Status](docs/status.md)

Build the guide: `python3 tools/guide/build.py` (needs Chromium, poppler-utils, python3-markdown, python3-yaml).
