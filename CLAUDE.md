---
description: 
alwaysApply: true
---

# Project environment contract

Agents and the user run Python in **one agreed environment**, not ad-hoc system Python.

## Canonical environment

| Item | Value |
|---|-----|
| Spec file | `requirements.txt` (repo root) |
| Env dir | `.venv` (repo root, gitignored) |
| Create | `python3 -m venv .venv` |
| Activate | `source .venv/bin/activate` |
| Install/Update | `pip install -r requirements.txt` |

If `requirements.txt` changes or a new package is required, **update the file in the same change** and tell the user to run the install command.

## Before running Python, notebooks, or tests

1. **Use the canonical env** — run commands with `.venv/bin/python …` / `.venv/bin/pip …`, or after `source .venv/bin/activate`. Do not use bare `/usr/bin/python3` or a different env unless the user explicitly overrides.
2. **Check the env exists** — `test -x .venv/bin/python` (or equivalent).
3. **Check required imports** — for the task at hand, verify packages from `requirements.txt` import successfully in that env.
4. **If anything is missing, stop and report** — do not silently substitute, skip execution, or add optional fallbacks (e.g. `try/except ImportError` around plots) to hide gaps.

## Required user message when blocked

Use this format so the user can fix the env once and both sides stay aligned:

```
Environment blocked

Canonical env: .venv (see requirements.txt)

Missing / problem:
- <package or tool>: <why it's needed>
- Error: <exact message, if any>

Setup (run locally):
python3 -m venv .venv       # first time
source .venv/bin/activate
pip install -r requirements.txt

I have not executed <notebook/script/test> until you confirm the env is ready.
```

## Notebooks (`**/*.ipynb`)

- **Dependencies**: only use packages listed in `requirements.txt`, or add them there first.
- **After creating or materially editing a notebook**: execute it end-to-end in `.venv` (e.g. `.venv/bin/jupyter nbconvert --execute …` or run all cells in that kernel).
- **If execution fails on missing deps**: stop, report using the template above, and do not claim the notebook "works."
- **Do not** mark a notebook done without a successful run in the canonical env, unless execution is blocked and you reported why.

## Scripts and collectors

Same rules: run with the canonical env; report missing deps; update `requirements.txt` when adding imports.

## When the user names a different env

Follow the user's override for that session, but still report any missing packages and prefer recording the final set in `requirements.txt` so the contract stays single-source.

---
description: Don't volunteer long docs or narrate work like a blog post
alwaysApply: true
---

# Communication — no slop

- Prefer concise, technical replies; skip filler and restating the task
- Do not create or expand README/docs unless the user asks (or a rule/skill requires it)
- When docs are requested: short and operational — commands and contracts, not essays
- Do not add unsolicited architecture diagrams, "typical workflow" tours, or dependency inventories
- In PRs/commits: why over what; no marketing language

---
description: No AI-slop docs — short READMEs and markdown only
globs: "**/README.md,**/readme.md,**/*.md"
alwaysApply: false
---

# Documentation style (no AI slop)

When writing or editing READMEs / markdown in this repo:

## Do

- Lead with what the thing is in a few short sentences
- Prefer setup + run commands over essays
- Use small tables only when they carry real info (paths → purpose, flag → meaning)
- Assume the reader can ask a human for details — docs are a bootstrap, not a textbook

## Do not

- Write long "overview / architecture / workflow / philosophy" sections unless explicitly asked
- Explain what every dependency is for line-by-line
- Restate the same workflow in prose + diagram + numbered list
- Add motivational filler ("research tooling to…", "comprehensive solution…", "empowers…")
- Inventory every dataset, endpoint, or CLI flag "for completeness"
- Link to missing or outdated files
- Pad with horizontal rules and nested headings for thin content

## Target shape for a package README

```markdown
# Name

Sentences describing what it is.

## Setup / run
\`\`\`bash
# the commands that matter
\`\`\`

## Files (optional mini-table)
| File | Purpose |
```

If unsure whether to expand a doc: **don't**. Leave it short.

Never execute shell commands that modifies databases (DDL, DML, migrations) without asking me first. Only provide the command for me to run.

stop sounding and looking like cringe + AI slop

When writing code, add comments that explain the *why* and *intuition* behind non-trivial 
logic, not just what the line does. Assume the reader is technically competent (grad-level 
CS) but unfamiliar with this specific codebase, library, or algorithm — write as if 
onboarding a smart collaborator, not a novice.

Rules:
- Comment on: non-obvious design decisions, why an approach was chosen over alternatives, 
  edge cases being handled, tricky math/algorithmic steps, and any "gotchas" (off-by-ones, 
  ordering dependencies, side effects).
- Do NOT comment on: obvious syntax, self-explanatory variable assignments, or restate 
  what the code visibly does (e.g. no "# increment counter" above `i += 1`).
- Crisp inline comments throughout code blocks.
- For functions/classes: a 1-2 line docstring stating purpose, inputs/outputs, and any 
  non-obvious contract (e.g. mutates input, assumes sorted array, not thread-safe).
- If an algorithm or formula is used, name it and note where it deviates from the textbook 
  version, if it does.
- Keep comments dense with information, not filler words. No "this function is used to..." 
  preambles — get straight to the substance.