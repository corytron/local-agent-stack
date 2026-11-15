"""Unit tests of tools/check_links.py on small throw-away git repositories."""

import importlib.util
import io
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(f"las_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


links = load("check_links")


class TestSlugs(unittest.TestCase):
    def test_github_slug(self):
        cases = {
            "Install the NVIDIA driver": "install-the-nvidia-driver",
            "What's `app.config`?": "whats-appconfig",
            "A - B": "a---b",
            "my_var and *emphasis*": "my_var-and-emphasis",
            "[Link text](x.md) here": "link-text-here",
            "Ünïcode Heading": "ünïcode-heading",
            "_under_ score": "under-score",
        }
        for text, slug in cases.items():
            with self.subTest(text=text):
                self.assertEqual(links.github_slug(text), slug)

    def test_python_markdown_slug(self):
        cases = {
            "Install the NVIDIA driver": "install-the-nvidia-driver",
            "A - B": "a-b",
            "Ünïcode Heading": "unicode-heading",
            "What's `app.config`?": "whats-appconfig",
        }
        for text, slug in cases.items():
            with self.subTest(text=text):
                self.assertEqual(links.python_markdown_slug(text), slug)

    def test_python_markdown_unique(self):
        used = set()
        self.assertEqual(
            [links.python_markdown_unique("steps", used) for _ in range(3)], ["steps", "steps_1", "steps_2"]
        )


class TestParse(unittest.TestCase):
    def test_links_headings_and_code(self):
        text = textwrap.dedent(
            """\
            # Title

            See [one](a.md#x) and ![img](pic.png "t") and [nested [b]](c.md).
            Not in `[code](nope.md)` spans.
            <!-- [hidden](nope.md) -->
            ```
            [fenced](nope.md)
            ```
            [ref]: <d e.md>
            <a href="f.md">x</a> <img src='g.png'>
            Setext
            ------
            [empty]()
            <a id="custom"></a>
            """
        )
        headings, ids, found, _ = links.parse_text("doc.md", text)
        targets = [link.target for link in found]
        self.assertEqual(targets, ["a.md#x", "pic.png", "c.md", "d e.md", "f.md", "g.png", ""])
        self.assertEqual([(h.level, h.text) for h in headings], [(1, "Title"), (2, "Setext")])
        self.assertEqual(ids, {"custom"})

    def test_guide_meta_block_and_attr_ids(self):
        text = "title: Intro\nkind: chapter\n\n# Intro\n\n## Topic {#my-id}\n\n!!! note\n    See [x](#topic).\n"
        headings, _, found, _ = links.parse_text("guide/chapters/01-intro.md", text)
        self.assertEqual(
            [(h.level, h.text, h.explicit_id) for h in headings], [(1, "Intro", None), (2, "Topic", "my-id")]
        )
        self.assertEqual([link.target for link in found], ["#topic"])


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(text))

    def check(self):
        out = io.StringIO()
        code = links.run(str(self.root), out, 1)
        return code, out.getvalue()


class TestRun(Repo):
    def test_good_links(self):
        self.write("README.md", "# Top\n\n[Docs](docs/) [Guide](docs/guide.md#a-heading) [Self](#top-1)\n\n## Top\n")
        self.write("docs/guide.md", "# Guide\n\n## A heading\n\n[back](../README.md) [line](../tools/x.py#L2)\n")
        self.write("tools/x.py", "a = 1\nb = 2\n")
        self.write(
            "docs/links.md",
            "[repo](https://github.com/corytron/local-agent-stack/blob/main/tools/x.py) [web](https://example.com/x)\n",
        )
        code, text = self.check()
        self.assertEqual(code, 0, text)
        self.assertIn("links: 3 files, 6 links checked, 0 broken", text)

    def test_broken_links(self):
        self.write(
            "README.md",
            "# Top\n\n[a](missing.md) [b](docs/guide.md#nope) [c](../outside.md) [d](tools/x.py#L9) [e]()\n"
            "[f](https://github.com/corytron/local-agent-stack/tree/main/gone/)\n",
        )
        self.write("docs/guide.md", "# Guide\n")
        self.write("tools/x.py", "a = 1\n")
        code, text = self.check()
        self.assertEqual(code, 1)
        for part in (
            "README.md:3: missing.md: no such file or folder",
            "README.md:3: #nope: no such heading or id in docs/guide.md",
            "README.md:3: ../outside.md points outside the repository",
            "README.md:3: #L9: tools/x.py has 2 lines",
            "README.md:3: empty link target",
            "README.md:4: /gone/: no such file or folder",
        ):
            self.assertIn(part, text)

    def test_ignored_files_are_not_targets(self):
        self.write(".gitignore", "build/\n")
        self.write("build/out.html", "x")
        self.write("README.md", "[out](build/out.html)\n")
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("no such file or folder", text)

    def test_guide_anchors_are_guide_wide(self):
        self.write("guide/guide.yaml", "chapters:\n  - chapters/01-a.md\n  - chapters/a-app.md\n")
        self.write(
            "guide/chapters/01-a.md",
            "title: A\n\n# A\n\n## Steps\n\nSee [b](#where-it-falls-short), [c](#steps-2), [d](#ch-a), [e](#nope).\n",
        )
        self.write(
            "guide/chapters/a-app.md",
            "title: App\nkind: appendix\n\n# App\n\n## Where it falls short\n\n## Steps\n\n#### Steps\n",
        )
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("guide/chapters/01-a.md:7: #nope: no such heading", text)
        self.assertEqual(text.count("no such heading"), 1, text)

    def test_jobs_must_be_a_number(self):
        with self.assertRaises(links.UsageError):
            links.job_count({"JOBS": "0"})
        self.assertEqual(links.job_count({"JOBS": "3"}), 3)

    def test_parallel_and_serial_agree(self):
        """The script itself, with a process pool (JOBS=4) and without (JOBS=1)."""
        for index in range(12):
            self.write(f"docs/d{index}.md", f"# D{index}\n\n[next](d{index + 1}.md) [self](#d{index})\n")
        outputs = []
        for jobs in ("1", "4"):
            done = subprocess.run(
                [sys.executable, "-I", "-B", str(TOOLS / "check_links.py"), "--root", str(self.root)],
                capture_output=True,
                text=True,
                check=False,
                env={"JOBS": jobs, "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(done.returncode, 1, done.stderr)
            outputs.append(done.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn("docs/d11.md:3: d12.md: no such file or folder", outputs[0])


if __name__ == "__main__":
    unittest.main()
