"""Unit tests of tools/deploy.py with a fake TrueNAS client (no network, no NAS)."""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent


def load(name):
    """tools/<name>.py as the module las_<name> (tools/ is not a package; secrets.py would shadow
    the standard library's secrets under its own name)."""
    spec = importlib.util.spec_from_file_location(f"las_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


deploy = load("deploy")

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
    assert lines[0] == "include:" and lines[3] == "services: {}", text
    return {
        "include": [{"path": lines[1].split(": ", 1)[1], "env_file": lines[2].split(": ", 1)[1]}],
        "services": {},
    }


def wrapper_of(stack):
    return {
        "include": [
            {
                "path": f"/mnt/tank/ai/stacks/local-agent-stack/stack/{stack}/compose.yaml",
                "env_file": f"/mnt/tank/ai/secrets/{stack}.env",
            }
        ],
        "services": {},
    }


def app_entry(name, stack, state="RUNNING", stored=None, images=(), custom=True):
    return {
        "name": name,
        "id": name,
        "state": state,
        "custom_app": custom,
        "stored": wrapper_of(stack) if stored is None else stored,
        "active_workloads": {"images": list(images)},
    }


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
            'uri = "wss://192.0.2.10/api/current"\n'
            'read_user = "deploy-read"\nread_key_file = "read.key"\n'
            'apply_user = "deploy-apply"\napply_key_file = "apply.key"\n'
        )
        for role in ("read", "apply"):
            key = self.config.parent / f"{role}.key"
            key.write_text(f"1-{role}-not-a-real-key\n")
            key.chmod(0o600)
        self.uris = []

    def factory(self, client):
        def make(uri):
            self.uris.append(uri)
            return client

        return make

    def run_main(self, client, *argv, images=None):
        out = io.StringIO()

        def runner(command, **_kwargs):
            return self.fake_runner(command, images)

        code = deploy.main(
            ["--file", str(self.desired), "--config", str(self.config), *argv],
            out=out,
            client_factory=self.factory(client),
            runner=runner,
        )
        return code, out.getvalue()

    def fake_runner(self, command, images):
        """git rev-parse/archive and docker compose config --images, as the release has them."""
        images = images or {}
        if command[:1] == ["git"] and "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0 if images else 1, b"", b"")
        if command[:1] == ["git"] and "archive" in command:
            stack = command[-1].split("/")[1]
            return subprocess.CompletedProcess(command, 0, make_tar(stack), b"")
        if command[:2] == ["docker", "compose"]:
            stack = Path(command[command.index("-f") + 1]).parent.name
            listed = "\n".join(images.get(stack, [])) + "\n"
            return subprocess.CompletedProcess(command, 0, listed.encode(), b"")
        raise AssertionError(command)


def make_tar(stack):
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as bundle:
        for name, text in (
            (f"stack/{stack}/compose.yaml", b"services: {}\n"),
            (f"stack/{stack}/{stack}.env.example", b""),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(text)
            bundle.addfile(info, io.BytesIO(text))
    return buffer.getvalue()


class TestDesiredState(Workspace):
    def test_valid_file_loads_in_order(self):
        desired = deploy.load_desired(self.desired, self.dir)
        self.assertEqual([app.name for app in desired.apps], ["ai-inference", "ai-web"])
        self.assertEqual(desired.release, "v1.0")

    def test_repository_file_is_valid(self):
        desired = deploy.load_desired(deploy.DEFAULT_FILE, deploy.ROOT, check_files=False)
        self.assertEqual(
            [(app.name, app.stack) for app in desired.apps],
            [("ai-inference", "inference"), ("ai-rag", "rag"), ("ai-web", "web"), ("ai-edge", "edge")],
        )

    def test_problems_are_all_reported(self):
        self.desired.write_text(
            'schema = 2\nrelease = "1.0"\ntruenas_version = "x"\nstacks_dir = "relative"\n'
            'secrets_dir = "/mnt/tank/ai/secrets"\nextra = 1\n'
            '[apps.Bad_Name]\nstack = "inference"\n[apps.ai-two]\nstack = "inference"\ncolour = "red"\n'
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
            "app name 'Bad_Name'",
            "unknown key 'colour'",
            "is also apps.Bad_Name.stack",
        ):
            self.assertIn(part, message)

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
        code = deploy.main(["--file", str(self.desired), "render", "--app", "ai-web"], out=out)
        self.assertEqual(code, 0)
        self.assertEqual(
            out.getvalue(),
            "# ai-web\n"
            "include:\n"
            "  - path: /mnt/tank/ai/stacks/local-agent-stack/stack/web/compose.yaml\n"
            "    env_file: /mnt/tank/ai/secrets/web.env\n"
            "services: {}\n",
        )

    def test_render_unknown_app(self):
        code = deploy.main(["--file", str(self.desired), "render", "--app", "nope"], out=io.StringIO())
        self.assertEqual(code, 2)


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
        self.assertEqual(self.uris, ["wss://192.0.2.10/api/current"])
        self.assertTrue(client.closed)
        writes = [call for call in client.calls if call[0] in ("app.create", "app.update", "app.redeploy")]
        self.assertEqual(writes, [])

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
                "ai-inference": app_entry("ai-inference", "inference", images=["x/y:1"]),
                "ai-web": app_entry("ai-web", "web", images=["docker.io/" + WEB_IMAGES[1], "old/image:1"]),
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
                "ai-inference": app_entry("ai-inference", "inference", images=["x/y:1"]),
                "ai-web": app_entry("ai-web", "web", images=running),
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
        self.assertIn("ai-inference: state -, YAML missing", text)
        self.assertIn("ai-web: state RUNNING, YAML matches, images not compared", text)


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
