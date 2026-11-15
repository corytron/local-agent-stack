#!/usr/bin/env python3
"""Make the TrueNAS SCALE server run what deploy/truenas.toml says, and show where it differs.

  deploy.py validate                   check deploy/truenas.toml and the stack files it names (offline)
  deploy.py render [--app NAME]        print each app's TrueNAS YAML (the include wrapper)
  deploy.py plan [--app NAME...]       what apply would do, per app (read-only key)
  deploy.py apply [--app NAME...]      create, update or redeploy the apps (full-admin key)
                  [--dry-run] [--timeout SECONDS]
  deploy.py drift [--app NAME...]      exit 3 when the NAS differs from the desired state
                  [--issue]            ... and keep one open GitHub issue labelled `deploy` (gh)
  deploy.py status                     one line per app: state, configuration, images

Common options: --file (default deploy/truenas.toml), --config (default
~/.config/local-agent-stack/truenas.toml), --local (on the NAS itself, as root: the local
middleware socket, no key).

What runs where (owner, 2026-11-15): nothing of this stack runs on the workstation full time (no
timers, no daemons), so drift is an on-demand command: run it by hand or by an agent, and after
every apply. A scheduled check, if wanted, is a TrueNAS cron job on the NAS: System > Advanced
Settings > Cron Jobs > Add (card and form labels checked in truenas/webui at TS-25.10.8:
Description, Command, Run As User, Schedule, Hide Standard Output, Hide Standard Error, Enabled),
Run As User root, Command
  python3 /mnt/tank/ai/stacks/local-agent-stack/tools/deploy.py drift --local
--local talks to the local middleware socket and needs no key (UNVERIFIED: that the NAS's system
Python can import truenas_api_client, which midclt uses, and has git for the image comparison;
without git the images are reported as not compared). Exit 3 marks drift; that TrueNAS mails a
cron job's output to root unless Hide Standard Output/Error is set is assumed, not verified.

The desired state (deploy/truenas.toml, read with tomllib): schema, release (the tag the NAS clone
is at), truenas_version, stacks_dir, secrets_dir, and [apps.<name>] tables with `stack = "<dir>"`.
Each app is a TrueNAS custom app whose YAML is exactly the include wrapper of
docs/stack-design.md, section 4:

  include:
    - path: <stacks_dir>/stack/<stack>/compose.yaml
      env_file: <secrets_dir>/<stack>.env
  services: {}

The workstation's connection settings (~/.config/local-agent-stack/truenas.toml, mode 0600, never
in the repository):

  uri = "wss://192.0.2.10/api/current"      # wss:// only: a key sent over ws:// is revoked
  read_user = "deploy-read"                 # a user whose group's privilege is READONLY_ADMIN
  read_key_file = "truenas-read.key"        # relative to the config file's folder, mode 0600
  apply_user = "deploy-apply"               # a user whose group's privilege is FULL_ADMIN
  apply_key_file = "truenas-apply.key"
  ca_file = "truenas-ca.pem"                # optional: the CA that signed the NAS's certificate

plan, drift and status log in with the read key; only apply loads the full-admin key (25.10 has
no smaller predefined role that may write apps: docs/research/f-project-tooling.md, section 2).

Middleware calls (checked against truenas/middleware at tag TS-25.10.8, API v25_10_5, and
truenas/api_client at tag TS-25.10.8; see "Verified" below):
  auth.login_ex {"mechanism": "API_KEY_PLAIN", "username", "api_key"} -> response_type SUCCESS
  system.info -> {"version": ...}       (version is system.version_short)
  app.query [filters] {options} -> name, state, custom_app, active_workloads.images (each
            container's Config.Image); queried without extra.retrieve_config, so no other app's
            configuration (and none of its secrets) is fetched
  app.config <name> -> the stored compose for a custom app (the parsed YAML apply sent)
  app.create {"custom_app": true, "app_name", "custom_compose_config_string"}   (job)
  app.update <name> {"custom_compose_config_string"}                           (job)
  app.redeploy <name>                                                           (job)
Client: truenas_api_client.Client(uri, verify_ssl=True); call(method, *params, job=True) waits for
a job. Install it on the workstation in a virtual environment:
  python3 -m venv ~/.local/share/local-agent-stack/deploy-venv
  ~/.local/share/local-agent-stack/deploy-venv/bin/pip install \\
      'git+https://github.com/truenas/api_client.git@TS-25.10.8'
and run deploy.py with that venv's python. The CA file is passed to the websocket library through
WEBSOCKET_CLIENT_CA_BUNDLE (websocket-client reads it when no CA is given in code).

What plan decides, per app (apply never deletes anything; "edge cases before automation"):
  create    the app does not exist                          -> app.create
  update    its stored YAML differs from the wrapper        -> app.update
  redeploy  the YAML matches but the images it runs are not the release's, or it CRASHED
                                                            -> app.redeploy
  conflict  an app of that name exists but is a catalog app -> reported, never touched
  none      in step (a STOPPED app is reported, not started: someone stopped it on purpose)
Apps on the NAS that the desired state does not name are listed as unmanaged, never removed.
The release's images come from `git archive <release> stack/<stack>` and `docker compose config
--images` on this machine; without git, docker or the tag, images are not compared (said so).

Exit codes: 0 done (drift: no drift), 1 a call or an apply step failed, 2 usage or configuration
error (including a NAS that reports another TrueNAS version), 3 drift found (drift only).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import difflib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "deploy" / "truenas.toml"
DEFAULT_CONFIG = Path.home() / ".config" / "local-agent-stack" / "truenas.toml"

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_DRIFT = 0, 1, 2, 3

APP_NAME_RE = re.compile(r"^[a-z]([-a-z0-9]*[a-z0-9])?$")  # AppCreateArgs.app_name, 1-40 characters
STACK_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RELEASE_RE = re.compile(r"^v[0-9]+\.[0-9]+(-beta\.[1-9][0-9]*)?$")
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+)+$")
PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")
DESIRED_KEYS = {"schema", "release", "truenas_version", "stacks_dir", "secrets_dir", "apps"}
APP_KEYS = {"stack"}
CONFIG_KEYS = {"uri", "read_user", "read_key_file", "apply_user", "apply_key_file", "ca_file"}
STATES_IN_STEP = {"RUNNING"}
ISSUE_TITLE = "Deploy drift: TrueNAS differs from deploy/truenas.toml"
ISSUE_LABEL = "deploy"
POLL_SECONDS = 5


class DeployError(Exception):
    """A step that failed: printed, exit 1."""


class ConfigError(Exception):
    """Bad input or a refusal before anything is called: printed, exit 2."""


# ---------------------------------------------------------------------------
# Desired state
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class App:
    name: str
    stack: str


@dataclasses.dataclass
class Desired:
    release: str
    truenas_version: str
    stacks_dir: str
    secrets_dir: str
    apps: list  # of App, in the file's order

    def wrapper(self, app):
        """The custom app's YAML: exactly docs/stack-design.md, section 4."""
        return (
            "include:\n"
            f"  - path: {self.stacks_dir}/stack/{app.stack}/compose.yaml\n"
            f"    env_file: {self.secrets_dir}/{app.stack}.env\n"
            "services: {}\n"
        )

    def wrapper_config(self, app):
        """The wrapper as TrueNAS stores and returns it (app.config: the parsed YAML)."""
        return {
            "include": [
                {
                    "path": f"{self.stacks_dir}/stack/{app.stack}/compose.yaml",
                    "env_file": f"{self.secrets_dir}/{app.stack}.env",
                }
            ],
            "services": {},
        }


def load_desired(path, root=ROOT, check_files=True):
    """The desired state, or ConfigError listing every problem found."""
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except OSError as error:
        raise ConfigError(f"{path}: {error.strerror or error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: not valid TOML: {error}") from error
    problems = []
    for key in sorted(set(data) - DESIRED_KEYS):
        problems.append(f"unknown key {key!r}")
    if data.get("schema") != 1:
        problems.append(f"schema must be 1, not {data.get('schema')!r}")
    release = data.get("release")
    if not isinstance(release, str) or not RELEASE_RE.match(release):
        problems.append(f"release must be a tag like v1.0 or v1.1-beta.1, not {release!r}")
    version = data.get("truenas_version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        problems.append(f"truenas_version must look like 25.10.8, not {version!r}")
    for key in ("stacks_dir", "secrets_dir"):
        value = data.get(key)
        if not isinstance(value, str) or not PATH_RE.match(value) or "//" in value or value.endswith("/"):
            problems.append(f"{key} must be an absolute path of letters, digits, . _ - and /, not {value!r}")
    apps = []
    table = data.get("apps")
    if not isinstance(table, dict) or not table:
        problems.append("[apps.<name>] tables are missing")
        table = {}
    stacks_seen = {}
    for name, entry in table.items():
        if not APP_NAME_RE.match(name) or len(name) > 40:
            problems.append(f"app name {name!r}: lowercase letters, digits and inner hyphens, 1 to 40 characters")
        if not isinstance(entry, dict):
            problems.append(f"apps.{name} must be a table")
            continue
        for key in sorted(set(entry) - APP_KEYS):
            problems.append(f"apps.{name}: unknown key {key!r}")
        stack = entry.get("stack")
        if not isinstance(stack, str) or not STACK_RE.match(stack):
            problems.append(f"apps.{name}.stack must name a folder under stack/, not {stack!r}")
            continue
        if stack in stacks_seen:
            problems.append(f"apps.{name}.stack {stack!r} is also apps.{stacks_seen[stack]}.stack")
        stacks_seen[stack] = name
        if check_files:
            for relative in (f"stack/{stack}/compose.yaml", f"stack/{stack}/{stack}.env.example"):
                if not (Path(root) / relative).is_file():
                    problems.append(f"apps.{name}: {relative} does not exist")
        apps.append(App(name, stack))
    if problems:
        raise ConfigError(f"{path}: " + "; ".join(problems))
    return Desired(release, version, data["stacks_dir"], data["secrets_dir"], apps)


def select_apps(desired, names):
    if not names:
        return list(desired.apps)
    known = {app.name: app for app in desired.apps}
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ConfigError("not in the desired state: " + ", ".join(unknown))
    return [app for app in desired.apps if app.name in names]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Settings:
    uri: str
    users: dict  # role -> user name
    key_files: dict  # role -> Path
    ca_file: Path | None


def load_settings(path):
    path = Path(path).expanduser()
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(
            f"{path} does not exist: write it as tools/deploy.py's docstring shows (mode 0600)"
        ) from error
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path}: {error}") from error
    problems = [f"unknown key {key!r}" for key in sorted(set(data) - CONFIG_KEYS)]
    uri = data.get("uri", "")
    if not isinstance(uri, str) or not uri.startswith("wss://"):
        problems.append("uri must start with wss:// (TrueNAS revokes an API key that travels over plain HTTP or ws://)")
    folder = path.parent
    users, key_files = {}, {}
    for role in ("read", "apply"):
        user = data.get(f"{role}_user")
        key_file = data.get(f"{role}_key_file")
        if user is not None and (not isinstance(user, str) or not user):
            problems.append(f"{role}_user must be a user name")
        if key_file is not None and (not isinstance(key_file, str) or not key_file):
            problems.append(f"{role}_key_file must be a file name")
        if isinstance(user, str) and user and isinstance(key_file, str) and key_file:
            users[role] = user
            key_files[role] = (folder / Path(key_file).expanduser()).resolve()
    ca_file = data.get("ca_file")
    ca_path = None
    if ca_file is not None:
        if not isinstance(ca_file, str) or not ca_file:
            problems.append("ca_file must be a file name")
        else:
            ca_path = (folder / Path(ca_file).expanduser()).resolve()
            if not ca_path.is_file():
                problems.append(f"ca_file {ca_path} does not exist")
    if problems:
        raise ConfigError(f"{path}: " + "; ".join(problems))
    return Settings(uri, users, key_files, ca_path)


def read_key(path):
    """An API key from a file only its owner can read; the key is never printed."""
    try:
        info = os.stat(path)
    except OSError as error:
        raise ConfigError(f"API key file {path}: {error.strerror or error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError(f"API key file {path} is not a regular file")
    if info.st_mode & 0o077:
        raise ConfigError(f"API key file {path} is readable by others (mode {info.st_mode & 0o777:04o}): chmod 600 it")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ConfigError(f"API key file {path} belongs to another user")
    with open(path, encoding="utf-8") as handle:
        key = handle.read().strip()
    if not key or "\n" in key:
        raise ConfigError(f"API key file {path} must hold the key alone, on one line")
    return key


def default_client_factory(uri):
    """truenas_api_client.Client, imported only when a connection is made."""
    try:
        from truenas_api_client import Client
    except ImportError as error:
        raise ConfigError(
            "truenas_api_client is not installed in this Python: see tools/deploy.py's docstring (TS-25.10.8)"
        ) from error
    if uri is None:
        return Client()  # the local middleware socket (on the NAS, as root)
    return Client(uri, verify_ssl=True)


class Session:
    """One logged-in connection; close() always."""

    def __init__(self, client):
        self.client = client

    def call(self, method, *params, job=False):
        try:
            if job:
                return self.client.call(method, *params, job=True)
            return self.client.call(method, *params)
        except (ConfigError, DeployError):
            raise
        except Exception as error:  # the client raises ClientException, ValidationErrors, CallTimeout, ...
            raise DeployError(f"{method}: {error}") from error

    def close(self):
        try:
            self.client.close()
        except Exception:  # noqa: S110 - closing a socket that is already gone is not an error
            pass


def connect(args, role, client_factory=default_client_factory):
    """A Session logged in with the role's key (read or apply), or with --local the local socket."""
    if args.local:
        return Session(client_factory(None))
    settings = load_settings(args.config)
    if role not in settings.users:
        raise ConfigError(f"{args.config}: {role}_user and {role}_key_file are needed for this command")
    key = read_key(settings.key_files[role])
    if settings.ca_file is not None:
        os.environ["WEBSOCKET_CLIENT_CA_BUNDLE"] = str(settings.ca_file)
    try:
        client = client_factory(settings.uri)
    except ConfigError:
        raise
    except Exception as error:
        raise DeployError(f"cannot connect to the NAS: {error}") from error
    session = Session(client)
    try:
        answer = session.call(
            "auth.login_ex", {"mechanism": "API_KEY_PLAIN", "username": settings.users[role], "api_key": key}
        )
    except DeployError:
        session.close()
        raise
    if not isinstance(answer, dict) or answer.get("response_type") != "SUCCESS":
        session.close()
        kind = answer.get("response_type") if isinstance(answer, dict) else answer
        raise DeployError(f"login as {settings.users[role]} failed ({kind})")
    return session


def check_version(session, desired):
    info = session.call("system.info")
    version = info.get("version") if isinstance(info, dict) else None
    if version != desired.truenas_version:
        raise ConfigError(
            f"the NAS reports TrueNAS {version!r}, deploy/truenas.toml says {desired.truenas_version!r}: "
            "review the API changes, then update truenas_version (and the tool) in a pull request"
        )
    return version


# ---------------------------------------------------------------------------
# Images of the release
# ---------------------------------------------------------------------------


def normalize_image(reference):
    reference = reference.strip()
    for prefix in ("docker.io/", "index.docker.io/"):
        if reference.startswith(prefix):
            reference = reference[len(prefix) :]
    if reference.startswith("library/"):
        reference = reference[len("library/") :]
    return reference


def run_quiet(command, **kwargs):
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, **kwargs)


def release_images(root, release, stack, runner=run_quiet):
    """The images stack/<stack>/compose.yaml names at the release tag, or (None, why not)."""
    rev = runner(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"refs/tags/{release}^{{commit}}"])
    if rev.returncode != 0:
        return None, f"tag {release} is not in this clone (git fetch --tags)"
    archive = runner(["git", "-C", str(root), "archive", "--format=tar", release, f"stack/{stack}"])
    if archive.returncode != 0:
        return None, f"stack/{stack} is not in {release}"
    with tempfile.TemporaryDirectory() as folder:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
            bundle.extractall(folder, filter="data")
        base = Path(folder) / "stack" / stack
        compose = runner(
            [
                "docker",
                "compose",
                "--env-file",
                str(base / f"{stack}.env.example"),
                "-f",
                str(base / "compose.yaml"),
                "config",
                "--images",
            ]
        )
    if compose.returncode != 0:
        detail = compose.stderr.decode("utf-8", "replace").strip().splitlines()
        return None, "docker compose config failed: " + (detail[-1] if detail else "no output")
    images = {normalize_image(line) for line in compose.stdout.decode("utf-8", "replace").splitlines() if line.strip()}
    return images, None


def all_release_images(root, release, apps, runner=run_quiet):
    """{app name: (images or None, why not)}, the apps' compose files rendered at the same time."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(apps))) as pool:
        futures = {app.name: pool.submit(release_images, root, release, app.stack, runner) for app in apps}
        result = {}
        for name, future in futures.items():
            try:
                result[name] = future.result()
            except OSError as error:
                result[name] = (None, f"cannot run git or docker: {error}")
        return result


def images_match(wanted, running):
    """Whether the running images are the wanted ones. A running image reported without its digest
    matches a wanted name:tag@sha256:... by name and tag."""
    if wanted == running:
        return True
    if len(wanted) != len(running):
        return False
    remaining = set(running)
    for image in wanted:
        if image in remaining:
            remaining.discard(image)
            continue
        without_digest = image.split("@", 1)[0]
        if without_digest in remaining:
            remaining.discard(without_digest)
            continue
        return False
    return not remaining


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AppPlan:
    name: str
    action: str  # create, update, redeploy, conflict, none
    state: str | None
    reasons: list
    diff: list
    notes: list


@dataclasses.dataclass
class Plan:
    version: str | None
    apps: list  # of AppPlan
    unmanaged: list  # app names on the NAS the desired state does not name

    def drifted(self):
        return any(item.action != "none" or item.state not in STATES_IN_STEP for item in self.apps)


def canonical(value):
    return json.dumps(value, indent=2, sort_keys=True).splitlines()


def query_apps(session):
    found = session.call("app.query", [], {})
    if not isinstance(found, list):
        raise DeployError(f"app.query returned {type(found).__name__}, not a list")
    return {entry.get("name") or entry.get("id"): entry for entry in found if isinstance(entry, dict)}


def plan_app(desired, app, entry, stored, images):
    wanted_images, why_not = images
    if entry is None:
        return AppPlan(app.name, "create", None, ["not installed"], [], [])
    state = entry.get("state")
    notes = []
    if not entry.get("custom_app"):
        return AppPlan(
            app.name, "conflict", state, ["an app of this name exists and is not a custom app: never touched"], [], []
        )
    want = desired.wrapper_config(app)
    if stored != want:
        diff = list(
            difflib.unified_diff(canonical(stored), canonical(want), "on the NAS (app.config)", "desired", lineterm="")
        )
        return AppPlan(app.name, "update", state, ["its YAML differs from the include wrapper"], diff, notes)
    running = {normalize_image(image) for image in (entry.get("active_workloads") or {}).get("images") or []}
    if wanted_images is None:
        notes.append(f"images not compared: {why_not}")
    elif state == "RUNNING" and not images_match(wanted_images, running):
        missing = sorted(wanted_images - running)
        extra = sorted(running - wanted_images)
        reason = f"runs images other than {desired.release}'s"
        if missing:
            reason += "; wanted: " + ", ".join(missing)
        if extra:
            reason += "; running: " + ", ".join(extra)
        notes.append(f"is the clone at {desired.stacks_dir} checked out at {desired.release}?")
        return AppPlan(app.name, "redeploy", state, [reason], [], notes)
    if state == "CRASHED":
        return AppPlan(app.name, "redeploy", state, ["CRASHED"], [], notes)
    if state == "STOPPED":
        notes.append("STOPPED: not started by apply (start it in Apps, or find out why it was stopped)")
    elif state not in STATES_IN_STEP:
        notes.append(f"{state}: in transition; run plan again in a minute")
    return AppPlan(app.name, "none", state, [], [], notes)


def make_plan(session, desired, apps, root=ROOT, runner=run_quiet, images=None):
    version = check_version(session, desired)
    on_nas = query_apps(session)
    if images is None:
        images = all_release_images(root, desired.release, apps, runner)
    plans = []
    for app in apps:
        entry = on_nas.get(app.name)
        stored = None
        if entry is not None and entry.get("custom_app"):
            stored = session.call("app.config", app.name)
        plans.append(plan_app(desired, app, entry, stored, images.get(app.name, (None, "not computed"))))
    managed = {app.name for app in desired.apps}
    unmanaged = sorted(name for name in on_nas if name not in managed)
    return Plan(version, plans, unmanaged)


def print_plan(plan, desired, out):
    out.write(f"TrueNAS {plan.version}; desired release {desired.release}\n")
    for item in plan.apps:
        state = item.state or "-"
        reasons = "; ".join(item.reasons) if item.reasons else "in step"
        out.write(f"{item.name}: {item.action} ({state}) {reasons}\n")
        for line in item.diff:
            out.write(f"    {line}\n")
        for note in item.notes:
            out.write(f"    note: {note}\n")
    for name in plan.unmanaged:
        out.write(f"{name}: unmanaged (not in deploy/truenas.toml; never removed by deploy.py)\n")


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def wait_running(session, name, timeout, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    state = None
    while True:
        found = session.call("app.query", [["name", "=", name]])
        state = found[0].get("state") if isinstance(found, list) and found else None
        if state == "RUNNING":
            return state
        if state == "CRASHED" or clock() >= deadline:
            raise DeployError(f"{name}: {state or 'missing'} after the change (waited up to {timeout} s)")
        sleep(POLL_SECONDS)


def apply_plan(session, desired, plan, out, dry_run=False, timeout=600, clock=time.monotonic, sleep=time.sleep):
    failures = 0
    by_name = {app.name: app for app in desired.apps}
    for item in plan.apps:
        app = by_name[item.name]
        if item.action in ("none", "conflict"):
            out.write(f"{item.name}: {item.action}, nothing to do\n")
            continue
        out.write(f"{item.name}: {item.action}{' (dry run)' if dry_run else ''}\n")
        if dry_run:
            continue
        try:
            if item.action == "create":
                session.call(
                    "app.create",
                    {"custom_app": True, "app_name": app.name, "custom_compose_config_string": desired.wrapper(app)},
                    job=True,
                )
            elif item.action == "update":
                session.call("app.update", app.name, {"custom_compose_config_string": desired.wrapper(app)}, job=True)
            elif item.action == "redeploy":
                session.call("app.redeploy", app.name, job=True)
            state = wait_running(session, app.name, timeout, clock, sleep)
            out.write(f"{item.name}: {state}\n")
        except DeployError as error:
            failures += 1
            out.write(f"{item.name}: FAILED: {error}\n")
    return failures


# ---------------------------------------------------------------------------
# Drift issue (gh)
# ---------------------------------------------------------------------------


def issue_body(plan, desired):
    lines = [
        f"`tools/deploy.py drift` found the NAS out of step with `deploy/truenas.toml` (release {desired.release}).",
        "",
        "| App | Action | State | Why |",
        "|---|---|---|---|",
    ]
    for item in plan.apps:
        if item.action == "none" and item.state in STATES_IN_STEP:
            continue
        why = "; ".join(item.reasons + item.notes) or "-"
        lines.append(f"| {item.name} | {item.action} | {item.state or '-'} | {why.replace('|', '/')} |")
    lines += ["", "Fix with `tools/deploy.py plan`, then `tools/deploy.py apply`; this issue closes itself on the"]
    lines.append("next `tools/deploy.py drift --issue` that finds no drift.")
    return "\n".join(lines) + "\n"


def run_gh(arguments):
    done = subprocess.run(["gh", *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True)
    if done.returncode != 0:
        raise DeployError(f"gh {arguments[0]} {arguments[1]}: {done.stderr.strip()}")
    return done.stdout


def sync_issue(plan, desired, out, gh=run_gh):
    """Keep exactly one open issue labelled deploy: opened or updated on drift, closed without."""
    listed = gh(["issue", "list", "--label", ISSUE_LABEL, "--state", "open", "--json", "number,title"])
    issues = [entry for entry in json.loads(listed or "[]") if entry.get("title") == ISSUE_TITLE]
    if plan.drifted():
        body = issue_body(plan, desired)
        if issues:
            gh(["issue", "edit", str(issues[0]["number"]), "--body", body])
            out.write(f"issue #{issues[0]['number']} updated\n")
        else:
            gh(["issue", "create", "--title", ISSUE_TITLE, "--label", ISSUE_LABEL, "--body", body])
            out.write("issue opened\n")
    else:
        for entry in issues:
            gh(["issue", "close", str(entry["number"]), "--comment", "`tools/deploy.py drift`: no drift."])
            out.write(f"issue #{entry['number']} closed\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_validate(args, out):
    desired = load_desired(args.file, ROOT if args.root is None else args.root)
    out.write(
        f"{args.file}: ok ({len(desired.apps)} apps, release {desired.release}, TrueNAS {desired.truenas_version})\n"
    )
    return EXIT_OK


def cmd_render(args, out):
    desired = load_desired(args.file, check_files=False)
    for app in select_apps(desired, [args.app] if args.app else []):
        out.write(f"# {app.name}\n{desired.wrapper(app)}")
    return EXIT_OK


def with_session(args, role, work, client_factory):
    session = connect(args, role, client_factory)
    try:
        return work(session)
    finally:
        session.close()


def cmd_plan(args, out, client_factory, runner):
    desired = load_desired(args.file, check_files=False)
    apps = select_apps(desired, args.app)

    def work(session):
        plan = make_plan(session, desired, apps, runner=runner)
        print_plan(plan, desired, out)
        return plan

    plan = with_session(args, "read", work, client_factory)
    if args.command == "drift":
        if args.issue:
            sync_issue(plan, desired, out)
        drifted = plan.drifted()
        out.write("drift: yes\n" if drifted else "drift: none\n")
        return EXIT_DRIFT if drifted else EXIT_OK
    return EXIT_OK


def cmd_status(args, out, client_factory, runner):
    desired = load_desired(args.file, check_files=False)

    def work(session):
        return make_plan(session, desired, desired.apps, runner=runner)

    plan = with_session(args, "read", work, client_factory)
    out.write(f"TrueNAS {plan.version}; desired release {desired.release}\n")
    for item in plan.apps:
        config = {"create": "missing", "update": "differs", "conflict": "not a custom app"}.get(item.action, "matches")
        if any(note.startswith("images not compared") for note in item.notes):
            images = "not compared"
        elif item.action == "redeploy" and item.state == "RUNNING":
            images = "differ"
        elif item.action in ("none", "redeploy"):
            images = "match"
        else:
            images = "-"
        out.write(f"{item.name}: state {item.state or '-'}, YAML {config}, images {images}\n")
    for name in plan.unmanaged:
        out.write(f"{name}: unmanaged\n")
    return EXIT_OK


def cmd_apply(args, out, client_factory, runner, clock=time.monotonic, sleep=time.sleep):
    desired = load_desired(args.file, check_files=False)
    apps = select_apps(desired, args.app)
    images = all_release_images(ROOT, desired.release, apps, runner)

    def work(session):
        plan = make_plan(session, desired, apps, runner=runner, images=images)
        print_plan(plan, desired, out)
        failures = apply_plan(session, desired, plan, out, args.dry_run, args.timeout, clock, sleep)
        if not args.dry_run:
            after = make_plan(session, desired, apps, runner=runner, images=images)
            out.write("after apply:\n")
            print_plan(after, desired, out)
            if after.drifted():
                failures += 1
        return failures

    failures = with_session(args, "apply", work, client_factory)
    return EXIT_FAILED if failures else EXIT_OK


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="deploy.py",
        description="Make the TrueNAS server run what deploy/truenas.toml says (docs/stack-design.md, section 8).",
        epilog="Exit codes: 0 ok, 1 a step failed, 2 usage or configuration, 3 drift (drift only).",
    )
    parser.add_argument("--file", default=str(DEFAULT_FILE), help="desired state (default: deploy/truenas.toml)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="connection settings and key files")
    parser.add_argument("--local", action="store_true", help="on the NAS as root: the local middleware socket")
    parser.add_argument("--root", default=None, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    commands.add_parser("validate", help="check the desired state and the stack files it names (offline)")
    render = commands.add_parser("render", help="print each app's TrueNAS YAML")
    render.add_argument("--app")
    plan = commands.add_parser("plan", help="what apply would do (read-only key)")
    plan.add_argument("--app", action="append", default=[])
    apply = commands.add_parser("apply", help="create, update or redeploy the apps (full-admin key)")
    apply.add_argument("--app", action="append", default=[])
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--timeout", type=int, default=600, help="seconds to wait for each app to run")
    drift = commands.add_parser("drift", help="exit 3 when the NAS differs (read-only key)")
    drift.add_argument("--app", action="append", default=[])
    drift.add_argument("--issue", action="store_true", help="keep one open GitHub issue labelled deploy (gh)")
    commands.add_parser("status", help="one line per app (read-only key)")
    return parser.parse_args(argv)


def main(argv=None, out=None, client_factory=default_client_factory, runner=run_quiet):
    out = out or sys.stdout
    args = parse_args(argv)
    try:
        if args.command == "validate":
            return cmd_validate(args, out)
        if args.command == "render":
            return cmd_render(args, out)
        if args.command in ("plan", "drift"):
            return cmd_plan(args, out, client_factory, runner)
        if args.command == "status":
            return cmd_status(args, out, client_factory, runner)
        return cmd_apply(args, out, client_factory, runner)
    except ConfigError as error:
        print(f"deploy.py: {error}", file=sys.stderr)
        return EXIT_USAGE
    except DeployError as error:
        print(f"deploy.py: {error}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
