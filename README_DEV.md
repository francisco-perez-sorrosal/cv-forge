# cv-forge — Developer Guide

## Setup

### Requirements

- Python 3.13
- pixi (package and environment manager)
- For PDF compilation: `latexmk` (macOS: `brew install latexmk`)
- For deployment: `wasmer` CLI (>=7) and `anybuild` (>=0.28.4)

### Installation

```bash
pixi install                          # install dependencies and set up environment
pixi run -e dev python -m pytest      # verify test suite runs (expects CV_DATA_DIR set or cv-data/ sibling dir)
```

## Repository Layout

```
src/cv_forge/
  models/          # Pydantic data models (Resume, SemanticOverlay, TailoringSpec)
  render/          # Jinja2 renderers and templates (markdown, LaTeX, HTML, Typst)
  data/            # Data loading and refresh (snapshot, provider, release fetching)
  mcp/             # MCP server, resources, tools, ASGI app
  cli/             # Console script: render, validate, export-schemas, fetch-snapshot, serve
  prompts/         # YAML prompt templates
plugins/cv/        # Consumer plugin: MCP declaration + skills
plugins/cv-forge/  # Maintainer plugin: edit, publish, deploy skills
schemas/           # Generated JSON schemas (source of truth for cv repo)
scripts/           # Helper scripts (release.sh, deploy.sh, check_wasix_ceilings.py)
.github/workflows/ # CI/CD: publish, deploy-mcp, ci, claude-code-review
```

## CLI Reference

```bash
pixi run cv-forge --version                   # Show version (from pyproject.toml)
pixi run cv-forge --help                      # Show all subcommands
```

### Render

Render CV data to one or more output formats.

```bash
pixi run cv-forge render -f <format> [--data-dir <path>] [-o <output-dir>] [--json]
```

**Formats:** `markdown`, `latex`, `html`, `typst`, `pdf`, `all`

**Examples:**
```bash
# Render all formats to ./rendered-cv/
pixi run cv-forge render -f all --data-dir ../cv/cv-data

# Render PDF to stdout (exit 0 on success, exit 1 on failure)
pixi run cv-forge render -f pdf --data-dir ../cv/cv-data -o - 2>/dev/null | file -

# Render with JSON summary (includes sha256 per output)
pixi run cv-forge render -f all --json
```

**Exit codes:** 0 = success, 1 = error, 2 = not implemented

### Validate

Check a data directory against schemas and cross-references.

```bash
pixi run cv-forge validate --data-dir <path>
```

Validates `resume.yaml` and `resume-semantics.yaml` against the generated schemas and enforces cross-references (entry IDs, topic names, relationship targets).

**Exit codes:** 0 = valid, 1 = invalid

### Export Schemas

Generate `schemas/*.schema.json` from the Pydantic models.

```bash
pixi run cv-forge export-schemas
```

Outputs two JSON Schema files:
- `schemas/resume.schema.json`
- `schemas/semantics.schema.json`

These are committed to git and mirrored into the `cv` repository for validation.

### Fetch Snapshot

Download a GitHub Release snapshot into a directory (for testing release-based data loading).

```bash
pixi run cv-forge fetch-snapshot [--tag <tag>] [--output <dir>]
```

**Defaults:** `--tag latest`, `--output .`

Downloads the eight release assets into the specified directory.

### Serve

Run the MCP server locally.

```bash
pixi run cv-forge serve [--transport stdio|streamable-http] [--host <host>] [--port <port>]
```

**Defaults:** `--transport stdio`, `--host 127.0.0.1`, `--port 8000`

**Examples:**
```bash
# Stdio mode (for Claude Code)
pixi run cv-forge serve --transport stdio

# HTTP mode (for browser testing)
pixi run cv-forge serve --transport streamable-http
# Then: curl http://127.0.0.1:8000/mcp/tools/list
```

## Data Layer and Environment

### Environment Variables

- **`CV_DATA_DIR`** — Path to a local `cv-data` directory. If set, the server loads from disk instead of fetching from GitHub Releases.
- **`WASMER_TOKEN`** — Secret for Wasmer Edge deployments (only needed for `scripts/deploy.sh` or `deploy-mcp.yml`).

### Startup Behavior

1. MCP server starts with a **baked snapshot** of the latest released CV data (hardcoded at build time via `anybuild`)
2. On first request, the server is immediately ready to answer (no network dependency)
3. Background refresh loop (every 15 minutes) checks GitHub Releases for updates
4. If an update is found, a new snapshot is fetched and swapped atomically
5. If GitHub is unreachable or a release is malformed, the server degrades to stale data (not failure)

**Health check endpoint:** `GET /healthz`

Returns 200 only when a validated snapshot is loaded. Body is JSON:

```json
{
  "origin": "release|local",
  "release_tag": "v0.1.0",
  "loaded_at": "2026-09-14T12:34:56Z",
  "refresh_state": "Fresh|Stale|Starting",
  "consecutive_failures": 0
}
```

### Testing

```bash
pixi run -e dev python -m pytest                    # full suite
pixi run -e dev python -m pytest -m 'not integration'  # skip integration tests
pixi run -e dev python -m pytest tests/cli/         # CLI tests only
CV_DATA_DIR= pixi run -e dev python -m pytest       # unset CV_DATA_DIR; integration tests auto-skip
```

Integration tests require the `cv-data/` directory at the project root (or at `CV_DATA_DIR`); they gracefully skip if it's absent.

## Wasmer Deployment

### Deployment Workflow

Two paths to deploy the MCP server to Wasmer Edge:

1. **Automated (GitHub Actions):** `.github/workflows/deploy-mcp.yml` runs on `v*` tags. Requires `WASMER_TOKEN` secret in this repo.
2. **Manual (workstation):** `scripts/deploy.sh` stages files, runs `anybuild`, and uploads to Wasmer.

### Using `scripts/deploy.sh`

```bash
./scripts/deploy.sh [--dry-run]
```

**Requirements:**
- `wasmer` CLI (>=7): https://docs.wasmer.io/developers/cli
- `anybuild` (>=0.28.4): included in `wasmer` installation
- `WASMER_TOKEN` environment variable set to a Wasmer API token

**What it does:**
1. Stages all tracked files via `git ls-files`
2. Verifies the working tree is clean (no untracked/uncommitted changes)
3. Runs `anybuild build` to prepare the bundle for Wasmer Edge
4. Uploads the bundle to Wasmer Edge app `fps-cv-mcp`
5. Waits for the deployment to be live
6. Probes `/healthz` to verify the MCP server is responsive
7. Prints the public URL

**Example:**
```bash
export WASMER_TOKEN=<your-token>
./scripts/deploy.sh

# Or with dry-run to see what would happen:
./scripts/deploy.sh --dry-run
```

### Wasmer Configuration

**App names:**
- `fps-cv-mcp` — MCP server (Python, WASIX runtime)
- `fps-cv` — Static HTML CV site (served alongside the MCP app)

**Environment variables (in Wasmer dashboard or via `wasmer app secrets`):**
- `WASMER_TOKEN` — Required for CI deployments

**Dependency ceilings (pinned in `pyproject.toml`):**
- `pydantic>=2.12,<2.13.5` — WASIX index caps at `2.13.4`
- `cryptography>=43,<50.0.1` — Required by `mcp[cli]`'s `pyjwt[crypto]`
- `cffi>=2.1,<2.1.1` — Required by cryptography

Run `scripts/check_wasix_ceilings.py` to validate pins before deploying.

## Development Workflow

### Adding a New Render Format

1. Add a template file `src/cv_forge/render/templates/cv.<ext>.j2`
2. Add a renderer function in `src/cv_forge/render/renderers.py`
3. Wire it into the `cli/main.py` render subcommand
4. Add tests in `tests/cli/test_render.py`
5. Update `.github/workflows/publish.yml` to include the new format in release assets

### Adding a New Tool or Resource

1. Create the tool/resource in a new or existing file under `src/cv_forge/mcp/tools/` or directly in `resources.py`
2. Use the `@mcp.tool()` or `@mcp.resource()` decorator
3. The decorator automatically registers it (via `pkgutil` walk in `main.py`)
4. Add tests in `tests/mcp/`

### Running Tests Locally

Use the `-e dev` flag to ensure `pytest` and other dev tools resolve correctly:

```bash
pixi run -e dev python -m pytest tests/cli/test_render.py::TestRender::test_render_pdf -v
```

### Linting and Formatting

The project uses `ruff` for linting and formatting:

```bash
pixi run ruff check src/                  # lint
pixi run ruff format src/                 # auto-format
```

## Troubleshooting

### Common Issues

**`pyenv: <tool>: command not found` during tests:**
- The `-e dev` flag scopes `pytest` to the pixi dev environment. Use `pixi run -e dev python -m pytest`, not bare `pytest`.

**`CV_DATA_DIR` unset and no `cv-data/` directory found:**
- Integration tests gracefully skip when the CV data is unavailable. Set `CV_DATA_DIR` to a path, or clone the `cv` repository as a sibling directory.

**Wasmer deployment fails with WASIX ceiling exceeded:**
- Check `scripts/check_wasix_ceilings.py` output. Pydantic, cryptography, or cffi may need a downgrade. See `FEEDBACK.md` for known issues.

For additional support or to file a Wasmer-related friction report, see `FEEDBACK.md`.
