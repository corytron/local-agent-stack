#!/usr/bin/env bash
# Run every check of the repository the same way on the workstation and in CI
# (docs/stack-design.md, section 8).
#
# Usage: tools/check.sh [--strict] [--only <name>...]
#   --strict          a check whose tool is not installed fails instead of being skipped
#                     (CI runs with it, so nothing is silently skipped on the runner)
#   --only <name>...  run only the named checks; they still report in the order below
#
# Checks, in order:
#   yaml       yamllint -s (.yamllint.yaml) over every YAML file git tracks or would track
#   shell      shellcheck -S style over every *.sh and every file with a sh/bash shebang
#   python     ruff check (with the S rules) and ruff format --check (pyproject.toml), then
#              python3 -B -m unittest, one process per tools/tests/test_*.py module
#   markdown   pymarkdown (.pymarkdown) over every Markdown file except the archival research
#              notes under docs/research/
#   workflows  actionlint; zizmor --min-severity medium over .github
#   compose    docker compose --env-file stack/<app>/<app>.env.example -f stack/<app>/compose.yaml
#              config -q, for every stack/<app>/ that has a compose.yaml (no daemon needed)
#   secrets    gitleaks (.gitleaks.toml) over the working tree and, at the same time, over the
#              history of every local ref (git log --all) or, in GitHub Actions, of HEAD only
#   links      python3 tools/check_links.py: every relative link and heading anchor of every
#              Markdown file resolves, offline
#   guide      python3 tools/guide/build.py: the guide renders to build/guide/*.pdf (needs
#              Chromium or Chrome, poppler-utils' pdfinfo, python3-markdown and python3-yaml)
#
# Every check runs at the same time, each one's output kept apart and reported in the order
# above as soon as it and every check before it are done, so the output reads like a serial
# run. Within a check, yaml, shell and markdown split their files into shards and python runs one
# process per test module. JOBS (environment) caps how many checks run at once and how many
# processes each check starts (default: nproc); JOBS=1 runs everything one at a time.
#
# One line per check: "ok <name>", "FAIL <name>" followed by the failing command's output, or
# "skip <name> (<tool> not installed: <hint>)". Exit 1 when a check failed, 2 on a usage error,
# else 0. Tools are looked up on PATH with tools/setup-checks.sh's tool directory first, then
# ~/.local/bin. ruff keeps its cache outside the tree, so gitleaks never reads a file being written.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TOOLS_DIR="${LAS_TOOLS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/local-agent-stack/check-tools}"
export PATH="$TOOLS_DIR/bin:$HOME/.local/bin:$PATH"
export RUFF_CACHE_DIR="${RUFF_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/local-agent-stack/ruff}"
export PYTHONDONTWRITEBYTECODE=1

ALL_CHECKS=(yaml shell python markdown workflows compose secrets links guide)

usage() {
	echo "usage: tools/check.sh [--strict] [--only <name>...]" >&2
	echo "checks: ${ALL_CHECKS[*]}" >&2
}

# The executables a check needs on PATH; a missing one makes the check a skip (or, with
# --strict, a failure).
tools_for() {
	case "$1" in
		yaml) echo yamllint git ;;
		shell) echo shellcheck git ;;
		python) echo ruff python3 ;;
		markdown) echo pymarkdown git ;;
		workflows) echo actionlint zizmor ;;
		compose) echo docker ;;
		secrets) echo gitleaks git ;;
		links) echo python3 git ;;
		guide) echo python3 pdfinfo chromium python3-markdown python3-yaml ;;
		*)
			echo "check.sh: no such check: $1" >&2
			exit 2
			;;
	esac
}

# How to get a missing tool.
hint_for() {
	case "$1" in
		yamllint | shellcheck | ruff | pymarkdown | actionlint | zizmor | gitleaks) echo "run tools/setup-checks.sh" ;;
		docker) echo "install Docker with the compose plugin" ;;
		pdfinfo) echo "apt install poppler-utils" ;;
		chromium) echo "install chromium (or google-chrome), or set CHROME to its path" ;;
		python3-markdown | python3-yaml) echo "apt install $1" ;;
		*) echo "install $1" ;;
	esac
}

# Whether a requirement is met: an executable on PATH, a Chromium/Chrome, or a Python module.
have_tool() {
	case "$1" in
		chromium)
			local candidate
			for candidate in "${CHROME:-}" chromium chromium-browser google-chrome google-chrome-stable; do
				if [[ -n "$candidate" ]] && command -v "$candidate" >/dev/null 2>&1; then
					return 0
				fi
			done
			return 1
			;;
		python3-markdown) python3 -c 'import markdown' >/dev/null 2>&1 ;;
		python3-yaml) python3 -c 'import yaml' >/dev/null 2>&1 ;;
		*) command -v "$1" >/dev/null 2>&1 ;;
	esac
}

# Print the command, then run it; the check's log shows what was run.
run() {
	echo "\$ $*"
	"$@"
}

# The files git tracks or would track (not ignored), NUL-separated, matching the pathspecs.
repo_files() {
	git ls-files -z --cached --others --exclude-standard -- "$@" | while IFS= read -r -d '' path; do
		if [[ -e "$path" ]]; then
			printf '%s\0' "$path"
		fi
	done
}

# sharded <files per shard at least> <command...> -- <file...>
# Runs the command over the files split into contiguous shards (at most max_jobs of them), all
# at once, and prints each shard's output in file order: the output of one run over all files.
sharded() {
	local per="$1"
	shift
	local -a cmd=()
	while [[ $# -gt 0 && "$1" != -- ]]; do
		cmd+=("$1")
		shift
	done
	shift
	local -a files=("$@")
	local total=${#files[@]} shards size start index rc=0 dir
	if [[ "$total" -eq 0 ]]; then
		echo "\$ ${cmd[*]}: no files"
		return 0
	fi
	shards=$(((total + per - 1) / per))
	if [[ "$shards" -gt "$max_jobs" ]]; then
		shards="$max_jobs"
	fi
	size=$(((total + shards - 1) / shards))
	echo "\$ ${cmd[*]} <$total files, $shards at once>"
	dir="$(mktemp -d "$results/shard.XXXXXX")"
	local -a pids=()
	start=0
	index=0
	while [[ "$start" -lt "$total" ]]; do
		(
			trap - INT
			"${cmd[@]}" "${files[@]:start:size}"
		) >"$dir/$index.log" 2>&1 &
		pids[index]=$!
		if [[ "$max_jobs" -eq 1 ]]; then
			wait "${pids[$index]}" || echo "$?" >"$dir/$index.failed"
		fi
		start=$((start + size))
		index=$((index + 1))
	done
	for index in "${!pids[@]}"; do
		if [[ "$max_jobs" -ne 1 ]]; then
			wait "${pids[$index]}" || echo "$?" >"$dir/$index.failed"
		fi
		cat "$dir/$index.log"
		if [[ -e "$dir/$index.failed" ]]; then
			rc=1
		fi
	done
	return "$rc"
}

check_yaml() {
	local -a files=()
	mapfile -d '' files < <(repo_files '*.yml' '*.yaml' '.yamllint.yaml')
	sharded 8 yamllint --strict --config-file .yamllint.yaml --format parsable -- "${files[@]}"
}

check_shell() {
	local -a files=() all=()
	local path first
	mapfile -d '' all < <(repo_files)
	for path in "${all[@]}"; do
		if [[ "$path" == *.sh ]]; then
			files+=("$path")
		elif [[ -f "$path" && ! "$path" =~ \.[A-Za-z0-9]+$ ]]; then
			first=""
			IFS= read -r first <"$path" 2>/dev/null || true
			if [[ "$first" =~ ^\#!.*[/[:space:]](ba|da|k)?sh([[:space:]]|$) ]]; then
				files+=("$path")
			fi
		fi
	done
	sharded 4 shellcheck -S style -- "${files[@]}"
}

check_python() {
	local rc=0 name log index failed=0 tests=0 modules
	run ruff check . || rc=1
	run ruff format --check . || rc=1
	if [[ ! -d tools/tests ]]; then
		echo "tools/tests/ does not exist: there are no Python unit tests to run"
		return 1
	fi
	local -a names=()
	mapfile -t names < <(find tools/tests -maxdepth 1 -name 'test_*.py' -type f -printf '%f\n' | LC_ALL=C sort)
	modules=${#names[@]}
	echo "\$ python3 -B -m unittest discover -s tools/tests -p <each of $modules modules, $max_jobs at once>"
	local dir pids=()
	dir="$(mktemp -d "$results/unittest.XXXXXX")"
	for index in "${!names[@]}"; do
		while [[ "$(jobs -rp | wc -l)" -ge "$max_jobs" ]]; do
			wait -n 2>/dev/null || true
		done
		(
			trap - INT
			if python3 -B -m unittest discover -s tools/tests -p "${names[$index]}" >"$dir/$index.log" 2>&1; then
				echo 0 >"$dir/$index.rc"
			else
				echo $? >"$dir/$index.rc"
			fi
		) &
		pids[index]=$!
	done
	for index in "${!pids[@]}"; do
		wait "${pids[$index]}" || true
	done
	for index in "${!names[@]}"; do
		name="${names[$index]}"
		log="$dir/$index.log"
		ran="$(awk '/^Ran [0-9]+ tests? in/ { n = $2 } END { print n + 0 }' "$log")"
		tests=$((tests + ran))
		if [[ "$(cat "$dir/$index.rc" 2>/dev/null || echo 1)" != 0 ]]; then
			failed=$((failed + 1))
			echo "== unittest $name"
			cat "$log"
		fi
	done
	echo "unittest: $modules modules, $tests tests, $failed modules failed"
	if [[ "$failed" -gt 0 || "$modules" -eq 0 ]]; then
		rc=1
	fi
	return "$rc"
}

check_markdown() {
	local -a files=()
	# docs/research/ holds archival research notes, kept as their authors wrote them: their links
	# are checked (links), their style is not.
	mapfile -d '' files < <(repo_files '*.md' ':(exclude)docs/research/')
	sharded 2 pymarkdown --config .pymarkdown --strict-config scan -- "${files[@]}"
}

check_workflows() {
	local rc=0
	run actionlint || rc=1
	run zizmor --min-severity medium --no-progress .github || rc=1
	return "$rc"
}

check_compose() {
	local dir app env index rc=0 found=0
	if ! docker compose version >/dev/null 2>&1; then
		echo "docker is installed but 'docker compose' is not: install the Docker compose plugin"
		return 1
	fi
	local -a apps=() pids=()
	for dir in stack/*/; do
		[[ -d "$dir" ]] || continue
		app="$(basename "$dir")"
		if [[ ! -f "stack/$app/compose.yaml" ]]; then
			echo "stack/$app/: no compose.yaml (yet); not checked"
			continue
		fi
		apps+=("$app")
	done
	if [[ ${#apps[@]} -eq 0 ]]; then
		echo "no stack/<app>/compose.yaml exists yet: nothing to check"
		return 0
	fi
	local logs
	logs="$(mktemp -d "$results/compose.XXXXXX")"
	for index in "${!apps[@]}"; do
		app="${apps[$index]}"
		env="stack/$app/$app.env.example"
		(
			trap - INT
			if [[ ! -f "$env" ]]; then
				echo "$env is missing: every stack/<app>/ documents its variables there (docs/stack-design.md, section 4)"
				exit 1
			fi
			run docker compose --env-file "$env" -f "stack/$app/compose.yaml" config -q
		) >"$logs/$index.log" 2>&1 &
		pids[index]=$!
		if [[ "$max_jobs" -eq 1 ]]; then
			wait "${pids[$index]}" || echo 1 >"$logs/$index.failed"
		fi
	done
	for index in "${!pids[@]}"; do
		if [[ "$max_jobs" -ne 1 ]]; then
			wait "${pids[$index]}" || echo 1 >"$logs/$index.failed"
		fi
		found=$((found + 1))
		cat "$logs/$index.log"
		if [[ -e "$logs/$index.failed" ]]; then
			rc=1
		fi
	done
	echo "compose: $found apps checked"
	return "$rc"
}

# Which history the secrets check reads: every local ref when run by hand (a stale branch or tag
# can hold history that a push --tags would publish), the checked-out commit's history in CI.
secrets_log_opts() {
	if [[ "${GITHUB_ACTIONS:-}" == true ]]; then
		echo HEAD
	else
		echo --all
	fi
}

check_secrets() {
	local rc=0
	if [[ ! -f .gitleaks.toml ]]; then
		echo ".gitleaks.toml is missing: the secrets check needs the repository's gitleaks rules"
		return 1
	fi
	local tree_log="$results/secrets-tree.log" history_log="$results/secrets-history.log" tree_pid history_pid
	(
		trap - INT
		run gitleaks dir . --config .gitleaks.toml --no-banner --redact
	) >"$tree_log" 2>&1 &
	tree_pid=$!
	if [[ "$max_jobs" -eq 1 ]]; then
		wait "$tree_pid" || rc=1
		tree_pid=""
	fi
	if git rev-parse --verify --quiet HEAD >/dev/null; then
		(
			trap - INT
			run gitleaks git . --config .gitleaks.toml --no-banner --redact "--log-opts=$(secrets_log_opts)"
		) >"$history_log" 2>&1 &
		history_pid=$!
	else
		echo "no commits yet: the history is not scanned" >"$history_log"
		history_pid=""
	fi
	if [[ -n "$tree_pid" ]]; then
		wait "$tree_pid" || rc=1
	fi
	if [[ -n "$history_pid" ]]; then
		wait "$history_pid" || rc=1
	fi
	cat "$tree_log" "$history_log"
	return "$rc"
}

check_links() {
	run python3 -I tools/check_links.py
}

check_guide() {
	run python3 -I tools/guide/build.py
}

strict=no
selected=()
while [[ $# -gt 0 ]]; do
	case "$1" in
		--strict)
			strict=yes
			shift
			;;
		--only)
			shift
			if [[ $# -eq 0 || "$1" == --* ]]; then
				echo "check.sh: --only needs at least one check name" >&2
				usage
				exit 2
			fi
			while [[ $# -gt 0 && "$1" != --* ]]; do
				known=no
				for name in "${ALL_CHECKS[@]}"; do
					if [[ "$name" == "$1" ]]; then
						known=yes
					fi
				done
				if [[ "$known" == no ]]; then
					echo "check.sh: unknown check: $1" >&2
					usage
					exit 2
				fi
				selected+=("$1")
				shift
			done
			;;
		-h | --help)
			usage
			exit 0
			;;
		*)
			echo "check.sh: unknown argument: $1" >&2
			usage
			exit 2
			;;
	esac
done

# Run in the canonical order, each selected check once.
to_run=()
for name in "${ALL_CHECKS[@]}"; do
	if [[ ${#selected[@]} -eq 0 ]]; then
		to_run+=("$name")
		continue
	fi
	for wanted in "${selected[@]}"; do
		if [[ "$wanted" == "$name" ]]; then
			to_run+=("$name")
			break
		fi
	done
done

if [[ -n "${JOBS:-}" ]]; then
	if [[ ! "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
		echo "check.sh: JOBS must be a whole number from 1 (JOBS=1 runs serially), not '$JOBS'" >&2
		exit 2
	fi
	max_jobs="$JOBS"
else
	max_jobs="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
fi
export JOBS="$max_jobs"

# Check number N (an index into to_run) keeps its output in $results/N.log and its result in
# $results/N.status, written last: "ok", "fail", "skip <tool>" or "missing <tool>".
results="$(mktemp -d)"
trap 'rm -rf "$results"' EXIT
pids=()
printed=0
failed=()

set_status() {
	echo "$2" >"$results/$1.status.tmp"
	mv "$results/$1.status.tmp" "$results/$1.status"
}

# Start check N in the background; it stops with check.sh on Ctrl-C.
start_check() {
	local index="$1"
	(
		trap - INT
		status=fail
		if "check_${to_run[$index]}" >"$results/$index.log" 2>&1; then
			status=ok
		fi
		set_status "$index" "$status"
	) &
	pids[index]=$!
}

running() {
	local count=0 index
	for index in "${!pids[@]}"; do
		[[ -e "$results/$index.status" ]] || count=$((count + 1))
	done
	echo "$count"
}

# Wait until a check is done; a check whose shell ended without a result (killed) failed.
wait_one() {
	local index
	wait -n 2>/dev/null || true
	for index in "${!pids[@]}"; do
		if [[ ! -e "$results/$index.status" ]] && ! kill -0 "${pids[$index]}" 2>/dev/null; then
			echo "check.sh: the check ended without a result" >>"$results/$index.log"
			set_status "$index" fail
		fi
	done
}

# Print every result that is done, in order, up to the first that is not.
report_ready() {
	local name status tool
	while [[ $printed -lt ${#to_run[@]} && -e "$results/$printed.status" ]]; do
		name="${to_run[$printed]}"
		read -r status tool <"$results/$printed.status"
		case "$status" in
			ok) echo "ok $name" ;;
			skip) echo "skip $name ($tool not installed: $(hint_for "$tool"))" ;;
			missing)
				echo "FAIL $name ($tool not installed: $(hint_for "$tool"))"
				failed+=("$name")
				;;
			*)
				echo "FAIL $name"
				sed 's/^/  /' "$results/$printed.log"
				failed+=("$name")
				;;
		esac
		printed=$((printed + 1))
	done
}

for index in "${!to_run[@]}"; do
	name="${to_run[$index]}"
	missing=""
	read -r -a tools <<<"$(tools_for "$name")"
	for tool in "${tools[@]}"; do
		if ! have_tool "$tool"; then
			missing="$tool"
			break
		fi
	done
	if [[ -n "$missing" ]]; then
		if [[ "$strict" == yes ]]; then
			set_status "$index" "missing $missing"
		else
			set_status "$index" "skip $missing"
		fi
		report_ready
		continue
	fi
	while [[ "$(running)" -ge "$max_jobs" ]]; do
		wait_one
		report_ready
	done
	start_check "$index"
done
while [[ $printed -lt ${#to_run[@]} ]]; do
	wait_one
	report_ready
done

if [[ ${#failed[@]} -gt 0 ]]; then
	echo "check.sh: ${#failed[@]} failed: ${failed[*]}"
	exit 1
fi
