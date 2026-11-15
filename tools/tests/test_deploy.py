"""Unit tests of tools/deploy.py with a fake TrueNAS client (no network, no NAS)."""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent


def load(name):
    """tools/<name>.py as the module las_<name> (tools/ is not a package; secrets.py would shadow
    the standard library's secrets under its own name)."""
    spec = importlib.util.spec_from_file_location(f"las_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


deploy = load("deploy")

try:
    import yaml
except ImportError:  # the test below that needs PyYAML is skipped without it
    yaml = None

DESIRED = textwrap.dedent(
    """\
    schema = 1
    release = "v1.0"
    truenas_version = "25.10.8"
    stacks_dir = "/mnt/tank/ai/stacks/local-agent-stack"
    secrets_dir = "/mnt/tank/ai/secrets"

    [apps.ai-inference]
    stack = "inference"

    [apps.ai-web]
    stack = "web"
    """
)

WEB_IMAGES = ["ghcr.io/open-webui/open-webui:v0.13.3-slim@sha256:" + "a" * 64, "searxng/searxng:2026.11.15-2d500cb6b"]
EDGE_OVERRIDE = "/mnt/tank/ai/appdata/caddy/internal-ca.override.yaml"
WEB_OVERRIDE = "/mnt/tank/ai/appdata/web/extra.override.yaml"
SECRET = "Zx9SuperSecretValue48charsLongForTheTestOnly0000"
DEFAULT_COMPOSE = b"services: {}\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


# The files hash of a stack folder whose compose.yaml is DEFAULT_COMPOSE and names no other file
# (what make_tar puts into the fake release), computed here without deploy.py.
FAKE_FILES_HASH = "sha256:" + sha((sha(DEFAULT_COMPOSE) + "  compose.yaml\n").encode())


class FakeClient:
    """Answers like the 25.10 middleware: a dict of apps, jobs that change it, every call recorded."""

    def __init__(self, apps=None, version="25.10.8", login="SUCCESS"):
        self.apps = apps or {}
        self.version = version
        self.login = login
        self.calls = []
        self.closed = False

    def call(self, method, *params, job=False):
        self.calls.append((method, params, job))
        if method == "auth.login_ex":
            return {"response_type": self.login}
        if method == "system.info":
            return {"version": self.version}
        if method == "app.query":
            filters = params[0] if params else []
            found = list(self.apps.values())
            for field, _op, value in filters:
                found = [entry for entry in found if entry.get(field) == value]
            return [{key: value for key, value in entry.items() if key != "stored"} for entry in found]
        if method == "app.config":
            return self.apps[params[0]]["stored"]
        if method == "app.create":
            data = params[0]
            assert job is True
            self.apps[data["app_name"]] = {
                "name": data["app_name"],
                "state": "RUNNING",
                "custom_app": data["custom_app"],
                "stored": parse_wrapper(data["custom_compose_config_string"]),
                "active_workloads": {"images": []},
            }
            return self.apps[data["app_name"]]
        if method == "app.update":
            assert job is True
            # crud.py update_internal: the YAML is stored; compose runs only when the app is not STOPPED.
            self.apps[params[0]]["stored"] = parse_wrapper(params[1]["custom_compose_config_string"])
            return self.apps[params[0]]
        if method == "app.redeploy":
            assert job is True
            self.apps[params[0]]["state"] = "RUNNING"
            return self.apps[params[0]]
        raise AssertionError(f"unexpected call {method}")

    def close(self):
        self.closed = True


def parse_wrapper(text):
    """The wrapper YAML deploy.py writes, parsed the way TrueNAS would (enough for these tests)."""
    lines = text.splitlines()
    assert lines[0] == "include:", text
    entry, index = {}, 1
    if lines[index] == "  - path:":
        entry["path"], index = [], index + 1
        while lines[index].startswith("      - "):
            entry["path"].append(lines[index][len("      - ") :])
            index += 1
    else:
        assert lines[index].startswith("  - path: "), text
        entry["path"], index = lines[index].split(": ", 1)[1], index + 1
    assert lines[index].startswith("    env_file: "), text
    entry["env_file"], index = lines[index].split(": ", 1)[1], index + 1
    assert lines[index] == "services: {}", text
    config = {"include": [entry], "services": {}}
    if index + 1 < len(lines):
        assert lines[index + 1] == "x-local-agent-stack:", text
        config["x-local-agent-stack"] = dict(line.strip().split(": ", 1) for line in lines[index + 2 :])
    return config


def wrapper_of(stack, overrides=(), **content):
    compose = f"/mnt/tank/ai/stacks/local-agent-stack/stack/{stack}/compose.yaml"
    config = {
        "include": [
            {
                "path": [compose, *overrides] if overrides else compose,
                "env_file": f"/mnt/tank/ai/secrets/{stack}.env",
            }
        ],
        "services": {},
    }
    if content:
        config["x-local-agent-stack"] = dict(content)
    return config


def app_entry(name, stack, state="RUNNING", stored=None, images=(), custom=True):
    return {
        "name": name,
        "id": name,
        "state": state,
        "custom_app": custom,
        "stored": wrapper_of(stack) if stored is None else stored,
        "active_workloads": {"images": list(images)},
    }


def make_tar(stack, files=None):
    """The `git archive` output of stack/<stack>: compose.yaml and the example env file by default."""
    files = files or {"compose.yaml": DEFAULT_COMPOSE, f"{stack}.env.example": b""}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as bundle:
        for name, text in files.items():
            info = tarfile.TarInfo(f"stack/{stack}/{name}")
            info.size = len(text)
            bundle.addfile(info, io.BytesIO(text))
    return buffer.getvalue()


def strip_extension(text):
    """The YAML without its x-local-agent-stack block (the last lines of the wrapper)."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("x-local-agent-stack:"):
            return "".join(lines[:index])
    return text


class Workspace(unittest.TestCase):
    """A temporary repository layout, settings file and key files for one test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for stack in ("inference", "web"):
            folder = self.dir / "stack" / stack
            folder.mkdir(parents=True)
            (folder / "compose.yaml").write_text("services: {}\n")
            (folder / f"{stack}.env.example").write_text("A=1\n")
        self.desired = self.dir / "truenas.toml"
        self.desired.write_text(DESIRED)
        self.config = self.dir / "conf" / "truenas.toml"
        self.config.parent.mkdir()
        self.config.write_text(
            'uri = "wss://192.0.2.10:444/api/current"\n'
            'read_user = "deploy-read"\nread_key_file = "read.key"\n'
            'apply_user = "deploy-apply"\napply_key_file = "apply.key"\n'
        )
        for role in ("read", "apply"):
            key = self.config.parent / f"{role}.key"
            key.write_text(f"1-{role}-not-a-real-key\n")
            key.chmod(0o600)
        self.uris = []
        self.tars = {}  # stack -> {name: bytes} in the fake release, when not make_tar's default
        self.stderr = ""

    def factory(self, client):
        def make(uri):
            self.uris.append(uri)
            return client

        return make

    def run_main(self, client, *argv, images=None):
        out = io.StringIO()

        def runner(command, **_kwargs):
            return self.fake_runner(command, images)

        with redirect_stderr(io.StringIO()) as err:
            code = deploy.main(
                ["--file", str(self.desired), "--config", str(self.config), *argv],
                out=out,
                client_factory=self.factory(client),
                runner=runner,
            )
        self.stderr = err.getvalue()
        return code, out.getvalue()

    def fake_runner(self, command, images, docker=True):
        """git rev-parse/archive and docker compose config --images, as the release has them. The
        tag is in the clone when images is not None; docker=False makes docker missing."""
        if command[:1] == ["git"] and "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0 if images is not None else 1, b"", b"")
        if command[:1] == ["git"] and "archive" in command:
            stack = command[-1].split("/")[1]
            return subprocess.CompletedProcess(command, 0, make_tar(stack, self.tars.get(stack)), b"")
        if command[:2] == ["docker", "compose"]:
            if not docker:
                raise FileNotFoundError(2, "No such file or directory", "docker")
            stack = Path(command[command.index("-f") + 1]).parent.name
            listed = "\n".join(images.get(stack, [])) + "\n"
            return subprocess.CompletedProcess(command, 0, listed.encode(), b"")
        raise AssertionError(command)

    def no_tag(self, command, **_kwargs):
        return self.fake_runner(command, None)

    def with_tag(self, command, **_kwargs):
        return self.fake_runner(command, {})


class TestDesiredState(Workspace):
    def test_valid_file_loads_in_order(self):
        desired = deploy.load_desired(self.desired, self.dir)
        self.assertEqual([app.name for app in desired.apps], ["ai-inference", "ai-web"])
        self.assertEqual(desired.release, "v1.0")
        self.assertIsNone(desired.env_dir)
        self.assertEqual(desired.apps[0].overrides, ())

    def test_repository_file_is_valid(self):
        desired = deploy.load_desired(deploy.DEFAULT_FILE, deploy.ROOT, check_files=False)
        self.assertEqual(
            [(app.name, app.stack) for app in desired.apps],
            [("ai-inference", "inference"), ("ai-rag", "rag"), ("ai-web", "web"), ("ai-edge", "edge")],
        )
        self.assertEqual(desired.env_dir, "~/.config/local-agent-stack/secrets")
        self.assertIs(desired.content_hashes, True)

    def test_content_hashes_setting(self):
        self.assertIs(deploy.load_desired(self.desired, self.dir).content_hashes, True)
        self.desired.write_text(DESIRED.replace("schema = 1\n", "schema = 1\ncontent_hashes = false\n"))
        self.assertIs(deploy.load_desired(self.desired, self.dir).content_hashes, False)
        self.desired.write_text(DESIRED.replace("schema = 1\n", 'schema = 1\ncontent_hashes = "no"\n'))
        with self.assertRaises(deploy.ConfigError) as caught:
            deploy.load_desired(self.desired, self.dir)
        self.assertIn("content_hashes must be true or false, not 'no'", str(caught.exception))

    def test_validate_says_when_the_hashes_are_off(self):
        self.desired.write_text(DESIRED.replace("schema = 1\n", "schema = 1\ncontent_hashes = false\n"))
        for argv in (["validate"], ["validate", "--no-hashes"]):
            with self.subTest(argv=argv):
                out = io.StringIO()
                code = deploy.main(["--file", str(self.desired), "--root", str(self.dir), *argv], out=out)
                self.assertEqual(code, 0)
                self.assertIn("ok (2 apps, release v1.0, TrueNAS 25.10.8, content hashes off)", out.getvalue())

    def test_problems_are_all_reported(self):
        self.desired.write_text(
            'schema = 2\nrelease = "1.0"\ntruenas_version = "x"\nstacks_dir = "relative"\n'
            'secrets_dir = "/mnt/tank/ai/secrets"\nextra = 1\nenv_dir = "secrets"\n'
            '[apps.Bad_Name]\nstack = "inference"\n[apps.ai-two]\nstack = "inference"\ncolour = "red"\n'
            'overrides = ["relative.yaml", "/a/b.yaml", "/a/b.yaml"]\n'
            '[apps.ai-three]\nstack = "web"\noverrides = "/a/b.yaml"\n'
        )
        with self.assertRaises(deploy.ConfigError) as caught:
            deploy.load_desired(self.desired, self.dir)
        message = str(caught.exception)
        for part in (
            "schema must be 1",
            "release must be a tag",
            "truenas_version",
            "stacks_dir",
            "unknown key 'extra'",
            "env_dir must be a folder",
            "app name 'Bad_Name'",
            "unknown key 'colour'",
            "is also apps.Bad_Name.stack",
            "apps.ai-two.overrides[0] must be an absolute path",
            "apps.ai-two.overrides lists /a/b.yaml twice",
            "apps.ai-three.overrides must be a list",
        ):
            self.assertIn(part, message)

    def test_overrides_and_env_dir_load(self):
        self.desired.write_text(
            DESIRED.replace("schema = 1\n", 'schema = 1\nenv_dir = "~/x/y"\n').replace(
                'stack = "web"\n', f'stack = "web"\noverrides = ["{WEB_OVERRIDE}"]\n'
            )
        )
        desired = deploy.load_desired(self.desired, self.dir)
        self.assertEqual(desired.env_dir, "~/x/y")
        self.assertEqual(desired.apps[1].overrides, (WEB_OVERRIDE,))

    def test_missing_stack_files_fail_validate(self):
        (self.dir / "stack" / "web" / "web.env.example").unlink()
        with self.assertRaises(deploy.ConfigError) as caught:
            deploy.load_desired(self.desired, self.dir)
        self.assertIn("stack/web/web.env.example does not exist", str(caught.exception))

    def test_app_name_longer_than_40_characters(self):
        self.desired.write_text(DESIRED.replace("ai-web", "a" * 41))
        with self.assertRaises(deploy.ConfigError):
            deploy.load_desired(self.desired, self.dir)

    def test_validate_command(self):
        out = io.StringIO()
        code = deploy.main(["--file", str(self.desired), "--root", str(self.dir), "validate"], out=out)
        self.assertEqual(code, 0)
        self.assertIn("ok (2 apps, release v1.0, TrueNAS 25.10.8)", out.getvalue())

    def test_render_is_the_include_wrapper(self):
        out = io.StringIO()
        with redirect_stderr(io.StringIO()) as err:
            code = deploy.main(["--file", str(self.desired), "render", "--app", "ai-web"], out=out, runner=self.no_tag)
        self.assertEqual(code, 0)
        self.assertEqual(
            out.getvalue(),
            "# ai-web\n"
            "include:\n"
            "  - path: /mnt/tank/ai/stacks/local-agent-stack/stack/web/compose.yaml\n"
            "    env_file: /mnt/tank/ai/secrets/web.env\n"
            "services: {}\n",
        )
        self.assertIn("ai-web: files not hashed: tag v1.0 is not in this clone", err.getvalue())

    def test_render_with_the_tag_carries_the_files_hash(self):
        out = io.StringIO()
        with redirect_stderr(io.StringIO()):
            code = deploy.main(
                ["--file", str(self.desired), "render", "--app", "ai-web"], out=out, runner=self.with_tag
            )
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().endswith(f"services: {{}}\nx-local-agent-stack:\n  files: {FAKE_FILES_HASH}\n"))

    def test_render_unknown_app(self):
        with redirect_stderr(io.StringIO()):
            code = deploy.main(["--file", str(self.desired), "render", "--app", "nope"], out=io.StringIO())
        self.assertEqual(code, 2)


class TestOptions(Workspace):
    """--file, --config, --local, --no-hashes (and the hidden --root) before or after the command."""

    def test_defaults(self):
        args = deploy.parse_args(["status"])
        self.assertEqual(args.file, str(deploy.DEFAULT_FILE))
        self.assertEqual(args.config, str(deploy.DEFAULT_CONFIG))
        self.assertIs(args.local, False)
        self.assertIs(args.no_hashes, False)
        self.assertIsNone(args.root)

    def test_before_and_after_the_command(self):
        for argv in (
            ["--file", "F", "--config", "C", "--local", "--no-hashes", "drift", "--app", "x"],
            ["drift", "--file", "F", "--config", "C", "--local", "--no-hashes", "--app", "x"],
            ["--file", "F", "--no-hashes", "drift", "--app", "x", "--config", "C", "--local"],
        ):
            with self.subTest(argv=argv):
                args = deploy.parse_args(argv)
                self.assertEqual(
                    (args.file, args.config, args.local, args.no_hashes, args.app), ("F", "C", True, True, ["x"])
                )

    def test_after_the_command_wins(self):
        self.assertEqual(deploy.parse_args(["--file", "before", "plan", "--file", "after"]).file, "after")
        self.assertEqual(deploy.parse_args(["--file", "before", "plan"]).file, "before")

    def test_validate_with_options_after(self):
        out = io.StringIO()
        code = deploy.main(["validate", "--file", str(self.desired), "--root", str(self.dir)], out=out)
        self.assertEqual(code, 0)
        self.assertIn("ok (2 apps", out.getvalue())

    def test_render_with_options_after(self):
        out = io.StringIO()
        with redirect_stderr(io.StringIO()):
            code = deploy.main(["render", "--app", "ai-web", "--file", str(self.desired)], out=out, runner=self.no_tag)
        self.assertEqual(code, 0)
        self.assertIn("stack/web/compose.yaml", out.getvalue())

    def test_local_after_the_command(self):
        client = FakeClient(
            {"ai-inference": app_entry("ai-inference", "inference"), "ai-web": app_entry("ai-web", "web")}
        )
        with redirect_stderr(io.StringIO()):
            code = deploy.main(
                ["drift", "--file", str(self.desired), "--config", "/nonexistent", "--local"],
                out=io.StringIO(),
                client_factory=self.factory(client),
                runner=self.no_tag,
            )
        self.assertEqual(code, 0)
        self.assertEqual(self.uris, [None])


class TestConnection(Workspace):
    def test_plain_ws_is_refused(self):
        self.config.write_text(self.config.read_text().replace("wss://", "ws://"))
        client = FakeClient()
        code, _ = self.run_main(client, "plan")
        self.assertEqual(code, 2)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.uris, [])

    def test_key_readable_by_others_is_refused(self):
        (self.config.parent / "read.key").chmod(0o644)
        client = FakeClient()
        code, _ = self.run_main(client, "plan")
        self.assertEqual(code, 2)
        self.assertEqual(self.uris, [])

    def test_plan_logs_in_with_the_read_key(self):
        client = FakeClient(
            {"ai-inference": app_entry("ai-inference", "inference"), "ai-web": app_entry("ai-web", "web")}
        )
        code, _ = self.run_main(client, "plan")
        self.assertEqual(code, 0)
        method, params, _ = client.calls[0]
        self.assertEqual(method, "auth.login_ex")
        self.assertEqual(
            params[0], {"mechanism": "API_KEY_PLAIN", "username": "deploy-read", "api_key": "1-read-not-a-real-key"}
        )
        self.assertEqual(self.uris, ["wss://192.0.2.10:444/api/current"])
        self.assertTrue(client.closed)
        writes = [call for call in client.calls if call[0] in ("app.create", "app.update", "app.redeploy")]
        self.assertEqual(writes, [])

    def test_uri_is_used_as_written(self):
        # The port is the TrueNAS web interface's HTTPS port, whatever the reader set it to; deploy.py
        # adds, removes and checks no port.
        for uri in ("wss://192.0.2.10:9443/api/current", "wss://truenas.lab.example.com/api/current"):
            with self.subTest(uri=uri):
                self.config.write_text(self.config.read_text().replace(self.config_uri(), uri))
                self.uris = []
                client = FakeClient(
                    {"ai-inference": app_entry("ai-inference", "inference"), "ai-web": app_entry("ai-web", "web")}
                )
                code, _ = self.run_main(client, "plan")
                self.assertEqual(code, 0)
                self.assertEqual(self.uris, [uri])

    def config_uri(self):
        return self.config.read_text().split('uri = "', 1)[1].split('"', 1)[0]

    def test_connection_failure_names_the_port(self):
        def refuse(uri):
            self.uris.append(uri)
            raise ConnectionRefusedError("[Errno 111] Connection refused")

        with redirect_stderr(io.StringIO()) as err:
            code = deploy.main(
                ["--file", str(self.desired), "--config", str(self.config), "plan"],
                out=io.StringIO(),
                client_factory=refuse,
                runner=lambda command, **_kwargs: self.fake_runner(command, None),
            )
        self.assertEqual(code, 1)
        self.assertEqual(self.uris, ["wss://192.0.2.10:444/api/current"])
        message = err.getvalue()
        self.assertIn("cannot connect to the NAS: [Errno 111] Connection refused", message)
        self.assertIn("wss://192.0.2.10:444/api/current", message)
        self.assertIn("HTTPS port, System > General Settings > GUI", message)
        self.assertNotIn("not-a-real-key", message)

    def test_failed_login(self):
        client = FakeClient(login="AUTH_ERR")
        code, _ = self.run_main(client, "plan")
        self.assertEqual(code, 1)
        self.assertTrue(client.closed)

    def test_other_truenas_version_is_refused(self):
        client = FakeClient(version="27.0.0")
        code, _ = self.run_main(client, "plan")
        self.assertEqual(code, 2)
        self.assertNotIn("app.query", [call[0] for call in client.calls])

    def test_local_socket_needs_no_settings(self):
        client = FakeClient(
            {"ai-inference": app_entry("ai-inference", "inference"), "ai-web": app_entry("ai-web", "web")}
        )
        out = io.StringIO()
        code = deploy.main(
            ["--file", str(self.desired), "--config", "/nonexistent", "--local", "drift"],
            out=out,
            client_factory=self.factory(client),
            runner=lambda command, **_: self.fake_runner(command, None),
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.uris, [None])
        self.assertNotIn("auth.login_ex", [call[0] for call in client.calls])

    def test_ca_file_goes_to_the_websocket_library(self):
        ca = self.config.parent / "ca.pem"
        ca.write_text("-----BEGIN CERTIFICATE-----\n")
        self.config.write_text(self.config.read_text() + 'ca_file = "ca.pem"\n')
        client = FakeClient(
            {"ai-inference": app_entry("ai-inference", "inference"), "ai-web": app_entry("ai-web", "web")}
        )
        old = os.environ.pop("WEBSOCKET_CLIENT_CA_BUNDLE", None)
        try:
            self.run_main(client, "plan")
            self.assertEqual(os.environ.get("WEBSOCKET_CLIENT_CA_BUNDLE"), str(ca.resolve()))
        finally:
            os.environ.pop("WEBSOCKET_CLIENT_CA_BUNDLE", None)
            if old is not None:
                os.environ["WEBSOCKET_CLIENT_CA_BUNDLE"] = old


class TestPlanAndApply(Workspace):
    def test_plan_classifies_every_case(self):
        client = FakeClient(
            {
                "ai-web": app_entry("ai-web", "web", stored={"services": {"x": {}}}),
                "other-app": app_entry("other-app", "x"),
            }
        )
        code, text = self.run_main(client, "plan")
        self.assertEqual(code, 0)
        self.assertIn("ai-inference: create (-) not installed", text)
        self.assertIn("ai-web: update (RUNNING)", text)
        self.assertIn("+++ desired", text)
        self.assertIn("other-app: unmanaged", text)

    def test_images_of_another_release_mean_redeploy(self):
        client = FakeClient(
            {
                "ai-inference": app_entry(
                    "ai-inference", "inference", images=["x/y:1"], stored=wrapper_of("inference", files=FAKE_FILES_HASH)
                ),
                "ai-web": app_entry(
                    "ai-web",
                    "web",
                    images=["docker.io/" + WEB_IMAGES[1], "old/image:1"],
                    stored=wrapper_of("web", files=FAKE_FILES_HASH),
                ),
            }
        )
        code, text = self.run_main(client, "drift", images={"inference": ["x/y:1"], "web": WEB_IMAGES})
        self.assertEqual(code, 3)
        self.assertIn("ai-web: redeploy (RUNNING) runs images other than v1.0's", text)
        self.assertIn("ai-inference: none (RUNNING) in step", text)

    def test_image_without_digest_matches_by_tag(self):
        running = [WEB_IMAGES[0].split("@")[0], WEB_IMAGES[1]]
        client = FakeClient(
            {
                "ai-inference": app_entry(
                    "ai-inference", "inference", images=["x/y:1"], stored=wrapper_of("inference", files=FAKE_FILES_HASH)
                ),
                "ai-web": app_entry("ai-web", "web", images=running, stored=wrapper_of("web", files=FAKE_FILES_HASH)),
            }
        )
        code, text = self.run_main(client, "drift", images={"inference": ["x/y:1"], "web": WEB_IMAGES})
        self.assertEqual(code, 0, text)
        self.assertIn("drift: none", text)

    def test_crashed_is_redeployed_stopped_is_only_reported(self):
        client = FakeClient(
            {
                "ai-inference": app_entry("ai-inference", "inference", state="CRASHED"),
                "ai-web": app_entry("ai-web", "web", state="STOPPED"),
            }
        )
        code, text = self.run_main(client, "apply")
        self.assertIn("ai-inference: redeploy (CRASHED)", text)
        self.assertIn("STOPPED: not started by apply", text)
        self.assertIn(("app.redeploy", ("ai-inference",), True), client.calls)
        self.assertNotIn("app.start", [call[0] for call in client.calls])
        self.assertEqual(code, 1)  # ai-web is still STOPPED afterwards: drift remains

    def test_update_of_a_stopped_app_does_not_wait_for_it(self):
        client = FakeClient(
            {
                "ai-inference": app_entry("ai-inference", "inference"),
                "ai-web": app_entry("ai-web", "web", state="STOPPED", stored={"services": {}}),
            }
        )
        code, text = self.run_main(client, "apply")
        self.assertIn("ai-web: update (STOPPED)", text)
        self.assertIn("STOPPED: apply stores the new YAML and does not start the app", text)
        self.assertIn("ai-web: YAML stored; STOPPED, not started", text)
        self.assertNotIn(("app.query", ([["name", "=", "ai-web"]],), False), client.calls)
        self.assertEqual(client.apps["ai-web"]["stored"], wrapper_of("web"))
        self.assertEqual(code, 1)  # still STOPPED: drift remains

    def test_catalog_app_of_the_same_name_is_never_touched(self):
        client = FakeClient(
            {
                "ai-inference": app_entry("ai-inference", "inference", custom=False),
                "ai-web": app_entry("ai-web", "web"),
            }
        )
        code, text = self.run_main(client, "apply")
        self.assertIn("ai-inference: conflict", text)
        self.assertEqual([call for call in client.calls if call[0].startswith("app.") and call[2]], [])
        self.assertNotIn(("app.config", ("ai-inference",), False), client.calls)
        self.assertEqual(code, 1)

    def test_apply_creates_and_updates_with_the_apply_key(self):
        client = FakeClient({"ai-web": app_entry("ai-web", "web", stored={"services": {}})})
        code, text = self.run_main(client, "apply", "--timeout", "1")
        self.assertEqual(code, 0, text)
        self.assertEqual(client.calls[0][1][0]["username"], "deploy-apply")
        self.assertEqual(client.calls[0][1][0]["api_key"], "1-apply-not-a-real-key")
        create = [call for call in client.calls if call[0] == "app.create"]
        self.assertEqual(len(create), 1)
        self.assertEqual(
            create[0][1][0],
            {
                "custom_app": True,
                "app_name": "ai-inference",
                "custom_compose_config_string": "include:\n"
                "  - path: /mnt/tank/ai/stacks/local-agent-stack/stack/inference/compose.yaml\n"
                "    env_file: /mnt/tank/ai/secrets/inference.env\n"
                "services: {}\n",
            },
        )
        update = [call for call in client.calls if call[0] == "app.update"]
        self.assertEqual(update[0][1][0], "ai-web")
        self.assertEqual(set(update[0][1][1]), {"custom_compose_config_string"})
        self.assertEqual(client.apps["ai-web"]["stored"], wrapper_of("web"))
        self.assertIn("after apply:", text)

    def test_dry_run_writes_nothing(self):
        client = FakeClient({})
        code, text = self.run_main(client, "apply", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("ai-inference: create (dry run)", text)
        self.assertNotIn("app.create", [call[0] for call in client.calls])

    def test_apply_of_one_app(self):
        client = FakeClient({})
        code, _ = self.run_main(client, "apply", "--app", "ai-web")
        self.assertEqual(code, 0)
        self.assertEqual([call[1][0]["app_name"] for call in client.calls if call[0] == "app.create"], ["ai-web"])

    def test_wait_running_gives_up_on_crash(self):
        client = FakeClient({"ai-web": app_entry("ai-web", "web", state="CRASHED")})
        with self.assertRaises(deploy.DeployError):
            deploy.wait_running(deploy.Session(client), "ai-web", 30, clock=lambda: 0, sleep=lambda _: None)

    def test_wait_running_times_out(self):
        client = FakeClient({"ai-web": app_entry("ai-web", "web", state="DEPLOYING")})
        ticks = iter(range(0, 1000, 10))
        with self.assertRaises(deploy.DeployError) as caught:
            deploy.wait_running(deploy.Session(client), "ai-web", 30, clock=lambda: next(ticks), sleep=lambda _: None)
        self.assertIn("DEPLOYING", str(caught.exception))

    def test_status_lines(self):
        client = FakeClient({"ai-web": app_entry("ai-web", "web")})
        code, text = self.run_main(client, "status")
        self.assertEqual(code, 0)
        self.assertIn("ai-inference: state -, YAML missing, files -, env -, images -\n", text)
        self.assertIn(
            "ai-web: state RUNNING, YAML matches, files not compared, env not compared, images not compared\n", text
        )

    def test_status_lines_with_the_tag(self):
        client = FakeClient(
            {
                "ai-inference": app_entry("ai-inference", "inference", images=["x/y:1"]),
                "ai-web": app_entry(
                    "ai-web", "web", images=WEB_IMAGES, stored=wrapper_of("web", files=FAKE_FILES_HASH)
                ),
            }
        )
        code, text = self.run_main(client, "status", images={"inference": ["x/y:2"], "web": WEB_IMAGES})
        self.assertEqual(code, 0)
        self.assertIn(
            "ai-inference: state RUNNING, YAML matches, files not recorded, env not compared, images differ", text
        )
        self.assertIn("ai-web: state RUNNING, YAML matches, files match, env not compared, images match", text)


class TestContentHashes(Workspace):
    """Changes to the files an app mounts and to its env file show as an update."""

    COMPOSE = textwrap.dedent(
        """\
        services:
          a:
            image: x
            volumes:
              - ./conf/a.yaml:/a.yaml:ro  # not ./this-one.txt
              - "./dir:/d:ro"
              - type: bind
                source: ./single.txt
                target: /s
              - ./gone.txt:/g:ro
          b:
            build:
              context: ./ctx
              dockerfile: ./ctx/Dockerfile
        # - ./commented.txt:/c
        """
    )

    def stack_folder(self):
        base = self.dir / "hashed"
        for name, text in {
            "compose.yaml": self.COMPOSE,
            "conf/a.yaml": "A",
            "dir/x": "X",
            "dir/sub/y": "Y",
            "ctx/Dockerfile": "FROM x",
            "single.txt": "S",
            "README.md": "R",
            "commented.txt": "C",
            "this-one.txt": "T",
        }.items():
            (base / name).parent.mkdir(parents=True, exist_ok=True)
            (base / name).write_text(text)
        return base

    def test_compose_sources_skip_build_inputs_and_comments(self):
        self.assertEqual(deploy.compose_sources(self.COMPOSE), ["conf/a.yaml", "dir", "gone.txt", "single.txt"])

    def test_files_hash_is_the_documented_manifest(self):
        base = self.stack_folder()
        manifest = (
            f"{sha(self.COMPOSE.encode())}  compose.yaml\n"
            f"{sha(b'A')}  conf/a.yaml\n"
            f"{sha(b'Y')}  dir/sub/y\n"
            f"{sha(b'X')}  dir/x\n"
            "missing  gone.txt\n"
            f"{sha(b'S')}  single.txt\n"
        )
        self.assertEqual(deploy.stack_files_hash(base), "sha256:" + sha(manifest.encode()))

    def test_files_hash_follows_mounted_files_only(self):
        base = self.stack_folder()
        before = deploy.stack_files_hash(base)
        for name in ("README.md", "ctx/Dockerfile", "commented.txt", "this-one.txt"):
            (base / name).write_text("changed")
        self.assertEqual(deploy.stack_files_hash(base), before)
        (base / "dir" / "sub" / "y").write_text("changed")
        self.assertNotEqual(deploy.stack_files_hash(base), before)

    def test_files_hash_without_docker(self):
        release = deploy.release_content(
            self.dir, "v1.0", "web", lambda command, **_: self.fake_runner(command, {}, docker=False)
        )
        self.assertEqual(release.files, FAKE_FILES_HASH)
        self.assertIsNone(release.images)
        self.assertIn("cannot run docker", release.images_why)

    def test_changed_config_file_is_an_update(self):
        self.tars["web"] = {"compose.yaml": b"services:\n  s:\n    volumes:\n      - ./c.yaml:/c\n", "c.yaml": b"new"}
        client = FakeClient(
            {
                "ai-inference": app_entry(
                    "ai-inference", "inference", stored=wrapper_of("inference", files=FAKE_FILES_HASH)
                ),
                "ai-web": app_entry("ai-web", "web", stored=wrapper_of("web", files=FAKE_FILES_HASH)),
            }
        )
        code, text = self.run_main(client, "apply", images={})
        self.assertIn("ai-inference: none (RUNNING) in step", text)
        self.assertIn("ai-web: update (RUNNING) the files of stack/web/ in v1.0 differ from the last apply", text)
        self.assertEqual(code, 0, text)
        recorded = client.apps["ai-web"]["stored"]["x-local-agent-stack"]["files"]
        self.assertNotEqual(recorded, FAKE_FILES_HASH)
        self.assertRegex(recorded, r"^sha256:[0-9a-f]{64}$")

    def test_hash_not_recorded_is_an_update_once(self):
        client = FakeClient(
            {"ai-inference": app_entry("ai-inference", "inference"), "ai-web": app_entry("ai-web", "web")}
        )
        code, text = self.run_main(client, "plan", images={})
        self.assertIn("ai-web: update (RUNNING) no hash of the files of stack/web/ recorded", text)
        code, text = self.run_main(client, "apply", images={})
        self.assertEqual(code, 0, text)
        code, text = self.run_main(client, "drift", images={})
        self.assertEqual(code, 0, text)

    def test_files_not_compared_keep_what_the_nas_recorded(self):
        stored = wrapper_of("web", files="sha256:" + "1" * 64)
        client = FakeClient(
            {
                "ai-inference": app_entry("ai-inference", "inference"),
                "ai-web": app_entry("ai-web", "web", stored=stored),
            }
        )
        code, text = self.run_main(client, "drift")  # the tag is not in this clone
        self.assertEqual(code, 0, text)
        self.assertIn("note: files not compared: tag v1.0 is not in this clone", text)

    def write_env_desired(self, env_dir=None, secrets_dir=None):
        text = DESIRED
        if secrets_dir is not None:
            text = text.replace('secrets_dir = "/mnt/tank/ai/secrets"', f'secrets_dir = "{secrets_dir}"')
        if env_dir is not None:
            text = text.replace("schema = 1\n", f'schema = 1\nenv_dir = "{env_dir}"\n')
        self.desired.write_text(text)

    def test_changed_env_file_is_an_update_and_never_printed(self):
        envs = self.dir / "envs"
        envs.mkdir()
        web_env = f"WEBUI_SECRET_KEY={SECRET}\n".encode()
        (envs / "web.env").write_bytes(web_env)
        (envs / "inference.env").write_text("LITELLM_MASTER_KEY=sk-local-example\n")
        self.write_env_desired(env_dir=str(envs))
        inference_env = "sha256:" + sha(b"LITELLM_MASTER_KEY=sk-local-example\n")
        client = FakeClient(
            {
                "ai-inference": app_entry(
                    "ai-inference", "inference", stored=wrapper_of("inference", env=inference_env)
                ),
                "ai-web": app_entry("ai-web", "web", stored=wrapper_of("web", env="sha256:" + "2" * 64)),
            }
        )
        code, text = self.run_main(client, "apply")
        self.assertIn("ai-inference: none (RUNNING) in step", text)
        self.assertIn("ai-web: update (RUNNING) its env file differs from the one hashed at the last apply", text)
        self.assertEqual(code, 0, text)
        update = [call for call in client.calls if call[0] == "app.update"][0][1][1]["custom_compose_config_string"]
        self.assertIn(f"  env: sha256:{sha(web_env)}\n", update)
        for shown in (text, self.stderr, update, json.dumps(client.calls)):
            self.assertNotIn(SECRET, shown)

    def test_env_hash_not_recorded_is_an_update(self):
        envs = self.dir / "envs"
        envs.mkdir()
        for stack in ("inference", "web"):
            (envs / f"{stack}.env").write_text("A=1\n")
        self.write_env_desired(env_dir=str(envs))
        client = FakeClient(
            {"ai-inference": app_entry("ai-inference", "inference"), "ai-web": app_entry("ai-web", "web")}
        )
        code, text = self.run_main(client, "status")
        self.assertIn(
            "ai-web: state RUNNING, YAML matches, files not compared, env not recorded, images not compared", text
        )
        code, text = self.run_main(client, "drift")
        self.assertEqual(code, 3)
        self.assertIn("ai-web: update (RUNNING) no hash of its env file recorded", text)

    def test_unreadable_env_copy_keeps_the_recorded_hash(self):
        self.write_env_desired(env_dir="~/las-test-nonexistent/secrets")
        recorded = "sha256:" + "3" * 64
        client = FakeClient(
            {
                "ai-inference": app_entry("ai-inference", "inference", stored=wrapper_of("inference", env=recorded)),
                "ai-web": app_entry("ai-web", "web", stored=wrapper_of("web", env=recorded)),
            }
        )
        code, text = self.run_main(client, "drift")
        self.assertEqual(code, 0, text)
        self.assertIn("note: env file not compared: cannot read ~/las-test-nonexistent/secrets/web.env", text)
        self.assertNotIn(str(Path.home()), text)

    def test_local_reads_the_env_files_in_secrets_dir(self):
        secrets = self.dir / "secrets"
        secrets.mkdir()
        (secrets / "inference.env").write_text("A=1\n")
        self.write_env_desired(env_dir="~/las-test-nonexistent", secrets_dir=str(secrets))
        desired = deploy.load_desired(self.desired, self.dir)
        stored = desired.wrapper_config(desired.apps[0], {"env": "sha256:" + sha(b"A=1\n")})
        client = FakeClient({"ai-inference": app_entry("ai-inference", "inference", stored=stored)})
        out = io.StringIO()
        with redirect_stderr(io.StringIO()):
            code = deploy.main(
                ["--file", str(self.desired), "status", "--local"],
                out=out,
                client_factory=self.factory(client),
                runner=self.no_tag,
            )
        self.assertEqual(code, 0)
        self.assertIn("ai-inference: state RUNNING, YAML matches, files not compared, env match", out.getvalue())


class TestOverrides(Workspace):
    def setUp(self):
        super().setUp()
        self.desired.write_text(DESIRED.replace('stack = "web"\n', f'stack = "web"\noverrides = ["{WEB_OVERRIDE}"]\n'))

    def test_render_lists_the_release_file_then_the_overrides(self):
        out = io.StringIO()
        with redirect_stderr(io.StringIO()):
            code = deploy.main(["render", "--app", "ai-web", "--file", str(self.desired)], out=out, runner=self.no_tag)
        self.assertEqual(code, 0)
        self.assertEqual(
            out.getvalue(),
            "# ai-web\n"
            "include:\n"
            "  - path:\n"
            "      - /mnt/tank/ai/stacks/local-agent-stack/stack/web/compose.yaml\n"
            f"      - {WEB_OVERRIDE}\n"
            "    env_file: /mnt/tank/ai/secrets/web.env\n"
            "services: {}\n",
        )

    def test_the_internal_ca_shape_of_appendix_d(self):
        desired = deploy.load_desired(deploy.DEFAULT_FILE, check_files=False)
        edge = deploy.App("ai-edge", "edge", (EDGE_OVERRIDE,))
        self.assertEqual(
            desired.wrapper(edge),
            "include:\n"
            "  - path:\n"
            "      - /mnt/tank/ai/stacks/local-agent-stack/stack/edge/compose.yaml\n"
            "      - /mnt/tank/ai/appdata/caddy/internal-ca.override.yaml\n"
            "    env_file: /mnt/tank/ai/secrets/edge.env\n"
            "services: {}\n",
        )

    def test_plan_shows_the_overrides_and_keeps_them(self):
        client = FakeClient(
            {
                "ai-inference": app_entry("ai-inference", "inference"),
                "ai-web": app_entry("ai-web", "web", stored=wrapper_of("web", (WEB_OVERRIDE,))),
            }
        )
        code, text = self.run_main(client, "drift")
        self.assertEqual(code, 0, text)
        self.assertIn(f"ai-web: none (RUNNING) in step\n    override: {WEB_OVERRIDE}\n", text)

    def test_apply_adds_a_missing_override(self):
        client = FakeClient(
            {"ai-inference": app_entry("ai-inference", "inference"), "ai-web": app_entry("ai-web", "web")}
        )
        code, text = self.run_main(client, "apply")
        self.assertEqual(code, 0, text)
        self.assertIn("ai-web: update (RUNNING) its YAML differs from the include wrapper", text)
        self.assertEqual(client.apps["ai-web"]["stored"], wrapper_of("web", (WEB_OVERRIDE,)))

    def test_apply_never_drops_an_override_it_knows(self):
        client = FakeClient(
            {
                "ai-inference": app_entry("ai-inference", "inference"),
                "ai-web": app_entry("ai-web", "web", state="CRASHED", stored=wrapper_of("web", (WEB_OVERRIDE,))),
            }
        )
        code, text = self.run_main(client, "apply")
        self.assertEqual(code, 0, text)
        self.assertNotIn("app.update", [call[0] for call in client.calls])
        self.assertEqual(client.apps["ai-web"]["stored"], wrapper_of("web", (WEB_OVERRIDE,)))


class TestWithoutHashes(Workspace):
    """content_hashes = false (or --no-hashes): the bare include wrapper, YAML and images compared only."""

    BARE = (
        "include:\n"
        "  - path: /mnt/tank/ai/stacks/local-agent-stack/stack/{stack}/compose.yaml\n"
        "    env_file: /mnt/tank/ai/secrets/{stack}.env\n"
        "services: {{}}\n"
    )

    def setUp(self):
        super().setUp()
        # Everything a run with the hashes on would see as changed: env copies that differ from what
        # the NAS recorded, and release files other than the recorded ones.
        envs = self.dir / "envs"
        envs.mkdir()
        for stack in ("inference", "web"):
            (envs / f"{stack}.env").write_text(f"KEY={SECRET}\n")
        self.tars["web"] = {"compose.yaml": b"services:\n  s:\n    volumes:\n      - ./c.yaml:/c\n", "c.yaml": b"new"}
        self.write(content_hashes="false", env_dir=str(envs))

    def write(self, content_hashes=None, env_dir=None, overrides=False):
        text = DESIRED
        if content_hashes is not None:
            text = text.replace("schema = 1\n", f"schema = 1\ncontent_hashes = {content_hashes}\n")
        if env_dir is not None:
            text = text.replace("schema = 1\n", f'schema = 1\nenv_dir = "{env_dir}"\n')
        if overrides:
            text = text.replace('stack = "web"\n', f'stack = "web"\noverrides = ["{WEB_OVERRIDE}"]\n')
        self.desired.write_text(text)

    def in_step(self, **stored):
        """Both apps installed with the bare wrapper (or the given stored YAML) and the release's images."""
        return FakeClient(
            {
                "ai-inference": app_entry(
                    "ai-inference", "inference", images=["x/y:1"], stored=stored.get("inference")
                ),
                "ai-web": app_entry("ai-web", "web", images=WEB_IMAGES, stored=stored.get("web")),
            }
        )

    IMAGES = {"inference": ["x/y:1"], "web": WEB_IMAGES}

    def test_render_is_the_bare_wrapper_and_reads_nothing(self):
        def runner(command, **_kwargs):
            raise AssertionError(f"render without hashes ran {command}")

        out = io.StringIO()
        with redirect_stderr(io.StringIO()) as err:
            code = deploy.main(["--file", str(self.desired), "render"], out=out, runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(
            out.getvalue(),
            "# ai-inference\n" + self.BARE.format(stack="inference") + "# ai-web\n" + self.BARE.format(stack="web"),
        )
        self.assertEqual(err.getvalue(), "")

    def test_no_hashes_option_overrides_the_file(self):
        self.write(env_dir=str(self.dir / "envs"))  # content_hashes left at its default, true
        for argv in (["--no-hashes", "render", "--app", "ai-web"], ["render", "--app", "ai-web", "--no-hashes"]):
            with self.subTest(argv=argv):
                out = io.StringIO()
                with redirect_stderr(io.StringIO()):
                    code = deploy.main(["--file", str(self.desired), *argv], out=out, runner=self.with_tag)
                self.assertEqual(code, 0)
                self.assertEqual(out.getvalue(), "# ai-web\n" + self.BARE.format(stack="web"))
        code, text = self.run_main(self.in_step(), "drift", "--no-hashes", images=self.IMAGES)
        self.assertEqual(code, 0, text)

    def test_render_keeps_the_overrides(self):
        self.write(content_hashes="false", overrides=True)
        out = io.StringIO()
        code = deploy.main(["--file", str(self.desired), "render", "--app", "ai-web"], out=out, runner=self.with_tag)
        self.assertEqual(code, 0)
        self.assertEqual(
            out.getvalue(),
            "# ai-web\n"
            "include:\n"
            "  - path:\n"
            "      - /mnt/tank/ai/stacks/local-agent-stack/stack/web/compose.yaml\n"
            f"      - {WEB_OVERRIDE}\n"
            "    env_file: /mnt/tank/ai/secrets/web.env\n"
            "services: {}\n",
        )

    def test_drift_compares_yaml_and_images_only_and_says_so_once(self):
        with mock.patch.object(deploy, "env_hash", side_effect=AssertionError("an env file was read")):
            code, text = self.run_main(self.in_step(), "drift", images=self.IMAGES)
        self.assertEqual(code, 0, text)
        self.assertIn("ai-inference: none (RUNNING) in step\n", text)
        self.assertIn("ai-web: none (RUNNING) in step\n", text)
        self.assertEqual(text.count(deploy.HASHES_OFF_NOTE), 1)
        self.assertTrue(text.startswith(f"TrueNAS 25.10.8; desired release v1.0\nnote: {deploy.HASHES_OFF_NOTE}\n"))
        self.assertNotIn("files not", text)
        self.assertNotIn("env file not", text)
        self.assertTrue(text.endswith("drift: none\n"))

    def test_status_shows_no_files_or_env(self):
        code, text = self.run_main(self.in_step(), "status", images=self.IMAGES)
        self.assertEqual(code, 0)
        self.assertEqual(text.count(deploy.HASHES_OFF_NOTE), 1)
        self.assertIn("ai-inference: state RUNNING, YAML matches, files -, env -, images match\n", text)
        self.assertIn("ai-web: state RUNNING, YAML matches, files -, env -, images match\n", text)

    def test_images_are_still_compared(self):
        images = {"inference": ["x/y:2"], "web": WEB_IMAGES}
        code, text = self.run_main(self.in_step(), "drift", images=images)
        self.assertEqual(code, 3)
        self.assertIn("ai-inference: redeploy (RUNNING) runs images other than v1.0's; wanted: x/y:2", text)
        code, text = self.run_main(self.in_step(), "drift")  # the tag is not in this clone
        self.assertEqual(code, 0, text)
        self.assertIn("note: images not compared: tag v1.0 is not in this clone", text)
        self.assertNotIn("files not compared", text)

    def test_apply_creates_with_the_bare_wrapper(self):
        client = FakeClient({"ai-web": app_entry("ai-web", "web", images=WEB_IMAGES)})
        # The fake app.create starts no containers: a release without images for inference matches.
        code, text = self.run_main(client, "apply", images={"inference": [], "web": WEB_IMAGES})
        self.assertEqual(code, 0, text)
        create = [call for call in client.calls if call[0] == "app.create"]
        self.assertEqual(
            create[0][1][0],
            {
                "custom_app": True,
                "app_name": "ai-inference",
                "custom_compose_config_string": self.BARE.format(stack="inference"),
            },
        )
        self.assertNotIn("app.update", [call[0] for call in client.calls])
        self.assertEqual(text.count(deploy.HASHES_OFF_NOTE), 1)  # plan and the plan after apply: once
        self.assertIn("after apply:", text)
        for shown in (text, self.stderr, json.dumps(client.calls)):
            self.assertNotIn(SECRET, shown)

    def test_recorded_hashes_are_removed_once(self):
        stored = {
            "inference": wrapper_of("inference"),
            "web": wrapper_of("web", files="sha256:" + "1" * 64, env="sha256:" + "2" * 64),
        }
        client = self.in_step(**stored)
        code, text = self.run_main(client, "status", images=self.IMAGES)
        self.assertIn("ai-web: state RUNNING, YAML differs, files -, env -, images match\n", text)
        code, text = self.run_main(client, "apply", images=self.IMAGES)
        self.assertEqual(code, 0, text)
        self.assertIn(
            "ai-web: update (RUNNING) its YAML carries an x-local-agent-stack block, which apply removes while "
            "content hashes are off",
            text,
        )
        self.assertIn("ai-inference: none (RUNNING) in step", text)
        update = [call for call in client.calls if call[0] == "app.update"]
        self.assertEqual([call[1][0] for call in update], ["ai-web"])
        self.assertEqual(update[0][1][1]["custom_compose_config_string"], self.BARE.format(stack="web"))
        self.assertEqual(client.apps["ai-web"]["stored"], wrapper_of("web"))
        code, text = self.run_main(client, "drift", images=self.IMAGES)
        self.assertEqual(code, 0, text)

    def test_turning_the_hashes_back_on_records_them(self):
        client = self.in_step()
        self.write(content_hashes="true", env_dir=str(self.dir / "envs"))
        code, text = self.run_main(client, "drift", images=self.IMAGES)
        self.assertEqual(code, 3)
        self.assertIn("ai-web: update (RUNNING) no hash of the files of stack/web/ recorded", text)
        self.assertNotIn(deploy.HASHES_OFF_NOTE, text)
        code, text = self.run_main(client, "apply", images=self.IMAGES)
        self.assertEqual(code, 0, text)
        self.assertEqual(set(client.apps["ai-web"]["stored"]["x-local-agent-stack"]), {"files", "env"})

    def test_drift_issue_carries_the_note(self):
        desired = deploy.load_desired(self.desired, self.dir)
        apps = [deploy.AppPlan("ai-web", "redeploy", "RUNNING", ["runs images other than v1.0's"], [], [])]
        body = deploy.issue_body(deploy.Plan("25.10.8", apps, [], hashes=False), desired)
        self.assertIn(f"Note: {deploy.HASHES_OFF_NOTE}.", body)
        self.assertNotIn("Note:", deploy.issue_body(deploy.Plan("25.10.8", apps, []), desired))


class TestTrueNASAppFiles(unittest.TestCase):
    """stack/<stack>/truenas-app.yaml is what the guide installs by hand: exactly what deploy.py
    renders for the repository's desired state, minus the content hashes."""

    def setUp(self):
        self.desired = deploy.load_desired(deploy.DEFAULT_FILE, check_files=False)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # The repository's desired state without env_dir, so that no test reads this machine's env files.
        text = deploy.DEFAULT_FILE.read_text(encoding="utf-8")
        self.file = Path(tmp.name) / "truenas.toml"
        self.file.write_text("".join(line for line in text.splitlines(True) if not line.startswith("env_dir")))

    def test_files_equal_the_rendered_wrapper(self):
        for app in self.desired.apps:
            with self.subTest(app=app.name):
                text = (REPO / "stack" / app.stack / "truenas-app.yaml").read_text(encoding="utf-8")
                self.assertEqual(text, self.desired.wrapper(app))

    def test_render_with_hashes_equals_the_files_without_them(self):
        def runner(command, **_kwargs):
            if "rev-parse" in command:
                return subprocess.CompletedProcess(command, 0, b"", b"")
            if "archive" in command:
                return subprocess.CompletedProcess(command, 0, make_tar(command[-1].split("/")[1]), b"")
            return subprocess.CompletedProcess(command, 0, b"x/y:1\n", b"")

        for app in self.desired.apps:
            with self.subTest(app=app.name):
                out = io.StringIO()
                with redirect_stderr(io.StringIO()):
                    code = deploy.main(["render", "--app", app.name, "--file", str(self.file)], out=out, runner=runner)
                self.assertEqual(code, 0)
                rendered = out.getvalue()
                self.assertIn(f"\nx-local-agent-stack:\n  files: {FAKE_FILES_HASH}\n", rendered)
                text = (REPO / "stack" / app.stack / "truenas-app.yaml").read_text(encoding="utf-8")
                self.assertEqual(strip_extension(rendered), f"# {app.name}\n{text}")

    def test_render_without_hashes_is_the_file_byte_for_byte(self):
        for app in self.desired.apps:
            with self.subTest(app=app.name):
                out = io.StringIO()
                code = deploy.main(
                    ["render", "--app", app.name, "--no-hashes", "--file", str(self.file)],
                    out=out,
                    runner=lambda command, **_: self.fail(f"ran {command}"),
                )
                self.assertEqual(code, 0)
                text = (REPO / "stack" / app.stack / "truenas-app.yaml").read_text(encoding="utf-8")
                self.assertEqual(out.getvalue(), f"# {app.name}\n{text}")

    @unittest.skipIf(yaml is None, "PyYAML is not installed")
    def test_wrapper_parses_to_wrapper_config(self):
        content = {"files": "sha256:" + "a" * 64, "env": "sha256:" + "b" * 64}
        for app in (deploy.App("ai-web", "web"), deploy.App("ai-edge", "edge", (EDGE_OVERRIDE, WEB_OVERRIDE))):
            for hashes in ({}, content):
                with self.subTest(app=app.name, hashes=bool(hashes)):
                    text = self.desired.wrapper(app, hashes)
                    self.assertEqual(yaml.safe_load(text), self.desired.wrapper_config(app, hashes))
                    self.assertEqual(parse_wrapper(text), self.desired.wrapper_config(app, hashes))


class TestDriftIssue(Workspace):
    def plan(self, drift):
        desired = deploy.load_desired(self.desired, self.dir)
        apps = [
            deploy.AppPlan("ai-inference", "none", "RUNNING", [], [], []),
            deploy.AppPlan("ai-web", "update" if drift else "none", "RUNNING", ["its YAML differs"], [], []),
        ]
        return desired, deploy.Plan("25.10.8", apps, [])

    def test_drift_opens_one_issue(self):
        desired, plan = self.plan(True)
        calls = []

        def gh(arguments):
            calls.append(arguments)
            return "[]" if arguments[1] == "list" else ""

        deploy.sync_issue(plan, desired, io.StringIO(), gh)
        self.assertEqual(calls[1][:2], ["issue", "create"])
        body = calls[1][calls[1].index("--body") + 1]
        self.assertIn("| ai-web | update | RUNNING |", body)
        self.assertNotIn("ai-inference", body)
        self.assertNotIn("192.0.2.10", body)

    def test_drift_updates_the_open_issue(self):
        desired, plan = self.plan(True)
        calls = []

        def gh(arguments):
            calls.append(arguments)
            return json.dumps([{"number": 7, "title": deploy.ISSUE_TITLE}]) if arguments[1] == "list" else ""

        deploy.sync_issue(plan, desired, io.StringIO(), gh)
        self.assertEqual(calls[1][:3], ["issue", "edit", "7"])

    def test_no_drift_closes_it(self):
        desired, plan = self.plan(False)
        calls = []

        def gh(arguments):
            calls.append(arguments)
            return json.dumps([{"number": 7, "title": deploy.ISSUE_TITLE}]) if arguments[1] == "list" else ""

        deploy.sync_issue(plan, desired, io.StringIO(), gh)
        self.assertEqual(calls[1][:3], ["issue", "close", "7"])


if __name__ == "__main__":
    unittest.main()
