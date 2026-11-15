#!/bin/sh
# Port inventory of a TrueNAS SCALE server (docs/v1.2-design.md, section 1): what listens on
# which port, which Docker containers publish which ports, which ports the TrueNAS web interface
# uses, and whether the ports the stack's edge proxy needs on the host are free. The stack needs
# 80/tcp, 443/tcp and 443/udp (Caddy, in the TrueNAS app ai-edge) and no other host port.
#
# Run it on the TrueNAS server, in System > Shell or over SSH, as truenas_admin:
#   sh /mnt/tank/ai/stacks/local-agent-stack/tools/port-inventory.sh [--json] [--no-sudo]
#
# Read-only: it writes no file and changes nothing. It runs exactly these commands:
#   ss -Hltunp                           listening TCP and UDP sockets, numeric, with processes
#   docker ps --format '{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Ports}}'
#                                        running containers, their compose project (TrueNAS runs
#                                        the app <app> as project ix-<app>) and published ports
#   midclt call system.general.config    ui_port and ui_httpsport, the web interface's HTTP and
#                                        HTTPS ports (System > General Settings > GUI)
# When it is not root, it runs them through sudo: `sudo -n true` checks whether sudo works without
# a password, and otherwise `sudo true` asks for the password once. Without sudo (--no-sudo, or sudo
# refused) it carries on: ss then names only the user's own processes, and docker usually cannot be
# read (the Docker socket is root's), so a port in use may show an unnamed process.
#
# Verdict per needed port: "free"; "ours" when only the ai-edge app publishes it (a run after the
# edge app is installed); "used by <who>"; "unknown" when ss could not be run and nothing else
# names a user. A socket of docker-proxy (Docker's userland proxy, which TrueNAS leaves on: its
# daemon.json does not set userland-proxy) is attributed to the container that docker ps shows
# publishing the port. The verdict is per port and protocol across all addresses; the tables show
# the addresses.
#
# Verified against primary sources (TrueNAS 25.10.8):
#   - ss is installed: the truenas package depends on keepalived, which depends on iproute2 in
#     Debian bookworm, the base of 25.10 (truenas/middleware debian/control and
#     truenas/scale-build conf/build.manifest at TS-25.10.8); -H, -l, -t, -u, -n and -p are in the
#     bookworm ss(8) manual page.
#   - docker ps --format placeholders .Names, .Label and .Ports (Docker CLI reference), and the
#     .Ports text "<ip>:<host port(s)>-><container port(s)>/<proto>", IPv6 in brackets, ranges as
#     <first>-<last>, an exposed port without "->" (docker/cli v28.3.1 DisplayablePorts; 25.10.8
#     ships Docker 28.3.1).
#   - system.general.config returns ui_port, ui_httpsport, ui_httpsredirect, ui_address and
#     ui_v6address (truenas/middleware TS-25.10.8, api/v25_10_5/system_general.py), and midclt
#     prints a dict as one line of json.dumps (truenas/api_client TS-25.10.8).
#
# Exit status: 0 every needed port is free or ours; 1 a needed port is used by something else or
# could not be checked; 2 usage error.
set -u

EDGE_APP=ai-edge
NEEDED="80/tcp 443/tcp 443/udp"
DOCKER_FORMAT='{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Ports}}'

usage() {
	cat <<'EOF'
usage: sh tools/port-inventory.sh [--json] [--no-sudo]

Lists the listening TCP and UDP sockets of this TrueNAS server, the ports Docker
containers publish, and the TrueNAS web interface's ports, then says whether the
ports the stack's edge proxy needs (80/tcp, 443/tcp, 443/udp) are free.
Read-only: it runs ss, docker ps and midclt call system.general.config.

  --json      print one JSON object instead of the tables
  --no-sudo   do not use sudo: process names are then shown only for your own
              sockets, and Docker's containers usually cannot be read
  -h, --help  print this help

Not root, it runs those commands through sudo, which asks for your password
once. Exit status: 0 every needed port is free or already used by the ai-edge
app; 1 a needed port is used by something else or could not be checked; 2 usage
error.
EOF
}

json=no
use_sudo=yes
while [ $# -gt 0 ]; do
	case "$1" in
		--json) json=yes ;;
		--no-sudo) use_sudo=no ;;
		-h | --help)
			usage
			exit 0
			;;
		*)
			printf 'port-inventory.sh: unknown argument: %s\n' "$1" >&2
			usage >&2
			exit 2
			;;
	esac
	shift
done

notes=""
add_note() {
	notes="$notes$1
"
}

# The first non-empty line of a command's output, tabs made spaces (for a note).
first_line() {
	printf '%s\n' "$1" | sed -n '/[^[:space:]]/{p;q;}' | tr '\t' ' '
}

# How the commands run: as root, through sudo, or as this user.
privilege=user
without_sudo="process names are shown only for your own sockets, and Docker's containers are not read unless your user may use Docker"
if [ "$(id -u 2>/dev/null)" = 0 ]; then
	privilege=root
elif [ "$use_sudo" = no ]; then
	add_note "Ran without sudo (--no-sudo): $without_sudo."
elif ! command -v sudo >/dev/null 2>&1; then
	add_note "sudo is not installed: $without_sudo."
elif sudo -n true 2>/dev/null; then
	privilege=sudo
else
	echo "port-inventory.sh: sudo asks for your password once (process names and Docker need root; --no-sudo skips it)" >&2
	if sudo true; then
		privilege=sudo
	else
		add_note "sudo did not succeed: $without_sudo. Run it again and give your password."
	fi
fi

priv() {
	if [ "$privilege" = sudo ]; then
		sudo "$@"
	else
		"$@"
	fi
}

# (a) Listening sockets.
ss_out=""
if ! command -v ss >/dev/null 2>&1; then
	ss_state="ss is not installed"
elif ss_out=$(priv ss -Hltunp 2>&1); then
	ss_state=ok
else
	ss_state="ss -Hltunp failed: $(first_line "$ss_out")"
	ss_out=""
fi

# (b) Ports published by Docker containers.
docker_out=""
if ! command -v docker >/dev/null 2>&1; then
	docker_state="docker is not installed"
elif docker_out=$(priv docker ps --format "$DOCKER_FORMAT" 2>&1); then
	docker_state=ok
else
	docker_state="docker ps failed: $(first_line "$docker_out")"
	docker_out=""
fi

# (c) The TrueNAS web interface's ports.
ui_http=""
ui_https=""
ui_redirect=""
ui_addresses=""
midclt_out=""
json_field() {
	printf '%s\n' "$midclt_out" | sed -n "s/.*\"$1\": *\\($2\\).*/\\1/p" | sed -n 1p
}
if ! command -v midclt >/dev/null 2>&1; then
	midclt_state="midclt is not installed (is this the TrueNAS server?)"
elif midclt_out=$(priv midclt call system.general.config 2>&1); then
	ui_http=$(json_field ui_port '[0-9][0-9]*')
	ui_https=$(json_field ui_httpsport '[0-9][0-9]*')
	ui_redirect=$(json_field ui_httpsredirect '[a-z][a-z]*')
	ui_addresses=$(json_field ui_address '\[[^]]*]'),$(json_field ui_v6address '\[[^]]*]')
	ui_addresses=$(printf '%s\n' "$ui_addresses" | sed 's/[][" ]//g')
	if [ -n "$ui_http" ] && [ -n "$ui_https" ]; then
		midclt_state=ok
	else
		midclt_state="midclt call system.general.config returned no ui_port and ui_httpsport"
	fi
else
	midclt_state="midclt call system.general.config failed: $(first_line "$midclt_out")"
fi

# (d) The report and the verdicts; awk's exit status is the script's.
{
	echo "@@meta"
	printf 'privilege\t%s\n' "$privilege"
	printf 'ss\t%s\n' "$ss_state"
	printf 'docker\t%s\n' "$docker_state"
	printf 'midclt\t%s\n' "$midclt_state"
	printf 'ui_http\t%s\n' "$ui_http"
	printf 'ui_https\t%s\n' "$ui_https"
	printf 'ui_redirect\t%s\n' "$ui_redirect"
	printf 'ui_addresses\t%s\n' "$ui_addresses"
	echo "@@notes"
	printf '%s' "$notes"
	echo "@@ss"
	printf '%s\n' "$ss_out"
	echo "@@docker"
	printf '%s\n' "$docker_out"
} | awk -v json="$json" -v edge="$EDGE_APP" -v needed="$NEEDED" '
function last_index(s, ch,    i, p) {
	p = 0
	while ((i = index(substr(s, p + 1), ch)) > 0)
		p += i
	return p
}

# The process names of a users:(("name",pid=1,fd=2),...) column, each once, comma-separated.
function process_names(s,    k, e, name, out, seen) {
	out = ""
	while ((k = index(s, "(\"")) > 0) {
		s = substr(s, k + 2)
		e = index(s, "\",")
		if (e == 0)
			break
		name = substr(s, 1, e - 1)
		s = substr(s, e + 2)
		if (!(name in seen)) {
			seen[name] = 1
			out = out (out == "" ? "" : ",") name
		}
	}
	return out
}

# One line of ss -Hltunp: Netid State Recv-Q Send-Q Local:Port Peer:Port [users:((...))]
function parse_ss(    c, port, j) {
	if (($1 != "tcp" && $1 != "udp") || NF < 6)
		return
	c = last_index($5, ":")
	port = substr($5, c + 1)
	if (c == 0 || port !~ /^[0-9]+$/)
		return
	ns++
	s_port[ns] = port + 0
	s_proto[ns] = $1
	s_addr[ns] = substr($5, 1, c - 1)
	j = index($0, "users:(")
	s_proc[ns] = (j > 0) ? process_names(substr($0, j + 7)) : ""
}

# One line of docker ps: name|compose project|ports, the ports as "0.0.0.0:80->80/tcp, ..."
function parse_docker(    f, p, n, i, e, a, left, right, slash, c, hp, dash, first, last) {
	if (split($0, f, "|") != 3 || f[1] == "")
		return
	n = split(f[3], p, ", ")
	for (i = 1; i <= n; i++) {
		e = p[i]
		a = index(e, "->")
		if (a == 0)
			continue
		left = substr(e, 1, a - 1)
		right = substr(e, a + 2)
		slash = index(right, "/")
		c = last_index(left, ":")
		if (slash == 0 || c == 0)
			continue
		hp = substr(left, c + 1)
		dash = index(hp, "-")
		first = (dash > 0) ? substr(hp, 1, dash - 1) : hp
		last = (dash > 0) ? substr(hp, dash + 1) : hp
		if (first !~ /^[0-9]+$/ || last !~ /^[0-9]+$/)
			continue
		nd++
		d_first[nd] = first + 0
		d_last[nd] = last + 0
		d_hports[nd] = hp
		d_proto[nd] = substr(right, slash + 1)
		d_cports[nd] = substr(right, 1, slash - 1)
		d_addr[nd] = substr(left, 1, c - 1)
		d_name[nd] = f[1]
		d_app[nd] = (f[2] ~ /^ix-/) ? substr(f[2], 4) : ""
	}
}

# Insertion sort of the row numbers 1..n by key[] into order[].
function sort_rows(n, key, order,    i, j, t) {
	for (i = 1; i <= n; i++)
		order[i] = i
	for (i = 2; i <= n; i++) {
		t = order[i]
		j = i - 1
		while (j > 0 && key[order[j]] > key[t]) {
			order[j + 1] = order[j]
			j--
		}
		order[j + 1] = t
	}
}

function add_user(k, label, ours,    i) {
	for (i = 1; i <= u_n[k]; i++)
		if (u_label[k, i] == label)
			return
	u_n[k]++
	u_label[k, u_n[k]] = label
	u_ours[k, u_n[k]] = ours
	if (!ours)
		u_others[k]++
}

function container_label(i) {
	return "container " d_name[i] (d_app[i] != "" ? " (app " d_app[i] ")" : " (not a TrueNAS app)")
}

# Who uses port/proto: containers that publish it, the web interface, then the other sockets.
function judge(k, port, proto,    i, by_docker, is_ui, label, published) {
	u_n[k] = 0
	u_others[k] = 0
	by_docker = 0
	for (i = 1; i <= nd; i++) {
		if (d_proto[i] != proto || port < d_first[i] || port > d_last[i])
			continue
		by_docker = 1
		published[d_addr[i]] = 1
		add_user(k, container_label(i), d_app[i] == edge)
	}
	is_ui = (proto == "tcp" && ui_ok && (port == ui_http || port == ui_https))
	if (is_ui)
		add_user(k, UI, 0)
	for (i = 1; i <= ns; i++) {
		if (s_proto[i] != proto || s_port[i] != port)
			continue
		# docker-proxy holds the published port; without sudo its name is not shown, so an
		# unnamed socket on an address a container publishes the port on is that container.
		if (s_proc[i] == "docker-proxy" && by_docker)
			continue
		if (s_proc[i] == "" && (s_addr[i] in published))
			continue
		if (is_ui && (s_proc[i] == "" || s_proc[i] == "nginx"))
			continue
		if (s_proc[i] == "docker-proxy")
			label = "docker-proxy (a port published by a container)"
		else if (s_proc[i] != "")
			label = s_proc[i]
		else if (privilege == "user")
			label = "a process whose name needs sudo"
		else
			label = "a kernel socket (no process)"
		add_user(k, label, 0)
	}
	if (u_others[k] > 0)
		v_state[k] = "used"
	else if (u_n[k] > 0)
		v_state[k] = "ours"
	else if (!ss_ok)
		v_state[k] = "unknown"
	else
		v_state[k] = "free"
	if (v_state[k] == "used" || v_state[k] == "unknown")
		bad++
}

function users_text(k, want_ours,    i, out) {
	out = ""
	for (i = 1; i <= u_n[k]; i++)
		if (u_ours[k, i] == want_ours)
			out = out (out == "" ? "" : ", ") u_label[k, i]
	return out
}

function verdict_text(k,    t) {
	if (v_state[k] == "free")
		return "free"
	if (v_state[k] == "unknown")
		return "unknown (ss could not be run)"
	if (v_state[k] == "ours")
		return "ours: " users_text(k, 1)
	t = "used by " users_text(k, 0)
	if (users_text(k, 1) != "")
		t = t "; also " users_text(k, 1)
	return t
}

function js(s,    out, i, c) {
	out = ""
	for (i = 1; i <= length(s); i++) {
		c = substr(s, i, 1)
		if (c == "\\" || c == "\"")
			out = out "\\" c
		else if (c == "\t")
			out = out "\\t"
		else
			out = out c
	}
	return "\"" out "\""
}

function js_state(name) {
	return (meta[name] == "ok") ? "\"ok\"" : js(meta[name])
}

function print_text(    i, r, k, used) {
	how = (privilege == "root") ? "as root" : (privilege == "sudo") ? "through sudo" : "without sudo"
	printf "Port inventory of this server (read-only; ran %s)\n", how
	print ""
	print "Listening sockets (ss -Hltunp)"
	if (!ss_ok)
		printf "  not available: %s\n", meta["ss"]
	else if (ns == 0)
		print "  none"
	else {
		printf "  %-6s %-6s %-24s %s\n", "PORT", "PROTO", "ADDRESS", "PROCESS"
		for (i = 1; i <= ns; i++) {
			r = s_order[i]
			printf "  %-6s %-6s %-24s %s\n", s_port[r], s_proto[r], s_addr[r], (s_proc[r] != "" ? s_proc[r] : "-")
		}
	}
	print ""
	print "Ports published by Docker containers (docker ps)"
	if (!docker_ok)
		printf "  not available: %s\n", meta["docker"]
	else if (nd == 0)
		print "  none"
	else {
		printf "  %-11s %-6s %-16s %-15s %-20s %s\n", "HOST PORT", "PROTO", "ADDRESS", "CONTAINER PORT", "CONTAINER", "TRUENAS APP"
		for (i = 1; i <= nd; i++) {
			r = d_order[i]
			printf "  %-11s %-6s %-16s %-15s %-20s %s\n", d_hports[r], d_proto[r], d_addr[r], d_cports[r], d_name[r], (d_app[r] != "" ? d_app[r] : "-")
		}
	}
	print ""
	print "TrueNAS web interface (midclt call system.general.config; System > General Settings > GUI)"
	if (!ui_ok)
		printf "  not available: %s\n", meta["midclt"]
	else {
		printf "  %-27s %s\n", "HTTP port (ui_port)", ui_http
		printf "  %-27s %s\n", "HTTPS port (ui_httpsport)", ui_https
		if (meta["ui_redirect"] != "")
			printf "  %-27s %s\n", "Redirect HTTP to HTTPS", (meta["ui_redirect"] == "true" ? "yes" : "no")
		if (meta["ui_addresses"] != "" && meta["ui_addresses"] != ",") {
			addresses = meta["ui_addresses"]
			gsub(/^,|,$/, "", addresses)
			gsub(/,/, ", ", addresses)
			printf "  %-27s %s\n", "Addresses", addresses
		}
	}
	print ""
	printf "Ports the stack needs on this server (Caddy, app %s)\n", edge
	for (k = 1; k <= nneed; k++)
		printf "  %-9s %s\n", need[k], verdict_text(k)
	ui_hint = 0
	for (k = 1; k <= nneed; k++)
		for (i = 1; i <= u_n[k]; i++)
			if (u_label[k, i] == UI)
				ui_hint = 1
	if (ui_hint || nn > 0) {
		print ""
		print "Notes"
		if (ui_hint)
			print "  - The TrueNAS web interface uses a port the stack needs: give it other ports in System > General Settings > GUI > Settings (Web Interface HTTP Port, Web Interface HTTPS Port)."
		for (i = 1; i <= nn; i++)
			printf "  - %s\n", notes[i]
	}
	print ""
	used = 0
	for (k = 1; k <= nneed; k++)
		if (v_state[k] == "used" || v_state[k] == "unknown")
			used++
	if (used == 0)
		print "Result: every port the stack needs is free or already used by the stack (exit 0)."
	else
		printf "Result: %d of %d ports the stack needs %s in use by something else or could not be checked (exit 1).\n", used, nneed, (used == 1 ? "is" : "are")
}

function print_json(    i, r, k, n, a, sep) {
	print "{"
	printf "  \"privileges\": %s,\n", js(privilege)
	printf "  \"sources\": {\"ss\": %s, \"docker\": %s, \"midclt\": %s},\n", js_state("ss"), js_state("docker"), js_state("midclt")
	if (!ss_ok)
		print "  \"sockets\": null,"
	else {
		print "  \"sockets\": ["
		for (i = 1; i <= ns; i++) {
			r = s_order[i]
			printf "    {\"port\": %d, \"proto\": %s, \"address\": %s, \"process\": %s}%s\n", s_port[r], js(s_proto[r]), js(s_addr[r]), js(s_proc[r]), (i < ns ? "," : "")
		}
		print "  ],"
	}
	if (!docker_ok)
		print "  \"published\": null,"
	else {
		print "  \"published\": ["
		for (i = 1; i <= nd; i++) {
			r = d_order[i]
			printf "    {\"host_ports\": %s, \"first\": %d, \"last\": %d, \"proto\": %s, \"address\": %s, \"container_ports\": %s, \"container\": %s, \"app\": %s}%s\n", js(d_hports[r]), d_first[r], d_last[r], js(d_proto[r]), js(d_addr[r]), js(d_cports[r]), js(d_name[r]), (d_app[r] != "" ? js(d_app[r]) : "null"), (i < nd ? "," : "")
		}
		print "  ],"
	}
	if (!ui_ok)
		print "  \"web_interface\": null,"
	else {
		n = split(meta["ui_addresses"], a, ",")
		addresses = ""
		for (i = 1; i <= n; i++)
			if (a[i] != "")
				addresses = addresses (addresses == "" ? "" : ", ") js(a[i])
		printf "  \"web_interface\": {\"http_port\": %d, \"https_port\": %d, \"https_redirect\": %s, \"addresses\": [%s]},\n", ui_http, ui_https, (meta["ui_redirect"] == "true" || meta["ui_redirect"] == "false" ? meta["ui_redirect"] : "null"), addresses
	}
	print "  \"needed\": ["
	for (k = 1; k <= nneed; k++) {
		split(need[k], a, "/")
		sep = ""
		printf "    {\"port\": %d, \"proto\": %s, \"verdict\": %s, \"users\": [", a[1], js(a[2]), js(v_state[k])
		for (i = 1; i <= u_n[k]; i++) {
			printf "%s{\"who\": %s, \"ours\": %s}", sep, js(u_label[k, i]), (u_ours[k, i] ? "true" : "false")
			sep = ", "
		}
		printf "]}%s\n", (k < nneed ? "," : "")
	}
	print "  ],"
	printf "  \"notes\": ["
	for (i = 1; i <= nn; i++)
		printf "%s%s", (i > 1 ? ", " : ""), js(notes[i])
	print "],"
	printf "  \"ok\": %s\n", (bad == 0 ? "true" : "false")
	print "}"
}

BEGIN {
	UI = "the TrueNAS web interface"
	section = ""
	ns = 0
	nd = 0
	nn = 0
	bad = 0
}
/^@@(meta|notes|ss|docker)$/ {
	section = substr($0, 3)
	next
}
section == "meta" {
	t = index($0, "\t")
	if (t > 0)
		meta[substr($0, 1, t - 1)] = substr($0, t + 1)
	next
}
section == "notes" {
	if ($0 != "")
		notes[++nn] = $0
	next
}
section == "ss" {
	parse_ss()
	next
}
section == "docker" {
	parse_docker()
	next
}
END {
	privilege = meta["privilege"]
	ss_ok = (meta["ss"] == "ok")
	docker_ok = (meta["docker"] == "ok")
	ui_ok = (meta["midclt"] == "ok")
	ui_http = meta["ui_http"] + 0
	ui_https = meta["ui_https"] + 0
	for (i = 1; i <= ns; i++)
		s_key[i] = sprintf("%05d %s %s", s_port[i], s_proto[i], s_addr[i])
	sort_rows(ns, s_key, s_order)
	for (i = 1; i <= nd; i++)
		d_key[i] = sprintf("%05d %s %s %s", d_first[i], d_proto[i], d_name[i], d_addr[i])
	sort_rows(nd, d_key, d_order)
	nneed = split(needed, need, " ")
	for (k = 1; k <= nneed; k++) {
		split(need[k], pp, "/")
		judge(k, pp[1] + 0, pp[2])
	}
	if (json == "yes")
		print_json()
	else
		print_text()
	exit (bad > 0) ? 1 : 0
}
'
