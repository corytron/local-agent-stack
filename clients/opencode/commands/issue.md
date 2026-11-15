---
description: Start work on a GitHub issue; usage /issue <number>
agent: coordinator
---
Start work on issue $1.

!`gh issue view $1`

1. If the issue above is closed or missing, stop and say so.
2. Create the branch from an up-to-date main: `git switch main`, `git pull --ff-only`, then
   `git switch -c <type>/$1-<short-slug>` (type: feat, fix, docs or chore).
3. Plan as /plan does: approach, files, contract, split, checks.
4. If more than one agent will work on it, write the contract into docs/ and commit it:
   `git commit -m "Contract for #$1: <title>"`.
5. Open the pull request early with /pr (its body says "Closes #$1").
6. Start the parts: at most 2 subagents at a time, each with a complete brief.
