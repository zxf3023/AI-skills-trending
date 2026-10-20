<h1 align="center">AI Skills Trending</h1>

<p align="center">
  <strong>See which AI and Agent Skill projects are actually trending, in one HTML report.</strong><br />
  Pulls the GitHub boards, classifies every project, deduplicates, and writes a report you can read in five minutes.
</p>

<p align="center">
  <a href="#get-started"><strong>Get started</strong></a>
  ·
  <a href="#what-ends-up-in-the-report">Report contents</a>
  ·
  <a href="#github-token-optional-but-recommended">GitHub token</a>
  ·
  <a href="#command-line">Command line</a>
  ·
  <a href="#data-method">Data method</a>
  ·
  <a href="#troubleshooting">Troubleshooting</a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.8%2B-3776AB?logo=python&logoColor=white" alt="Python 3.8 or newer" /></a>
  <img src="https://img.shields.io/badge/dependencies-none-2ea44f" alt="No dependencies" />
  <img src="https://img.shields.io/badge/pip%20install-not%20required-2ea44f" alt="No pip install required" />
  <img src="https://img.shields.io/badge/license-not%20specified-lightgrey" alt="License not specified" />
</p>

<div align="center">

[中文](./README.md) | English

</div>

---

## What this is

GitHub's trending boards mix everything together: model releases, agent runtimes, skill packs, plugins, and a long tail of unrelated projects. Working out which entries are worth your time takes a lot of scrolling.

AI Skills Trending does that pass for you. One run fetches the official GitHub Trending boards plus topic searches, sorts everything into **AI** and **Agent Skill**, deduplicates across boards, ranks by total stars, and renders a single HTML report where every project carries a link, a star count, and a plain-language note on what it does.

Pure Python standard library. Nothing to `pip install`. Ships as a GUI and a CLI.

---

## How a run works

| Step | What happens |
|---|---|
| **1. Fetch** | Pulls the official Trending daily, weekly and monthly boards |
| **2. Expand** | Runs topic searches for the All-time, Monthly, Weekly and Daily boards, top N per board |
| **3. Classify** | Sorts each project into the AI or Agent Skill section, deduplicates across boards, ranks by total stars |
| **4. Render** | Writes the HTML report: summary tables plus a detail card per project |

The All-time board comes from GitHub Search sorted by total stars. The monthly, weekly and daily boards combine the Trending page with a date-window search, because the Trending page has no pagination and stops at roughly 25 entries.

---

## Get started

### Requirements

- Python 3.8 or newer ([download](https://www.python.org/downloads/))
- Tick **Add python.exe to PATH** during installation
- No third-party packages

### Option 1: one click (Windows)

Double-click `run_report.bat`. The launcher probes for an interpreter in this order: `py -3`, then `python`, then the Microsoft Store build. If none is found it prints the download link and pauses.

### Option 2: the GUI

```bash
python github_trending_report.py
```

| Field | What it does |
|---|---|
| Output folder | Where the HTML report is saved. Use **Browse...** to pick one |
| Boards | All-time / Monthly / Weekly / Daily. Tick any combination |
| Per-board limit | Set separately for AI and Agent Skill, 1-100 each |
| Output scope | Everything / Skill projects only / AI projects only |
| GitHub Token | Optional. Paste, then click **Confirm** to verify and activate it |

### Option 3: the command line

```bash
python github_trending_report.py --cli \
    --out-dir "D:/reports" \
    --boards all-time,monthly,weekly,daily \
    --topn-ai 50 --topn-sk 50 \
    --only all \
    --token ghp_xxx
```

| Flag | Meaning |
|---|---|
| `--cli` | Run in the console, no GUI |
| `--out-dir` | HTML output folder. Defaults to the script folder |
| `--boards` | Comma-separated boards. Case-insensitive |
| `--topn-ai` / `--topn-sk` | Items per board for AI / Agent Skill, 1-100 |
| `--topn` | Sets both at once |
| `--only` | `all`, `skill`, or `ai` |
| `--token` | Optional GitHub token |
| `--check-token` | Verify the token, then exit |

---

## Output scope

| Scope | What you get |
|---|---|
| **Everything** (default) | 1.1 Agent Skill projects → 1.2 Agent Skill project details → 1.3 Other projects → 1.4 Other project details |
| **Skill projects only** | Agent Skill projects from both sections, merged and deduplicated into one block |
| **AI projects only** | The AI section with Agent Skill projects removed |

There is no trend-analysis section. The report is the tables and the write-ups.

---

## What ends up in the report

Every project gets a summary-table row and a detail card. Each card carries five fields:

| Field | Content |
|---|---|
| **What it is** | One line identifying the project |
| **What it does** | A plain-language note on what you would actually use it for |
| **What it solves** | The need it addresses |
| **Why it matters** | Its standing or traction, with star figures |
| **Who it is for** | The people or teams it suits |

Cards are tagged **Curated** or **Auto-generated**. `kb.json` holds hand-written entries for 67 projects; anything not in it gets generated text, clearly labelled so you know what to double-check.

---

## GitHub token (optional, but recommended)

GitHub rate-limits its search endpoints hard. Anonymous access allows **10 requests per minute per IP**, and going over returns `403 rate limit exceeded`. The program waits and retries rather than crashing, but the run gets noticeably slower.

A read-only token raises the limit to **30 requests per minute** and typically saves one to two minutes per run.

> [!NOTE]
> The token needs **no scopes at all**. Read access to public data is enough. Do not tick anything on the generation page.

**In the GUI:** paste the token into the **GitHub Token** field and click **Confirm**. It is verified on the spot and the account name is shown. The field is masked by default; tick **Show** to reveal it. The **Get a token...** button opens the generation page.

**Via environment variable:** set `GITHUB_TOKEN` (or `GH_TOKEN`) if you prefer to keep it out of the UI. This suits scripted or scheduled runs.

The token lives in memory for the current run only. It is never written to disk and never uploaded.

---

## Data method

Worth knowing before you compare this report against something else:

- The Trending **daily** board ranks by short-term star velocity, not total stars.
- The monthly, weekly and daily lists are topped up with a date-window plus total-stars search, so they can differ from an in-extension velocity board.
- The AI and SKILL pools are merged, deduplicated, then split into Agent Skill and everything else.
- Agent Skill classification is deliberately strict: a project lands in that section only with skill or plugin evidence in its name or description, or an entry in the curated knowledge base. Topic tags alone never decide it.
- Star counts and rankings are fetched live, so they change on every run.

---

## Files

| File | Purpose |
|---|---|
| `github_trending_report.py` | Main program: GUI and console, standard library only |
| `kb.json` | Curated write-ups for 67 projects. Safe to delete; new projects then use auto-generated text |
| `run_report.bat` | Windows launcher. Probes for Python, pure ASCII, CRLF line endings |
| `USAGE.txt` | Usage notes, including an error-reference table |
| `README_en.md` | This file (English) |
| `README.md` | [中文版](./README.md) |

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `'xxx' is not recognized as an internal or external command` | The `.bat` picked up LF line endings or non-ASCII comments from an editor or archiver, so cmd.exe ran a comment as a command. Use the shipped launcher: pure ASCII, CRLF endings |
| `The system cannot find the path specified` | An old launcher hard-coded a Python path from another machine. The current one probes instead |
| No window appears, but the program is running | `tkinter` is missing from your Python build. The program falls back to console mode automatically |
| `403 rate limit exceeded` | Anonymous search quota exhausted. The program waits and retries; add a token to raise the limit to 30 per minute |
| `401` on every search | The token is invalid or expired. Click **Confirm** in the GUI to re-check, or clear the field to fall back to the anonymous limit |

---

## Notes

- A full run takes roughly 2 to 5 minutes, most of it spent waiting on rate limits.
- An internet connection is required (`github.com` and `api.github.com`).
- Report filenames carry a timestamp, so re-running never overwrites an earlier report.

---

## License

No license is specified for this repository. It is published for reference and personal use.
