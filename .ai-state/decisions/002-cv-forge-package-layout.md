---
id: dec-002
draft_id: dec-draft-8cc49ae3
title: One cv_forge package with models/render/data/mcp/cli subpackages, replacing cv_mcp_server
status: accepted
category: architectural
date: 2026-09-13
summary: The `cv_mcp_server` package is renamed to `cv_forge` and decomposed into five subpackages — `models`, `render`, `data`, `mcp`, `cli` — so that the MCP server is one surface among four rather than the name of the whole thing, and the network/path/pure layers stop sharing a namespace.
tags: [package-structure, naming, cohesion, python]
made_by: fperezsorrosal
agent_type: systems-architect
branch: cv-repo-split
pipeline_tier: full
affected_files:
  - src/cv_mcp_server/
  - pyproject.toml
  - scripts/render_cv.py
  - tests/
affected_reqs: [REQ-07, REQ-08, REQ-09, REQ-14, REQ-15]
---

## Context

The distribution is named `cv-mcp-server` and its package `cv_mcp_server`, dating from when serving the CV over MCP was the entire point. It is no longer. The same code now: defines the data's shape (`models/`), renders five output formats (`renderers.py` + `templates/`), is driven by a standalone script (`scripts/render_cv.py`, which lives *outside* the package and reaches into it), serves MCP (`server.py`, `resources.py`, `tools/`), and — after this split — will additionally fetch data over HTTP, export JSON Schemas, and back two Claude Code plugins.

Two concrete symptoms of the mismatch:

1. `scripts/render_cv.py` is not part of the package, so it cannot be a console entry point, cannot be installed, and hardcodes `PROJECT_ROOT = Path(__file__).parent.parent` with no env-var escape hatch — a defect the inventory flagged as breaking outright post-split. The publish workflow needs to invoke the renderer as a first-class command, not a path-relative script.
2. `server.py` currently holds the transport configuration, the data-directory resolution, the PDF path constant, the eager store load, *and* the `FastMCP` construction — five responsibilities in 52 lines, of which only one is actually about MCP.

The flat layout also gives no home for the new network-facing code. Dropping a `release.py` next to `renderers.py` and `store.py` would put "knows about HTTP and GitHub" in the same namespace as "is a pure function of a Resume model."

## Decision

Rename the distribution to `cv-forge` and the package to `cv_forge`, laid out as:

```
src/cv_forge/
  models/   resume.py, semantics.py, tailoring.py    # pure Pydantic, no I/O
  render/   renderers.py, templates/                 # pure functions of a store
  data/     store.py, snapshot.py, provider.py, release.py, local.py
  mcp/      server.py, app.py, resources.py, tools/
  cli/      main.py                                  # console_scripts entry: cv-forge
```

The layering rule is one sentence: **`models/` and `render/` know nothing about paths or the network; `data/` owns both; `mcp/` and `cli/` are the two drivers.** `data/local.py` is the only module that reads a filesystem path; `data/release.py` is the only module that opens a socket.

`scripts/render_cv.py` becomes `cv_forge.cli.main`, exposed as the `cv-forge` console script, so CI and the maintainer plugin invoke the same command (REQ-07).

`renderers.py` (651 lines) moves **verbatim** into `render/`. It is the largest module and a plausible split candidate, but splitting it inside the same change that renames the package and rewrites the data layer would make the diff unreviewable. Deferred, explicitly, to a later pass.

## Considered Options

### A. Rename to `cv_forge` with subpackages (chosen)

- **Pro**: the package name matches the repository and the product; every new module has an obvious home; the CLI gets a legitimate entry point; the pure/impure boundary becomes a directory boundary rather than a convention; the rename is at its cheapest precisely now, when every import is already moving to a new repository.
- **Con**: a large mechanical diff touching every source and test file; `git log --follow` needs the flag to cross the rename (it does cross it); anyone with the old package installed must reinstall.

### B. Keep `cv_mcp_server`, add a sibling `cv_forge` package for the CLI

- **Pro**: smallest diff; the MCP server's imports are untouched.
- **Con**: two distributions or one distribution with two top-level packages, for one product. The renderer would have to live in one of them and be imported by the other, so the dependency direction between "the thing named after the server" and "the thing named after the repo" would be backwards. This is the option that looks surgical and is actually the most confusing outcome.

### C. Keep everything flat under a renamed `cv_forge`

- **Pro**: rename without restructuring — fewer moving parts in one step.
- **Con**: leaves `release.py` (sockets), `local.py` (paths), `renderers.py` (pure) and `resources.py` (MCP) as peers in one namespace. The layering rule would exist only as a comment, with nothing enforcing it. Given that the data layer is being rewritten in this same change anyway, the incremental cost of placing the new files correctly is close to zero.

## Consequences

**Positive**
- `cv-forge render -f html` is a real command with a real `--help`, usable identically by a human, by CI, and by a plugin skill.
- The import graph enforces the layering: a `models/` module that imported `httpx` would be visibly wrong.
- `mcp/app.py` gains a natural home for the ASGI factory and lifespan, which is what makes the import-time side effects removable.

**Negative**
- One large mechanical commit that must be reviewed as a rename rather than read line by line. Mitigated by making it its own step with a green test suite on both sides.
- Any external reference to `cv_mcp_server` (none known outside this repo) breaks.

**Neutral**
- `cv-forge` is not published to PyPI, so the distribution name does not need to be globally unique.

## Disconfirmation

**Activation**: no — the layering follows directly from the data-layer decision (`dec-006`); a lens sweep would restate it.

**Falsifier.** This decision is wrong if, six months on, the subpackage boundaries are routinely crossed in the wrong direction — specifically, if any module under `models/` or `render/` imports from `data/`, `mcp/` or `cli/`. That import is mechanically detectable and would mean the decomposition is decorative rather than load-bearing. A lint rule asserting it is cheap and should be added if the boundary is ever observed to slip.

**Steelmanned runner-up.** Option C (rename, stay flat) is defensible on Simplicity-First grounds: 2,553 lines of Python across 15 modules is small enough that a flat namespace is navigable by reading the directory listing, and subpackages add import ceremony (`from cv_forge.render.renderers import render_markdown`) for a codebase nobody gets lost in. The real argument against it is not size but *trajectory*: this change adds the first network-facing code the project has ever had, and the moment a module can make an HTTP request, "which modules are pure?" stops being answerable by reading names.

**Reversal trigger.** Flatten back to a single namespace if, after the data layer settles, `data/` holds fewer than three modules — that would mean the boundary was drawn around one file and the ceremony is not earning its place.
