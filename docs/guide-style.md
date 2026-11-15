# Guide authoring contract

The deployment guide is written in Markdown, one file per chapter under `guide/chapters/`, and
rendered by `tools/guide/build.py` into a vendor-style A4 PDF (`build/guide/*.pdf`). The order
of chapters is `guide/guide.yaml`. Every chapter writer follows this file.

## File shape

```
title: <Chapter title>
kind: chapter            (or: appendix)

# <Chapter title>

One or two paragraphs introducing the chapter. The build puts a "Topics:" list of the
chapter's H2 headings under this introduction by itself; do not write one.

## <Topic>              (H2: a topic, listed in Topics and the contents)

### <Task or concept>   (H3: in the contents)

#### Prerequisites      (H4: task-block labels, not in the contents)
#### About this task
#### Steps
#### Results
#### Next steps
```

- The first line block is Python-Markdown `meta`: `title:` and optional `kind: appendix`.
  Appendices are lettered A, B, C in order; chapters numbered 1, 2, 3.
- H2 and H3 headings go in the contents with page numbers. Keep them short (one line).
  Headings must be unique across the whole guide (the build de-duplicates ids, but links break).
- Cross-references: `[Install the NVIDIA driver](#install-the-nvidia-driver)`, the anchor
  being the heading lowercased with spaces as hyphens.

## Voice (match a commercial vendor guide)

- Second person, present tense, imperative steps: "Click **Save**." "Run the following command."
- UI elements in bold, paths with `>`: **Apps** > **Configuration** > **Settings**.
- A task is: optional **Prerequisites**, **About this task** (what and why, one paragraph),
  **Steps** (numbered; each step one action; sub-results as a plain paragraph under the step,
  indented four spaces), **Results** (what the reader should now see), optional **Next steps**.
- Every command the reader types is in a fenced code block, copy-pasteable, one command per
  line where possible. Placeholders are in angle brackets and explained: `<truenas-ip>`.
- Verification after every major step: what to run and the exact expected output (or the shape
  of it).
- No marketing, no first person, no "simply", "just", "easy".
- Private data never appears: the server is `192.0.2.10` (`truenas.lab.example.com`), the workstation
  `192.0.2.20` (`c4dev`), the domain `lab.example.com`, the pool `tank`, keys `sk-local-...`.

## Elements

Callouts (indented four spaces under the line):

```
!!! note
    Text.

!!! caution
    Text about possible data loss or hardware damage (rendered bold).

!!! warning
    Text about credential exposure or loss of service (rendered bold).
```

Tables: a paragraph `Table: <Title>` directly above a pipe table; the build numbers tables
across the guide ("Table 7. Port assignments"). Keep tables to 2-5 columns.

Code: fenced blocks with no language tag needed. Long lines wrap in print; prefer breaking
commands with `\`.

Figures: `<figure markdown><img src="../figures/x.svg"><figcaption>Figure: ...</figcaption></figure>`
(only when a diagram genuinely helps; inline SVG under `guide/figures/`).

## Accuracy

Every version, image tag, flag, environment variable, UI label and port comes from the research
notes in `docs/research/` (which cite their sources) or from a primary source you checked. If
something is not verified, do not write it as fact: say what to check, or leave it out.
The files the guide tells the reader to install live in `stack/` and the guide quotes them;
when the guide and `stack/` disagree, `stack/` wins and the guide is the bug.
