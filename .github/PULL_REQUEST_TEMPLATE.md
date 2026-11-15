<!-- One pull request per issue, from a branch named after it (CLAUDE.md, "Everything runs through GitHub"). -->

Closes #

## What changes

- One line per change; the issue says why.

## Checks

- [ ] `tools/check.sh` passes locally (the same checks as CI's Lint, Compose stack, Secrets and Guide jobs)
- [ ] `CHANGELOG.md` has a line under `## Unreleased` if the stack or the guide changes
- [ ] The guide and `stack/` agree (the guide quotes `stack/`; when they differ, `stack/` wins)
- [ ] Placeholders only: `192.0.2.10`, `192.0.2.20`, `lab.example.com`, pool `tank`, keys `sk-local-...`
- [ ] Anything not verified in a primary source is marked UNVERIFIED and listed here
