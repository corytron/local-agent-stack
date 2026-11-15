#!/usr/bin/env python3
"""Check the relative links and heading anchors of every Markdown file in the repository, offline.

  check_links.py [--root DIR]

Files: every Markdown file git tracks or would track (git ls-files --cached --others
--exclude-standard '*.md': new files count before their first commit, ignored ones never).

Links: inline links and images ([text](target), ![alt](target)), reference definitions
([id]: target), and the href of <a> and the src of <img> written as HTML. Nothing inside a fenced
code block, a code span or an HTML comment is a link. Indented lines are read as text, because the
guide's callouts (!!! note) hold their text indented four spaces.

A link is broken when
  - its target is not a file or folder git tracks or would track. A relative target is taken from
    the linking file's folder; a leading / is the root of the repository, as on GitHub. A link to
    this repository on github.com (https://github.com/corytron/local-agent-stack/blob|tree|raw/main/
    <path>) is checked as the local <path>. Other http(s), mailto and scheme links are not checked
    (there is no network);
  - its #anchor names no place in the target. In a Markdown file: a heading by GitHub's slug rules
    (lower case; punctuation other than - and _ removed; each space becomes -; a repeated slug gets
    -1, -2, ...), or an id="..." or <a name="..."> written in HTML; #top always works.
    In a guide chapter (guide/chapters/*.md) an anchor may also name a heading of any chapter,
    with the ids tools/guide/build.py gives them: Python-Markdown's toc slugs (ASCII, lower case,
    punctuation removed, runs of spaces and hyphens become one -, a repeat within a chapter gets
    _1, _2, ...; {#id} sets one), made unique across the guide with -2, -3, ..., and each chapter's
    ch-<number or letter>, because the guide is one HTML document. On any other file only GitHub's
    line anchors (#L12, #L12-L20) are checked, against the file's length.

Output: one line per broken link, FILE:LINE: message, then "links: N files, M links checked,
K broken" (M counts the links that were checked: relative ones and those to this repository).

Files are parsed by up to JOBS processes at once (environment; default: the cores this process may
use; JOBS=1 one at a time). Standard library only; git runs read-only. Exit codes: 0 nothing broken,
1 broken links, 2 usage (bad arguments, not a git work tree, JOBS not a whole number from 1).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import html
import os
import posixpath
import re
import subprocess
import sys
import unicodedata
import urllib.parse

EXIT_OK, EXIT_BROKEN, EXIT_USAGE = 0, 1, 2

REPOSITORY = "corytron/local-agent-stack"
GUIDE_CHAPTERS = "guide/chapters/"
GUIDE_CONFIG = "guide/guide.yaml"
# Parse in a pool only when there are at least this many files: a pool costs more than a few files.
POOL_MIN_FILES = 8

FENCE_RE = re.compile(r"^ *(`{3,}|~{3,})(.*)$")
ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
ATTR_ID_RE = re.compile(r"[ \t]*\{[^}]*#([A-Za-z0-9_:.-]+)[^}]*\}[ \t]*$")
META_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:")
CODE_SPAN_RE = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
BRACKETS = r"\[(?:[^\[\]\\]|\\.|\[(?:[^\[\]\\]|\\.)*\])*\]"
DESTINATION = r"(<[^<>\n]*>|(?:[^\s()<>\\]|\\.|\((?:[^\s()\\]|\\.)*\))+)"
TITLE = r"""(?:[ \t]+(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\((?:[^()\\]|\\.)*\)))?"""
INLINE_LINK_RE = re.compile(r"(!?)" + BRACKETS + r"\([ \t]*" + DESTINATION + TITLE + r"[ \t]*\)")
EMPTY_LINK_RE = re.compile(r"(!?)" + BRACKETS + r"\([ \t]*\)")
DEFINITION_RE = re.compile(r"^ {0,3}\[((?:[^\[\]\\]|\\.)+)\]:[ \t]*(<[^<>\n]*>|\S+)")
HTML_LINK_RE = re.compile(r"""<(a|img)\b[^>]*?\s(href|src)\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+)""", re.IGNORECASE)
HTML_ID_RE = re.compile(r"""<[A-Za-z][A-Za-z0-9-]*\b[^>]*?\s(?:id|name)\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+)""")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
REPO_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/" + re.escape(REPOSITORY) + r"/(?:blob|tree|raw)/main(/[^?#]*)?([?#].*)?$",
    re.IGNORECASE,
)
LINE_ANCHOR_RE = re.compile(r"^L([0-9]+)(?:C[0-9]+)?(?:-L([0-9]+)(?:C[0-9]+)?)?$")
CHAPTER_LINE_RE = re.compile(r"^\s*-\s*['\"]?(chapters/[^'\"\s#]+)['\"]?\s*(?:#.*)?$")
KIND_RE = re.compile(r"^kind:\s*(\S+)", re.MULTILINE)
PM_IDCOUNT_RE = re.compile(r"^(.*)_([0-9]+)$")
# Lines that start a list item, a quote, a table row or a guide callout: never a setext heading's text.
BLOCK_STARTS = ("- ", "* ", "+ ", ">", "|", "!!!")
ORDERED_ITEM_RE = re.compile(r"[0-9]+[.)] ")


class UsageError(Exception):
    """A run that cannot start: printed to stderr, exit 2."""


@dataclasses.dataclass
class Heading:
    line: int
    level: int
    text: str  # the heading's raw Markdown text
    explicit_id: str | None = None  # {#id} (attr_list, the guide's Python-Markdown)


@dataclasses.dataclass
class Link:
    line: int
    target: str


@dataclasses.dataclass
class Parsed:
    path: str
    headings: list
    ids: set  # id="..." and name="..." written in HTML
    links: list
    lines: int
    error: str | None = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def strip_code_spans(text):
    """The text with every code span blanked out (same length, so columns stay where they were)."""
    return CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), text)


def unescape_target(target):
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", target).strip()


def parse_text(path, text):
    """The headings, HTML ids and links of one Markdown document."""
    text = COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    lines = text.split("\n")
    headings, ids, links = [], set(), []
    fence = None  # the opening fence (character, length) while inside a fenced code block
    previous = None  # (line number, text) of the previous paragraph line, for setext headings
    in_meta = path.startswith(GUIDE_CHAPTERS)  # Python-Markdown meta block at the top of a chapter
    for number, line in enumerate(lines, 1):
        if in_meta:
            if META_RE.match(line) or (line.startswith((" ", "\t")) and line.strip() and number > 1):
                continue
            in_meta = False
            if not line.strip():
                continue
        match = FENCE_RE.match(line)
        if fence is not None:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1]:
                if not match.group(2).strip():
                    fence = None
            continue
        if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence = (match.group(1)[0], len(match.group(1)))
            previous = None
            continue
        if not line.strip():
            previous = None
            continue
        atx = ATX_RE.match(line)
        if atx:
            headings.append(make_heading(number, len(atx.group(1)), atx.group(2) or ""))
            previous = None
        else:
            setext = SETEXT_RE.match(line)
            if setext and previous is not None:
                level = 1 if setext.group(1)[0] == "=" else 2
                headings.append(make_heading(previous[0], level, previous[1].strip()))
                previous = None
                continue
            stripped = line.lstrip()
            starts_block = stripped.startswith(BLOCK_STARTS) or ORDERED_ITEM_RE.match(stripped)
            previous = None if starts_block else (number, line)
        scan = strip_code_spans(line)
        for found in HTML_ID_RE.finditer(scan):
            ids.add(found.group(1).strip("\"'"))
        definition = DEFINITION_RE.match(scan)
        if definition:
            links.append(Link(number, unescape_target(line[definition.start(2) : definition.end(2)])))
            continue
        for found in INLINE_LINK_RE.finditer(scan):
            links.append(Link(number, unescape_target(line[found.start(2) : found.end(2)])))
        links.extend(Link(number, "") for _ in EMPTY_LINK_RE.finditer(scan))
        for found in HTML_LINK_RE.finditer(scan):
            value = line[found.start(3) : found.end(3)].strip("\"'")
            links.append(Link(number, html.unescape(value).strip()))
    return headings, ids, links, len(lines)


def make_heading(number, level, text):
    explicit = None
    match = ATTR_ID_RE.search(text)
    if match:
        explicit = match.group(1)
        text = text[: match.start()]
    return Heading(number, level, text.strip(), explicit)


def parse_file(root, path):
    try:
        with open(os.path.join(root, path), encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as error:
        return Parsed(path, [], set(), [], 0, "cannot read: %s" % error)
    headings, ids, links, count = parse_text(path, text)
    return Parsed(path, headings, ids, links, count)


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------


def rendered_text(markdown):
    """Roughly the text a heading renders to: link and image text kept, code spans' contents kept,
    emphasis markers, HTML tags and backslash escapes removed, entities decoded."""
    spans = []

    def keep_code(match):
        spans.append(match.group(2).strip() if match.group(2).strip() else match.group(2))
        return "\x00%d\x00" % (len(spans) - 1)

    text = CODE_SPAN_RE.sub(keep_code, markdown)
    text = re.sub(r"!?\[((?:[^\[\]\\]|\\.)*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"!?\[((?:[^\[\]\\]|\\.)*)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"(?<![A-Za-z0-9])_+|_+(?![A-Za-z0-9])", "", text)
    text = re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", text)
    text = html.unescape(text)
    text = re.sub(r"\x00([0-9]+)\x00", lambda m: spans[int(m.group(1))], text)
    return text.strip()


def github_slug(text):
    """GitHub's heading anchor (github-slugger): lower case, keep letters, numbers, marks, -, _ and
    spaces, then each space becomes a hyphen."""
    kept = []
    for char in rendered_text(text).lower():
        if char in "-_ " or unicodedata.category(char)[0] in "LNM":
            kept.append(char)
    return "".join(kept).replace(" ", "-")


def python_markdown_slug(text):
    """Python-Markdown's toc slugify: ASCII only, punctuation removed, lower case, runs of spaces
    and hyphens become one hyphen."""
    value = unicodedata.normalize("NFKD", rendered_text(text)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def github_anchors(parsed):
    anchors, seen = set(), {}
    for heading in parsed.headings:
        slug = github_slug(heading.text)
        if slug in seen:
            seen[slug] += 1
            slug = "%s-%d" % (slug, seen[slug])
        else:
            seen[slug] = 0
        anchors.add(slug)
    return anchors | parsed.ids | {"top"}


def python_markdown_unique(slug, used):
    """Python-Markdown's toc unique(): a used id (or an empty one) gets _1, then _2, ..."""
    while slug in used or not slug:
        match = PM_IDCOUNT_RE.match(slug)
        slug = "%s_%d" % (match.group(1), int(match.group(2)) + 1) if match else "%s_1" % slug
    used.add(slug)
    return slug


def read_text(path):
    """A file's text, or "" when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return ""


def guide_order(root, chapters):
    """The chapters in guide/guide.yaml's order (read without a YAML parser: its chapters list is
    one "- chapters/NN-slug.md" a line), then any others, sorted."""
    order = []
    for line in read_text(os.path.join(root, GUIDE_CONFIG)).splitlines():
        match = CHAPTER_LINE_RE.match(line)
        if match:
            order.append("guide/" + match.group(1))
    listed = [path for path in order if path in chapters]
    return listed + sorted(path for path in chapters if path not in listed)


def guide_anchors(root, parsed_by_path):
    """Every id the built guide has: the chapters' Python-Markdown heading ids, h2 and h3 made
    unique across the guide as tools/guide/build.py does, and ch-1, ch-2, ..., ch-a, ch-b, ..."""
    chapters = [path for path in parsed_by_path if path.startswith(GUIDE_CHAPTERS)]
    anchors, seen = set(), set()
    number, letter = 0, 0
    for path in guide_order(root, chapters):
        parsed = parsed_by_path[path]
        meta = read_text(os.path.join(root, path)).split("\n\n", 1)[0]
        match = KIND_RE.search(meta)
        kind = match.group(1) if match else "chapter"
        if kind == "appendix":
            label = chr(ord("a") + letter)
            letter += 1
        else:
            number += 1
            label = str(number)
        chapter_id = "ch-%s" % label
        anchors.add(chapter_id)
        seen.add(chapter_id)
        used = set()
        for heading in parsed.headings:
            slug = heading.explicit_id or python_markdown_unique(python_markdown_slug(heading.text), used)
            anchors.add(slug)
            if heading.level in (2, 3):
                unique, count = slug, 2
                while unique in seen:
                    unique, count = "%s-%d" % (slug, count), count + 1
                seen.add(unique)
                anchors.add(unique)
        anchors |= parsed.ids
    return anchors | {"top"}


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


def git_files(root):
    try:
        output = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise UsageError("cannot list the files of %s with git: %s" % (root, error)) from error
    files = {name for name in output.decode("utf-8", "surrogateescape").split("\0") if name}
    return {name for name in files if os.path.lexists(os.path.join(root, name))}


def folders_of(files):
    folders = set()
    for name in files:
        folder = posixpath.dirname(name)
        while folder and folder not in folders:
            folders.add(folder)
            folder = posixpath.dirname(folder)
    return folders


def line_count(root, path, cache):
    if path not in cache:
        try:
            with open(os.path.join(root, path), "rb") as handle:
                cache[path] = handle.read().count(b"\n") + 1
        except OSError:
            cache[path] = 0
    return cache[path]


class Checker:
    def __init__(self, root, files, parsed_by_path):
        self.root = root
        self.files = files
        self.folders = folders_of(files)
        self.parsed = parsed_by_path
        self.anchor_cache = {}
        self.lines_cache = {}
        self._guide = None

    def guide(self):
        if self._guide is None:
            self._guide = guide_anchors(self.root, self.parsed)
        return self._guide

    def anchors_of(self, path):
        if path not in self.anchor_cache:
            parsed = self.parsed.get(path)
            if parsed is None:
                parsed = parse_file(self.root, path)
                self.parsed[path] = parsed
            anchors = github_anchors(parsed)
            if path.startswith(GUIDE_CHAPTERS):
                anchors = anchors | self.guide()
            self.anchor_cache[path] = anchors
        return self.anchor_cache[path]

    def check(self, source, target):
        """None when the link works, else what is wrong; also whether the link was checked at all."""
        if not target:
            return "empty link target", True
        repo = REPO_URL_RE.match(target)
        if repo:
            target = "/" + (repo.group(1) or "/").lstrip("/") + (repo.group(2) or "")
        elif SCHEME_RE.match(target) or target.startswith("//"):
            return None, False
        path_part, _, fragment = target.partition("#")
        path_part = path_part.partition("?")[0]
        path_part = urllib.parse.unquote(path_part)
        fragment = urllib.parse.unquote(fragment)
        if not path_part:
            resolved = source
        else:
            if path_part.startswith("/"):
                joined = path_part.lstrip("/")
            else:
                joined = posixpath.join(posixpath.dirname(source), path_part)
            resolved = posixpath.normpath(joined) if joined else "."
            if resolved == ".":
                resolved = ""
            if resolved.startswith("../") or resolved == "..":
                return "%s points outside the repository" % path_part, True
            if resolved and resolved not in self.files and resolved not in self.folders:
                return "%s: no such file or folder (%s)" % (path_part, resolved), True
            if path_part.endswith("/") and resolved in self.files:
                return "%s: is a file, not a folder" % path_part, True
        if not fragment:
            return None, True
        if resolved.endswith(".md"):
            if fragment not in self.anchors_of(resolved):
                return "#%s: no such heading or id in %s" % (fragment, resolved or "."), True
            return None, True
        line_anchor = LINE_ANCHOR_RE.match(fragment)
        if line_anchor and resolved in self.files:
            count = line_count(self.root, resolved, self.lines_cache)
            last = int(line_anchor.group(2) or line_anchor.group(1))
            if int(line_anchor.group(1)) < 1 or last > count:
                return "#%s: %s has %d lines" % (fragment, resolved, count), True
        return None, True


def job_count(environ=None):
    environ = os.environ if environ is None else environ
    text = environ.get("JOBS", "")
    if text:
        if not re.fullmatch(r"[1-9][0-9]*", text):
            raise UsageError("JOBS must be a whole number from 1 (JOBS=1 runs serially), not %r" % text)
        return int(text)
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


def parse_all(root, paths, jobs):
    if jobs <= 1 or len(paths) < POOL_MIN_FILES:
        return [parse_file(root, path) for path in paths]
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(jobs, len(paths))) as pool:
        return list(pool.map(parse_file, [root] * len(paths), paths, chunksize=4))


def run(root, out, jobs):
    files = git_files(root)
    markdown = sorted(name for name in files if name.endswith(".md"))
    parsed = parse_all(root, markdown, jobs)
    by_path = {item.path: item for item in parsed}
    checker = Checker(root, files, by_path)
    checked = broken = 0
    for item in parsed:
        if item.error:
            out.write("%s:1: %s\n" % (item.path, item.error))
            broken += 1
            continue
        for link in item.links:
            problem, counted = checker.check(item.path, link.target)
            checked += counted
            if problem:
                broken += 1
                out.write("%s:%d: %s\n" % (item.path, link.line, problem))
    out.write("links: %d files, %d links checked, %d broken\n" % (len(markdown), checked, broken))
    return EXIT_BROKEN if broken else EXIT_OK


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(
        prog="check_links.py",
        description="Check the relative links and heading anchors of every Markdown file, offline.",
    )
    parser.add_argument("--root", default=None, help="top of the git work tree (default: this repository)")
    args = parser.parse_args(argv)
    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        if not os.path.isdir(os.path.join(root, ".git")) and not os.path.isfile(os.path.join(root, ".git")):
            raise UsageError("%s is not the top of a git work tree" % root)
        return run(root, out, job_count())
    except UsageError as error:
        print("check_links.py: error: %s" % error, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
