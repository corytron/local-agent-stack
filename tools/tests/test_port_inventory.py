"""Unit tests of tools/port-inventory.sh, run by dash against fake ss, docker, midclt, sudo and id.

The fixtures are command output in the formats verified for TrueNAS 25.10.8 (ss -Hltunp of
iproute2, docker ps --format of Docker CLI 28.3.1, midclt's one-line json.dumps of
system.general.config); the values are made up. Each run gets a PATH of only the fakes and links to
sed, tr, awk, cat and true, so the real ss and docker of the machine running the tests are never used.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
SCRIPT = TOOLS / "port-inventory.sh"
SH = shutil.which("dash") or "/bin/sh"  # TrueNAS's /bin/sh is dash
DOCKER_FORMAT = '{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Ports}}'
ANY4 = "0.0.0.0"  # noqa: S104 - the IPv4 wildcard address as ss and docker print it (test data; nothing binds)

FAKES = {
    # id -u: 0 inside the fake sudo or when the test runs "as root", else a user's uid.
    "id": 'if [ "${FAKE_ROOT:-0}" = 1 ]; then echo 0; else echo 950; fi\n',
    # sudo: FAKE_SUDO=ok (no password needed), password (only an interactive sudo works), fail.
    "sudo": (
        'if [ "$1" = -n ]; then\n'
        "\tshift\n"
        '\tif [ "${FAKE_SUDO:-ok}" != ok ]; then echo "sudo: a password is required" >&2; exit 1; fi\n'
        "fi\n"
        'if [ "${FAKE_SUDO:-ok}" = fail ]; then echo "sudo: 3 incorrect password attempts" >&2; exit 1; fi\n'
        'FAKE_ROOT=1 exec "$@"\n'
    ),
    # ss: process names only for root, as ss -p shows another user's sockets without them.
    "ss": 'if [ "${FAKE_ROOT:-0}" = 1 ]; then cat "$FAKE_DIR/ss.root"; else cat "$FAKE_DIR/ss.user"; fi\n',
    # docker: the socket is root's unless FAKE_DOCKER_USER=1.
    "docker": (
        'if [ "${FAKE_ROOT:-0}" = 1 ] || [ "${FAKE_DOCKER_USER:-0}" = 1 ]; then\n'
        '\tcat "$FAKE_DIR/docker.out"\n'
        "\texit 0\n"
        "fi\n"
        'echo "permission denied while trying to connect to the Docker daemon socket at'
        ' unix:///var/run/docker.sock" >&2\n'
        "exit 1\n"
    ),
    "midclt": (
        'if [ -e "$FAKE_DIR/midclt.fail" ]; then echo "Failed to run middleware call. Daemon not running?" >&2;'
        " exit 1; fi\n"
        'cat "$FAKE_DIR/midclt.out"\n'
    ),
}

# Every fake appends its name and arguments, tab-separated, to calls.log before it acts.
LOG = (
    'printf \'%s\' "${0##*/}" >>"$FAKE_DIR/calls.log"\n'
    'for a in "$@"; do printf \'\\t%s\' "$a"; done >>"$FAKE_DIR/calls.log"\n'
    'echo >>"$FAKE_DIR/calls.log"\n'
)


def ss_line(proto, address, port, *procs):
    """One line of ss -Hltunp (Netid State Recv-Q Send-Q Local:Port Peer:Port Process)."""
    state, queue = ("LISTEN", "4096") if proto == "tcp" else ("UNCONN", "0")
    peer = "[::]:*" if address.startswith("[") else f"{ANY4}:*"
    local = f"{address}:{port}"
    users = ",".join(f'("{name}",pid={pid},fd={fd})' for name, pid, fd in procs)
    line = f"{proto}   {state} 0      {queue:<6} {local:>22} {peer:>14}"
    return line + (f" users:({users})" if users else "")


def ss_line_list(proto, address, port, *procs):
    return [ss_line(proto, address, port, *procs)]


def both(proto, port, *procs):
    return [ss_line(proto, ANY4, port, *procs), ss_line(proto, "[::]", port, *procs)]


BASE_SOCKETS = [
    *both("tcp", 22, ("sshd", 1201, 3)),
    ss_line("tcp", ANY4, 111, ("rpcbind", 801, 4), ("systemd", 1, 64)),
    *both("tcp", 445, ("smbd", 2310, 31)),
    ss_line("tcp", ANY4, 2049),  # nfsd: a kernel socket, no process
    ss_line("udp", "127.0.0.1", 323, ("chronyd", 990, 5)),
    *both("udp", 5353, ("avahi-daemon", 1102, 12)),
    ss_line("udp", ANY4, 3702, ("wsdd.py", 2555, 6)),
]


def ui_sockets(http, https):
    return [
        *both("tcp", http, ("nginx", 3001, 7), ("nginx", 3002, 7)),
        *both("tcp", https, ("nginx", 3001, 8), ("nginx", 3002, 8)),
    ]


EDGE_SOCKETS = [
    *both("tcp", 80, ("docker-proxy", 41001, 7)),
    *both("tcp", 443, ("docker-proxy", 41002, 7)),
    *both("udp", 443, ("docker-proxy", 41003, 7)),
]

EDGE_CONTAINER = (
    "caddy|ix-ai-edge|0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, 0.0.0.0:443->443/udp,"
    " [::]:443->443/tcp, [::]:443->443/udp"
)
STACK_CONTAINERS = [
    "llama-swap|ix-ai-inference|",
    "litellm|ix-ai-inference|",
    "open-webui|ix-ai-web|8080/tcp",
    "gpu-exporter|ix-ai-edge|",
]


def midclt_answer(http, https, redirect=True, v4=(ANY4,), v6=("::",)):
    """system.general.config as midclt prints it: json.dumps of the dict, on one line."""
    return json.dumps(
        {
            "id": 1,
            "ui_certificate": {
                "id": 1,
                "name": "truenas_default",
                "certificate": "-----BEGIN CERTIFICATE-----\nMIIBexample\n-----END CERTIFICATE-----\n",
            },
            "ui_httpsport": https,
            "ui_httpsredirect": redirect,
            "ui_httpsprotocols": ["TLSv1.2", "TLSv1.3"],
            "ui_port": http,
            "ui_address": list(v4),
            "ui_v6address": list(v6),
            "ui_allowlist": [],
            "ui_consolemsg": False,
            "ui_x_frame_options": "SAMEORIGIN",
            "kbdmap": "us",
            "timezone": "UTC",
            "usage_collection": False,
            "wizardshown": True,
            "usage_collection_is_set": True,
            "ds_auth": False,
        }
    )


def strip_users(text):
    """The same ss output as a user without root sees it: no process column for others' sockets."""
    return "".join(re.sub(r"\s+users:\(.*\)$", "", line) + "\n" for line in text.splitlines())


class Server:
    """A temporary fake TrueNAS: the fixtures, the fakes and a PATH of nothing else."""

    def __init__(self, test, sockets=(), containers=(), ui=(81, 444), missing=(), awk=None, **midclt):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.cwd = self.dir / "cwd"
        self.cwd.mkdir()
        for name, body in FAKES.items():
            if name in missing:
                continue
            path = self.bin / name
            path.write_text("#!/bin/sh\n" + LOG + body)
            path.chmod(0o755)
        for tool in ("sed", "tr", "cat", "true"):
            os.symlink(shutil.which(tool), self.bin / tool)
        if awk is None:
            os.symlink(shutil.which("awk"), self.bin / "awk")
        else:
            command = awk.split()
            command[0] = shutil.which(command[0])
            wrapper = self.bin / "awk"
            wrapper.write_text("#!/bin/sh\nexec " + " ".join(command) + ' "$@"\n')
            wrapper.chmod(0o755)
        ss_root = "".join(line + "\n" for line in sockets)
        (self.dir / "ss.root").write_text(ss_root)
        (self.dir / "ss.user").write_text(strip_users(ss_root))
        (self.dir / "docker.out").write_text("".join(line + "\n" for line in containers))
        if ui is None:
            (self.dir / "midclt.fail").write_text("")
        else:
            (self.dir / "midclt.out").write_text(midclt_answer(*ui, **midclt) + "\n")

    def run(self, *args, sudo="ok", root=False, docker_user=False, interpreter=None):
        env = {
            "PATH": str(self.bin),
            "FAKE_DIR": str(self.dir),
            "FAKE_SUDO": sudo,
            "LC_ALL": "C",
        }
        if root:
            env["FAKE_ROOT"] = "1"
        if docker_user:
            env["FAKE_DOCKER_USER"] = "1"
        command = [*(interpreter or [SH]), str(SCRIPT), *args]
        done = subprocess.run(
            command, env=env, cwd=self.cwd, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL
        )
        return done

    def calls(self):
        log = self.dir / "calls.log"
        if not log.exists():
            return []
        return [tuple(line.split("\t")) for line in log.read_text().splitlines()]


def verdicts(stdout):
    """The lines of the "Ports the stack needs" section, as {"80/tcp": "free", ...}."""
    section = stdout.split("Ports the stack needs on this server", 1)[1].split("\n\n", 1)[0]
    found = {}
    for line in section.splitlines()[1:]:
        port, verdict = line.strip().split(None, 1)
        found[port] = verdict
    return found


READS = [
    ("ss", "-Hltunp"),
    ("docker", "ps", "--format", DOCKER_FORMAT),
    ("midclt", "call", "system.general.config"),
]


class TestUsage(unittest.TestCase):
    def test_help(self):
        server = Server(self)
        done = server.run("--help")
        self.assertEqual(done.returncode, 0)
        self.assertTrue(done.stdout.startswith("usage: sh tools/port-inventory.sh [--json] [--no-sudo]"))
        self.assertEqual(server.calls(), [])

    def test_unknown_argument(self):
        server = Server(self)
        done = server.run("--bogus")
        self.assertEqual(done.returncode, 2)
        self.assertIn("unknown argument: --bogus", done.stderr)
        self.assertIn("usage:", done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual(server.calls(), [])


class TestVerdicts(unittest.TestCase):
    def test_moved_web_interface_leaves_the_ports_free(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(81, 444), STACK_CONTAINERS[:1])
        done = server.run()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(verdicts(done.stdout), {"80/tcp": "free", "443/tcp": "free", "443/udp": "free"})
        self.assertIn("ran through sudo", done.stdout)
        self.assertRegex(done.stdout, r"HTTP port \(ui_port\) +81\n")
        self.assertRegex(done.stdout, r"HTTPS port \(ui_httpsport\) +444\n")
        self.assertRegex(done.stdout, r"Redirect HTTP to HTTPS +yes\n")
        self.assertRegex(done.stdout, r"Addresses +0\.0\.0\.0, ::\n")
        self.assertRegex(done.stdout, r"  444    tcp    0\.0\.0\.0 +nginx\n")
        self.assertRegex(done.stdout, r"  111    tcp    0\.0\.0\.0 +rpcbind,systemd\n")
        self.assertIn("Result: every port the stack needs is free or already used by the stack (exit 0).", done.stdout)

    def test_only_read_commands_run(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(81, 444), STACK_CONTAINERS)
        server.run()
        calls = server.calls()
        self.assertEqual([call for call in calls if call[0] != "sudo" and call[0] != "id"], READS)
        self.assertEqual(
            [call for call in calls if call[0] == "sudo"],
            [("sudo", "-n", "true")] + [("sudo", *read) for read in READS],
        )
        self.assertEqual(list(server.cwd.iterdir()), [])

    def test_sockets_are_sorted_by_port(self):
        server = Server(self, list(reversed(BASE_SOCKETS + ui_sockets(81, 444))))
        done = server.run()
        ports = re.findall(r"^  (\d+) +(?:tcp|udp) ", done.stdout, re.MULTILINE)
        self.assertEqual([int(port) for port in ports], sorted(int(port) for port in ports))

    def test_web_interface_on_the_default_ports(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(80, 443), ui=(80, 443))
        done = server.run()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(
            verdicts(done.stdout),
            {
                "80/tcp": "used by the TrueNAS web interface",
                "443/tcp": "used by the TrueNAS web interface",
                "443/udp": "free",
            },
        )
        self.assertIn("System > General Settings > GUI > Settings", done.stdout)
        self.assertIn("Result: 2 of 3 ports the stack needs are in use by something else", done.stdout)

    def test_the_stack_edge_app_is_ours(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(81, 444) + EDGE_SOCKETS, [EDGE_CONTAINER, *STACK_CONTAINERS])
        done = server.run()
        self.assertEqual(done.returncode, 0, done.stdout)
        ours = "ours: container caddy (app ai-edge)"
        self.assertEqual(verdicts(done.stdout), {"80/tcp": ours, "443/tcp": ours, "443/udp": ours})
        self.assertRegex(done.stdout, r"  443 +udp +\[::\] +443 +caddy +ai-edge\n")
        self.assertRegex(done.stdout, r"  80 +tcp +0\.0\.0\.0 +docker-proxy\n")

    def test_another_app_on_443(self):
        sockets = BASE_SOCKETS + ui_sockets(81, 444) + both("tcp", 443, ("docker-proxy", 5001, 4))
        server = Server(self, sockets, ["npm|ix-npm|0.0.0.0:443->443/tcp, [::]:443->443/tcp"])
        done = server.run()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(verdicts(done.stdout)["443/tcp"], "used by container npm (app npm)")
        self.assertIn("Result: 1 of 3 ports the stack needs is in use", done.stdout)

    def test_a_plain_container_is_not_a_truenas_app(self):
        sockets = BASE_SOCKETS + both("tcp", 80, ("docker-proxy", 5001, 4))
        server = Server(self, sockets, ["web-test||0.0.0.0:80->8080/tcp, [::]:80->8080/tcp"])
        done = server.run()
        self.assertEqual(verdicts(done.stdout)["80/tcp"], "used by container web-test (not a TrueNAS app)")
        self.assertRegex(done.stdout, r"  80 +tcp +0\.0\.0\.0 +8080 +web-test +-\n")

    def test_the_host_port_counts_not_the_container_port(self):
        containers = [
            "npm|ix-npm|0.0.0.0:30021->443/tcp, 0.0.0.0:30020->80/tcp",  # container 443 on host 30021
            "alt|ix-alt|0.0.0.0:443->8443/tcp",  # host 443 to container 8443
        ]
        server = Server(self, BASE_SOCKETS, containers)
        done = server.run()
        self.assertEqual(
            verdicts(done.stdout),
            {"80/tcp": "free", "443/tcp": "used by container alt (app alt)", "443/udp": "free"},
        )

    def test_a_published_range_covers_its_ports(self):
        server = Server(self, BASE_SOCKETS, ["ranged|ix-ranged|0.0.0.0:400-500->400-500/udp"])
        done = server.run()
        self.assertEqual(verdicts(done.stdout)["443/udp"], "used by container ranged (app ranged)")
        self.assertEqual(verdicts(done.stdout)["443/tcp"], "free")
        self.assertRegex(done.stdout, r"  400-500 +udp +0\.0\.0\.0 +400-500 +ranged +ranged\n")

    def test_an_exposed_port_is_not_published(self):
        server = Server(self, BASE_SOCKETS, ["exposed|ix-exposed|80/tcp, 443/tcp, 443/udp"])
        done = server.run()
        self.assertEqual(verdicts(done.stdout), {"80/tcp": "free", "443/tcp": "free", "443/udp": "free"})
        self.assertIn("Ports published by Docker containers (docker ps)\n  none\n", done.stdout)

    def test_a_host_process_on_80(self):
        server = Server(self, BASE_SOCKETS + both("tcp", 80, ("haproxy", 777, 5)))
        done = server.run()
        self.assertEqual(verdicts(done.stdout)["80/tcp"], "used by haproxy")

    def test_ours_and_another_user_on_one_port(self):
        sockets = BASE_SOCKETS + ui_sockets(80, 444) + EDGE_SOCKETS[2:]
        server = Server(self, sockets, ["caddy|ix-ai-edge|0.0.0.0:443->443/tcp, 0.0.0.0:443->443/udp"], ui=(80, 444))
        done = server.run()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(verdicts(done.stdout)["80/tcp"], "used by the TrueNAS web interface")
        self.assertEqual(verdicts(done.stdout)["443/tcp"], "ours: container caddy (app ai-edge)")


class TestPrivileges(unittest.TestCase):
    def test_as_root_sudo_is_not_used(self):
        server = Server(self, BASE_SOCKETS + ss_line_list("udp", ANY4, 443))
        done = server.run(root=True)
        self.assertIn("ran as root", done.stdout)
        self.assertEqual([call for call in server.calls() if call[0] == "sudo"], [])
        self.assertEqual(verdicts(done.stdout)["443/udp"], "used by a kernel socket (no process)")

    def test_sudo_asks_for_the_password_once(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(81, 444))
        done = server.run(sudo="password")
        self.assertEqual(done.returncode, 0)
        self.assertIn("sudo asks for your password once", done.stderr)
        self.assertIn("ran through sudo", done.stdout)
        sudo_calls = [call for call in server.calls() if call[0] == "sudo"]
        self.assertEqual(sudo_calls[:2], [("sudo", "-n", "true"), ("sudo", "true")])

    def test_without_sudo_the_owner_of_a_used_port_is_unnamed(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(81, 444) + EDGE_SOCKETS, [EDGE_CONTAINER])
        done = server.run(sudo="fail")
        self.assertEqual(done.returncode, 1)
        self.assertIn("ran without sudo", done.stdout)
        self.assertIn("sudo did not succeed", done.stdout)
        self.assertIn("not available: docker ps failed: permission denied", done.stdout)
        self.assertEqual(verdicts(done.stdout)["80/tcp"], "used by a process whose name needs sudo")
        self.assertRegex(done.stdout, r"  22     tcp    0\.0\.0\.0 +-\n")

    def test_without_sudo_the_web_interface_is_still_named(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(80, 443), ui=(80, 443))
        done = server.run("--no-sudo")
        self.assertEqual(verdicts(done.stdout)["443/tcp"], "used by the TrueNAS web interface")
        self.assertEqual([call for call in server.calls() if call[0] == "sudo"], [])
        self.assertIn("Ran without sudo (--no-sudo)", done.stdout)

    def test_docker_readable_without_sudo(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(81, 444) + EDGE_SOCKETS, [EDGE_CONTAINER])
        done = server.run("--no-sudo", docker_user=True)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(verdicts(done.stdout)["443/udp"], "ours: container caddy (app ai-edge)")

    def test_an_unnamed_socket_on_another_address_still_counts(self):
        sockets = BASE_SOCKETS + [
            ss_line("tcp", "192.0.2.11", 443, ("docker-proxy", 41002, 7)),
            ss_line("tcp", "192.0.2.10", 443, ("haproxy", 777, 5)),
        ]
        server = Server(self, sockets, ["caddy|ix-ai-edge|192.0.2.11:443->443/tcp"])
        done = server.run("--no-sudo", docker_user=True)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(
            verdicts(done.stdout)["443/tcp"],
            "used by a process whose name needs sudo; also container caddy (app ai-edge)",
        )

    def test_no_sudo_installed(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(81, 444), missing=("sudo",))
        done = server.run()
        self.assertEqual(done.returncode, 0)
        self.assertIn("sudo is not installed", done.stdout)


class TestMissingSources(unittest.TestCase):
    def test_without_ss_free_cannot_be_told(self):
        server = Server(self, missing=("ss",))
        done = server.run()
        self.assertEqual(done.returncode, 1)
        self.assertIn("not available: ss is not installed", done.stdout)
        self.assertEqual(verdicts(done.stdout)["80/tcp"], "unknown (ss could not be run)")

    def test_without_ss_docker_still_shows_ours(self):
        server = Server(self, containers=[EDGE_CONTAINER], missing=("ss",))
        done = server.run()
        self.assertEqual(done.returncode, 0)
        self.assertEqual(verdicts(done.stdout)["443/tcp"], "ours: container caddy (app ai-edge)")

    def test_without_midclt_nginx_is_named(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(80, 443), missing=("midclt",))
        done = server.run()
        self.assertIn("not available: midclt is not installed (is this the TrueNAS server?)", done.stdout)
        self.assertEqual(verdicts(done.stdout)["80/tcp"], "used by nginx")

    def test_midclt_fails(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(81, 444), ui=None)
        done = server.run()
        self.assertIn(
            "not available: midclt call system.general.config failed: Failed to run middleware call.", done.stdout
        )
        self.assertEqual(done.returncode, 0)

    def test_without_docker(self):
        server = Server(self, BASE_SOCKETS + ui_sockets(81, 444), missing=("docker",))
        done = server.run()
        self.assertIn("not available: docker is not installed", done.stdout)


class TestJson(unittest.TestCase):
    def test_json_report(self):
        server = Server(
            self,
            BASE_SOCKETS + ui_sockets(80, 444) + EDGE_SOCKETS[2:],
            ["caddy|ix-ai-edge|0.0.0.0:443->443/tcp, 0.0.0.0:443->443/udp", *STACK_CONTAINERS],
            ui=(80, 444),
            v4=(ANY4, "192.0.2.10"),
        )
        done = server.run("--json")
        self.assertEqual(done.returncode, 1)
        report = json.loads(done.stdout)
        self.assertEqual(report["privileges"], "sudo")
        self.assertEqual(report["sources"], {"ss": "ok", "docker": "ok", "midclt": "ok"})
        self.assertEqual(report["sockets"][0], {"port": 22, "proto": "tcp", "address": ANY4, "process": "sshd"})
        self.assertIn({"port": 2049, "proto": "tcp", "address": ANY4, "process": ""}, report["sockets"])
        self.assertEqual(
            report["published"][0],
            {
                "host_ports": "443",
                "first": 443,
                "last": 443,
                "proto": "tcp",
                "address": ANY4,
                "container_ports": "443",
                "container": "caddy",
                "app": "ai-edge",
            },
        )
        self.assertEqual(
            report["web_interface"],
            {"http_port": 80, "https_port": 444, "https_redirect": True, "addresses": [ANY4, "192.0.2.10", "::"]},
        )
        self.assertEqual(
            report["needed"],
            [
                {
                    "port": 80,
                    "proto": "tcp",
                    "verdict": "used",
                    "users": [{"who": "the TrueNAS web interface", "ours": False}],
                },
                {
                    "port": 443,
                    "proto": "tcp",
                    "verdict": "ours",
                    "users": [{"who": "container caddy (app ai-edge)", "ours": True}],
                },
                {
                    "port": 443,
                    "proto": "udp",
                    "verdict": "ours",
                    "users": [{"who": "container caddy (app ai-edge)", "ours": True}],
                },
            ],
        )
        self.assertEqual(report["notes"], [])
        self.assertFalse(report["ok"])

    def test_json_with_missing_sources(self):
        server = Server(self, BASE_SOCKETS, ui=None, missing=("docker",))
        done = server.run("--json", sudo="fail")
        report = json.loads(done.stdout)
        self.assertEqual(report["privileges"], "user")
        self.assertIsNone(report["published"])
        self.assertIsNone(report["web_interface"])
        self.assertEqual(report["sources"]["docker"], "docker is not installed")
        self.assertTrue(report["sources"]["midclt"].startswith("midclt call system.general.config failed"))
        self.assertTrue(report["ok"])
        self.assertEqual(done.returncode, 0)
        self.assertTrue(report["notes"][0].startswith("sudo did not succeed"))


class TestPortability(unittest.TestCase):
    """The same report from every awk and POSIX shell at hand (TrueNAS: dash, and gawk or mawk)."""

    SOCKETS = BASE_SOCKETS + ui_sockets(80, 444) + EDGE_SOCKETS[2:] + both("tcp", 8000, ("python3", 9, 3))
    CONTAINERS = ["caddy|ix-ai-edge|0.0.0.0:443->443/tcp, 0.0.0.0:443->443/udp", "r|ix-r|0.0.0.0:79-81->79-81/tcp"]

    def reference(self, *args):
        return Server(self, self.SOCKETS, self.CONTAINERS, ui=(80, 444)).run(*args)

    def test_awk_implementations(self):
        candidates = {
            "mawk": "mawk",
            "gawk": "gawk --posix",
            "original-awk": "original-awk",
            "busybox": "busybox awk",
        }
        found = {name: cmd for name, cmd in candidates.items() if shutil.which(cmd.split()[0])}
        if not found:
            self.skipTest("no other awk installed")
        for args in ((), ("--json",)):
            expected = self.reference(*args)
            for name, cmd in found.items():
                with self.subTest(awk=name, args=args):
                    server = Server(self, self.SOCKETS, self.CONTAINERS, ui=(80, 444), awk=cmd)
                    done = server.run(*args)
                    self.assertEqual((done.returncode, done.stdout), (expected.returncode, expected.stdout))

    def test_busybox_sh(self):
        if not shutil.which("busybox"):
            self.skipTest("busybox is not installed")
        expected = self.reference()
        server = Server(self, self.SOCKETS, self.CONTAINERS, ui=(80, 444))
        done = server.run(interpreter=[shutil.which("busybox"), "sh"])
        self.assertEqual((done.returncode, done.stdout), (expected.returncode, expected.stdout))


if __name__ == "__main__":
    unittest.main()
