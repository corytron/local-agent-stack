---
description: Run the project's checks (tools/check.sh) and summarise what fails
---
!`if [ -x tools/check.sh ]; then tools/check.sh $ARGUMENTS 2>&1 | tail -n 120; else echo "This project has no tools/check.sh."; fi`

Summarise the check output above. For each failing check: its name, the file and line it
names, and the most likely fix. If everything passed, say so in one line. Do not change files
unless I ask.
