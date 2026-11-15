# Status

- 2026-11-15: **v1.1 released** (https://github.com/corytron/local-agent-stack/releases/tag/v1.1):
  the MCP hub image rebuilt with zod 4.6.7 (#25, high advisory); guide revision A01.
- 2026-11-15: **v1.0 released** (https://github.com/corytron/local-agent-stack/releases/tag/v1.0):
  the deployment guide PDF (385 pages), `stack-v1.0.tar.gz`, `SHA256SUMS.txt`, with build
  attestations. Both project-built images (Caddy, MCP hub) are public and pinned by digest.
- Nothing has run on the TrueNAS server yet: every hardware figure is an estimate, and every
  not-verified item is listed in Chapter 1, "Validation status and known issues".
- Next: issue #18 (one-command maintenance update: stop the stack, update in order, verify,
  roll back) and issue #17 (deploy.py image comparison with overrides).
