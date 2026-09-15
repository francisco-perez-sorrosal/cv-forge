# Release Process

This document describes the release workflows for both the `cv-forge` machinery repository and the `cv` data repository.

## cv-forge Release (SemVer)

The `cv-forge` repository uses **Semantic Versioning** (SemVer). Releases are driven by `scripts/release.sh` and tagged on the `main` branch.

### Quick Start

```bash
scripts/release.sh patch          # 0.0.5 -> 0.0.6
scripts/release.sh minor          # 0.0.5 -> 0.1.0
scripts/release.sh major          # 0.0.5 -> 1.0.0
scripts/release.sh 1.2.3          # explicit version
scripts/release.sh patch --dry-run # preview only
```

### What `release.sh` Does

1. **Validates** the working tree is clean
2. **Bumps** `pyproject.toml`'s `[project].version`
3. **Propagates** the version into both `plugin.json` files (consumer + maintainer plugins)
4. **Commits** the version changes
5. **Tags** the commit as `v<version>` (e.g., `v0.0.6`)
6. **Re-points** the moving `v<MAJOR>` alias (e.g., `v0`) to the new tag
7. **Pushes** the commit and tags to `origin`

The push to `origin` **triggers** `.github/workflows/deploy-mcp.yml`, which:
- Builds the MCP server app for Wasmer Edge
- Deploys to the `fps-cv-mcp` Wasmer Edge app
- Publishes release assets (eight files)

### Manual Workflow

If you prefer not to use `release.sh`:

```bash
# 1. Edit pyproject.toml and update [project].version
# 2. Manually edit both plugin.json files
# 3. Commit
git add pyproject.toml plugins/cv/.claude-plugin/plugin.json plugins/cv-forge/.claude-plugin/plugin.json
git commit -m "chore(release): 0.0.6"

# 4. Tag
git tag v0.0.6
git tag -f v0  # re-point major alias

# 5. Push
git push origin main v0.0.6 v0
```

### Deploy-MCP Workflow

When a `v*` tag is pushed, `.github/workflows/deploy-mcp.yml` automatically:

1. Checks out the code at that tag
2. Validates the WASIX dependency ceilings via `scripts/check_wasix_ceilings.py`
3. Uses `anybuild` to build a Wasmer-compatible bundle (same `scripts/deploy.sh` path as the manual flow)
4. Uploads the bundle to Wasmer Edge app `fps-cv-mcp`
5. Polls `/healthz` to verify the server is live
6. Reports success or failure

**Requirements:**
- `WASMER_TOKEN` secret must be set in this repo's GitHub Settings > Secrets and variables > Actions

**Critical: setup-wasmer version format**
The workflow uses `wasmerio/setup-wasmer@v3.1` with `version: 'v7.4.1'` (with the `v` prefix). The action passes the version string to the installer, which downloads from GitHub releases using that exact tag. Without the `v` prefix, the download 404s and the action exits 0 with nothing installed — so the version field must include the `v`. This is not documented in the action's `action.yml`; see `FEEDBACK.md: F-005, F-008` for the upstream issue.

### Publish Workflow: LaTeX and PDF Generation

The reusable publish workflow (`.github/workflows/publish.yml`, invoked by the `cv` repository) renders the CV to PDF using TinyTeX on a clean `ubuntu-latest` runner. The workflow installs a curated set of TeX Live packages via `tlmgr`:

**Required TeX packages (installed by CI):**
- Core: `moderncv`, `geometry`, `babel`, `babel-english`, `xcolor`
- Fonts: `fontawesome6`, `fontawesome5`, `academicons`, `marvosym`, `lmodern` (collection-fontsrecommended), `multirow`, `arydshln`
- Collections: `collection-fontsrecommended` (required fonts), `collection-pictures` (pgf/tikz for moderncv), `collection-latexrecommended` (microtype, fancyhdr)
- Utilities: `enumitem`, `multibib`, `amsfonts`, `hyperref`, `etoolbox`, `biblatex`, `biber`, `latexmk`, `collection-latex`

**Why this set matters:** MacTeX and TinyTeX diverged between 2024 and 2026. The templates use hardcoded LaTeX macros from `moderncv`, which now requires `fontawesome6` instead of the older `fontawesome5`. The full set ensures both local (MacTeX) and CI (TinyTeX) produce byte-identical PDFs (verify by comparing page count and `pdftotext` output after the first publish; see `FEEDBACK.md: F-009` for the TeX Live lag discovery).

**Rendering step:** The publish workflow runs `pixi run --manifest-path cv-forge/pyproject.toml cv-forge render -f all --release-tag <ref>` using absolute paths (`$GITHUB_WORKSPACE`) for data and output directories, since `--manifest-path` changes the working directory. The `--release-tag` parameter embeds the pushed ref into the HTML output's `<meta name="cv-release-tag" content="...">` and footer; the same tag is asserted present in the site liveness check (REQ-06).

### Release Assets

The publish workflow (in the `cv` repository) generates eight stable assets under `releases/latest/download/`:

| Asset | Format | Purpose |
|-------|--------|---------|
| `resume.md` | Markdown | Full CV for AI consumption |
| `resume.tex` | LaTeX (moderncv) | Full CV for local compilation |
| `resume.html` | HTML | Interactive CV for web browsers |
| `resume.typst` | Typst (moderner-cv) | Full CV for Typst compilation |
| `resume.pdf` | PDF | Compiled full CV |
| `resume-tailored.tex` | LaTeX (tailored) | Tailored template (requires TailoringSpec) |
| `resume-tailored.typst` | Typst (tailored) | Tailored template (requires TailoringSpec) |
| `release.json` | JSON | Release metadata and asset manifest |

These assets are **stable and version-free** — they are always available under `releases/latest/download/`.

## Republishing an Existing Release

To re-run the publish workflow without creating a new tag (for example, if the render output changed but the CV data did not):

```bash
gh workflow run publish.yml \
  --repo francisco-perez-sorrosal/cv \
  -f tag=2026.09.14
```

Or via the GitHub Actions UI:
1. Open Actions → Publish CV workflow
2. Click "Run workflow" (top right)
3. Enter the tag in the `ref` input field
4. Click "Run workflow"

**What happens:**
- The reusable workflow runs again at the exact same tag
- Release assets are regenerated and uploaded with `--clobber` (overwrites existing files)
- The HTML site is redeployed
- The MCP server automatically fetches the updated release assets within its next refresh interval (15 minutes by default)

This is useful when templates change (and hence PDF/HTML output changes) without data edits. All assets remain at the same version-free URL (`releases/latest/download/<name>`).

## cv (Data) Repository Release (CalVer)

The `cv` data repository uses **Calendar Versioning** (CalVer: `YYYY.MM.DD`). Releases are triggered by pushing a CalVer tag from the data repo.

### Workflow

1. **Tag a release in the `cv` repo:**
   ```bash
   git tag 2026.09.14
   git push origin 2026.09.14
   ```

2. **This triggers `cv`'s `.github/workflows/publish.yml`:**
   ```yaml
   on:
     push:
       tags:
         - '[0-9][0-9][0-9][0-9].*'  # CalVer pattern
   ```

3. **`publish.yml` calls the reusable workflow from `cv-forge`:**
   ```yaml
   uses: francisco-perez-sorrosal/cv-forge/.github/workflows/publish.yml@v1
   with:
     ref: ${{ github.ref }}
     data-path: cv-data/
     deploy-site: true
     site-app: fps-cv
     formats: markdown,latex,html,typst,pdf
   secrets:
     WASMER_TOKEN: ${{ secrets.WASMER_TOKEN }}
   ```

4. **The reusable workflow (in `cv-forge`):**
   - Checks out both `cv` and `cv-forge` repos at the specified refs
   - Runs `cv-forge render -f all --release-tag <ref>` against `cv-data/` — the tag is embedded in the HTML output's `<meta name="cv-release-tag" content="<ref>">` and footer line
   - Compiles the PDF with `latexmk`
   - Builds `release.json` with asset hashes and URLs
   - Uploads the eight assets to the GitHub Release
   - Deploys the HTML site to Wasmer static site app `fps-cv`
   - Verifies the site is live by fetching `/` and asserting the `cv-release-tag` meta tag carries the pushed ref (REQ-06)
   - Fails unless all steps succeed

### Cross-Repo Contract

| Artifact | Owner | Coupling |
|----------|-------|----------|
| `publish.yml@v1` | `cv-forge` | `cv` pins this at `@v1` (moving tag), exact version auto-resolves |
| `schemas/*.schema.json` | `cv-forge` generates, `cv` mirrors | `cv` CI validates against a local copy (via raw HTTP fetch) |
| GitHub Release assets | Generated by `cv`'s publish workflow | Served from `releases/latest/download/`; consumed by MCP server |

No credentials cross the repo boundary:
- `cv` publishes under its own `GITHUB_TOKEN` (provided automatically by GitHub Actions)
- `cv-forge` has its own `WASMER_TOKEN` for Wasmer deployments
- Schema drift is detected by `cv` CI, not prevented — a malformed update can be reverted by opening a PR with the correct schema

## Rollback

### cv-forge Rollback

If a `cv-forge` release is bad:

1. **Revert the tag:**
   ```bash
   git push -d origin v0.0.6  # delete remote tag
   git tag -d v0.0.6          # delete local tag
   ```

2. **Tag the previous good version and push:**
   ```bash
   git checkout <previous-commit>
   git tag v0.0.6-rollback
   git push origin v0.0.6-rollback
   ```

3. **Or re-point `v<MAJOR>` to a previous SemVer tag:**
   ```bash
   git tag -f v0 v0.0.5
   git push -f origin v0
   ```

This will trigger a new deploy of the previous version.

### cv (Data) Rollback

If a CV release is bad:

1. **Revert the commit** that introduced the bad data
2. **Delete the bad tag:**
   ```bash
   git push -d origin 2026.09.14
   ```

3. **Tag a new CalVer release:**
   ```bash
   git tag 2026.09.14-rollback  # or the next date
   git push origin 2026.09.14-rollback
   ```

This triggers a new publish with the reverted data.

### Tag Triggers Summary

| Tag pattern | Repository | Workflow triggered | Result |
|-------------|------------|-------------------|--------|
| `vX.Y.Z` (SemVer) | `cv-forge` | `.github/workflows/deploy-mcp.yml` | Builds and deploys the MCP server to `fps-cv-mcp` Wasmer app |
| `v<MAJOR>` alias | `cv-forge` | None — consumed by the `cv` plugin and marketplace only | Points to the latest `vX.Y.Z` release; no workflow trigger |
| `YYYY.MM.DD[.N]` (CalVer) | `cv` | `.github/workflows/publish.yml` (calls `cv-forge`'s reusable workflow) | Renders CV in all formats, publishes eight release assets, deploys HTML to `fps-cv` Wasmer app |

**Note:** The `v1` alias (moving major version tag in `cv-forge`) is consumed by the consumer plugin's MCP URL and the publish workflow's reusable workflow reference (`@v1`). It is never a published release tag itself — only the latest `v1.x.x` SemVer release is deployed.

## Verifying a Deployment

After a release, verify the MCP server is live:

```bash
# Check the health endpoint
curl -s https://fps-cv-mcp.wasmer.app/healthz | jq .

# Expected response:
{
  "status": "ok",
  "origin": {"kind": "release", "tag": "2026.09.14", "published_at": "2026-09-14T12:00:00Z"},
  "release_tag": "2026.09.14",
  "loaded_at": "2026-09-14T12:34:56Z",
  "refresh_state": "fresh",
  "cv_forge_version": "0.0.5",
  "consecutive_failures": 0
}
```

Verify the static HTML site:

```bash
curl -s https://fps-cv.wasmer.app/ | head -20
```

Verify GitHub Release assets are present:

```bash
curl -I https://github.com/francisco-perez-sorrosal/cv/releases/latest/download/resume.pdf
```

## Troubleshooting

### Release Fails with "working tree not clean"

```bash
git status
git stash push -u -m "temp-wip"
scripts/release.sh patch
git stash pop
```

### Release Tags But Doesn't Push

```bash
git push origin main
git push origin v0.0.6 v0
```

### Deploy-MCP Never Starts

Check `.github/workflows/deploy-mcp.yml` logs:
1. Open the GitHub Actions tab for this repo
2. Click on the failed run
3. Check the "Build and deploy" job for WASIX ceiling violations or `anybuild` errors
4. See `FEEDBACK.md` for known Wasmer issues

### HTML Site Doesn't Update After Publish

The static site app (`fps-cv`) is deployed via the reusable `publish.yml` workflow, not by `deploy-mcp.yml`. Verify:
1. The `cv` repo's publish workflow completed (check Actions tab)
2. The reusable workflow was invoked with `deploy-site: true`
3. Run `curl https://fps-cv.wasmer.app/` to see if the content is fresh

For additional support, see `FEEDBACK.md` for known issues and friction reports.
