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
from contextlib import redirect_stderr
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
        self.assertEqual(set(found), {"LAB_DOMAIN", "LOCAL_LLM_KEY", "MCP_HUB_TOKEN"})
        self.assertIn("--share web.env", text)
        self.assertTrue(text.startswith("# client.env, written by tools/secrets.py gen client.\n"))

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
            "client LAB_DOMAIN shared",
            "client LOCAL_LLM_KEY provided",
            "client MCP_HUB_TOKEN shared",
        ):
            self.assertIn(line, out.getvalue())

    def test_repository_examples_list_every_generated_secret(self):
        for app in ("inference", "rag", "web", "edge", "client"):
            example = secrets_tool.example_path(app)
            if not example.is_file():
                continue  # still being written
            text = example.read_text(encoding="utf-8")
            for name in secrets_tool.VARIABLES[app]:
                with self.subTest(app=app, name=name):
                    self.assertRegex(text, rf"(?m)^#?\s*{name}=")


class TestClient(unittest.TestCase):
    """gen client: clients/client.env.example filled from web.env and a prompt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.web = self.dir / "web.env"
        self.web.write_text("LAB_DOMAIN=lab.example.com\nMCP_HUB_TOKEN=HubToken123\nWEBUI_SECRET_KEY=other\n")
        self.prompts = []

    def ask(self, answer):
        def prompt(text):
            self.prompts.append(text)
            return answer

        return prompt

    def run_gen(self, *argv, answer="sk-local-example-key"):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stderr(err):
            code = secrets_tool.main(["gen", "client", *argv], out=out, ask=self.ask(answer))
        return code, out.getvalue(), err.getvalue()

    def test_repository_example_says_where_each_value_comes_from(self):
        text = secrets_tool.example_path("client").read_text(encoding="utf-8")
        self.assertEqual(set(values(text)), {"LAB_DOMAIN", "LOCAL_LLM_KEY", "MCP_HUB_TOKEN"})
        for part in ("edge.env", "chapter 4", "MCP_HUB_TOKEN in web.env", "--share web.env", "--ask LOCAL_LLM_KEY"):
            self.assertIn(part, text)

    def test_share_copies_the_hub_token_and_the_domain_from_web_env(self):
        code, text, err = self.run_gen("--share", str(self.web))
        self.assertEqual(code, 0, err)
        found = values(text)
        self.assertEqual(found["MCP_HUB_TOKEN"], "HubToken123")
        self.assertEqual(found["LAB_DOMAIN"], "lab.example.com")
        self.assertEqual(found["LOCAL_LLM_KEY"], "sk-local-replace-with-your-litellm-virtual-key")
        self.assertNotIn("WEBUI_SECRET_KEY", text)
        self.assertEqual(err, "")
        self.assertEqual(self.prompts, [])

    def test_without_share_the_placeholders_are_named(self):
        code, text, err = self.run_gen()
        self.assertEqual(code, 0)
        self.assertEqual(values(text)["MCP_HUB_TOKEN"], "replace-with-the-mcp-hub-token")
        self.assertIn("MCP_HUB_TOKEN is a placeholder: run gen client with --share <web.env>", err)

    def test_ask_reads_the_key_without_printing_it(self):
        target = self.dir / "client.env"
        code, text, err = self.run_gen("--share", str(self.web), "--ask", "LOCAL_LLM_KEY", "-o", str(target))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.prompts, ["LOCAL_LLM_KEY: "])
        self.assertEqual(values(target.read_text())["LOCAL_LLM_KEY"], "sk-local-example-key")
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)
        self.assertNotIn("sk-local-example-key", text + err)

    def test_ask_refuses_what_it_cannot_take(self):
        for argv, answer, message in (
            (["--ask", "NOPE"], "x", "has no such variable"),
            (["--ask", "LOCAL_LLM_KEY"], "", "no value entered"),
            (["--ask", "LOCAL_LLM_KEY"], "sk-local with space", "the value may hold only"),
            (["--ask", "LOCAL_LLM_KEY"], "sk-local-$(id)", "the value may hold only"),
        ):
            with self.subTest(argv=argv, answer=answer):
                code, text, err = self.run_gen(*argv, answer=answer)
                self.assertEqual(code, 2)
                self.assertIn(message, err)
                self.assertEqual(text, "")
        err = io.StringIO()
        with redirect_stderr(err):
            code = secrets_tool.main(["gen", "inference", "--ask", "LITELLM_MASTER_KEY"], out=io.StringIO(), ask=str)
        self.assertEqual(code, 2)
        self.assertIn("gen generates this value", err.getvalue())

    def test_output_sources_in_a_shell(self):
        target = self.dir / "client.env"
        code, _, err = self.run_gen("--share", str(self.web), "--ask", "LOCAL_LLM_KEY", "-o", str(target))
        self.assertEqual(code, 0, err)
        done = subprocess.run(
            [
                "sh",
                "-c",
                'set -eu; . "$1"; printf "%s %s %s" "$LAB_DOMAIN" "$LOCAL_LLM_KEY" "$MCP_HUB_TOKEN"',
                "sh",
                target,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "lab.example.com sk-local-example-key HubToken123")


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
