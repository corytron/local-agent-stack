/**
 * guard: hard rules for every OpenCode session on this workstation (OpenCode 2.3, V2 plugin API).
 *
 * clients/install.sh links this file to ~/.config/opencode/plugins/guard.ts; OpenCode loads
 * direct .ts files from that directory. It refuses:
 *   1. git push to main or master, a push of every branch, and a push that does not name its
 *      branch (so the current branch cannot silently be main);
 *   2. writing a file whose path looks like a secret store (.env, private keys, ~/.ssh, cloud
 *      credentials, ~/.config/local-agent-stack) or whose new text contains a credential
 *      (private key block, cloud or forge token);
 *   3. wiping commands: rm -r of /, ~, a top-level system directory, a home or pool directory or
 *      the whole working tree, --no-preserve-root, mkfs, dd or a redirect onto a disk, fork bombs.
 *
 * Mechanisms (opencode.ai/docs/build/plugins/server, migrate-v1):
 *   ctx.permission.hook("evaluate") sees every permission check that rules resolved to allow or
 *   ask: shell commands as the scanner's command strings (one per subcommand), edit targets as
 *   paths. Setting effect "deny" refuses it and the message reaches the model.
 *   ctx.tool.hook("execute.before") sees the tool input (write: path, content; edit: path,
 *   oldString, newString; patch: patchText) and blocks the call by throwing.
 * The "policies" in clients/opencode/opencode.jsonc repeat the simplest forms of these rules,
 * so they still hold if a project's config disables this plugin.
 *
 * Plugin.define(plugin) returns its argument unchanged (@opencode/plugin 2.3.0,
 * dist/promise/plugin.js), so this file exports the plain object and imports types only
 * (Plugin.Plugin is the interface Plugin.define takes): nothing has to be installed next to it.
 */
import type { Plugin } from "@opencode/plugin"

const PROTECTED_BRANCHES = new Set(["main", "master"])

// ---------------------------------------------------------------------------------------------
// Shell commands

/** Split a scanner-produced command into words, dropping one level of quotes. */
function words(command: string): string[] {
  const out: string[] = []
  const re = /"((?:\\.|[^"\\])*)"|'([^']*)'|(\S+)/g
  for (const m of command.matchAll(re)) out.push(m[1] ?? m[2] ?? m[3] ?? "")
  return out
}

const base = (word: string) => word.slice(word.lastIndexOf("/") + 1)

/** Drop VAR=value prefixes and wrappers such as sudo, env, nice, timeout, xargs. */
function unwrap(tokens: string[]): string[] {
  const wrappers = new Set(["sudo", "doas", "env", "nice", "nohup", "time", "command", "builtin",
    "exec", "stdbuf", "ionice", "timeout", "xargs", "chrt", "setsid"])
  const withArgument = new Set(["-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-n", "-c",
    "-s", "-k", "-I", "-L", "-P"])
  let i = 0
  while (i < tokens.length) {
    const t = tokens[i]
    if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(t)) { i++; continue }
    const name = base(t)
    if (!wrappers.has(name)) break
    i++
    while (i < tokens.length && tokens[i].startsWith("-")) {
      const option = tokens[i++]
      if (withArgument.has(option) && i < tokens.length) i++
    }
    if (name === "timeout" && i < tokens.length && /^\d/.test(tokens[i])) i++
  }
  return tokens.slice(i)
}

function gitPush(tokens: string[]): string | undefined {
  if (tokens.length === 0 || base(tokens[0]) !== "git") return
  let i = 1
  const globalWithArgument = new Set(["-C", "-c", "--git-dir", "--work-tree", "--namespace"])
  while (i < tokens.length && tokens[i].startsWith("-")) {
    if (globalWithArgument.has(tokens[i++])) i++
  }
  if (tokens[i] !== "push") return

  const pushWithArgument = new Set(["-o", "--push-option", "--repo", "--receive-pack", "--exec"])
  const flags = new Set<string>()
  const positional: string[] = []
  let onlyPositional = false
  for (let j = i + 1; j < tokens.length; j++) {
    const t = tokens[j]
    if (onlyPositional || !t.startsWith("-") || t === "-") { positional.push(t); continue }
    if (t === "--") { onlyPositional = true; continue }
    const name = t.split("=")[0]
    flags.add(name)
    if (pushWithArgument.has(name) && !t.includes("=")) j++
  }

  if (flags.has("--all") || flags.has("--branches") || flags.has("--mirror")) {
    return "This push sends every branch, including main. Push one feature branch by name: git push -u origin <branch>."
  }
  const refspecs = positional.slice(1)
  if (refspecs.length === 0) {
    if (flags.has("--tags")) return
    return "Name the branch you push (the current branch might be main): git push -u origin <feature-branch>."
  }
  for (const refspec of refspecs) {
    const spec = refspec.replace(/^\+/, "")
    if (spec === "HEAD") {
      return "Name the branch instead of HEAD: git push -u origin <feature-branch>."
    }
    const target = (spec.includes(":") ? spec.slice(spec.lastIndexOf(":") + 1) : spec)
      .replace(/^refs\/heads\//, "")
    if (PROTECTED_BRANCHES.has(target)) {
      return `Never push to ${target}. Push a feature branch and open a pull request: git push -u origin <branch>, then gh pr create.`
    }
  }
}

/** Targets whose recursive removal would wipe a system, a home, a pool or the working tree. */
function dangerousTarget(raw: string): boolean {
  const t = raw.replace(/\$\{HOME\}|\$HOME/g, "~")
  const trimmed = t.length > 1 ? t.replace(/\/+$/, "") : t
  if (["/", "/*", "~", "~/*", ".", "./*", "..", "../*", "*", ".*"].includes(trimmed)) return true
  if (/^~[A-Za-z0-9_.-]*\/?\*?$/.test(trimmed)) return true
  const top = "bin|boot|dev|etc|home|lib|lib32|lib64|libx32|media|mnt|opt|proc|root|run|sbin|srv|sys|usr|var|Users|Applications|Library|System|Volumes|private"
  if (new RegExp(`^/(${top})(/\\*)?$`).test(trimmed)) return true
  if (/^\/(home|Users|mnt|Volumes)\/[^/]+(\/\*)?$/.test(trimmed)) return true
  return false
}

function wipe(tokens: string[], command: string): string | undefined {
  if (/:\s*\(\s*\)\s*\{/.test(command)) return "Fork bombs are not allowed."
  if (/>\s*\/dev\/(sd|hd|vd|xvd|nvme|mmcblk|disk|rdisk)/.test(command)) {
    return "Writing onto a disk device is not allowed."
  }
  if (tokens.length === 0) return
  const name = base(tokens[0])
  const args = tokens.slice(1)
  if (args.includes("--no-preserve-root")) return "--no-preserve-root is not allowed."
  if (name.startsWith("mkfs") || name === "wipefs") return `${name} is not allowed: it erases a filesystem.`
  if (name === "dd" && args.some((a) => /^of=\/dev\//.test(a))) return "dd onto a device is not allowed."
  if (name === "shred" && args.some((a) => a.startsWith("/dev/"))) return "shred of a device is not allowed."

  const options = args.filter((a) => a.startsWith("-") && a !== "-" && a !== "--")
  const operands = args.filter((a) => !a.startsWith("-"))
  const recursive = options.some((o) => o === "--recursive" || /^-[A-Za-z]*[rR]/.test(o))
  const refuse = (target: string) =>
    `Refusing ${name} on ${target}: it would wipe a system, home, pool or the whole working tree. Remove specific paths instead, or ask the owner to run it.`

  if (name === "rm" && recursive) {
    const target = operands.find(dangerousTarget)
    if (target !== undefined) return refuse(target)
  }
  if ((name === "chmod" || name === "chown" || name === "chgrp") && recursive) {
    const target = operands.slice(1).find(dangerousTarget)
    if (target !== undefined) return refuse(target)
  }
  if (name === "find" && args.includes("-delete") && operands.length > 0 && dangerousTarget(operands[0])) {
    return refuse(operands[0])
  }
}

function checkCommand(command: string): string | undefined {
  const tokens = unwrap(words(command))
  return gitPush(tokens) ?? wipe(tokens, command)
}

// ---------------------------------------------------------------------------------------------
// Files

const SECRET_PATHS: RegExp[] = [
  /\.env$/, // .env, client.env, edge.env (not edge.env.example)
  /(^|\/)\.env\.(?!example$|sample$|template$|dist$)[^/]+$/, // .env.local, .env.production
  /\.(pem|key|p12|pfx|jks|keystore|kdbx|ovpn)$/i,
  /(^|\/)id_(rsa|dsa|ecdsa|ed25519)(_sk)?$/,
  /(^|\/)\.ssh\//,
  /(^|\/)\.gnupg\//,
  /(^|\/)\.(netrc|git-credentials|pgpass|npmrc|pypirc)$/,
  /(^|\/)\.aws\/(credentials|config)$/,
  /(^|\/)\.docker\/config\.json$/,
  /(^|\/)\.kube\/config$/,
  /(^|\/)\.config\/gh\/hosts\.yml$/,
  /(^|\/)\.config\/local-agent-stack\//,
  /(^|\/)secrets\//,
]

function secretPath(path: string): string | undefined {
  const p = path.replace(/\\/g, "/")
  if (SECRET_PATHS.some((re) => re.test(p))) {
    return `Refusing to write ${path}: it looks like a secret file. Secrets stay out of the repository; document the variable in a *.env.example file with a placeholder instead.`
  }
}

const SECRET_TEXT: Array<[string, RegExp]> = [
  ["a private key", /-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----/],
  ["an AWS access key", /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/],
  ["a GitHub token", /\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b/],
  ["a GitLab token", /\bglpat-[A-Za-z0-9_-]{20,}\b/],
  ["a Slack token", /\bxox[abprs]-[A-Za-z0-9-]{10,}/],
  ["a Hugging Face token", /\bhf_[A-Za-z0-9]{30,}\b/],
  ["a Cloudflare API token", /\bcf(?:ut|at)_[A-Za-z0-9_-]{32,}\b/],
  // sk-... API keys (LiteLLM, OpenAI, Anthropic): only when the tail mixes letters and digits,
  // so placeholders such as sk-local-... or sk-xxxxxxxx pass.
  ["an API key", /\bsk-(?:[A-Za-z]+-)?(?=[A-Za-z0-9_-]*[0-9])(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{20,}\b/],
]

function secretText(text: string): string | undefined {
  for (const [what, re] of SECRET_TEXT) {
    if (re.test(text)) {
      return `Refusing to write ${what} into a file. Use a placeholder (for example sk-local-...) and keep the real value in an environment variable or a secrets file outside the repository.`
    }
  }
}

/**
 * What a write, edit or patch call adds, read from its input; undefined for every other tool
 * (read, shell, ...), which is recognised by the absence of these fields rather than by tool
 * name. Patch targets are paths inside patchText; the permission hook checks those.
 */
function written(input: unknown): { path?: string; text: string } | undefined {
  if (typeof input !== "object" || input === null) return
  const i = input as Record<string, unknown>
  const path = typeof i.path === "string" ? i.path : typeof i.filePath === "string" ? i.filePath : undefined
  if (typeof i.content === "string") return { path, text: i.content }
  if (typeof i.newString === "string") return { path, text: i.newString }
  if (typeof i.patchText === "string") {
    return { text: i.patchText.split("\n").filter((line) => line.startsWith("+")).join("\n") }
  }
}

// ---------------------------------------------------------------------------------------------

const guard: Plugin.Plugin = {
  id: "local-agent-stack.guard",
  async setup(ctx) {
    await ctx.permission.hook("evaluate", (event) => {
      let reason: string | undefined
      if (event.action === "shell") {
        for (const command of event.resources) reason ??= checkCommand(command)
      } else if (event.action === "edit") {
        for (const path of event.resources) reason ??= secretPath(path)
      }
      if (reason !== undefined) {
        event.effect = "deny"
        event.message = `guard: ${reason}`
      }
    })

    await ctx.tool.hook("execute.before", (event) => {
      const change = written(event.input)
      if (change === undefined) return
      const reason = (change.path !== undefined ? secretPath(change.path) : undefined) ?? secretText(change.text)
      if (reason !== undefined) throw new Error(`guard: ${reason}`)
    })
  },
}

export default guard
