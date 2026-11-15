---
description: Plan a change before any code is written (read-only); usage /plan <what to change or issue number>
agent: plan
---
Plan this change: $ARGUMENTS

Read first, change nothing: AGENTS.md, docs/status.md if it exists, the issue if a number was
given (`gh issue view <number>`), and the code and docs the change touches.

Then write the plan with exactly these headings:

1. **Goal**: one sentence, with the issue number.
2. **Approach**: 3 to 6 bullets.
3. **Files**: every file to create or change, one line each on why.
4. **Contract**: what the parts share (interface, file layout, names, ports, variables) and the
   docs/ file it goes in. Write "none" for a one-file change.
5. **Split**: at most 3 parts with disjoint files. For each: the agent (researcher or builder),
   the files it owns, and the command that proves it is done. One part is fine.
6. **Checks**: the commands that prove the whole change works.
7. **Open questions**: only real design choices the owner must make.

Mark every fact you did not confirm in a primary source `UNVERIFIED`. Stop after the plan.
