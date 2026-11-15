#!/usr/bin/env python3
"""Render the deployment guide (guide/guide.yaml + guide/chapters/*.md) to build/guide/*.pdf.

Pipeline (docs/guide-style.md is the authoring contract):
  1. Render every chapter's Markdown to HTML in parallel (one process per chapter, JOBS caps).
  2. Assemble one HTML document: cover, notes page, contents, chapters, appendices.
  3. Print it with headless Chromium twice: pass 1 finds the page of every heading from the
     PDF's named destinations (pdfinfo -dests), pass 2 prints the contents with those numbers.
     The contents length does not depend on the numbers, so two passes are exact.

Usage: tools/guide/build.py [--html-only] [--out build/guide]
Env:   CHROME=<chromium binary>  JOBS=<max processes>
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown
import yaml

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "guide"
TEMPLATE = GUIDE / "template"

EXTENSIONS = ["tables", "fenced_code", "admonition", "attr_list", "md_in_html", "sane_lists", "meta", "toc"]
EXT_CONFIG = {"toc": {"permalink": False, "toc_depth": "2-3"}}


def slug_unique(seen: set[str], base: str) -> str:
	s, n = base, 2
	while s in seen:
		s, n = f"{base}-{n}", n + 1
	seen.add(s)
	return s


def nest_fences(text: str) -> str:
	"""Turn indented ``` fences (code inside a list item) into indented code blocks.

	Python-Markdown's fenced_code extension only recognises fences at column 0, so a fence under a
	numbered step would render as inline code. An indented code block (fence indent + 4 spaces)
	is what Markdown nests inside list items.
	"""
	out, lines, i = [], text.split("\n"), 0
	while i < len(lines):
		m = re.match(r"^( +)(```|~~~)[^`]*$", lines[i])
		if not m:
			out.append(lines[i])
			i += 1
			continue
		indent, fence = m.group(1), m.group(2)
		j = i + 1
		while j < len(lines) and lines[j].strip() != fence:
			j += 1
		body = lines[i + 1:j]
		if out and out[-1].strip():
			out.append("")
		pad = indent + "    "
		out.extend(pad + (b[len(indent):] if b.startswith(indent) else b.lstrip()) if b.strip() else "" for b in body)
		out.append("")
		i = j + 1
	return "\n".join(out)


INCLUDE = re.compile(r"^( *)\{\{\s*include\s+(\S+)(?:\s+lines=(\d+)-(\d+))?\s*\}\}\s*$", re.M)


def expand_includes(text: str, path: str) -> str:
	"""Replace `{{ include <repo-relative path> [lines=A-B] }}` with a fenced copy of that file.

	The guide quotes stack/ and clients/ files this way, so the printed text is always the file
	that ships (docs/guide-style.md). A missing file or line range fails the build.
	"""
	def repl(m: re.Match) -> str:
		indent, rel = m.group(1), m.group(2)
		src = ROOT / rel
		if not src.is_file():
			raise SystemExit(f"{path}: include of missing file {rel}")
		lines = src.read_text(encoding="utf-8").rstrip("\n").split("\n")
		if m.group(3):
			a, b = int(m.group(3)), int(m.group(4))
			if not 1 <= a <= b <= len(lines):
				raise SystemExit(f"{path}: include {rel} lines={a}-{b} out of range (1-{len(lines)})")
			lines = lines[a - 1:b]
		body = "\n".join(indent + ln if ln else "" for ln in lines)
		return f"{indent}```\n{body}\n{indent}```"
	return INCLUDE.sub(repl, text)


def render_chapter(path: str) -> dict:
	"""Markdown -> {title, kind, html, headings[(level, id, text)]}; runs in a worker process."""
	text = nest_fences(expand_includes(Path(path).read_text(encoding="utf-8"), path))
	md = markdown.Markdown(extensions=EXTENSIONS, extension_configs=EXT_CONFIG)
	body = md.convert(text)
	meta = {k: " ".join(v) for k, v in md.Meta.items()}
	title = meta.get("title")
	m = re.search(r"<h1[^>]*>(.*?)</h1>\s*", body, re.S)
	if m:
		title = title or re.sub(r"<[^>]+>", "", m.group(1)).strip()
		body = body[: m.start()] + body[m.end():]
	if not title:
		raise SystemExit(f"{path}: no title (meta 'title:' or a '# ' heading)")
	# intro = everything before the first h2: goes above the Topics list, as the vendor guide does
	m2 = re.search(r"<h2[\s>]", body)
	intro, rest = (body[: m2.start()], body[m2.start():]) if m2 else (body, "")
	headings = [(int(l), i, re.sub(r"<[^>]+>", "", t).strip())
		for l, i, t in re.findall(r'<h([23]) id="([^"]+)">(.*?)</h\1>', rest, re.S)]
	return {"path": path, "title": title, "kind": meta.get("kind", "chapter"), "intro": intro,
		"html": rest, "headings": headings}


def number_figures(doc: str) -> str:
	doc = doc.replace('src="../figures/', f'src="{(GUIDE / "figures").as_uri()}/')
	n = 0

	def repl(m: re.Match) -> str:
		nonlocal n
		n += 1
		return f"<figcaption>Figure {n}. {m.group(1)}</figcaption>"
	return re.sub(r"<figcaption>\s*Figure:\s*(.*?)</figcaption>", repl, doc, flags=re.S)


def number_tables(doc: str) -> str:
	n = 0

	def repl(m: re.Match) -> str:
		nonlocal n
		n += 1
		return f'<p class="table-caption">Table {n}. {m.group(1)}</p>\n<table'
	return re.sub(r"<p>Table:\s*(.*?)</p>\s*<table", repl, doc, flags=re.S)


def build_html(cfg: dict, chapters: list[dict], pages: dict[str, int] | None) -> str:
	seen: set[str] = set()
	css_pages, body_parts, toc_rows = [], [], []
	ch_no, app_no = 0, 0
	for i, ch in enumerate(chapters):
		if ch["kind"] == "appendix":
			label = chr(ord("A") + app_no)
			app_no += 1
			toc_label = f"Appendix {label}: {ch['title']}"
		else:
			ch_no += 1
			label = str(ch_no)
			toc_label = f"Chapter {label}: {ch['title']}"
		cid = slug_unique(seen, f"ch-{label.lower()}")
		# make heading ids unique across the whole document
		body = ch["html"]
		heads = []
		for lvl, hid, text in ch["headings"]:
			uid = slug_unique(seen, hid)
			if uid != hid:
				body = body.replace(f'id="{hid}"', f'id="{uid}"', 1)
			heads.append((lvl, uid, text))
		# H4/H5 task labels ("Steps", "Prerequisites") repeat in every task: make their ids unique too
		body = re.sub(r'<h([45]) id="([^"]+)">', lambda m: f'<h{m.group(1)} id="{slug_unique(seen, m.group(2))}">', body)
		page = f"c{i}"
		title_css = ch["title"].replace("\\", "\\\\").replace('"', '\\"')
		css_pages.append(
			f'@page {page}:left {{ @bottom-left {{ content: counter(page) "\\2003\\2003 {title_css}"; padding-left: 14mm; }} }}\n'
			f'@page {page}:right {{ @bottom-right {{ content: "{title_css}\\2003\\2003 " counter(page); padding-right: 14mm; }} }}')
		topics = "".join(f'<li><a href="#{h[1]}">{html.escape(h[2])}</a></li>' for h in heads if h[0] == 2)
		topics_html = f'<div class="topics"><h4>Topics:</h4><ul>{topics}</ul></div>' if topics else ""
		tab_cls = "tab appendix" if ch["kind"] == "appendix" else "tab"
		body_parts.append(
			f'<section class="chapter" style="page: {page}">'
			f'<div class="opener"><div class="{tab_cls}">{label}</div>'
			f'<h1 id="{cid}">{html.escape(ch["title"])}</h1></div>'
			f'{ch["intro"]}{topics_html}{body}</section>')

		def pg(anchor: str) -> str:
			return str(pages.get(anchor, "")) if pages else "0"
		toc_rows.append(f'<li class="lvl1"><a class="row" href="#{cid}"><span class="label">{html.escape(toc_label)}</span>'
			f'<span class="dots"></span><span class="pg">{pg(cid)}</span></a></li>')
		for lvl, uid, text in heads:
			toc_rows.append(f'<li class="lvl{lvl}"><a class="row" href="#{uid}"><span class="label">{html.escape(text)}</span>'
				f'<span class="dots"></span><span class="pg">{pg(uid)}</span></a></li>')

	css_pages.append('@page toc:left { @bottom-left { content: counter(page) "\\2003\\2003 Contents"; padding-left: 14mm; } }\n'
		'@page toc:right { @bottom-right { content: "Contents\\2003\\2003 " counter(page); padding-right: 14mm; } }')
	css = (TEMPLATE / "guide.css").read_text(encoding="utf-8")
	esc = html.escape
	notes = (
		'<div class="admonition note"><p class="admonition-title">Note</p><p>A NOTE indicates important information that helps you make better use of the stack.</p></div>'
		'<div class="admonition caution"><p class="admonition-title">Caution</p><p>A CAUTION indicates either potential damage to hardware or loss of data and tells you how to avoid the problem.</p></div>'
		'<div class="admonition warning"><p class="admonition-title">Warning</p><p>A WARNING indicates a potential for exposure of data or credentials, or loss of service, and tells you how to avoid it.</p></div>')
	doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{esc(cfg['product'])} {esc(cfg['version'])} {esc(cfg['doc'])}</title>
<meta name="author" content="{esc(cfg.get('author', ''))}">
<style>{css}
{chr(10).join(css_pages)}
.toc {{ page: toc; }}
</style></head><body>
<div class="cover"><div class="title-block"><h1>{esc(cfg['product'])} {esc(cfg['version'])}</h1>
<p class="subtitle">{esc(cfg['doc'])}</p></div>
<div class="band"><div class="meta">{esc(cfg['date'])}<br>Rev. {esc(cfg['rev'])}</div>
<div class="wordmark">{cfg['wordmark']}</div></div></div>
<div class="notes-page"><h2>Notes, cautions, and warnings</h2>{notes}
<p class="legal">{esc(cfg.get('legal', ''))}</p></div>
<nav class="toc"><div class="toc-head">Contents</div><ol>{''.join(toc_rows)}</ol></nav>
{''.join(body_parts)}
</body></html>"""
	return number_figures(number_tables(doc))


def chrome_bin() -> str:
	for c in [os.environ.get("CHROME"), "chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]:
		if c and shutil.which(c):
			return c
	raise SystemExit("no Chromium found; set CHROME")


def print_pdf(src: Path, pdf: Path) -> None:
	cmd = [chrome_bin(), "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
		"--generate-pdf-document-outline", f"--print-to-pdf={pdf}", src.as_uri()]
	r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
	if r.returncode != 0 or not pdf.exists():
		sys.stderr.write(r.stderr)
		raise SystemExit("Chromium failed to print the guide")


def read_dests(pdf: Path) -> dict[str, int]:
	out = subprocess.run(["pdfinfo", "-dests", str(pdf)], capture_output=True, text=True, check=True).stdout
	pages = {}
	for line in out.splitlines():
		m = re.match(r'\s*(\d+)\s+\[.*\]\s+"(.*)"\s*$', line)
		if m:
			pages[m.group(2)] = int(m.group(1))
	return pages


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--out", default=str(ROOT / "build" / "guide"))
	ap.add_argument("--html-only", action="store_true")
	a = ap.parse_args()
	cfg = yaml.safe_load((GUIDE / "guide.yaml").read_text(encoding="utf-8"))
	files = [str(GUIDE / f) for f in cfg["chapters"]]
	jobs = int(os.environ.get("JOBS", os.cpu_count() or 1))
	with cf.ProcessPoolExecutor(max_workers=max(1, min(jobs, len(files)))) as ex:
		chapters = list(ex.map(render_chapter, files))
	out = Path(a.out)
	out.mkdir(parents=True, exist_ok=True)
	stem = cfg.get("filename", "deployment-guide")
	src = out / f"{stem}.html"
	src.write_text(build_html(cfg, chapters, None), encoding="utf-8")
	if a.html_only:
		print(src)
		return
	pdf = out / f"{stem}.pdf"
	print_pdf(src, pdf)
	pages = read_dests(pdf)
	src.write_text(build_html(cfg, chapters, pages), encoding="utf-8")
	print_pdf(src, pdf)
	missing = [c for c in chapters if not pages]
	if missing:
		raise SystemExit("no named destinations found in the PDF; contents has no page numbers")
	print(pdf)


if __name__ == "__main__":
	main()
