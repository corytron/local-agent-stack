#!/usr/bin/env python3
"""Make the TrueNAS SCALE server run what deploy/truenas.toml says, and show where it differs.

  deploy.py [OPTIONS] validate                    check the desired state and the stack files it names (offline)
  deploy.py [OPTIONS] render [--app NAME]         print each app's TrueNAS YAML as apply would write it (offline)
  deploy.py [OPTIONS] plan [--app NAME]...        what apply would do, per app (read-only key)
  deploy.py [OPTIONS] apply [--app NAME]... [--dry-run] [--timeout SECONDS]
                                                  create, update or redeploy the apps (full-admin key)
  deploy.py [OPTIONS] drift [--app NAME]... [--issue]
                                                  exit 3 when the NAS differs from the desired state;
                                                  --issue keeps one open GitHub issue labelled `deploy` (gh)
  deploy.py [OPTIONS] status                      one line per app: state, YAML, files, env, images

OPTIONS stand before or after the command: `deploy.py --local drift` and `deploy.py drift --local`
are the same; an option written on both sides takes the value written after the command.
  --file FILE     the desired state (default: deploy/truenas.toml in this clone)
  --config FILE   the connection settings (default: ~/.config/local-agent-stack/truenas.toml)
  --local         on the NAS itself, as root: the local middleware socket, no key and no settings
                  file; the env files are read from secrets_dir
  --no-hashes     run as if the desired state said content_hashes = false (see "Without content
                  hashes" below), whatever it says

What runs where (owner, 2026-11-15): nothing of this stack runs on the workstation full time (no
timers, no daemons), so drift is an on-demand command: run it by hand or by an agent, and after
every apply. A scheduled check, if wanted, is a TrueNAS cron job on the NAS: System > Advanced
Settings > Cron Jobs > Add (card and form labels checked in truenas/webui at TS-25.10.8:
Description, Command, Run As User, Schedule, Hide Standard Output, Hide Standard Error, Enabled),
Run As User root, and this Command, written on one line (the guide's chapter 10 prints it so):
  out=$(env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory
  GIT_CONFIG_VALUE_0=/mnt/tank/ai/stacks/local-agent-stack
  python3 /mnt/tank/ai/stacks/local-agent-stack/tools/deploy.py
  --local --file /mnt/tank/ai/stacks/desired.toml drift 2>&1) || echo "$out" >&2
The clone belongs to truenas_admin and the job runs as root, so git needs the clone in its
safe.directory setting (passed in the environment) to read the release tag; without it, the files
and images are reported as not compared. The desired state is the reader's copy, placed beside the
clone. --local needs no key (UNVERIFIED: that the NAS's system Python can import
truenas_api_client, which midclt uses). Exit 3 marks drift; the command prints the report only
then, on standard error, which TrueNAS reports when Hide Standard Error is cleared (that it mails
it to root is assumed, not verified).

The desired state (deploy/truenas.toml, read with tomllib; a reader keeps a copy outside the
clone and passes it with --file):
  schema = 1
  release = "v1.0"                          the tag the NAS clone is checked out at
  truenas_version = "25.10.8"               the NAS must report exactly this version
  stacks_dir = "/mnt/tank/ai/stacks/local-agent-stack"
  secrets_dir = "/mnt/tank/ai/secrets"
  env_dir = "~/.config/local-agent-stack/secrets"
                                            optional: where this machine keeps copies of the env
                                            files (<env_dir>/<stack>.env), for the env hash
  content_hashes = true                     optional, default true; false leaves the content hashes
                                            out (see "Without content hashes" below)
  [apps.ai-edge]                            one table per TrueNAS custom app, in apply's order
  stack = "edge"                            a folder under stack/
  overrides = ["/mnt/tank/ai/appdata/caddy/internal-ca.override.yaml"]
                                            optional: compose files on the NAS merged over the
                                            release's compose file, in this order

Each app is a TrueNAS custom app whose YAML is the include wrapper of docs/stack-design.md,
section 4, followed by the content hashes (none with content_hashes = false). For the default paths
and an app without overrides, stack/<stack>/truenas-app.yaml holds the first four lines byte for
byte (what the guide installs by hand, and what render prints after its "# <app>" line, minus the
hashes):

  include:
    - path: <stacks_dir>/stack/<stack>/compose.yaml
      env_file: <secrets_dir>/<stack>.env
  services: {}
  x-local-agent-stack:
    files: sha256:<64 hex digits>
    env: sha256:<64 hex digits>

With overrides, `path` is a list: the release's compose file first, then each override (the shape
of the coder fallback in the guide's chapter 4 and of the internal CA in appendix D). Compose
merges the files before it includes the result, so apply keeps the overrides:

  include:
    - path:
        - <stacks_dir>/stack/<stack>/compose.yaml
        - <override>
      env_file: <secrets_dir>/<stack>.env
  services: {}
  x-local-agent-stack: ...

Content hashes. Compose recreates a container when its service definition changes, not when a file
it bind-mounts changes, so without help a changed Caddyfile or llama-swap config would leave plan
at "none". The top-level extension x-local-agent-stack records two hashes in the app's YAML; a
change to either makes plan report update, and apply's app.update recreates the app's containers:
  files  sha256 over the lines "<sha256 of the file>  <path>\\n", sorted by path, of compose.yaml and
         of every file under stack/<stack>/ that compose.yaml names with a ./ path outside build:,
         context: and dockerfile: (the bind-mount sources; a directory stands for every regular
         file below it; a path that does not exist is the line "missing  <path>"). Build contexts
         are left out because a redeploy does not rebuild an image. The files come from
         `git archive <release> stack/<stack>`, so every machine computes the same value from the
         same tag; without git or the tag they are not compared.
  env    sha256 of the env file's bytes: with --local the file in secrets_dir, otherwise
         <env_dir>/<stack>.env, the workstation's copy that the guide installs on the NAS. The
         content is never printed or sent; only the hash leaves the file (into the app's YAML and
         plan's diff), and a hash cannot be reversed to values that include a random secret.
A hash this run cannot compute is "not compared" (a note says why) and plan keeps the value the NAS
has recorded, so a machine without git or without the env copies never undoes what another one
recorded. A hash the NAS has not recorded (an app installed by hand from truenas-app.yaml, or by an
older deploy.py) is an update: apply records it, which recreates the app's containers once.
Changes to an override file, or to a file only an override mounts, are not detected: redeploy by
hand. Compose accepts any top-level key that starts with x- and ignores it (Compose Specification;
`docker compose config` with Compose v5.6.0 on c4dev accepted both wrapper shapes with the
extension; the Compose version TrueNAS bundles was not tried).

Without content hashes. TrueNAS checks a custom app's YAML with `docker compose config` before it
stores it, so a bundled Compose that refused the extension would fail every app.create and
app.update that carries it. For that case, `content_hashes = false` in the desired state (or
--no-hashes on one run) leaves the hashes out: render and apply write exactly the include wrapper,
for an app without overrides the four lines of stack/<stack>/truenas-app.yaml, and an app whose
stored YAML still carries the extension is an update that removes it. plan and drift compare the
YAML and the images only and say once that changes to the release's files and to the env files are
not detected (redeploy those apps by hand); the env files are not read, and status shows `files -`
and `env -`. Turning the hashes back on makes every app an update once, which records them.

The workstation's connection settings (~/.config/local-agent-stack/truenas.toml, mode 0600, never
in the repository; the TrueNAS web interface and its API move to port 8443 in the guide's
chapter 3):

  uri = "wss://192.0.2.10:8443/api/current" # wss:// only: a key sent over ws:// is revoked
  read_user = "deploy-read"                 # a user whose group's privilege is READONLY_ADMIN
  read_key_file = "truenas-read.key"        # relative to the config file's folder, mode 0600
  apply_user = "deploy-apply"               # a user whose group's privilege is FULL_ADMIN
  apply_key_file = "truenas-apply.key"
  ca_file = "truenas-ca.pem"                # optional: the CA that signed the NAS's certificate

plan, drift and status log in with the read key; only apply loads the full-admin key (25.10 has
no smaller predefined role that may write apps: docs/research/f-project-tooling.md, section 2).

Middleware calls (checked against truenas/middleware at tag TS-25.10.8, API v25_10_5, and
truenas/api_client at tag TS-25.10.8):
  auth.login_ex {"mechanism": "API_KEY_PLAIN", "username", "api_key"} -> response_type SUCCESS
  system.info -> {"version": ...}       (version is system.version_short)
  app.query [filters] {options} -> name, state, custom_app, active_workloads.images (each
            container's Config.Image); queried without extra.retrieve_config, so no other app's
            configuration (and none of its secrets) is fetched
  app.config <name> -> the stored compose for a custom app: the parsed YAML apply sent, extension
            included (plugins/apps/custom_app_utils.py validate_payload loads it with
            safe_yaml_load and checks it with `docker compose config`; ix_apps/lifecycle.py
            update_app_config stores it)
  app.create {"custom_app": true, "app_name", "custom_compose_config_string"}   (job)
  app.update <name> {"custom_compose_config_string"}                           (job; runs
            `compose up --force-recreate --remove-orphans` unless the app is STOPPED, which only
            stores the YAML: plugins/apps/crud.py update_internal)
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
  update    its stored YAML differs from the wrapper: the include (paths, overrides, env_file),
            or a content hash (the release's files or the env file changed, or not recorded;
            without content hashes: an extension still stored)
                                                            -> app.update (recreates the containers
                                                               of a running app)
  redeploy  the YAML matches but the images it runs are not the release's, or it CRASHED
                                                            -> app.redeploy
  conflict  an app of that name exists but is a catalog app -> reported, never touched
  none      in step (a STOPPED app is reported, not started: someone stopped it on purpose; an
            update of a STOPPED app only stores its YAML)
Apps on the NAS that the desired state does not name are listed as unmanaged, never removed.
The release's images come from the same `git archive` and `docker compose config --images` on this
machine; without git, docker or the tag, images are not compared (said so).

Exit codes: 0 done (drift: no drift), 1 a call or an apply step failed, 2 usage or configuration
error (including a NAS that reports another TrueNAS version), 3 drift found (drift only).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import difflib
import hashlib
import io
import json
import os
import posixpath
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
ENV_DIR_RE = re.compile(r"^(/|~/)[A-Za-z0-9._/-]+$")
DESIRED_KEYS = {
    "schema",
    "release",
    "truenas_version",
    "stacks_dir",
    "secrets_dir",
    "env_dir",
    "content_hashes",
    "apps",
}
APP_KEYS = {"stack", "overrides"}
CONFIG_KEYS = {"uri", "read_user", "read_key_file", "apply_user", "apply_key_file", "ca_file"}
STATES_IN_STEP = {"RUNNING"}
ISSUE_TITLE = "Deploy drift: TrueNAS differs from deploy/truenas.toml"
ISSUE_LABEL = "deploy"
POLL_SECONDS = 5

# The top-level Compose extension that carries the content hashes, and its keys in YAML order.
EXTENSION = "x-local-agent-stack"
CONTENT_KEYS = ("files", "env")
HASHES_OFF_NOTE = (
    "content hashes are off (content_hashes = false or --no-hashes): changes to the release's files "
    "and to the env files are not detected; redeploy the apps they touch by hand"
)
# A ./path in compose.yaml (bind-mount sources); keys whose ./paths are build inputs are skipped.
SOURCE_RE = re.compile(r"(?<![\w./-])\./[\w.-][\w./-]*")
BUILD_KEYS = {"build", "context", "dockerfile"}


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
    overrides: tuple = ()  # absolute paths on the NAS, merged over the release's compose file


@dataclasses.dataclass
class Desired:
    release: str
    truenas_version: str
    stacks_dir: str
    secrets_dir: str
    apps: list  # of App, in the file's order
    env_dir: str | None = None  # as written in the file (may start with ~/); never expanded for display
    content_hashes: bool = True  # false: the YAML carries no x-local-agent-stack block (docstring)

    def compose_path(self, app):
        return f"{self.stacks_dir}/stack/{app.stack}/compose.yaml"

    def env_path(self, app):
        return f"{self.secrets_dir}/{app.stack}.env"

    def wrapper(self, app, content=None):
        """The custom app's YAML: docs/stack-design.md, section 4, with the overrides and the content
        hashes (module docstring). Without overrides and hashes it is stack/<stack>/truenas-app.yaml."""
        lines = ["include:"]
        if app.overrides:
            lines.append("  - path:")
            lines += [f"      - {path}" for path in (self.compose_path(app), *app.overrides)]
        else:
            lines.append(f"  - path: {self.compose_path(app)}")
        lines.append(f"    env_file: {self.env_path(app)}")
        lines.append("services: {}")
        if content:
            lines.append(f"{EXTENSION}:")
            lines += [f"  {key}: {content[key]}" for key in CONTENT_KEYS if key in content]
        return "\n".join(lines) + "\n"

    def wrapper_config(self, app, content=None):
        """The wrapper as TrueNAS stores and returns it (app.config: the parsed YAML)."""
        path = [self.compose_path(app), *app.overrides] if app.overrides else self.compose_path(app)
        config = {"include": [{"path": path, "env_file": self.env_path(app)}], "services": {}}
        if content:
            config[EXTENSION] = {key: content[key] for key in CONTENT_KEYS if key in content}
        return config


def check_path(value, problems, label):
    if not isinstance(value, str) or not PATH_RE.match(value) or "//" in value or value.endswith("/"):
        problems.append(f"{label} must be an absolute path of letters, digits, . _ - and /, not {value!r}")
        return False
    return True


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
        check_path(data.get(key), problems, key)
    env_dir = data.get("env_dir")
    if env_dir is not None and (
        not isinstance(env_dir, str) or not ENV_DIR_RE.match(env_dir) or "//" in env_dir or env_dir.endswith("/")
    ):
        problems.append(
            f"env_dir must be a folder like ~/.config/local-agent-stack/secrets or /abs/path, not {env_dir!r}"
        )
    content_hashes = data.get("content_hashes", True)
    if not isinstance(content_hashes, bool):
        problems.append(f"content_hashes must be true or false, not {content_hashes!r}")
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
        overrides = entry.get("overrides", [])
        if not isinstance(overrides, list):
            problems.append(f"apps.{name}.overrides must be a list of absolute paths")
            overrides = []
        for index, override in enumerate(overrides):
            if check_path(override, problems, f"apps.{name}.overrides[{index}]") and overrides.index(override) != index:
                problems.append(f"apps.{name}.overrides lists {override} twice")
        if check_files:
            for relative in (f"stack/{stack}/compose.yaml", f"stack/{stack}/{stack}.env.example"):
                if not (Path(root) / relative).is_file():
                    problems.append(f"apps.{name}: {relative} does not exist")
        apps.append(App(name, stack, tuple(overrides)))
    if problems:
        raise ConfigError(f"{path}: " + "; ".join(problems))
    return Desired(release, version, data["stacks_dir"], data["secrets_dir"], apps, env_dir, content_hashes)


def hashes_on(args, desired):
    """Whether this run records and compares the content hashes: the desired state's content_hashes,
    unless --no-hashes turns them off."""
    return desired.content_hashes and not args.no_hashes


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
# What the release holds: images and the files hash; the env file's hash
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


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def compose_sources(text):
    """The ./paths compose.yaml names outside build:, context: and dockerfile:, normalized and sorted
    (comments ignored)."""
    found = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        body = line.split(" #", 1)[0]
        key = body.strip().lstrip("- ").split(":", 1)[0].strip().strip("\"'")
        if key in BUILD_KEYS:
            continue
        for match in SOURCE_RE.finditer(body):
            found.add(posixpath.normpath(match.group(0)))
    return sorted(found)


def stack_files_hash(base):
    """The files hash of one stack folder (module docstring): compose.yaml and its ./ sources."""
    base = Path(base)
    compose = (base / "compose.yaml").read_bytes()
    entries = {"compose.yaml": sha256_hex(compose)}
    for source in compose_sources(compose.decode("utf-8", "replace")):
        target = base / source
        if source == ".." or source.startswith("../"):
            entries[source] = "outside"
        elif target.is_dir():
            for folder, subfolders, names in os.walk(target):
                subfolders.sort()
                for name in names:
                    path = Path(folder) / name
                    if path.is_file() and not path.is_symlink():
                        entries[path.relative_to(base).as_posix()] = sha256_hex(path.read_bytes())
        elif target.is_file():
            entries[source] = sha256_hex(target.read_bytes())
        else:
            entries[source] = "missing"
    manifest = "".join(f"{entries[name]}  {name}\n" for name in sorted(entries))
    return "sha256:" + sha256_hex(manifest.encode("utf-8"))


@dataclasses.dataclass
class Release:
    """What one stack folder holds at the release tag; None with a reason when not computed."""

    images: set | None
    images_why: str | None
    files: str | None
    files_why: str | None


def release_content(root, release, stack, runner=run_quiet):
    """The images and the files hash of stack/<stack> at the release tag (git archive)."""
    rev = runner(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"refs/tags/{release}^{{commit}}"])
    if rev.returncode != 0:
        why = f"tag {release} is not in this clone (git fetch --tags)"
        return Release(None, why, None, why)
    archive = runner(["git", "-C", str(root), "archive", "--format=tar", release, f"stack/{stack}"])
    if archive.returncode != 0:
        why = f"stack/{stack} is not in {release}"
        return Release(None, why, None, why)
    with tempfile.TemporaryDirectory() as folder:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
            bundle.extractall(folder, filter="data")
        base = Path(folder) / "stack" / stack
        try:
            files, files_why = stack_files_hash(base), None
        except OSError as error:
            files, files_why = None, f"cannot read stack/{stack} of {release}: {error.strerror or error}"
        try:
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
        except OSError as error:
            return Release(None, f"cannot run docker: {error}", files, files_why)
    if compose.returncode != 0:
        detail = compose.stderr.decode("utf-8", "replace").strip().splitlines()
        return Release(
            None, "docker compose config failed: " + (detail[-1] if detail else "no output"), files, files_why
        )
    images = {normalize_image(line) for line in compose.stdout.decode("utf-8", "replace").splitlines() if line.strip()}
    return Release(images, None, files, files_why)


def all_release_content(root, release, apps, runner=run_quiet):
    """{app name: Release}, the apps' folders read at the same time."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(apps))) as pool:
        futures = {app.name: pool.submit(release_content, root, release, app.stack, runner) for app in apps}
        result = {}
        for name, future in futures.items():
            try:
                result[name] = future.result()
            except OSError as error:
                why = f"cannot run git: {error}"
                result[name] = Release(None, why, None, why)
        return result


def env_hash(desired, app, local):
    """(sha256 of the app's env file, None) or (None, why not). The file is read where this run can
    read it: with --local the file in secrets_dir, otherwise the copy in env_dir. Its content is
    hashed and dropped, never printed; `why` names the path as the desired state writes it."""
    if local:
        shown = desired.env_path(app)
        path = Path(shown)
    elif desired.env_dir is not None:
        shown = f"{desired.env_dir}/{app.stack}.env"
        path = Path(shown).expanduser()
    else:
        return None, "env_dir is not set in the desired state (and this is not --local on the NAS)"
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            return None, f"{shown} is not a regular file"
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as error:
        return None, f"cannot read {shown}: {error.strerror or error}"
    return "sha256:" + sha256_hex(data), None


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
    content: dict = dataclasses.field(default_factory=dict)  # the hashes the YAML apply writes carries
    checks: dict = dataclasses.field(default_factory=dict)  # yaml, files, env, images -> status words
    overrides: tuple = ()


@dataclasses.dataclass
class Plan:
    version: str | None
    apps: list  # of AppPlan
    unmanaged: list  # app names on the NAS the desired state does not name
    hashes: bool = True  # false: content hashes off, YAML and images compared only

    def drifted(self):
        return any(item.action != "none" or item.state not in STATES_IN_STEP for item in self.apps)


def canonical(value):
    return json.dumps(value, indent=2, sort_keys=True).splitlines()


def query_apps(session):
    found = session.call("app.query", [], {})
    if not isinstance(found, list):
        raise DeployError(f"app.query returned {type(found).__name__}, not a list")
    return {entry.get("name") or entry.get("id"): entry for entry in found if isinstance(entry, dict)}


def computed_content(release, env):
    """The hashes this run computed, and why each missing one was not."""
    computed = {"files": release.files, "env": env[0]}
    why_not = {"files": release.files_why, "env": env[1]}
    return computed, why_not


def content_notes(computed, why_not, verb="compared"):
    notes = []
    for key, label in (("files", "files"), ("env", "env file")):
        if computed[key] is None:
            notes.append(f"{label} not {verb}: {why_not[key]}")
    return notes


def plan_app(desired, app, entry, stored, release, env, hashes=True):
    """One app's action. With hashes off, the release's files hash and env are ignored: the YAML
    wanted is the bare include wrapper, and files and env stay "-"."""
    if hashes:
        computed, why_not = computed_content(release, env)
    else:
        computed, why_not = dict.fromkeys(CONTENT_KEYS), {}
    checks = {"yaml": "-", "files": "-", "env": "-", "images": "-"}
    if entry is None:
        content = {key: value for key, value in computed.items() if value is not None}
        checks["yaml"] = "missing"
        notes = content_notes(computed, why_not, "hashed") if hashes else []
        return AppPlan(app.name, "create", None, ["not installed"], [], notes, content, checks, app.overrides)
    state = entry.get("state")
    if not entry.get("custom_app"):
        checks["yaml"] = "not a custom app"
        return AppPlan(
            app.name,
            "conflict",
            state,
            ["an app of this name exists and is not a custom app: never touched"],
            [],
            [],
            {},
            checks,
            app.overrides,
        )
    notes = content_notes(computed, why_not) if hashes else []
    recorded = stored.get(EXTENSION) if isinstance(stored, dict) else None
    recorded = recorded if isinstance(recorded, dict) else {}
    content = {}
    for key in CONTENT_KEYS if hashes else ():
        if computed[key] is not None:
            content[key] = computed[key]
            checks[key] = (
                "match" if recorded.get(key) == computed[key] else "differ" if key in recorded else "not recorded"
            )
        else:
            checks[key] = "not compared"
            if key in recorded:
                content[key] = recorded[key]  # not computed here: keep what the NAS has recorded
    want = desired.wrapper_config(app, content)
    reasons = []
    without = (
        {key: value for key, value in (stored or {}).items() if key != EXTENSION}
        if isinstance(stored, dict)
        else stored
    )
    if without != desired.wrapper_config(app):
        reasons.append("its YAML differs from the include wrapper")
        checks["yaml"] = "differs"
    elif not hashes and stored != want:
        reasons.append(f"its YAML carries an {EXTENSION} block, which apply removes while content hashes are off")
        checks["yaml"] = "differs"
    else:
        checks["yaml"] = "matches"
    if checks["files"] == "differ":
        reasons.append(f"the files of stack/{app.stack}/ in {desired.release} differ from the last apply")
    elif checks["files"] == "not recorded":
        reasons.append(f"no hash of the files of stack/{app.stack}/ recorded (installed by hand?)")
    if checks["env"] == "differ":
        reasons.append("its env file differs from the one hashed at the last apply")
    elif checks["env"] == "not recorded":
        reasons.append("no hash of its env file recorded")
    if stored != want and not reasons:
        reasons.append("its content hashes differ from the desired ones")
    running = {normalize_image(image) for image in (entry.get("active_workloads") or {}).get("images") or []}
    wanted_images = release.images
    if wanted_images is None:
        notes.append(f"images not compared: {release.images_why}")
        checks["images"] = "not compared"
    elif state != "RUNNING":
        checks["images"] = "not running"
    else:
        checks["images"] = "match" if images_match(wanted_images, running) else "differ"
    if stored != want:
        diff = list(
            difflib.unified_diff(canonical(stored), canonical(want), "on the NAS (app.config)", "desired", lineterm="")
        )
        if checks["env"] == "differ":
            notes.append("if apply ran from another machine, its copy of the env file differs from the one read here")
        if state == "STOPPED":
            notes.append("STOPPED: apply stores the new YAML and does not start the app")
        return AppPlan(app.name, "update", state, reasons, diff, notes, content, checks, app.overrides)
    if checks["images"] == "differ":
        missing = sorted(wanted_images - running)
        extra = sorted(running - wanted_images)
        reason = f"runs images other than {desired.release}'s"
        if missing:
            reason += "; wanted: " + ", ".join(missing)
        if extra:
            reason += "; running: " + ", ".join(extra)
        notes.append(f"is the clone at {desired.stacks_dir} checked out at {desired.release}?")
        return AppPlan(app.name, "redeploy", state, [reason], [], notes, content, checks, app.overrides)
    if state == "CRASHED":
        return AppPlan(app.name, "redeploy", state, ["CRASHED"], [], notes, content, checks, app.overrides)
    if state == "STOPPED":
        notes.append("STOPPED: not started by apply (start it in Apps, or find out why it was stopped)")
    elif state not in STATES_IN_STEP:
        notes.append(f"{state}: in transition; run plan again in a minute")
    return AppPlan(app.name, "none", state, [], [], notes, content, checks, app.overrides)


def make_plan(session, desired, apps, root=ROOT, runner=run_quiet, release=None, local=False, hashes=True):
    version = check_version(session, desired)
    on_nas = query_apps(session)
    if release is None:
        release = all_release_content(root, desired.release, apps, runner)
    plans = []
    for app in apps:
        entry = on_nas.get(app.name)
        stored = None
        if entry is not None and entry.get("custom_app"):
            stored = session.call("app.config", app.name)
        content = release.get(app.name) or Release(None, "not computed", None, "not computed")
        env = env_hash(desired, app, local) if hashes else (None, None)  # off: the env file is not read
        plans.append(plan_app(desired, app, entry, stored, content, env, hashes))
    managed = {app.name for app in desired.apps}
    unmanaged = sorted(name for name in on_nas if name not in managed)
    return Plan(version, plans, unmanaged, hashes)


def print_header(plan, desired, out, note=True):
    """The first line of plan and status, and once per run the note that the hashes are off."""
    out.write(f"TrueNAS {plan.version}; desired release {desired.release}\n")
    if note and not plan.hashes:
        out.write(f"note: {HASHES_OFF_NOTE}\n")


def print_plan(plan, desired, out, note=True):
    print_header(plan, desired, out, note)
    for item in plan.apps:
        state = item.state or "-"
        reasons = "; ".join(item.reasons) if item.reasons else "in step"
        out.write(f"{item.name}: {item.action} ({state}) {reasons}\n")
        for override in item.overrides:
            out.write(f"    override: {override}\n")
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
            yaml_text = desired.wrapper(app, item.content)
            if item.action == "create":
                session.call(
                    "app.create",
                    {"custom_app": True, "app_name": app.name, "custom_compose_config_string": yaml_text},
                    job=True,
                )
            elif item.action == "update":
                session.call("app.update", app.name, {"custom_compose_config_string": yaml_text}, job=True)
                if item.state == "STOPPED":
                    out.write(f"{item.name}: YAML stored; STOPPED, not started\n")
                    continue
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
    if not plan.hashes:
        lines += ["", f"Note: {HASHES_OFF_NOTE}."]
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


def repo_root(args):
    return ROOT if args.root is None else Path(args.root)


def cmd_validate(args, out):
    desired = load_desired(args.file, repo_root(args))
    off = "" if hashes_on(args, desired) else ", content hashes off"
    out.write(
        f"{args.file}: ok ({len(desired.apps)} apps, release {desired.release}, "
        f"TrueNAS {desired.truenas_version}{off})\n"
    )
    return EXIT_OK


def cmd_render(args, out, runner):
    """Each app's YAML as apply would write it for a new app: the hashes this machine can compute,
    or with the hashes off the include wrapper alone (nothing is read from git or the env files)."""
    desired = load_desired(args.file, check_files=False)
    apps = select_apps(desired, [args.app] if args.app else [])
    if not hashes_on(args, desired):
        for app in apps:
            out.write(f"# {app.name}\n{desired.wrapper(app)}")
        return EXIT_OK
    release = all_release_content(repo_root(args), desired.release, apps, runner)
    for app in apps:
        computed, why_not = computed_content(release[app.name], env_hash(desired, app, args.local))
        for note in content_notes(computed, why_not, "hashed"):
            print(f"deploy.py: {app.name}: {note}", file=sys.stderr)
        content = {key: value for key, value in computed.items() if value is not None}
        out.write(f"# {app.name}\n{desired.wrapper(app, content)}")
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
    hashes = hashes_on(args, desired)

    def work(session):
        plan = make_plan(session, desired, apps, repo_root(args), runner, local=args.local, hashes=hashes)
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
    hashes = hashes_on(args, desired)

    def work(session):
        return make_plan(session, desired, desired.apps, repo_root(args), runner, local=args.local, hashes=hashes)

    plan = with_session(args, "read", work, client_factory)
    print_header(plan, desired, out)
    for item in plan.apps:
        checks = item.checks
        out.write(
            f"{item.name}: state {item.state or '-'}, YAML {checks['yaml']}, files {checks['files']}, "
            f"env {checks['env']}, images {checks['images']}\n"
        )
    for name in plan.unmanaged:
        out.write(f"{name}: unmanaged\n")
    return EXIT_OK


def cmd_apply(args, out, client_factory, runner, clock=time.monotonic, sleep=time.sleep):
    desired = load_desired(args.file, check_files=False)
    apps = select_apps(desired, args.app)
    release = all_release_content(repo_root(args), desired.release, apps, runner)
    hashes = hashes_on(args, desired)

    def work(session):
        plan = make_plan(session, desired, apps, runner=runner, release=release, local=args.local, hashes=hashes)
        print_plan(plan, desired, out)
        failures = apply_plan(session, desired, plan, out, args.dry_run, args.timeout, clock, sleep)
        if not args.dry_run:
            after = make_plan(session, desired, apps, runner=runner, release=release, local=args.local, hashes=hashes)
            out.write("after apply:\n")
            print_plan(after, desired, out, note=False)
            if after.drifted():
                failures += 1
        return failures

    failures = with_session(args, "apply", work, client_factory)
    return EXIT_FAILED if failures else EXIT_OK


def add_options(parser, defaults):
    """The options every command takes. The top-level parser carries the defaults; each command's
    parser takes the same options with argparse.SUPPRESS as default, so a value given after the
    command replaces one given before it and an absent one leaves it alone."""

    def default(value):
        return value if defaults else argparse.SUPPRESS

    parser.add_argument(
        "--file", default=default(str(DEFAULT_FILE)), help="desired state (default: deploy/truenas.toml)"
    )
    parser.add_argument("--config", default=default(str(DEFAULT_CONFIG)), help="connection settings and key files")
    parser.add_argument(
        "--local",
        action="store_true",
        default=default(False),
        help="on the NAS as root: the local middleware socket; env files from secrets_dir",
    )
    parser.add_argument(
        "--no-hashes",
        action="store_true",
        default=default(False),
        help="as content_hashes = false: no x-local-agent-stack block; YAML and images compared only",
    )
    parser.add_argument("--root", default=default(None), help=argparse.SUPPRESS)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="deploy.py",
        description="Make the TrueNAS server run what deploy/truenas.toml says (docs/stack-design.md, section 8). "
        "The options --file, --config, --local and --no-hashes go before or after the command.",
        epilog="Exit codes: 0 ok, 1 a step failed, 2 usage or configuration, 3 drift (drift only).",
    )
    add_options(parser, defaults=True)
    common = argparse.ArgumentParser(add_help=False)
    add_options(common, defaults=False)
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    commands.add_parser("validate", parents=[common], help="check the desired state and the stack files it names")
    render = commands.add_parser("render", parents=[common], help="print each app's TrueNAS YAML (offline)")
    render.add_argument("--app")
    plan = commands.add_parser("plan", parents=[common], help="what apply would do (read-only key)")
    plan.add_argument("--app", action="append", default=[])
    apply = commands.add_parser("apply", parents=[common], help="create, update or redeploy the apps (full-admin key)")
    apply.add_argument("--app", action="append", default=[])
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--timeout", type=int, default=600, help="seconds to wait for each app to run")
    drift = commands.add_parser("drift", parents=[common], help="exit 3 when the NAS differs (read-only key)")
    drift.add_argument("--app", action="append", default=[])
    drift.add_argument("--issue", action="store_true", help="keep one open GitHub issue labelled deploy (gh)")
    commands.add_parser("status", parents=[common], help="one line per app (read-only key)")
    return parser.parse_args(argv)


def main(argv=None, out=None, client_factory=default_client_factory, runner=run_quiet):
    out = out or sys.stdout
    args = parse_args(argv)
    try:
        if args.command == "validate":
            return cmd_validate(args, out)
        if args.command == "render":
            return cmd_render(args, out, runner)
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
