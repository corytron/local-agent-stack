---
description: Check, push the current branch by name and open or update its pull request; usage /pr [issue number]
agent: coordinator
---
Branch, working tree and commits not on main:

!`git branch --show-current; git status --short; git log --oneline origin/main..HEAD`

Open or update the pull request for this branch. Issue: $ARGUMENTS

1. If the branch is main or master, stop: never push to main. Create a feature branch first.
2. If files are uncommitted, list them and ask before committing.
3. Run `tools/check.sh` if the project has it. Fix failures, or stop and report them.
4. If the change alters what the project does or documents, make sure CHANGELOG.md has a line
   for it under "## Unreleased" with the issue number; add and commit it if missing.
5. Push the branch by name: `git push -u origin <branch>`.
6. `gh pr view` for this branch. If there is no pull request, create one:
   `gh pr create --base main --title "<what it does>" --body "<what and why>

   Closes #<issue>"`. Otherwise report its URL and what the new commits add.
