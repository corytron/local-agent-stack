# Status

- 2026-11-15: v1.0 in preparation on PR #10 (`feat/stack-3`).
  - Research (#1, merged), stack design contract (#3), the four TrueNAS apps and the workstation
    clients (#4), tooling, CI and evals (#6), the deployment guide (#5, 18 chapters and appendices).
  - Review round: `docs/reviews/v1.0-coverage-repo.md` and `docs/reviews/v1.0-coverage-docs.md`;
    fixes in progress. Release waits until both lists are resolved.
  - Before tagging v1.0: merge #10, let the Caddy and MCP hub image workflows publish from main,
    make both GHCR packages public (owner, GitHub UI), pin their digests in a follow-up PR.
  - Nothing has run on the TrueNAS server yet: every hardware figure is an estimate and every
    `UNVERIFIED` item is a note in the guide (Chapter 1, "Validation status and known issues").
  - Open follow-ups: #17 (deploy.py image comparison with overrides).
