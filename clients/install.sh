#!/usr/bin/env bash
# clients/install.sh: set up the coding-agent side of the local agent stack on this machine
# (c4dev or the Mac). Safe to run again: it changes only what differs, and it never replaces a
# file of yours without moving it to <name>.bak.<time> first.
#
#   clients/install.sh [--dry-run] [--no-shell-rc] [--no-opencode] [--no-ssh-mcp]
#
# What it does (docs/stack-design.md §7, clients/README.md):
#   1. installs OpenCode OPENCODE_VERSION into ~/.opencode/bin: the same npm package and place
#      the official installer (https://opencode.ai/v2/install --version) uses, checked against
#      the sha512 below;
#   2. turns off OpenCode's shared background service, so every `opencode` runs its own server
#      that ends with it (owner rule: nothing of the stack runs full time on a workstation);
#   3. links clients/opencode/{opencode.jsonc,agents,commands,plugins} into ~/.config/opencode;
#   4. creates ~/.config/local-agent-stack/client.env (mode 600) with placeholders, once;
#   5. installs ssh-mcp SSH_MCP_VERSION for the SSH tool if Node.js >= 20.6 is present, and
#      copies its deny-by-default policy example once;
#   6. links ssh-mcp-stdio and claude-local into ~/.local/bin;
#   7. adds a marked block to your shell profile that loads client.env and sets PATH.
# It installs no service, timer or daemon.
set -euo pipefail

OPENCODE_VERSION=2.3.0
SSH_MCP_VERSION=2.26.0
NODE_MIN=20.6

# sha512 of https://registry.npmjs.org/@opencode/cli-<target>/-/cli-<target>-2.3.0.tgz, as npm's
# dist.integrity for that version (read 2026-11-15).
opencode_integrity() {
	case "$1" in
	linux-x64) echo "sha512-8T3K8L6Nd4fSG5BSgofqhmIDQ1ZvzDZZ2J7bFVB9RK1d5Hjqh24IcxgbcwpgGKkdvItrayi4Rl+wrSmhl17FFg==" ;;
	linux-x64-baseline) echo "sha512-wIMo9anUJIVlnBJlGM0lB7n+jmFMstRwjN6Lw8+s0hp+HpA94LmVMDDkTg+iQqzcsatlJaHre39v8x+jGQErRQ==" ;;
	linux-x64-musl) echo "sha512-wi9aSJOMaKgifrF4cyoE2hqIG26VtUhMvI1AFKbjItID16pcEpE0zZ2bGvL1Yb+1WgTeemWQLea/sNculu7v7A==" ;;
	linux-x64-baseline-musl) echo "sha512-yEraTu+gstB9g44Irx253Z7xx3d8G/6VX3sH5toynsLU8K3VI4+UAFFP6r5Waao6hYy0ATiSg2uwNdbZl1ZnJw==" ;;
	linux-arm64) echo "sha512-1IF1NQFD5mdZ7NcU81UifdYAVKEDAP/J07ylbgE4ZATminS7pOn5SOXVzyOkuN1WLcDzXunkju0hw8hug48wTg==" ;;
	linux-arm64-musl) echo "sha512-RJHOnYFNVLKg5ZVPDUBJI6noq+wkAg0+Ofndeirl/2TBmXq6qm8PF3nMkmCs4zCfwlZuzk1eiDBMgEyStY9wPA==" ;;
	darwin-arm64) echo "sha512-ey2HOWX2DK2YJrKta5a+pcvIlkiCyJJsN7NjkJZPsVg9TDXpQWE1OJLWVFqjxZcWNtaMjvKYlrlCY6g8Z2Lb+A==" ;;
	darwin-x64) echo "sha512-OARYGefjQb1xClR9lX0bTl/unxaJ2H9kpyqYuEH+59YdgantqpMdPrXXnJgwiydk3WP94CxWLXFOxSYtCxoDQQ==" ;;
	darwin-x64-baseline) echo "sha512-23KB1N3fK4seZ5Dc7izb9UKUqv24SVnEzH2WRU+LDMoEXQJzK/mgqADyBvjYG7J4l2GlB9dZ9Lr1qOWXpXNKvQ==" ;;
	*) return 1 ;;
	esac
}

DRY_RUN=0
SHELL_RC=1
DO_OPENCODE=1
DO_SSH_MCP=1

usage() {
	sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
	case "$1" in
	--dry-run) DRY_RUN=1 ;;
	--no-shell-rc) SHELL_RC=0 ;;
	--no-opencode) DO_OPENCODE=0 ;;
	--no-ssh-mcp) DO_SSH_MCP=0 ;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		echo "install.sh: unknown option $1" >&2
		usage >&2
		exit 2
		;;
	esac
	shift
done

CLIENTS_DIR=$(cd "$(dirname "$0")" && pwd -P)
STAMP=$(date +%Y%m%d-%H%M%S)
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
OPENCODE_CONFIG="$CONFIG_HOME/opencode"
STACK_CONFIG="$CONFIG_HOME/local-agent-stack"
OPENCODE_BIN_DIR="$HOME/.opencode/bin"
LOCAL_BIN="$HOME/.local/bin"
SSH_MCP_PREFIX="$HOME/.local/share/local-agent-stack/ssh-mcp"
OS=$(uname -s)
case "$OS" in
Darwin) SSH_MCP_CONFIG_DIR="$HOME/Library/Application Support/ssh-mcp" ;;
*) SSH_MCP_CONFIG_DIR="$CONFIG_HOME/ssh-mcp" ;;
esac

WORK_DIR=""
trap '[ -z "$WORK_DIR" ] || rm -rf "$WORK_DIR"' EXIT

say() { printf '%s\n' "$*"; }
note() { printf '  %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() {
	printf 'install.sh: %s\n' "$*" >&2
	exit 1
}

# Run a command, or print it with --dry-run.
run() {
	if [ "$DRY_RUN" = 1 ]; then
		printf '  [dry-run] %s\n' "$*"
	else
		"$@"
	fi
}

# A result line, printed only when something was really done.
did() {
	if [ "$DRY_RUN" = 0 ]; then
		note "$@"
	fi
}

# Move an existing file or link aside, keeping it.
backup() {
	local path=$1
	note "keeping your $path as $path.bak.$STAMP"
	run mv "$path" "$path.bak.$STAMP"
}

# Make $2 a symlink to $1. An existing file that is not that link is backed up first.
link() {
	local target=$1 path=$2
	if [ -L "$path" ] && [ "$(readlink "$path")" = "$target" ]; then
		note "ok      $path"
		return
	fi
	if [ -e "$path" ] || [ -L "$path" ]; then
		backup "$path"
	fi
	run mkdir -p "$(dirname "$path")"
	run ln -s "$target" "$path"
	did "linked  $path -> $target"
}

# Copy $1 to $2 with mode $3, only when $2 does not exist.
copy_once() {
	local source=$1 path=$2 mode=$3
	if [ -e "$path" ]; then
		note "ok      $path (exists, left as it is)"
		return
	fi
	run mkdir -p "$(dirname "$path")"
	run cp "$source" "$path"
	run chmod "$mode" "$path"
	did "created $path"
}

version_ge() { # version_ge 22.11.0 20.6
	local IFS=.
	local -a a b
	read -r -a a <<<"$1"
	read -r -a b <<<"$2"
	local i
	for i in 0 1 2; do
		local x=${a[i]:-0} y=${b[i]:-0}
		if ((10#$x > 10#$y)); then return 0; fi
		if ((10#$x < 10#$y)); then return 1; fi
	done
	return 0
}

for tool in curl tar openssl uname; do
	command -v "$tool" >/dev/null 2>&1 || die "$tool is required"
done

if [ "$DRY_RUN" = 1 ]; then
	say "Dry run: nothing is changed."
fi

# 1. OpenCode ---------------------------------------------------------------------------------

opencode_target() {
	local os arch target
	case "$OS" in
	Linux) os=linux ;;
	Darwin) os=darwin ;;
	*) die "unsupported OS $OS (Linux and macOS only)" ;;
	esac
	case "$(uname -m)" in
	x86_64 | amd64) arch=x64 ;;
	aarch64 | arm64) arch=arm64 ;;
	*) die "unsupported CPU $(uname -m)" ;;
	esac
	if [ "$os" = darwin ] && [ "$arch" = x64 ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = 1 ]; then
		arch=arm64
	fi
	target="$os-$arch"
	if [ "$arch" = x64 ]; then
		if [ "$os" = linux ] && ! grep -qwi avx2 /proc/cpuinfo 2>/dev/null; then
			target="$target-baseline"
		elif [ "$os" = darwin ] && [ "$(sysctl -n hw.optional.avx2_0 2>/dev/null || echo 0)" != 1 ]; then
			target="$target-baseline"
		fi
	fi
	if [ "$os" = linux ] && { [ -f /etc/alpine-release ] || { ldd --version 2>&1 || true; } | grep -qi musl; }; then
		target="$target-musl"
	fi
	echo "$target"
}

install_opencode() {
	say "OpenCode $OPENCODE_VERSION"
	local current=""
	if [ -x "$OPENCODE_BIN_DIR/opencode" ]; then
		current=$("$OPENCODE_BIN_DIR/opencode" --version 2>/dev/null || true)
		current=${current##* }
		current=${current#v}
	fi
	if [ "$current" = "$OPENCODE_VERSION" ]; then
		note "ok      $OPENCODE_BIN_DIR/opencode is $OPENCODE_VERSION"
		return
	fi

	local target integrity url
	target=$(opencode_target)
	integrity=$(opencode_integrity "$target") || die "no pinned checksum for target $target; use the official installer: curl -fsSL https://opencode.ai/v2/install | bash -s -- --version $OPENCODE_VERSION"
	url="https://registry.npmjs.org/@opencode/cli-$target/-/cli-$target-$OPENCODE_VERSION.tgz"
	note "${current:+replacing $current; }downloading $url"
	if [ "$DRY_RUN" = 1 ]; then
		printf '  [dry-run] download, check %s, install to %s/opencode\n' "${integrity:0:20}..." "$OPENCODE_BIN_DIR"
		return
	fi
	WORK_DIR=$(mktemp -d)
	curl -fsSL --proto '=https' --tlsv1.2 -o "$WORK_DIR/opencode.tgz" "$url"
	local actual
	actual="sha512-$(openssl dgst -sha512 -binary "$WORK_DIR/opencode.tgz" | openssl base64 -A)"
	[ "$actual" = "$integrity" ] || die "checksum mismatch for $url (expected $integrity, got $actual)"
	note "checksum ok"
	tar -xzf "$WORK_DIR/opencode.tgz" -C "$WORK_DIR"
	[ -f "$WORK_DIR/package/bin/opencode" ] || die "package/bin/opencode missing from $url"
	mkdir -p "$OPENCODE_BIN_DIR"
	if [ -e "$OPENCODE_BIN_DIR/opencode" ]; then
		mv "$OPENCODE_BIN_DIR/opencode" "$OPENCODE_BIN_DIR/opencode.bak.$STAMP"
		note "previous binary kept as $OPENCODE_BIN_DIR/opencode.bak.$STAMP"
	fi
	install -m 755 "$WORK_DIR/package/bin/opencode" "$OPENCODE_BIN_DIR/opencode"
	note "installed $OPENCODE_BIN_DIR/opencode ($("$OPENCODE_BIN_DIR/opencode" --version 2>/dev/null || echo "version unknown"))"
}

# 2. No background service ----------------------------------------------------------------------

disable_service() {
	say "OpenCode background service"
	if [ ! -x "$OPENCODE_BIN_DIR/opencode" ] && [ "$DRY_RUN" = 0 ]; then
		warn "opencode is not installed; skipped"
		return
	fi
	# Documented in opencode.ai/docs/cli: makes private per-command servers the default and
	# stops a running shared service. Setting it again is harmless.
	run "$OPENCODE_BIN_DIR/opencode" service set disabled true
	did "disabled: each opencode command runs its own server and stops it on exit"
}

# 3. Configs ------------------------------------------------------------------------------------

link_configs() {
	say "OpenCode configuration in $OPENCODE_CONFIG"
	if [ -e "$OPENCODE_CONFIG/opencode.json" ] && [ ! -L "$OPENCODE_CONFIG/opencode.json" ]; then
		warn "$OPENCODE_CONFIG/opencode.json would be merged with opencode.jsonc; moving it aside"
		backup "$OPENCODE_CONFIG/opencode.json"
	fi
	link "$CLIENTS_DIR/opencode/opencode.jsonc" "$OPENCODE_CONFIG/opencode.jsonc"
	local file
	for file in "$CLIENTS_DIR"/opencode/agents/*.md "$CLIENTS_DIR"/opencode/commands/*.md "$CLIENTS_DIR"/opencode/plugins/*.ts; do
		link "$file" "$OPENCODE_CONFIG/${file#"$CLIENTS_DIR"/opencode/}"
	done
}

# 4. client.env ---------------------------------------------------------------------------------

client_env() {
	say "Client secrets in $STACK_CONFIG"
	local path="$STACK_CONFIG/client.env"
	if [ -e "$path" ]; then
		note "ok      $path (exists, left as it is)"
	else
		run mkdir -p "$STACK_CONFIG"
		run chmod 700 "$STACK_CONFIG"
		if [ "$DRY_RUN" = 1 ]; then
			printf '  [dry-run] write %s (mode 600) with placeholders\n' "$path"
		else
			(
				umask 077
				cat >"$path" <<'EOF'
# Local agent stack: values for OpenCode, claude-local and the shell (docs/stack-design.md §6).
# Mode 600. Never commit this file.
LAB_DOMAIN=lab.example.com
LOCAL_LLM_KEY=sk-local-replace-with-your-litellm-virtual-key
MCP_HUB_TOKEN=replace-with-the-mcp-hub-token
EOF
			)
			note "created $path: replace the placeholders"
		fi
	fi
}

# 5. ssh-mcp ------------------------------------------------------------------------------------

install_ssh_mcp() {
	say "ssh-mcp $SSH_MCP_VERSION (SSH tool, stdio, started by OpenCode per session)"
	local node_version
	if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
		note "skipped: Node.js $NODE_MIN or newer and npm are needed (on Ubuntu: sudo apt install nodejs npm)"
		return
	fi
	node_version=$(node --version)
	node_version=${node_version#v}
	if ! version_ge "$node_version" "$NODE_MIN"; then
		note "skipped: Node.js $node_version is older than $NODE_MIN"
		return
	fi
	local installed=""
	if [ -f "$SSH_MCP_PREFIX/node_modules/ssh-mcp/package.json" ]; then
		installed=$(sed -n 's/^ *"version": *"\([^"]*\)".*/\1/p' "$SSH_MCP_PREFIX/node_modules/ssh-mcp/package.json" | head -n 1)
	fi
	if [ "$installed" = "$SSH_MCP_VERSION" ]; then
		note "ok      $SSH_MCP_PREFIX has ssh-mcp $SSH_MCP_VERSION"
	else
		# npm checks every package against the registry's integrity hash; no install scripts run.
		run mkdir -p "$SSH_MCP_PREFIX"
		run npm install --prefix "$SSH_MCP_PREFIX" --ignore-scripts --no-audit --no-fund --no-update-notifier --save-exact "ssh-mcp@$SSH_MCP_VERSION"
		did "installed ssh-mcp $SSH_MCP_VERSION in $SSH_MCP_PREFIX"
	fi
	run mkdir -p "$SSH_MCP_CONFIG_DIR"
	run chmod 700 "$SSH_MCP_CONFIG_DIR"
	copy_once "$CLIENTS_DIR/ssh-mcp/config.example.toml" "$SSH_MCP_CONFIG_DIR/config.toml" 600
}

# 6. Launchers ----------------------------------------------------------------------------------

link_launchers() {
	say "Launchers in $LOCAL_BIN"
	link "$CLIENTS_DIR/ssh-mcp/ssh-mcp-stdio" "$LOCAL_BIN/ssh-mcp-stdio"
	link "$CLIENTS_DIR/claude-code/claude-local" "$LOCAL_BIN/claude-local"
}

# 7. Shell profile ------------------------------------------------------------------------------

BEGIN_MARK="# >>> local-agent-stack (clients/install.sh) >>>"
END_MARK="# <<< local-agent-stack <<<"

rc_block() {
	cat <<'EOF'
# >>> local-agent-stack (clients/install.sh) >>>
if [ -r "$HOME/.config/local-agent-stack/client.env" ]; then
	set -a
	. "$HOME/.config/local-agent-stack/client.env"
	set +a
fi
case ":$PATH:" in *":$HOME/.opencode/bin:"*) ;; *) PATH="$HOME/.opencode/bin:$PATH" ;; esac
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
export PATH
export OPENCODE_DISABLE_MODELS_FETCH=1 OPENCODE_DISABLE_FREE_MODELS=1
# <<< local-agent-stack <<<
EOF
}

shell_rc() {
	local rc
	case "$(basename "${SHELL:-sh}")" in
	zsh) rc="${ZDOTDIR:-$HOME}/.zshrc" ;;
	bash) rc="$HOME/.bashrc" ;;
	*) rc="$HOME/.profile" ;;
	esac
	say "Shell profile $rc"
	local block current
	block=$(rc_block)
	if [ -f "$rc" ] && grep -qF "$BEGIN_MARK" "$rc"; then
		current=$(awk -v b="$BEGIN_MARK" -v e="$END_MARK" '$0==b{p=1} p{print} $0==e{p=0}' "$rc")
		if [ "$current" = "$block" ]; then
			note "ok      block present"
			return
		fi
		if [ "$DRY_RUN" = 1 ]; then
			printf '  [dry-run] replace the local-agent-stack block in %s (backup first)\n' "$rc"
			return
		fi
		cp "$rc" "$rc.bak.$STAMP"
		awk -v b="$BEGIN_MARK" -v e="$END_MARK" '$0==b{p=1; next} p&&$0==e{p=0; next} !p{print}' "$rc.bak.$STAMP" >"$rc"
		printf '%s\n' "$block" >>"$rc"
		note "updated block (previous file kept as $rc.bak.$STAMP)"
		return
	fi
	if [ "$DRY_RUN" = 1 ]; then
		printf '  [dry-run] append the local-agent-stack block to %s (backup first)\n' "$rc"
		return
	fi
	[ -f "$rc" ] && cp "$rc" "$rc.bak.$STAMP"
	printf '\n%s\n' "$block" >>"$rc"
	note "appended block; open a new terminal or run: . $rc"
}

# -----------------------------------------------------------------------------------------------

if [ "$DO_OPENCODE" = 1 ]; then
	install_opencode
	disable_service
fi
link_configs
client_env
if [ "$DO_SSH_MCP" = 1 ]; then
	install_ssh_mcp
fi
link_launchers
if [ "$SHELL_RC" = 1 ]; then
	shell_rc
else
	say "Shell profile: skipped (--no-shell-rc). Add this to it yourself:"
	rc_block | sed 's/^/  /'
fi

say ""
say "Next:"
note "1. Put your values into $STACK_CONFIG/client.env (LAB_DOMAIN, LOCAL_LLM_KEY, MCP_HUB_TOKEN)."
note "2. Open a new terminal, then check: opencode --version   (expect $OPENCODE_VERSION)"
note "3. In a project: opencode models   (expect local/local-coder, local/local-fast)"
note "4. SSH tool: edit $SSH_MCP_CONFIG_DIR/config.toml, then enable mcp.servers.ssh (clients/README.md)."
