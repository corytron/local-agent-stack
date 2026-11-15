#!/usr/bin/env bash
# Benchmark sweep for the ai-inference app's llama.cpp build (docs/stack-design.md §8;
# docs/research/b-inference.md §5.3; docs/research/a-models.md §12). Run it on the TrueNAS host
# (System > Shell, or SSH), as root or with sudo, one benchmark at a time: it needs the GPU to
# itself. It prints a Markdown table on stdout; progress and errors go to stderr.
#
# Modes:
#   bench   llama-bench (`/app/llama bench` in the image): prompt processing (pp) and generation
#           (tg) tokens/s at each KV depth in --contexts, for every -ub in --ubatch, in one run.
#   server  one llama-server per (context, -ub) pair: does it start (fit in VRAM), how much GPU
#           memory it holds, and the prompt and generation speed of one chat request that fills
#           --fill percent of the context. This covers what llama-bench cannot run, such as
#           --spec-type draft-mtp, and reports the draft acceptance rate.
# Where it runs:
#   default   docker exec into the running llama-swap container: the production build and image.
#   --oneoff  a throwaway container from the same image (works while ai-inference is stopped).
# Before a GPU run the script asks llama-swap to unload coder and coder-moe (--unload), so the
# measurement has the card to itself; llama-swap loads a model again on its next request.
#
# `/app/llama bench` is the llama-bench subcommand of llama.cpp's multi-call binary (app/llama.cpp
# at b12407), which the server image, and so the llama-swap image, ships next to llama-server.
# UNVERIFIED: not yet run on the server (no GPU on the workstation). Checked so far: --dry-run,
# a clean ShellCheck run, and tests of the request JSON and the timings parser.
#
# Examples (extra llama.cpp flags go after --; without them the coder defaults below are used):
#   sudo tools/bench.sh -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 0,16384,32768 -u 512,1024
#   sudo tools/bench.sh -m Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf -c 0,16384 -u 2048 \
#     -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ncmoe 14,16,18,20 -t 8,12,16 -lm none
#   sudo tools/bench.sh -m Qwen3-Embedding-0.6B-Q8_0.gguf -c 0 -u 512,2048 -g 0 --unload none \
#     -- -dev none -embd 1 -t 8,16
#   sudo tools/bench.sh --mode server -m Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf -c 49152,65536 \
#     -u 512,1024 -- -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -ot token_embd.weight=CPU \
#     --spec-type draft-mtp

set -euo pipefail

readonly DEFAULT_IMAGE="ghcr.io/mostlygeek/llama-swap:v273-cuda-b12407@sha256:8fd9f1cfe9e96cddf53fbdc5cb2683b19633ab49b1a41a406e6239376ead65e6"
# The coder model's GPU flags (stack/inference/llama-swap/config.yaml), used when no extra flags
# are given.
readonly DEFAULT_EXTRA=(-ngl 99 -fa on -ctk q8_0 -ctv q8_0)

mode=bench
model=""
contexts=""
ubatches="512,1024,2048"
prompt=2048
gen=128
reps=3
fill=75
container=llama-swap
oneoff=0
image="$DEFAULT_IMAGE"
models_dir="${AI_ROOT:-/mnt/tank/ai}/models"
unload="coder,coder-moe"
port=18080
start_timeout=600
dry_run=0
extra=()
docker_bin="${DOCKER:-docker}"

target=""          # container the commands run in
server_pid=""      # host PID of the docker exec client running llama-server (server mode)
server_log=""

usage() {
	cat <<'EOF'
Usage: tools/bench.sh -m MODEL [options] [-- EXTRA_LLAMA_FLAGS...]

  -m, --model FILE        GGUF file under /models/gguf in the container, or an absolute path
                          inside the container (required)
      --mode MODE         bench (llama-bench, default) or server (llama-server fit and speed)
  -c, --contexts LIST     comma-separated token counts. bench: KV depths (-d), default
                          0,16384,32768. server: context sizes (-c), default 32768,65536
  -u, --ubatch LIST       comma-separated -ub values (default 512,1024,2048)
  -p, --prompt N          bench: prompt tokens per pp test (default 2048)
  -g, --gen N             bench: generated tokens per tg test, 0 to skip (default 128);
                          server: max_tokens of the request
  -r, --reps N            bench: repetitions per test (default 3)
  -f, --fill PCT          server: share of the context the request's prompt fills (default 75)
      --container NAME    the llama-swap container (default llama-swap)
      --oneoff            run in a throwaway container from --image instead of docker exec
      --image REF         image for --oneoff (default: the pinned llama-swap image)
      --models-dir DIR    host directory mounted at /models for --oneoff
                          (default ${AI_ROOT:-/mnt/tank/ai}/models)
      --unload LIST       llama-swap model ids to unload first, "all", or "none"
                          (default coder,coder-moe)
      --port N            server: loopback port for the test server (default 18080)
      --timeout SEC       server: seconds to wait for a server to start (default 600)
      --dry-run           print the docker commands instead of running them
  -h, --help              this help

Extra flags after -- go to llama-bench (bench) or llama-server (server) unchanged. Without them:
  -ngl 99 -fa on -ctk q8_0 -ctv q8_0
llama-bench takes comma lists in most flags (for example -t 8,12,16 or -ncmoe 14,16,18).
Environment: DOCKER (docker command, default docker), AI_ROOT.
EOF
}

die() {
	printf 'bench.sh: %s\n' "$*" >&2
	exit 2
}

log() {
	printf 'bench.sh: %s\n' "$*" >&2
}

need_value() {
	if [ "$#" -lt 2 ] || [ -z "$2" ]; then die "option $1 needs a value (see --help)"; fi
}

is_uint() {
	[[ $1 =~ ^[0-9]+$ ]]
}

is_list() {
	[[ $1 =~ ^[0-9]+(,[0-9]+)*$ ]]
}

max_of() {
	local max=0 v
	local -a values
	IFS=, read -r -a values <<<"$1"
	for v in "${values[@]}"; do
		if [ "$v" -gt "$max" ]; then max=$v; fi
	done
	printf '%s\n' "$max"
}

# Print a command, quoted so it can be pasted back into a shell.
show() {
	printf '+'
	printf ' %q' "$@"
	printf '\n'
}

# Run a docker command, or print it with --dry-run.
docker_run() {
	if [ "$dry_run" -eq 1 ]; then
		show "$docker_bin" "$@" >&2
		return 0
	fi
	"$docker_bin" "$@"
}

# Run a command inside the target container.
dx() {
	docker_run exec "$target" "$@"
}

container_running() {
	[ "$("$docker_bin" inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = true ]
}

parse_args() {
	while [ "$#" -gt 0 ]; do
		case "$1" in
		-m | --model) need_value "$@"; model=$2; shift 2 ;;
		--mode) need_value "$@"; mode=$2; shift 2 ;;
		-c | --contexts) need_value "$@"; contexts=$2; shift 2 ;;
		-u | --ubatch) need_value "$@"; ubatches=$2; shift 2 ;;
		-p | --prompt) need_value "$@"; prompt=$2; shift 2 ;;
		-g | --gen) need_value "$@"; gen=$2; shift 2 ;;
		-r | --reps) need_value "$@"; reps=$2; shift 2 ;;
		-f | --fill) need_value "$@"; fill=$2; shift 2 ;;
		--container) need_value "$@"; container=$2; shift 2 ;;
		--oneoff) oneoff=1; shift ;;
		--image) need_value "$@"; image=$2; shift 2 ;;
		--models-dir) need_value "$@"; models_dir=$2; shift 2 ;;
		--unload) need_value "$@"; unload=$2; shift 2 ;;
		--port) need_value "$@"; port=$2; shift 2 ;;
		--timeout) need_value "$@"; start_timeout=$2; shift 2 ;;
		--dry-run) dry_run=1; shift ;;
		-h | --help) usage; exit 0 ;;
		--) shift; extra=("$@"); break ;;
		*) die "unknown argument: $1 (see --help)" ;;
		esac
	done

	[ -n "$model" ] || die "--model is required (see --help)"
	case "$mode" in
	bench) : "${contexts:=0,16384,32768}" ;;
	server) : "${contexts:=32768,65536}" ;;
	*) die "--mode must be bench or server" ;;
	esac
	is_list "$contexts" || die "--contexts must be a comma-separated list of integers"
	is_list "$ubatches" || die "--ubatch must be a comma-separated list of integers"
	local n
	for n in "$prompt" "$gen" "$reps" "$fill" "$port" "$start_timeout"; do
		is_uint "$n" || die "not a non-negative integer: $n"
	done
	if [ "$fill" -lt 1 ] || [ "$fill" -gt 95 ]; then die "--fill must be between 1 and 95"; fi
	[[ $unload =~ ^[A-Za-z0-9._,-]+$ ]] || die "--unload must be model ids, all or none"
	if [ "${#extra[@]}" -eq 0 ]; then extra=("${DEFAULT_EXTRA[@]}"); fi
	case "$model" in
	/*) model_path=$model ;;
	*) model_path="/models/gguf/$model" ;;
	esac
}

cleanup() {
	stop_server
	if [ "$oneoff" -eq 1 ] && [ -n "$target" ] && [ "$dry_run" -eq 0 ]; then
		"$docker_bin" rm -f "$target" >/dev/null 2>&1 || true
	fi
	if [ -n "$server_log" ]; then rm -f "$server_log"; fi
}

# Ask llama-swap to unload GPU models so the benchmark has the card to itself
# (POST /api/models/unload[/<id>], internal/server/server.go at v273).
unload_models() {
	[ "$unload" = none ] && return 0
	if [ "$dry_run" -eq 0 ] && ! container_running "$container"; then
		log "container $container is not running; nothing to unload"
		return 0
	fi
	local id path
	local -a ids
	if [ "$unload" = all ]; then
		ids=("")
	else
		IFS=, read -r -a ids <<<"$unload"
	fi
	for id in "${ids[@]}"; do
		path="/api/models/unload${id:+/$id}"
		log "unloading ${id:-all models} in $container"
		# The key is expanded inside the container from its own environment (compose.yaml), so it
		# never appears on this host's command line.
		# shellcheck disable=SC2016
		docker_run exec "$container" sh -c \
			'curl -fsS -o /dev/null -X POST -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" "http://127.0.0.1:8080$1"' \
			sh "$path" || log "warning: could not unload ${id:-all models}"
	done
	if [ "$dry_run" -eq 0 ]; then sleep 3; fi
}

start_oneoff() {
	target="las-bench-$$"
	log "starting throwaway container $target from $image"
	docker_run run -d --rm --name "$target" --gpus all \
		-e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
		-v "$models_dir:/models:ro" \
		--entrypoint sleep "$image" infinity >/dev/null
}

check_model() {
	if [ "$dry_run" -eq 1 ]; then return 0; fi
	dx test -r "$model_path" || die "model not readable in $target: $model_path"
}

describe() {
	printf -- "- model: \`%s\`\n" "$model_path"
	if [ "$oneoff" -eq 1 ]; then
		printf -- "- container: throwaway, image \`%s\`\n" "$image"
	else
		printf -- "- container: \`%s\`\n" "$target"
	fi
	printf -- "- flags: \`%s\`\n" "${extra[*]}"
	printf -- '- date: %s\n\n' "$(date -u +%Y-%m-%dT%H:%MZ)"
}

run_bench() {
	local max_ub batch
	max_ub=$(max_of "$ubatches")
	batch=$((max_ub > 2048 ? max_ub : 2048))
	printf '## llama-bench sweep\n\n'
	describe
	printf -- '- depths (-d): %s; -ub: %s; -p %s, -n %s, %s repetitions\n\n' \
		"$contexts" "$ubatches" "$prompt" "$gen" "$reps"
	# llama-bench options (tools/llama-bench/README.md at b12407): comma lists run every
	# combination; -d prefills the KV cache to that depth before each test; -o md is the table.
	dx /app/llama bench -m "$model_path" -p "$prompt" -n "$gen" -d "$contexts" \
		-ub "$ubatches" -b "$batch" -r "$reps" -o md "${extra[@]}"
}

# GPU memory in use and total, in MiB (whole card).
gpu_mem() {
	local out
	if command -v nvidia-smi >/dev/null 2>&1; then
		out=$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1) || out=""
	else
		out=$("$docker_bin" exec "$target" nvidia-smi --query-gpu=memory.used,memory.total \
			--format=csv,noheader,nounits 2>/dev/null | head -n 1) || out=""
	fi
	out=${out// /}
	if [ -n "$out" ]; then printf '%s / %s\n' "${out%%,*}" "${out#*,}"; else printf 'n/a\n'; fi
}

# A chat request whose prompt is about $1 tokens of varied common words, then a coding task, so
# the generated text is ordinary code (a fair case for MTP drafting). ignore_eos keeps generation
# going for max_tokens; cache_prompt false measures a cold prefill.
make_request() {
	awk -v n="$1" -v gen="$gen" 'BEGIN {
		m = split("the of and to in is was for on that with as by at from it be this are or an " \
			"have not but had his they which one you were her all she there would their we him " \
			"been has when who will more no if out so said what up its about into than them can " \
			"only other new some could time these two may then do first any my now such like our " \
			"over man me even most made after also did many before must through back years where " \
			"much your way well down should because each just those people how too little state " \
			"good very make world still own see men work long get here between both life being " \
			"under never day same another know while last might us great old year off come since " \
			"against go came right used take three", w, " ")
		srand(42)
		printf "{\"messages\":[{\"role\":\"user\",\"content\":\""
		for (i = 0; i < n; i++) printf "%s ", w[int(rand() * m) + 1]
		printf "\\n\\nIgnore the words above. Write a Python module that reads a CSV file of "
		printf "orders, totals them per customer and prints a report. Include docstrings and "
		printf "unit tests.\"}],\"max_tokens\":%d,\"temperature\":0,\"ignore_eos\":true,", gen
		printf "\"cache_prompt\":false,\"stream\":false}"
	}'
}

# Value of a numeric JSON field in a one-line response (the timings object of llama-server,
# tools/server/server-common.cpp at b12407).
json_num() {
	printf '%s' "$2" | sed -n "s/.*\"$1\":\([0-9.eE+-]*\).*/\1/p" | head -n 1
}

fmt1() {
	if [ -n "$1" ]; then awk -v v="$1" 'BEGIN { printf "%.1f", v }'; else printf 'n/a'; fi
}

stop_server() {
	[ -n "$server_pid" ] || return 0
	# shellcheck disable=SC2016
	"$docker_bin" exec "$target" sh -c \
		'if [ -f /tmp/las-bench.pid ]; then kill "$(cat /tmp/las-bench.pid)" 2>/dev/null; rm -f /tmp/las-bench.pid; fi' \
		>/dev/null 2>&1 || true
	wait "$server_pid" 2>/dev/null || true
	server_pid=""
	sleep 2
}

server_case() {
	local ctx=$1 ub=$2 batch waited=0 started=0 mem words resp
	local pn pps gn gps dn da acc
	batch=$((ub > 2048 ? ub : 2048))
	local -a cmd=(/app/llama-server --host 127.0.0.1 --port "$port" --no-webui
		-m "$model_path" -c "$ctx" -ub "$ub" -b "$batch" -np 1 "${extra[@]}")

	if [ "$dry_run" -eq 1 ]; then
		show "$docker_bin" exec "$target" "${cmd[@]}" >&2
		printf '| %s | %s | (dry run) | | | | | | |\n' "$ctx" "$ub"
		return 0
	fi

	log "context $ctx, -ub $ub: starting llama-server"
	: >"$server_log"
	# llama-server runs as the main process of a docker exec session and writes its PID first, so
	# it can be stopped by PID inside the container.
	# shellcheck disable=SC2016
	"$docker_bin" exec "$target" sh -c 'echo $$ > /tmp/las-bench.pid; exec "$@"' sh "${cmd[@]}" \
		>"$server_log" 2>&1 &
	server_pid=$!
	while [ "$waited" -lt "$start_timeout" ]; do
		if ! kill -0 "$server_pid" 2>/dev/null; then break; fi
		if "$docker_bin" exec "$target" curl -fsS -o /dev/null "http://127.0.0.1:$port/health" 2>/dev/null; then
			started=1
			break
		fi
		sleep 2
		waited=$((waited + 2))
	done
	if [ "$started" -ne 1 ]; then
		log "context $ctx, -ub $ub: did not start; last lines of its log:"
		tail -n 8 "$server_log" >&2 || true
		stop_server
		printf '| %s | %s | no | | | | | | |\n' "$ctx" "$ub"
		return 0
	fi

	mem=$(gpu_mem)
	words=$((ctx * fill / 100 - gen - 128))
	if [ "$words" -lt 16 ]; then words=16; fi
	log "context $ctx, -ub $ub: started (GPU $mem MiB); sending a ~$words-token prompt"
	resp=$(make_request "$words" | "$docker_bin" exec -i "$target" curl -fsS --max-time 3600 \
		-H 'Content-Type: application/json' --data-binary @- \
		"http://127.0.0.1:$port/v1/chat/completions" 2>/dev/null | tr -d '\n') || resp=""
	stop_server

	if [ -z "$resp" ]; then
		log "context $ctx, -ub $ub: the request failed"
		printf '| %s | %s | yes | %s | request failed | | | | |\n' "$ctx" "$ub" "$mem"
		return 0
	fi
	pn=$(json_num prompt_n "$resp")
	pps=$(json_num prompt_per_second "$resp")
	gn=$(json_num predicted_n "$resp")
	gps=$(json_num predicted_per_second "$resp")
	dn=$(json_num draft_n "$resp")
	da=$(json_num draft_n_accepted "$resp")
	acc="-"
	if [ -n "$dn" ] && [ -n "$da" ] && [ "${dn%.*}" -gt 0 ] 2>/dev/null; then
		acc="$(awk -v a="$da" -v d="$dn" 'BEGIN { printf "%.0f%%", 100 * a / d }')"
	fi
	printf '| %s | %s | yes | %s | %s | %s | %s | %s | %s |\n' "$ctx" "$ub" "$mem" \
		"${pn:-n/a}" "$(fmt1 "$pps")" "${gn:-n/a}" "$(fmt1 "$gps")" "$acc"
}

run_server() {
	local ctx ub
	local -a ctx_list ub_list
	IFS=, read -r -a ctx_list <<<"$contexts"
	IFS=, read -r -a ub_list <<<"$ubatches"
	if [ "$dry_run" -eq 0 ]; then server_log=$(mktemp); fi
	printf '## llama-server sweep\n\n'
	describe
	printf -- '- one chat request per row: prompt fills ~%s%% of the context, max_tokens %s\n\n' \
		"$fill" "$gen"
	printf '| context (-c) | -ub | starts | GPU MiB used / total | prompt tokens | prompt t/s | generated tokens | generation t/s | draft accepted |\n'
	printf '|---:|---:|---|---|---:|---:|---:|---:|---:|\n'
	for ctx in "${ctx_list[@]}"; do
		for ub in "${ub_list[@]}"; do
			server_case "$ctx" "$ub"
		done
	done
}

main() {
	parse_args "$@"
	command -v "$docker_bin" >/dev/null 2>&1 || die "docker not found (run on the TrueNAS host)"
	trap cleanup EXIT
	trap 'exit 130' INT TERM

	unload_models
	if [ "$oneoff" -eq 1 ]; then
		start_oneoff
	else
		target=$container
		if [ "$dry_run" -eq 0 ] && ! container_running "$target"; then
			die "container $target is not running; start ai-inference or use --oneoff"
		fi
	fi
	check_model

	case "$mode" in
	bench) run_bench ;;
	server) run_server ;;
	esac
	log "done. llama-swap loads models again on their next request."
}

main "$@"
