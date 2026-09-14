# Wasmer DX Feedback Ledger — `cv-forge`

Friction observed while building and operating `cv-forge` on Wasmer software — Wasmer Edge (Python/WASIX app hosting, static sites, secrets, domains), `anybuild`, the `wasmer` CLI, `setup-wasmer` for GitHub Actions, the WASIX package index, and the docs at <https://docs.wasmer.io/>. Every stage of the work appends here; nothing is edited away. A sibling ledger for the same maintainer's `wasmer-sdk-mcp` project uses the same shape; entries here cross-reference it as `sdk-mcp F-NNN` when an item reproduces in a second project.

**Purpose.** Each entry is written for Wasmer's engineers **and their agents**, with none of our context assumed: exact versions, commands, verbatim output, expected vs actual, and a proposed fix when we have one. Each entry becomes a GitHub issue in the right upstream repo, filed per that repo's contribution structure.

**Target repos** (verify each repo's `CONTRIBUTING.md` / issue templates before filing):
- `wasmerio/anybuild` — build/deploy tool for Python/MCP apps
- `wasmerio/wasmer` — runtime and `wasmer` CLI
- `wasmerio/setup-wasmer` — GitHub Action
- `wasmerio/docs` (or wherever docs.wasmer.io is sourced — confirm) — documentation
- Wasmer Edge (managed platform, no public repo known — confirm; else file under `wasmerio/wasmer` or the support channel)
- WASIX package index (`python-registry.wasix.org`) — confirm owning repo

**Entry shape.** One `###` per item, id `F-NNN` (this ledger's own namespace, never reused), in this order:
- **Target repo** — one of the above (or "unknown — triage").
- **Area** — Edge deploy / Edge runtime / static site / anybuild / CLI / WASIX index / CI action / docs.
- **Severity** — `blocker` (could not proceed) · `workaround` (proceeded, but had to work around it) · `paper-cut` (cost time or trust) · `wish` (missing capability).
- **Environment** — OS, `wasmer --version`, `anybuild --version`, package versions, Python version. Omit only when the item is docs-only.
- **Steps to reproduce** — commands or URLs, in order.
- **Expected** / **Actual** — actual includes verbatim output or error text in a code block.
- **Proposed fix** — concrete: a doc section, an API, an error message, a default.
- **Docs consulted** — the exact docs.wasmer.io URL(s) read before hitting the problem, and what they said or did not say.
- **Evidence** — file paths in this repo, commit, URLs. Paths under `.ai-work/` and `tmp/` are **local-only** (gitignored pipeline scratch); when an entry is filed upstream, inline the quoted output those files hold.
- **Related** — `sdk-mcp F-NNN` when the sibling ledger already records it (say whether it still reproduces, and on which versions).

**Who writes.** Any agent or person touching a Wasmer surface in this project: an implementer executing a deploy step, the orchestrator running a live poke, a CI run that fails on a Wasmer step. Record at the moment of friction, not at the end. A positive surprise ("this just worked, unlike sdk-mcp F-NNN") is also an entry — mark severity `resolved-upstream` so Wasmer can see what improved.

| id | target repo | area | severity | one-line |
|----|-------------|------|----------|----------|
| F-001 | wasmer (CLI) | CLI / distribution | resolved-upstream | `wasmer self-update` 6.1.0 → 7.4.1 completed on 2026-09-13; it hung and failed on 2026-09-05 (sdk-mcp F-017) |
| F-002 | wasmer (CLI) / installer | CLI / distribution | paper-cut | `wasmer self-update` post-install hint leaks a raw ANSI reset (`[0m`) when stdout is not a TTY |
| F-003 | anybuild / docs | anybuild / docs | paper-cut | `anybuild --help` after install does not say the binary is not on PATH unless `~/.anybuild/env` is sourced; installer's `ANYBUILD_NO_PATH_UPDATE=1` is undocumented on docs.wasmer.io |

---

## Sibling-ledger items to re-verify in this project

From `wasmer-sdk-mcp`'s ledger (2026-09-04/05, anybuild 0.28.3, CLI 6.1.0 → 7.4.0). Each gets its own `F-NNN` here once observed again (or observed fixed):

| sdk-mcp id | one-line | where it would surface here |
|---|---|---|
| F-009 | anybuild injects `FASTMCP_HOST`/`FASTMCP_PORT`, which `mcp` 2.x ignores | M1.20 `main.py` port resolution, M3.2 first deploy |
| F-017 | `wasmer self-update` hangs then fails on `get.wasmer.io:443` | M1.0 toolchain |
| F-018 | WASIX wheel index lags PyPI (`pydantic-core` ≤ 2.46.4) and anybuild pins the host resolve | M1.3 `pydantic` pin, M3.2 |
| F-019 | anybuild shells out to `wasmer run --volume`, rejected by CLI < 7; no version check | M3.2 |
| F-020 | CLI 6.1.0 upload dies on bare HTTP 500 from `registry.wasmer.io/gcs-upload` | M3.2 |
| F-021 | anybuild ships the whole project dir, ignoring `.gitignore` | M1.20 `scripts/deploy.sh` staging |
| F-025 | `cross-requirements.txt` compiled with `--no-deps` silently drops extras | M1.3 (`mcp[cli]` extra dropped on purpose) |
| F-038 | No local Edge runtime; every end-to-end test is a production deploy | M3.3 live poke |
| F-039 | `setup-wasmer` input undocumented; example pins a CLI too old for anybuild | M1.28 `deploy-mcp.yml` |
| F-041 | `wasmer deploy` health-checks `/` and reports 404 for an app that only serves `/mcp` | M3.2 (we add `/healthz`; does the deploy check honour it?) |

---

### F-001 — `wasmer self-update` now completes (6.1.0 → 7.4.1); it hung on 2026-09-05
- **Target repo:** wasmerio/wasmer (CLI / distribution)
- **Area:** CLI / distribution
- **Severity:** resolved-upstream (positive report — the failure recorded eight days earlier did not reproduce)
- **Environment:** macOS arm64 (Darwin 25.3), `wasmer` 6.1.0 installed via the `get.wasmer.io` shell installer at `~/.wasmer/bin`, 2026-09-13.
- **Steps to reproduce:**
  1. `wasmer --version` → `wasmer 6.1.0`
  2. `wasmer self-update`
  3. `wasmer --version`
- **Expected:** the CLI upgrades itself to the current release.
- **Actual:** it did — `wasmer 7.4.1` afterwards. Output tail (run non-interactively, stdout not a TTY):
  ```
  If you want to have the commands available now please execute:

  source /Users/fperez/.wasmer/wasmer.sh[0m
  ```
  Wall time was not measured (the command ran inside a batched background job together with two unrelated installs); it did not hit the job's 10-minute timeout.
- **Proposed fix:** none needed for the upgrade itself. Worth knowing on your side that whatever made `get.wasmer.io:443` time out on 2026-09-05 (sdk-mcp F-017) was transient or has been fixed; if it was infrastructure, a status-page entry would let users tell "wait" from "work around".
- **Docs consulted:** none for this step (the sibling ledger's workaround — download the release from GitHub — was the fallback plan, not needed).
- **Evidence:** local pipeline log `.ai-work/cv-repo-split/` (local-only); inline output above is the complete relevant tail.
- **Related:** sdk-mcp F-017 (hang + `connection timeout` on 2026-09-05, same machine, same install method). Does **not** reproduce on 2026-09-13.

### F-002 — `wasmer self-update`'s post-install hint prints a raw `[0m` when stdout is not a TTY
- **Target repo:** wasmerio/wasmer (CLI) or the `get.wasmer.io` installer script — triage
- **Area:** CLI / distribution
- **Severity:** paper-cut
- **Environment:** as F-001; `wasmer self-update` invoked from a non-interactive shell (output captured to a file).
- **Steps to reproduce:**
  1. `wasmer self-update > out.log 2>&1`
  2. `tail -3 out.log`
- **Expected:** plain text when stdout is not a terminal (or a complete escape sequence pair if colour is forced).
- **Actual:** the closing hint carries a bare reset sequence with no opening colour code, visible as literal `[0m` in logs and CI output:
  ```
  source /Users/fperez/.wasmer/wasmer.sh[0m
  ```
- **Proposed fix:** gate colour output on `isatty(stdout)` (and honour `NO_COLOR`), or emit the opening and closing sequences together. Small, but every CI log of `self-update`/installer runs shows it.
- **Docs consulted:** n/a.
- **Evidence:** inline output above (complete).
- **Related:** none in the sibling ledger.

### F-003 — anybuild's installer puts the binary off `PATH` by default and the `ANYBUILD_NO_PATH_UPDATE` switch is undocumented
- **Target repo:** wasmerio/anybuild (installer at `https://anybuild.run/install`) + docs.wasmer.io
- **Area:** anybuild / docs
- **Severity:** paper-cut
- **Environment:** macOS arm64 (Darwin 25.3), installer fetched 2026-09-13, installs anybuild **0.28.4** to `~/.anybuild/bin/anybuild`.
- **Steps to reproduce:**
  1. `curl -fsSL https://anybuild.run/install -o anybuild-install.sh` (we download-then-inspect rather than pipe to `sh`, as any security-conscious CI would).
  2. `ANYBUILD_NO_PATH_UPDATE=1 sh anybuild-install.sh` — the variable exists in the script (line 86) but appears nowhere on docs.wasmer.io; we found it only by reading the script.
  3. `anybuild --version` → `command not found`; `~/.anybuild/bin/anybuild --version` → `0.28.4`.
- **Expected:** the docs page that says "install anybuild" documents (a) the download-and-inspect form of the installer, (b) `ANYBUILD_INSTALL_DIR` and `ANYBUILD_NO_PATH_UPDATE`, (c) that without shell-rc editing the binary lives at `~/.anybuild/bin` and `. "$HOME/.anybuild/env"` puts it on `PATH`. A Homebrew formula (as `wasmer` has) would remove the question entirely.
- **Actual:** the installer's final lines are the only place this is said:
  ```
  Downloading Anybuild for aarch64-apple-darwin...
  Installed Anybuild 0.28.4 to /Users/fperez/.anybuild/bin/anybuild
  Run this now to update your current shell:
    . "$HOME/.anybuild/env"
  ```
- **Proposed fix:** document the installer's environment variables and the non-rc install path on docs.wasmer.io's anybuild page; publish a Homebrew tap/formula; have `wasmer` CLI 7.x offer `wasmer anybuild` or a `wasmer install anybuild` so one installer covers both tools.
- **Docs consulted:** <https://docs.wasmer.io/> anybuild section (2026-09-13) — no mention of `ANYBUILD_NO_PATH_UPDATE`/`ANYBUILD_INSTALL_DIR`.
- **Evidence:** installer script (243 lines) saved locally at pipeline scratch; the two variables are read at lines 86 and 171.
- **Related:** sdk-mcp F-024 (anybuild `--help` lists no subcommands) — adjacent onboarding friction, same tool.
