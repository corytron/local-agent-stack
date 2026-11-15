#!/usr/bin/env bash
# Install the tools tools/check.sh needs, pinned, without sudo (docs/stack-design.md, section 8),
# and point git at the repository's hooks (git config core.hooksPath tools/hooks).
#
# Usage: tools/setup-checks.sh [TOOL...]
#   TOOL  install only these: ruff zizmor shellcheck yamllint pymarkdown (one Python lane),
#         actionlint, gitleaks. Default: all of them. CI's Secrets job asks for gitleaks only.
#
# Where things go. Every tool lands in this repository's own tool directory,
#   $LAS_TOOLS_DIR (default ${XDG_DATA_HOME:-~/.local/share}/local-agent-stack/check-tools),
# whose bin/ tools/check.sh puts first on PATH, so this repository always runs the versions
# pinned here even when another project keeps other versions in ~/.local/bin. Each command is
# also linked into ~/.local/bin when ~/.local/bin has no command of that name (an existing one
# is never replaced: the VM shares ~/.local/bin with other projects).
#   - Python tools (ruff, zizmor, yamllint, pymarkdown and shellcheck from shellcheck-py): one
#     virtual environment, $LAS_TOOLS_DIR/venv, filled from tools/requirements-checks.txt with
#     `pip install --require-hashes --no-deps --only-binary=:all:`: every file is checked against
#     the sha256 listed there, nothing unlisted and no source build is installed. Their commands
#     are linked into $LAS_TOOLS_DIR/bin (the venv's own bin/ never goes on PATH, so `python3`
#     stays the system one). Reinstalled only when the requirements file changes.
#   - actionlint 1.7.12 and gitleaks 8.30.1: release archives fetched with curl into a fresh
#     temporary directory, verified against the sha256 below before anything is extracted, then
#     installed into $LAS_TOOLS_DIR/bin; when the release URL fails, the same asset is fetched by
#     its id from the GitHub REST API (the sha256 check is the same either way). Skipped when the
#     command on PATH already reports the pinned version.
#   - shellcheck: shellcheck-py's 0.11.0 is installed in the venv either way (check.sh uses it);
#     it is linked into ~/.local/bin only when no shellcheck is on PATH at all.
#
# The installs run in three lanes at the same time: Python, actionlint, gitleaks. Each lane's
# output is kept apart and printed in that order; the exit status is that of the first lane that
# failed. JOBS=1 runs the lanes one after another and stops at the first failure.
# In GitHub Actions ($GITHUB_PATH set) $LAS_TOOLS_DIR/bin is added to the job's PATH, and
# core.hooksPath is left alone. Linux x86_64 only for the release binaries.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUIREMENTS="$ROOT/tools/requirements-checks.txt"

TOOLS_DIR="${LAS_TOOLS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/local-agent-stack/check-tools}"
TOOLS_BIN="$TOOLS_DIR/bin"
VENV="$TOOLS_DIR/venv"
USER_BIN="$HOME/.local/bin"

ACTIONLINT_VERSION=1.7.12
ACTIONLINT_ASSET="actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz"
ACTIONLINT_URL="https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${ACTIONLINT_ASSET}"
ACTIONLINT_SHA256=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
# The same asset through the REST API (`gh api repos/rhysd/actionlint/releases/tags/v1.7.12`:
# its digest field matches the sha256 above).
ACTIONLINT_API_URL="https://api.github.com/repos/rhysd/actionlint/releases/assets/384924896"

GITLEAKS_VERSION=8.30.1
GITLEAKS_ASSET="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
GITLEAKS_URL="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${GITLEAKS_ASSET}"
GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
GITLEAKS_API_URL="https://api.github.com/repos/gitleaks/gitleaks/releases/assets/378332058"

# The commands the Python lane provides, and the venv entry point each one is.
PY_COMMANDS=(ruff zizmor shellcheck yamllint pymarkdown)
ALL_TOOLS=("${PY_COMMANDS[@]}" actionlint gitleaks)

usage() {
	echo "usage: tools/setup-checks.sh [TOOL...]" >&2
	echo "tools: ${ALL_TOOLS[*]}" >&2
}

wanted=()
for arg in "$@"; do
	case "$arg" in
		-h | --help)
			usage
			exit 0
			;;
	esac
	known=no
	for tool in "${ALL_TOOLS[@]}"; do
		if [[ "$tool" == "$arg" ]]; then
			known=yes
		fi
	done
	if [[ "$known" == no ]]; then
		echo "setup-checks.sh: unknown tool: $arg" >&2
		usage
		exit 2
	fi
	wanted+=("$arg")
done
if [[ ${#wanted[@]} -eq 0 ]]; then
	wanted=("${ALL_TOOLS[@]}")
fi

if [[ -n "${JOBS:-}" && ! "${JOBS}" =~ ^[1-9][0-9]*$ ]]; then
	echo "setup-checks.sh: JOBS must be a whole number from 1 (JOBS=1 installs serially), not '$JOBS'" >&2
	exit 2
fi

is_wanted() {
	local tool
	for tool in "$@"; do
		for want in "${wanted[@]}"; do
			if [[ "$want" == "$tool" ]]; then
				return 0
			fi
		done
	done
	return 1
}

mkdir -p "$TOOLS_BIN" "$USER_BIN"
export PATH="$TOOLS_BIN:$USER_BIN:$PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# version_of <command> [executable]: the version the command (found on PATH, or the given
# executable) reports, or nothing when there is none.
version_of() {
	local exe="${2:-$1}"
	command -v "$exe" >/dev/null 2>&1 || return 0
	case "$1" in
		ruff | zizmor) "$exe" --version 2>/dev/null | awk 'NR == 1 { print $2 }' ;;
		shellcheck) "$exe" --version 2>/dev/null | awk '/^version:/ { print $2 }' ;;
		yamllint) "$exe" --version 2>/dev/null | awk 'NR == 1 { print $2 }' ;;
		pymarkdown) "$exe" version 2>/dev/null | awk 'NR == 1 { print $1 }' ;;
		actionlint) "$exe" --version 2>/dev/null | awk 'NR == 1 { print $1 }' ;;
		gitleaks) "$exe" version 2>/dev/null | awk 'NR == 1 { sub(/^v/, "", $1); print $1 }' ;;
	esac
}

# Link $TOOLS_BIN/<cmd> into ~/.local/bin unless ~/.local/bin already has that command (or,
# for shellcheck, unless any shellcheck is on PATH outside $TOOLS_BIN).
link_user_bin() {
	local cmd="$1" other
	if [[ ! -x "$TOOLS_BIN/$cmd" ]]; then
		return
	fi
	if [[ -e "$USER_BIN/$cmd" || -L "$USER_BIN/$cmd" ]]; then
		if [[ "$(readlink -f "$USER_BIN/$cmd")" != "$(readlink -f "$TOOLS_BIN/$cmd")" ]]; then
			echo "  $cmd: kept the existing $USER_BIN/$cmd ($(version_of "$cmd" "$USER_BIN/$cmd")); tools/check.sh runs $TOOLS_BIN/$cmd"
		fi
		return
	fi
	if [[ "$cmd" == shellcheck ]]; then
		other="$(PATH="${PATH#"$TOOLS_BIN:"}" command -v shellcheck || true)"
		if [[ -n "$other" ]]; then
			echo "  shellcheck: $other is on PATH; not linked into $USER_BIN (tools/check.sh runs $TOOLS_BIN/shellcheck)"
			return
		fi
	fi
	ln -s "$TOOLS_BIN/$cmd" "$USER_BIN/$cmd"
	echo "  $cmd: linked into $USER_BIN"
}

lane_python() {
	local stamp="$VENV/.requirements.sha256" want_sum have_sum="" cmd
	if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
		echo "setup-checks.sh: the Python tools need python3 3.11 or newer" >&2
		exit 1
	fi
	want_sum="$(sha256sum "$REQUIREMENTS" | awk '{ print $1 }')"
	if [[ -f "$stamp" ]]; then
		have_sum="$(cat "$stamp")"
	fi
	if [[ "$have_sum" == "$want_sum" && -x "$VENV/bin/python" ]]; then
		echo "python tools: already installed from this tools/requirements-checks.txt ($VENV)"
	else
		rm -rf "$VENV"
		if ! python3 -m venv "$VENV" >"$WORK/venv.log" 2>&1; then
			cat "$WORK/venv.log" >&2
			echo "setup-checks.sh: python3 -m venv failed (on Debian and Ubuntu: apt install python3-venv)" >&2
			exit 1
		fi
		"$VENV/bin/python" -m pip install --require-hashes --no-deps --only-binary=:all: \
			--quiet --disable-pip-version-check --no-input --requirement "$REQUIREMENTS"
		echo "$want_sum" >"$stamp"
		echo "python tools: installed into $VENV (every file's sha256 checked by pip)"
	fi
	for cmd in "${PY_COMMANDS[@]}"; do
		if [[ ! -x "$VENV/bin/$cmd" ]]; then
			echo "setup-checks.sh: $VENV/bin/$cmd is missing after the install" >&2
			exit 1
		fi
		ln -sfn "$VENV/bin/$cmd" "$TOOLS_BIN/$cmd"
	done
	for cmd in "${PY_COMMANDS[@]}"; do
		if is_wanted "$cmd"; then
			link_user_bin "$cmd"
		fi
	done
}

# install_release_binary <command> <version> <url> <asset name> <sha256> <api url>
# The archive holds the binary at its top level under the command's name.
install_release_binary() {
	local cmd="$1" want="$2" url="$3" asset="$4" sha256="$5" api_url="$6" have actual dir
	have="$(version_of "$cmd")"
	if [[ "$have" == "$want" ]]; then
		echo "$cmd $want: already installed ($(command -v "$cmd"))"
		return
	fi
	if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
		echo "setup-checks.sh: $cmd $want is pinned for Linux x86_64 only; this is $(uname -s) $(uname -m)" >&2
		exit 1
	fi
	dir="$WORK/$cmd"
	mkdir -p "$dir/extract"
	if ! curl --fail --silent --show-error --location --retry 3 --proto '=https' --tlsv1.2 \
		--output "$dir/$asset" "$url"; then
		echo "setup-checks.sh: $url failed; trying the same asset through the GitHub API" >&2
		curl --fail --silent --show-error --location --retry 3 --proto '=https' --tlsv1.2 \
			--header 'Accept: application/octet-stream' --output "$dir/$asset" "$api_url"
	fi
	actual="$(sha256sum "$dir/$asset" | awk '{ print $1 }')"
	if [[ "$actual" != "$sha256" ]]; then
		echo "setup-checks.sh: sha256 mismatch for $asset: expected $sha256, got $actual; not installed" >&2
		exit 1
	fi
	tar -xzf "$dir/$asset" -C "$dir/extract" "$cmd"
	install -m 0755 "$dir/extract/$cmd" "$TOOLS_BIN/$cmd"
	have="$(version_of "$cmd" "$TOOLS_BIN/$cmd")"
	if [[ "$have" != "$want" ]]; then
		echo "setup-checks.sh: installed $asset but $cmd reports '${have:-nothing}' (wanted $want)" >&2
		exit 1
	fi
	echo "$cmd $want: installed ($TOOLS_BIN/$cmd, sha256 verified)"
	link_user_bin "$cmd"
}

lane_actionlint() {
	install_release_binary actionlint "$ACTIONLINT_VERSION" "$ACTIONLINT_URL" "$ACTIONLINT_ASSET" \
		"$ACTIONLINT_SHA256" "$ACTIONLINT_API_URL"
}

lane_gitleaks() {
	install_release_binary gitleaks "$GITLEAKS_VERSION" "$GITLEAKS_URL" "$GITLEAKS_ASSET" \
		"$GITLEAKS_SHA256" "$GITLEAKS_API_URL"
}

lanes=()
if is_wanted "${PY_COMMANDS[@]}"; then
	lanes+=(lane_python)
fi
if is_wanted actionlint; then
	lanes+=(lane_actionlint)
fi
if is_wanted gitleaks; then
	lanes+=(lane_gitleaks)
fi

# Each lane in the background (a background job ignores Ctrl-C unless told otherwise; these
# stop with the script), its output into $WORK/<lane>.out and .err.
pids=()
statuses=()
for index in "${!lanes[@]}"; do
	(
		trap - INT
		"${lanes[$index]}"
	) >"$WORK/${lanes[$index]}.out" 2>"$WORK/${lanes[$index]}.err" &
	pids[index]=$!
	if [[ "${JOBS:-}" == 1 ]]; then
		statuses[index]=0
		wait "${pids[$index]}" || statuses[index]=$?
		if [[ "${statuses[$index]}" -ne 0 ]]; then
			break
		fi
	fi
done
first_failure=0
for index in "${!pids[@]}"; do
	if [[ -z "${statuses[$index]:-}" ]]; then
		statuses[index]=0
		wait "${pids[$index]}" || statuses[index]=$?
	fi
	cat "$WORK/${lanes[$index]}.out"
	cat "$WORK/${lanes[$index]}.err" >&2
	if [[ "${statuses[$index]}" -ne 0 && "$first_failure" -eq 0 ]]; then
		first_failure="${statuses[$index]}"
	fi
done
if [[ "$first_failure" -ne 0 ]]; then
	exit "$first_failure"
fi

if [[ -n "${GITHUB_PATH:-}" ]]; then
	echo "$TOOLS_BIN" >>"$GITHUB_PATH"
	echo "GitHub Actions: $TOOLS_BIN added to GITHUB_PATH"
elif git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
	# The hooks of tools/hooks/ (pre-push: no push to main, the fast checks first).
	if [[ "$(git -C "$ROOT" config --get core.hooksPath || true)" != tools/hooks ]]; then
		git -C "$ROOT" config core.hooksPath tools/hooks
		echo "git: core.hooksPath set to tools/hooks"
	else
		echo "git: core.hooksPath is tools/hooks"
	fi
fi

# Every tool's version, as tools/check.sh will find it.
echo "versions (tools/check.sh looks in $TOOLS_BIN first):"
for tool in "${ALL_TOOLS[@]}"; do
	if command -v "$tool" >/dev/null 2>&1; then
		echo "  $tool $(version_of "$tool") ($(command -v "$tool"))"
	else
		echo "  $tool (not installed)"
	fi
done
