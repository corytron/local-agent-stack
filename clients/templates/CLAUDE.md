@AGENTS.md

<!-- Template from local-agent-stack/clients/templates/CLAUDE.md. The import above loads
AGENTS.md, so Claude Code and OpenCode read the same rules: keep the rules there and only
Claude Code specifics here. Claude Code reads a bare AGENTS.md only when no CLAUDE.md exists in
the working directory or any directory above it (code.claude.com/docs/en/memory), so a
CLAUDE.md in your home directory would hide it; the import avoids that. -->

## Claude Code

- Subagents: use the Agent tool with the same roles as AGENTS.md (researcher, builder,
  reviewer). Give each a self-contained brief and the exact files it may edit.
- On the local gateway (`claude-local`), run at most 2 subagents at a time, as AGENTS.md says.
  Remote Control, web search and fast mode are not available there.
- Project hooks and permissions go in `.claude/settings.json`; enforce the same rules as the
  OpenCode guard plugin: no push to main, no secrets written to files.
