"""Unit tests of tools/secrets.py."""

import importlib.util
import io
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(f"las_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


secrets_tool = load("secrets")

GENERATED_RE = re.compile(r"^[A-Za-z0-9]{48}$")
KEY_RE = re.compile(r"^sk-[A-Za-z0-9]{48}$")

EXAMPLE = """\
# Example for the inference app.
LITELLM_MASTER_KEY=sk-local-change-me
LITELLM_SALT_KEY=sk-local-change-me
LITELLM_DB_PASSWORD=change-me
LLAMA_SWAP_API_KEY=sk-local-change-me
# AI_ROOT=/mnt/tank/ai
TZ=Etc/UTC
"""


def values(text):
    found = {}
    for line in text.splitlines():
        match = secrets_tool.ASSIGNMENT_RE.match(line)
        if match:
            found[match.group(2)] = match.group(3)
    return found


class TestGenerate(unittest.TestCase):
    def test_every_generated_secret_is_new_and_random(self):
        text = secrets_tool.generate("inference", EXAMPLE)
        found = values(text)
        self.assertRegex(found["LITELLM_MASTER_KEY"], KEY_RE)
        self.assertRegex(found["LITELLM_SALT_KEY"], KEY_RE)
        self.assertRegex(found["LLAMA_SWAP_API_KEY"], KEY_RE)
        self.assertRegex(found["LITELLM_DB_PASSWORD"], GENERATED_RE)
        self.assertEqual(len({found[name] for name in secrets_tool.VARIABLES["inference"]}), 4)
        self.assertNotEqual(found, values(secrets_tool.generate("inference", EXAMPLE)))

    def test_other_lines_are_kept(self):
        text = secrets_tool.generate("inference", EXAMPLE)
        self.assertIn("# Example for the inference app.\n", text)
        self.assertIn("# AI_ROOT=/mnt/tank/ai\n", text)
        self.assertIn("TZ=Etc/UTC\n", text)
        self.assertNotIn("change-me", text)

    def test_missing_variables_are_added(self):
        text = secrets_tool.generate("rag", "PG_PASSWORD=x\n")
        found = values(text)
        self.assertRegex(found["PG_PASSWORD"], GENERATED_RE)
        self.assertRegex(found["DOCLING_API_KEY"], GENERATED_RE)
        self.assertRegex(found["OIKB_API_KEY"], GENERATED_RE)
        self.assertEqual(found["OIKB_TOKEN"], "replace-with-oikb-token")
        self.assertIn("# Set later: the API key of Open WebUI's indexer user", text)
        self.assertIn("# Not in the example file", text)

    def test_reader_provided_values_stay_placeholders(self):
        example = (
            "LAB_DOMAIN=lab.example.com\nACME_EMAIL=admin@example.com\nDNS_PROVIDER=cloudflare\nDNS_PROVIDER_TOKEN=x\n"
        )
        self.assertEqual(values(secrets_tool.generate("edge", example)), values(example))

    def test_shared_value_is_copied_not_generated(self):
        example = "PG_PASSWORD=same-as-rag\nDOCLING_API_KEY=same-as-rag\n"
        text = secrets_tool.generate("web", example, shared={"PG_PASSWORD": "fromRag123", "DOCLING_API_KEY": "d0c"})
        self.assertEqual(values(text)["PG_PASSWORD"], "fromRag123")
        self.assertEqual(values(text)["DOCLING_API_KEY"], "d0c")
        text = secrets_tool.generate("web", example)
        self.assertEqual(values(text)["PG_PASSWORD"], "same-as-rag")

    def test_mcp_hub_token_and_database_passwords_are_url_safe(self):
        found = values(secrets_tool.generate("web", None))
        self.assertRegex(found["MCP_HUB_TOKEN"], r"^[A-Za-z0-9._~+/-]+$")
        self.assertRegex(values(secrets_tool.generate("rag", None))["PG_PASSWORD"], r"^[A-Za-z0-9]+$")
        self.assertRegex(values(secrets_tool.generate("inference", None))["LITELLM_DB_PASSWORD"], r"^[A-Za-z0-9]+$")

    def test_without_example(self):
        text = secrets_tool.generate("client", None)
        found = values(text)
        self.assertEqual(set(found), {"LOCAL_LLM_KEY", "MCP_HUB_TOKEN"})
        self.assertIn("--share web.env", text)

    def test_unknown_app(self):
        with self.assertRaises(secrets_tool.UsageError):
            secrets_tool.generate("nope", None)
        self.assertEqual(secrets_tool.main(["gen", "nope"], out=io.StringIO()), 2)

    def test_section_6_names(self):
        out = io.StringIO()
        self.assertEqual(secrets_tool.main(["names"], out=out), 0)
        for line in (
            "inference LITELLM_MASTER_KEY key",
            "rag OIKB_TOKEN provided",
            "web PG_PASSWORD shared",
            "web MCP_HUB_TOKEN secret",
            "edge DNS_PROVIDER_TOKEN provided",
        ):
            self.assertIn(line, out.getvalue())

    def test_repository_examples_list_every_generated_secret(self):
        for app in ("inference", "rag", "web", "edge"):
            example = secrets_tool.example_path(app)
            if not example.is_file():
                continue  # still being written
            text = example.read_text(encoding="utf-8")
            for name in secrets_tool.VARIABLES[app]:
                with self.subTest(app=app, name=name):
                    self.assertRegex(text, rf"(?m)^#?\s*{name}=")


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_share_file_is_read(self):
        rag = self.dir / "rag.env"
        rag.write_text('PG_PASSWORD="abc123"\nDOCLING_API_KEY=zzz\n')
        example = self.dir / "web.env.example"
        example.write_text("PG_PASSWORD=placeholder\n")
        out = io.StringIO()
        code = secrets_tool.main(["gen", "web", "--example", str(example), "--share", str(rag)], out=out)
        self.assertEqual(code, 0)
        self.assertEqual(values(out.getvalue())["PG_PASSWORD"], "abc123")
        self.assertEqual(values(out.getvalue())["DOCLING_API_KEY"], "zzz")

    def test_output_file_is_private_and_never_replaced(self):
        target = self.dir / "inference.env"
        example = self.dir / "inference.env.example"
        example.write_text(EXAMPLE)
        self.assertEqual(secrets_tool.main(["gen", "inference", "--example", str(example), "-o", str(target)]), 0)
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)
        before = target.read_text()
        self.assertEqual(secrets_tool.main(["gen", "inference", "--example", str(example), "-o", str(target)]), 1)
        self.assertEqual(target.read_text(), before)

    def test_runs_as_a_script_beside_its_namesake(self):
        """python3 tools/secrets.py must import the standard library's secrets, not itself."""
        done = subprocess.run(
            [sys.executable, "-B", str(TOOLS / "secrets.py"), "gen", "rag", "--example", os.devnull],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(values(done.stdout)["PG_PASSWORD"], GENERATED_RE)


if __name__ == "__main__":
    unittest.main()
