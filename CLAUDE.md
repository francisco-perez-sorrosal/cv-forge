# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

`cv-forge` — the machinery for serving Francisco Perez-Sorrosal's CV in multiple formats. The CV *data* lives in a separate `cv` repository; this repository contains the Python MCP server, document renderers, CLI, plugins, and CI/CD pipelines that consume and publish that data.

A single structured YAML description (in the `cv` repo) turns into every form a consumer might want: an MCP tool surface for AI agents, five rendered document formats (markdown, LaTeX, HTML, Typst, PDF), a public web page, and a plugin for Claude Code or Desktop.

## Architecture and Layout

The codebase follows a one-line layering rule: **`models` and `render` know nothing about paths or the network; `data` owns both; `mcp` and `cli` are the two drivers.**

**`src/cv_forge/`** (Python package):
- `models/` — Pydantic definitions of `Resume`, `SemanticOverlay`, `TailoringSpec`. No I/O, no paths, no network. Source of the exported JSON schemas.
- `render/` — Jinja2 renderers and templates producing markdown, LaTeX (moderncv), HTML, Typst (moderner-cv). Full and tailored variants.
- `data/` — Only code that touches filesystem paths or the network: `CvDataSnapshot`, `CvDataProvider`, `ReleaseFetcher`, local directory loader.
- `mcp/` — MCP server: resources (`fps-cv://`), tools, ASGI app, lifespan, `/healthz`.
- `cli/` — Console script `cv-forge`: `render`, `validate`, `export-schemas`, `fetch-snapshot`, `serve`.

**`plugins/`** — Two Claude Code plugins:
- `plugins/cv/` — Consumer-facing: native HTTP MCP declaration + `cv-analyst` and `cv-tailoring` skills.
- `plugins/cv-forge/` — Maintainer-facing: `cv-data-edit`, `cv-publish`, `cv-forge-deploy` skills.

**`schemas/`** — JSON Schema pair generated from models, committed and drift-checked. Mirrored into the `cv` repo.

**`scripts/`**, **`.github/workflows/`**, **`Makefile`** — Deployment, release, CI/CD.

## Common Commands

### Setup and Testing

```bash
pixi install                                  # install dependencies
pixi run -e dev python -m pytest             # run the test suite (dev environment required)
```

### CLI Commands (all via `pixi run cv-forge <subcommand>`)

Each subcommand supports `--help` and `--json` for machine-readable output (where applicable):

- `render -f <fmt|all> [-o <dir>] --data-dir <dir>` — Render CV data to markdown, LaTeX, HTML, Typst, or PDF. PDF requires `latexmk`.
- `validate --data-dir <dir>` — Check data directory against schemas and cross-references.
- `export-schemas` — Generate `schemas/*.schema.json` from Pydantic models.
- `fetch-snapshot [--tag <release-tag>] [--output <dir>]` — Download a GitHub Release snapshot into a directory.
- `serve [--transport stdio|streamable-http] [--host <host>] [--port <port>]` — Run the MCP server locally.

### Development

```bash
pixi run mcps                                    # deprecated; use `cv-forge serve --transport stdio`
pixi run cv-forge serve --transport streamable-http   # local server on http://127.0.0.1:8000/mcp
```

### Release

```bash
scripts/release.sh patch           # bump patch version, tag, push
scripts/release.sh minor --dry-run # show what would change
scripts/release.sh 1.0.0           # tag a specific version
```

Version is the single source of truth in `pyproject.toml`; `release.sh` propagates it into both `plugin.json` files.

## Data Layer and MCP Server

**Data flow:** The MCP server loads CV data from GitHub Release assets (baked snapshot at startup, refreshed every 15 minutes). Override via `CV_DATA_DIR` environment variable to load from a local directory instead (useful for local development). When both a release snapshot and a local directory are available, the release snapshot takes precedence.

**Environment variables** (all optional):
- `CV_DATA_DIR` — Path to a local cv-data directory (defaults to sibling `cv-data/` directory at startup if present).
- `WASMER_TOKEN` — Secret for Wasmer Edge deployments. Only needed for `scripts/deploy.sh` or GitHub Actions `deploy-mcp.yml`.

**Health check endpoint:** The server exposes `GET /healthz` returning 200 only when a validated snapshot is loaded, with a JSON body carrying `origin`, `release_tag`, `loaded_at`, `refresh_state`, `consecutive_failures`. Essential for deployment verification.

## Testing

```bash
pixi run -e dev python -m pytest               # full suite
pixi run -e dev python -m pytest tests/cli/    # CLI tests only
```

Use the `-e dev` flag — `pyenv` may intercept bare `pytest`. Integration tests that require the `cv-data/` directory can be skipped with `-m 'not integration'` or by unsetting `CV_DATA_DIR` (they detect and deselect gracefully).

## Cross-Repo Contract

Two repositories, one data-publishing boundary:

**`cv` repository (data only):**
- `cv-data/resume.yaml`, `resume-semantics.yaml` — Structured CV content and semantic overlay
- `schemas/` — JSON Schema pair mirrored from this repo's schema exports
- `.github/workflows/publish.yml` — Pushes a CalVer tag; invokes this repo's reusable workflow at `cv-forge/.github/workflows/publish.yml@v1`

**`cv-forge` repository (machinery):**
- GitHub Release assets (8 total): `resume.md`, `resume.tex`, `resume.html`, `resume.typst`, `resume.pdf`, `resume-tailored.tex`, `resume-tailored.typst`, `release.json`
- Reusable workflow at `.github/workflows/publish.yml` — implements the render, compile, upload, deploy pipeline
- Deployment via `.github/workflows/deploy-mcp.yml` on `v*` tags
- Wasmer Edge apps: `fps-cv-mcp` (MCP server), `fps-cv` (static HTML site)

No credential crosses the boundary in either direction. Both repos consume pinned artifact references; schema drift is detected, not prevented.

## Plugins

The `cv` plugin (consumer-facing) and `cv-forge` plugin (maintainer-facing) are distributed via bit-agora marketplace. Install with:

```bash
claude plugin marketplace add francisco-perez-sorrosal/bit-agora
claude plugin install cv
```

Marketplace entries carry no `version` field; version is propagated from `pyproject.toml` at release time.

## WASIX Dependency Pins

The MCP server runs on Wasmer Edge (WASIX runtime). Three dependencies are pinned to ceiling versions due to WASIX package index availability:
- `pydantic>=2.12,<2.13.5` — WASIX index caps at `2.13.4`; ceiling is the published max, not a compat concern
- `cryptography>=43,<50.0.1` — Required by `mcp[cli]`'s `pyjwt[crypto]`
- `cffi>=2.1,<2.1.1` — Required by cryptography

`scripts/check_wasix_ceilings.py` validates the ceilings at CI time.

## Jinja2/LaTeX Template Gotchas

- `{% raw %}...{% endraw %}` blocks in templates protect LaTeX special chars from Jinja2. These work correctly inside `{% include %}` — included files process raw/endraw independently
- `_preamble.tex.j2` contains personal data (name, title, profiles) between two raw blocks. Both `cv.tex.j2` and `cv_tailored.tex.j2` get personal data from this shared partial. The `profile_override` is handled separately in `cv_tailored.tex.j2` inside `\begin{document}`, not in the preamble
- `_template_context()` passes `enrich=False` for all LaTeX rendering — semantic enrichment (project links, skill levels) is for markdown, HTML, and Typst
- LaTeX commands containing `{#N}` (e.g., `\newcommand{\foo}[1]{#1}`) must be inside `{% raw %}` blocks because `{#` triggers Jinja2's comment parser. This is distinct from the `{{ "{" }}` brace-escaping used elsewhere
- New Pydantic models follow `ConfigDict(populate_by_name=True)` + `Field()` pattern — same as `resume.py` and `semantics.py`

## Jinja2/Typst Template Gotchas

- Typst templates (`.typ.j2`) use the same `{% raw %}` block pattern as LaTeX for native Typst code (e.g., `#import`, `#cv-entry(`, `= Section Heading`)
- `_preamble.typ.j2` imports `moderner-cv` 0.2.1 and sets up `#show: moderner-cv.with(...)` with personal data injection between raw blocks
- Typst special characters (`#`, `$`, `@`, `<`, `>`) are escaped via `_typst_escape_filter` — lighter than LaTeX (fewer specials in content mode)
- `render_typst()` defaults to `enrich=True` (like markdown), unlike LaTeX which always uses `enrich=False`. This means the Typst work entry partial renders project links when enriched
- `render_tailored_typst()` uses `enrich=False` (like tailored LaTeX) — tailored output stays focused on job relevance
- The `moderner-cv` package is resolved client-side by Typst's package manager on first compile. No server-side dependency
- Both `cv.typ.j2` and `cv_tailored.typ.j2` share `_preamble.typ.j2` and `_work_entry.typ.j2` partials

## Feedback Ledger

`FEEDBACK.md` records friction observed while building this project on Wasmer. Each entry targets Wasmer's engineers and their agents with exact versions, verbatim output, and proposed fixes. Entries are filed as upstream issues in `wasmerio/anybuild`, `wasmerio/wasmer`, etc., per their contribution structure.

For deployment and release details, see `README_DEV.md` and `RELEASE_PROCESS.md`.

## Important Notes

- The CV contains real professional information — handle appropriately
- CV data is source-controlled in the `cv` repository, not here
- All Wasmer Edge deployments and operations are first-class, documented paths — no render.com fallback
