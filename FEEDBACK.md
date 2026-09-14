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
| F-004 | WASIX index / anybuild | WASIX index / packaging | workaround | A greenfield `mcp` 2.2.0 server resolves `cryptography 50.0.1` + `cffi 2.1.1` (via `pyjwt[crypto]`); WASIX index tops out at `50.0.0` / `2.1.0`, and `cryptography` is imported at module load — three native ceilings (`pydantic-core`, `cryptography`, `cffi`) must now be hand-pinned |
| F-005 | anybuild | anybuild / Python-MCP provider | paper-cut | The MCP provider appends `mcp[cli]` to the cross-install command unconditionally, re-adding the `[cli]` extra (typer, rich, …) a project deliberately dropped to keep the Edge image small |
| F-006 | WASIX index + Wasmer Edge runtime | WASIX index / Edge runtime / packaging | blocker | `cffi 2.1.0+wasix.{1,2,3}` ships `_cffi_backend.cpython-313-wasm32-wasi.so` (non-threads suffix) but the Edge `python/python 3.13.17` runtime is a wasi-threads build that only loads `…-wasi-threads.so` — so `cryptography` (required by every `mcp` 2.x at import) dies on Edge with `ModuleNotFoundError: _cffi_backend`; the same image imports fine under `wasmer run` locally, which is a non-threads build |
| F-007 | wasmer (CLI) / Wasmer Edge | Edge deploy / CLI | paper-cut | `wasmer deploy` health-checks `/` and reports a false "fails with a non-success status code of 404" for an app that serves `/healthz` and `/mcp`; the same sentence with `500` was the only signal for the real F-006 crash |
| F-009 | wasmer (CLI) / static-website template / docs | static site / Edge deploy | workaround | `wasmer app create --template static-website` scaffolds `app.yaml` + `Staticfile` + `settings/config.toml` + `public/` and its README says "run `wasmer deploy`", but `wasmer deploy --non-interactive` refuses: "The app.yaml references a local package, but no wasmer.toml manifest was found … use --build-remote"; a hand-written `wasmer.toml` for `wasmer/static-web-server` fixes it |
| F-008 | setup-wasmer | CI action | paper-cut | `wasmerio/setup-wasmer` v3.1 targets Node.js 20 (GitHub force-runs it on Node 24 with a deprecation annotation) and the CLI it installs was not on PATH inside a `pixi run` step (`WASMER_DIR` is exported, `$WASMER_DIR/bin` is not reliably on PATH) |
| F-005 | wasmerio/setup-wasmer | CI action | paper-cut | `action.yml`'s only documented input is `version` (default `''`); no README/marketplace text states the accepted format (plain SemVer? `v`-prefixed? range?) or what `''` resolves to -- confirmed empirically, not from docs |

---

## Sibling-ledger items to re-verify in this project

From `wasmer-sdk-mcp`'s ledger (2026-09-04/05, anybuild 0.28.3, CLI 6.1.0 → 7.4.0). Each gets its own `F-NNN` here once observed again (or observed fixed):

| sdk-mcp id | one-line | where it would surface here |
|---|---|---|
| F-009 | anybuild injects `FASTMCP_HOST`/`FASTMCP_PORT`, which `mcp` 2.x ignores | Mitigated in code since M1.8 (`("PORT", "FASTMCP_PORT")` fallback in `mcp/main.py`/`main.py`); `app.yaml` deliberately sets neither, letting Edge's own injection and the code's fallback agree. Unverified live until M3.2. |
| F-017 | `wasmer self-update` hangs then fails on `get.wasmer.io:443` | M1.0 toolchain |
| F-018 | WASIX wheel index lags PyPI (`pydantic-core` ≤ 2.46.4) and anybuild pins the host resolve | M1.3 `pydantic` pin, M3.2 |
| F-019 | anybuild shells out to `wasmer run --volume`, rejected by CLI < 7; no version check | Mitigated at M1.20: `scripts/deploy.sh` asserts `wasmer --version >= 7.0.0` and aborts with a named reason before invoking anybuild. Unverified live until M3.2 (this machine already carries 7.4.1, so the assertion itself has not been exercised against a real 6.x failure here). |
| F-020 | CLI 6.1.0 upload dies on bare HTTP 500 from `registry.wasmer.io/gcs-upload` | Same mitigation as F-019 (version assert prevents reaching this path); unverified live until M3.2 |
| F-021 | anybuild ships the whole project dir, ignoring `.gitignore` | Mitigated at M1.20: `scripts/deploy.sh` stages `git ls-files` output (plus a `baked/` fallback snapshot) into a temp dir and never invokes `anybuild` from the repo root. Dry-run verified locally (152 tracked+baked files staged, zero untracked leakage); real `anybuild` invocation still pending M3.2. |
| F-025 | `cross-requirements.txt` compiled with `--no-deps` silently drops extras | M1.3 (`mcp[cli]` extra dropped on purpose) |
| F-038 | No local Edge runtime; every end-to-end test is a production deploy | M3.3 live poke |
| F-039 | `setup-wasmer` input undocumented; example pins a CLI too old for anybuild | Materialized as this ledger's F-005 (M1.28 `publish.yml`, static-site job); `deploy-mcp.yml` itself is deferred to M1.28b pending M1.20 |
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
- **Reproduced in CI (2026-09-14):** same gap confirmed on a second platform while authoring `.github/workflows/deploy-mcp.yml` (M1.28b) — `ubuntu-latest` GitHub Actions runner, installer downloaded to a file (never piped to `sh`) and run with `ANYBUILD_NO_PATH_UPDATE=1`, then `~/.anybuild/bin` appended to `$GITHUB_PATH` in place of sourcing `$HOME/.anybuild/env`. `anybuild.run/`'s landing page still has no mention of the variable as of this date (`curl`-and-`grep` came back empty). No new entry needed — this strengthens F-003 with a second, independent environment rather than duplicating it.

### F-004 — Current `mcp` 2.2.0 pulls `cryptography`/`cffi` one patch above the WASIX index; three native ceilings must be hand-pinned
- **Target repo:** WASIX package index (`python-registry.wasix.org`, owning repo to confirm) + wasmerio/anybuild (resolution strategy) + docs.wasmer.io (Python/MCP guide)
- **Area:** WASIX index / packaging
- **Severity:** workaround (would be a `blocker` at first cross-install; caught by a code review before the first `anybuild` run)
- **Environment:** macOS arm64 (Darwin 25.3), Python 3.13, `pixi` 0.40.3 lock for `osx-arm64` + `linux-64`, `mcp` **2.2.0** (official Python SDK, released 2026), 2026-09-13. WASIX index queried the same day.
- **Steps to reproduce:**
  1. New project with `dependencies = ["mcp>=2.2,<3", "pydantic>=2.12,<2.13.5"]` (the `pydantic` ceiling is already the known one — sdk-mcp F-018).
  2. Resolve normally (`pixi install` / `uv lock`).
  3. Compare the lock against the index:
     | Package | Host resolve (PyPI) | Max on `python-registry.wasix.org` | Why it is in the closure |
     |---|---|---|---|
     | `cryptography` | 50.0.1 | `50.0.0+wasix.2` (`cp313-abi3`, `cp314-abi3`) | `mcp` → `pyjwt[crypto]>=2.10.1`; imported at module top in `mcp/server/request_state.py:22-25` (`AESGCM`, `HKDF`, `SHA256`) — not an optional auth path |
     | `cffi` | 2.1.1 | `2.1.0+wasix.3` (`cp313`, `cp314`) | via `cryptography` |
     | `pydantic-core` | 2.46.5 (if `pydantic` unpinned) | `2.46.4+wasix.2` | via `pydantic` (known: sdk-mcp F-018) |
  4. `anybuild` cross-installs with `uv pip install --platform wasix_wasm32 --only-binary=:all:` from the host-pinned `cross-requirements.txt`.
- **Expected:** either the index tracks PyPI closely enough that the *current* official MCP SDK resolves cleanly on WASIX, or the tooling tells me up front which resolved versions have no WASIX wheel and which nearest version does — before a deploy attempt.
- **Actual:** nothing in `anybuild`, `wasmer`, or the docs surfaces the gap. The failure would appear at cross-install time as a missing-wheel error for `cryptography==50.0.1` (or, if `anybuild`'s `--no-deps` compile drops the `crypto` extra — sdk-mcp F-025 — as an import-time death on Edge with a bare HTTP 500 and no traceback, the sdk-mcp F-026 signature). We now carry three hand-written ceilings with comments:
  ```toml
  # WASIX ceilings (verified 2026-09-13 against python-registry.wasix.org):
  # pydantic-core 2.46.4, cryptography 50.0.0, cffi 2.1.0.
  "pydantic>=2.12,<2.13.5",
  "cryptography>=43,<50.0.1",
  "cffi>=2.1,<2.1.1",
  ```
  and a CI script that re-queries the index so the pins fail loudly when they drift.
- **Proposed fix:** (1) `anybuild` (or `wasmer`) gains a `check` mode that diffs a lockfile against the WASIX index and prints per-package "resolved X, WASIX max Y, nearest satisfiable Z" *before* building — the data is all public; (2) a published, machine-readable "WASIX index vs PyPI lag" page (or a `constraints.txt` per Python ABI that users can pass to their resolver) so pins do not have to be discovered one package at a time; (3) the docs' Python/MCP quick-start states plainly that the official `mcp` 2.x SDK needs these three ceilings today.
- **Docs consulted:** <https://docs.wasmer.io/> Python on Edge / anybuild pages (2026-09-13) — no mention of index lag, ceilings, or a constraints file.
- **Evidence:** `pyproject.toml` (pins with comments), `pixi.lock` lines ~445/471 (pre-fix resolve `cffi 2.1.1`, `cryptography 50.0.1`); review report `.ai-work/cv-repo-split/LIGHT_REVIEW_M1.3.md` § F1 (local-only; the table above inlines its content).
- **Related:** sdk-mcp F-018 (same class, `pydantic-core`; still reproduces on 2026-09-13), F-025 (extras dropped), F-026 (native trap → bare 500).

### F-005 — anybuild's Python-MCP provider unconditionally appends `mcp[cli]` to the cross-install
- **Target repo:** wasmerio/anybuild
- **Area:** anybuild / Python-MCP provider
- **Severity:** paper-cut
- **Environment:** macOS arm64 (Darwin 25.3), anybuild 0.28.4, `wasmer` 7.4.1, Python 3.13, 2026-09-14. Project declares `mcp>=2.2,<3` (no extras) on purpose.
- **Steps to reproduce:**
  1. `Anybuild` with `python_framework = "mcp"`.
  2. `anybuild auto --platform=wasmer …` (or a local `--runner=wasmer` build) and read the install step it prints.
- **Expected:** the provider installs what `pyproject.toml` declares (`cross-requirements.txt` already carries `mcp==2.2.0`).
- **Actual:** the provider adds the extra itself:
  ```
  $ uvx pip install -r cross-requirements.txt mcp[cli] --target /opt/venv/lib/python3.13/site-packages --platform wasix_wasm32 --only-binary=:all: --python-version=3.13 --compile
  ```
  so `typer`, `rich`, `shellingham`, `pydantic-settings`, `python-dotenv`, `httpx-sse`, … land in the Edge image even though the server never imports them. Combined with sdk-mcp F-025 (extras are *dropped* when compiling `cross-requirements.txt`), the provider both strips extras the project asked for and adds one it did not.
- **Proposed fix:** honour the project's own `mcp` requirement string; if the provider needs the CLI extra for its own tooling, install it into a build-time-only environment, not `/opt/venv`. At minimum, document the injection on the Python-MCP provider page.
- **Docs consulted:** <https://docs.wasmer.io/> anybuild Python/MCP pages (2026-09-14) — no mention of the injected extra.
- **Evidence:** deploy log of the first `fps-cv-mcp` deploy (local-only, quoted above); `pyproject.toml` `dependencies` block.
- **Related:** sdk-mcp F-025.

### F-006 — `cffi`'s WASIX wheel targets the non-threads ABI; the Edge runtime is a wasi-threads build, so `cryptography` (and every `mcp` 2.x server) dies at import
- **Target repo:** WASIX package index (`python-registry.wasix.org`, owning repo to confirm) — the `cffi` wheel; and Wasmer Edge runtime / docs — the local-vs-Edge interpreter mismatch is undocumented
- **Area:** WASIX index / Edge runtime / packaging
- **Severity:** blocker (first deploy of a stock `mcp` 2.2.0 server returns HTTP 500 on every request)
- **Environment:** macOS arm64 (Darwin 25.3), anybuild 0.28.4, `wasmer` 7.4.1, project pins `mcp>=2.2,<3`, `cryptography>=43,<50.0.1`, `cffi>=2.1,<2.1.1`; image manifest generated by anybuild: `"python/python" = "=3.13.17"` (reports CPython 3.13.15); deployed app version `dav_RLmILtmuJDl5`, region `us-hillsboro`, 2026-09-14.
- **Steps to reproduce:**
  1. Any project whose dependency closure includes `cryptography` (here: `mcp` 2.2.0 → `pyjwt[crypto]` → `cryptography 50.0.0+wasix.2` → `cffi 2.1.0+wasix.3`; `mcp/server/request_state.py:22` imports `cryptography` at module load, so it cannot be avoided).
  2. `anybuild auto --platform=wasmer …` — build and upload succeed; `wasmer deploy` reports "deployed successfully" then "fails with a non-success status code of 500".
  3. `curl -i https://fps-cv-mcp.wasmer.app/healthz` → `HTTP/2 500`, `x-edge-request-outcome: workload_failure`, HTML error page.
  4. `wasmer app logs fps-cv-mcp` →
     ```
     File "/opt/venv/lib/python3.13/site-packages/cryptography/exceptions.py", line 9, in <module>
       from cryptography.hazmat.bindings._rust import exceptions as rust_exceptions
     ModuleNotFoundError: No module named '_cffi_backend'
     ```
  5. Inspect the image anybuild built (`.anybuild/local/build/opt/venv/lib/python3.13/site-packages/`): the module **is** there, as `_cffi_backend.cpython-313-wasm32-wasi.so`. Every other native wheel in the closure uses a different suffix: `pydantic_core/_pydantic_core.cpython-313-wasm32-wasi-threads.so`, `yaml/_yaml.cpython-313-wasm32-wasi-threads.so`, `cryptography/hazmat/bindings/_rust.abi3.so`.
  6. Under the *local* runtime — `wasmer run python/python@3.13.17 --mapdir /site:<that site-packages> -- -c "import _cffi_backend; import pydantic_core"` — `_cffi_backend` imports and `pydantic_core` fails (`No module named 'pydantic_core._pydantic_core'`); `sysconfig.get_config_var('EXT_SUFFIX')` is `.cpython-313-wasm32-wasi.so` and `EXTENSION_SUFFIXES` is `['.cpython-313-wasm32-wasi.so', '.abi3.so', '.so']`. On Edge the observed behaviour is the mirror image (`pydantic_core` loads — the sibling project runs on it — and `_cffi_backend` does not).
- **Expected:** one ABI: every wheel on the index built with the suffix the Edge interpreter actually probes, and the `python/python` package behaving the same under `wasmer run` and on Edge (or the difference documented, with `EXT_SUFFIX` stated per target).
- **Actual:** the index mixes ABIs (`cffi` = non-threads, `pydantic-core`/`pyyaml` = threads) and the same package version resolves to a non-threads build locally and a threads build on Edge, so a closure that imports cleanly under `wasmer run` traps on Edge with no hint that an extension suffix is the cause. All three published `cffi` builds (`+wasix.1/.2/.3`, cp313 and cp314) carry the non-threads suffix.
- **Proposed fix:** rebuild `cffi` for the wasi-threads ABI (or publish both suffixes in one wheel, as the interpreter's `EXTENSION_SUFFIXES` list allows); make `wasmer run python/python` and Edge use the same build, or print the target ABI in `anybuild`'s build summary and have `anybuild` cross-check every `.so` suffix in the venv against it before upload — a one-line check that would have turned a bare production 500 into a build-time error. Document `EXT_SUFFIX` per runtime on docs.wasmer.io.
- **Docs consulted:** <https://docs.wasmer.io/> Python on Edge / anybuild pages (2026-09-14) — nothing on threads vs non-threads interpreter builds or extension suffixes.
- **Evidence:** app version `dav_RLmILtmuJDl5`; `wasmer app logs fps-cv-mcp`; local anybuild build tree (local-only) with the file list above; this repo's `scripts/deploy.sh` (vendor shim) and `main.py` (`vendor/wasix` on `sys.path`).
- **Related:** sdk-mcp F-026 (native extension trap → bare 500, no traceback), F-018 (index lag). Different root cause from both.
- **Workaround in this repo:** `scripts/deploy.sh` cross-installs the pinned `cffi` wheel into `vendor/wasix/` inside the staged tree and adds a copy named `_cffi_backend.cpython-313-wasm32-wasi-threads.so`; `main.py` prepends `vendor/wasix` to `sys.path`. Status: **works** — the redeploy (2026-09-14, second app version) answers `GET /healthz` with HTTP 200 and serves `tools/list` over stateless streamable HTTP; the non-threads-built `.so` loads and runs under the threads interpreter once the file name matches, which confirms the suffix probe, not the ABI, was the failure. The shim is still a workaround: it ships a second copy of the module in `/app` and depends on the index's file name staying stable.

### F-007 — `wasmer deploy` health-checks `/` and reports a false failure for an app that serves `/healthz` and `/mcp`
- **Target repo:** wasmerio/wasmer (CLI) / Wasmer Edge
- **Area:** Edge deploy / CLI
- **Severity:** paper-cut (reproduces sdk-mcp F-041 on a second project)
- **Environment:** `wasmer` 7.4.1, anybuild 0.28.4, app `fps-cv-mcp` (`app.yaml` in this repo), 2026-09-14.
- **Steps to reproduce:** `scripts/deploy.sh fps-cv-mcp` (wraps `anybuild --platform=wasmer` → `wasmer deploy`).
- **Expected:** the post-deploy wait either probes a documented, configurable path (e.g. `healthz` from `app.yaml`) or reports the probed path and status without calling the deploy a failure.
- **Actual:**
  ```
  ✔ App fps-cv-mcp (francisco-perez-sorrosal) deployed successfully.
  Waiting for new deployment to become available...
  The app version was deployed correctly, but fails with a non-success status code of 404 Not Found
  ```
  while, seconds later, `curl -i https://fps-cv-mcp.wasmer.app/healthz` is `HTTP/2 200` with the expected JSON body. The first (genuinely broken) deploy of this app produced the same sentence with `500` — the message shape does not distinguish "your app has no `/`" from "your app crashed", which cost real diagnosis time (see F-006).
- **Proposed fix:** a `health_check_path` (or reuse of a `healthz`-style convention) in `app.yaml`; and print the probed URL in the message.
- **Docs consulted:** <https://docs.wasmer.io/> Edge app configuration (2026-09-14) — no health-check path setting found.
- **Evidence:** deploy logs of both app versions (local-only; sentences quoted verbatim above).
- **Related:** sdk-mcp F-041 — still reproduces on CLI 7.4.1.

### F-008 — `setup-wasmer` v3.1: Node 20 deprecation annotation, and the installed CLI is not on PATH inside a `pixi run` step
- **Target repo:** wasmerio/setup-wasmer
- **Area:** CI action
- **Severity:** blocker → workaround (two CI deploys failed; root cause found on the second with a diagnostic step: `version: '7.4.1'` makes the wrapped installer 404 on the release download, and the action then reports success with nothing installed — `version: 'v7.4.1'` works)
- **Environment:** GitHub Actions `ubuntu-latest`, `wasmerio/setup-wasmer@24b15c95…` (v3.1) with `version: '7.4.1'`, `prefix-dev/setup-pixi` + `pixi run -e dev ./scripts/deploy.sh`, 2026-09-14, run `34862858731` in `francisco-perez-sorrosal/cv-forge`.
- **Steps to reproduce:**
  1. A job with `setup-pixi` → `setup-wasmer` → a step running `pixi run -e dev <script that does command -v wasmer>`.
- **Expected:** `wasmer` resolvable from any later step, including inside `pixi run`; an action that runs on the Node version the runner supports without a deprecation banner.
- **Actual:**
  ```
  ! Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on Node.js 24: wasmerio/setup-wasmer@24b15c95…
  …
  env:
    WASMER_DIR: /home/runner/.wasmer
    WASMER_CACHE_DIR: /home/runner/.wasmer/cache
  deploy.sh: preflight failed -- wasmer CLI not found on PATH (need >= 7.0.0: …)
  ```
  A second run with a diagnostic step (`command -v wasmer; ls $WASMER_DIR/bin`) showed `~/.wasmer/bin` does not exist at all, and the action's own step log explains why:
  ```
  downloading: wasmer-linux-amd64
  Installing provided version: 7.4.1
  error: File download failed with code 404
  Executed installer. (Exit code 0)
  Updated environment variables.
  ```
  `version: '7.4.1'` is passed verbatim to the installer, which builds a GitHub release URL from it; the release tags are `v7.4.1`, so the download 404s — and the action reports success anyway. `version: 'v7.4.1'` installs correctly. So the PATH observation is a symptom, not the cause; the cause is a silently ignored installer failure plus an undocumented `version` format.
- **Proposed fix:** make the action fail when the installer fails (propagate the installer's exit code, or check that `$WASMER_DIR/bin/wasmer --version` works before "Updated environment variables"); accept both `7.4.1` and `v7.4.1` (normalise the prefix) and document the format in `action.yml`'s input description; publish a Node-24 build; append `$WASMER_DIR/bin` to `GITHUB_PATH` explicitly (see sdk-mcp F-039).
- **Docs consulted:** the action's README (no `version` format, no PATH note), 2026-09-14.
- **Evidence:** run `34862858731`, job `deploy`, step "Deploy fps-cv-mcp" (log quoted above); `scripts/deploy.sh` resolution block.
- **Related:** sdk-mcp F-039.

### F-009 — The static-website template deploys only after adding a `wasmer.toml` its scaffold does not include
- **Target repo:** wasmerio/wasmer (CLI `deploy`), the `static-website` template repo, docs.wasmer.io (static site / CDN tutorial)
- **Area:** static site / Edge deploy
- **Severity:** workaround
- **Environment:** `wasmer` 7.4.1 (locally and via `setup-wasmer` in GitHub Actions `ubuntu-latest`), 2026-09-14.
- **Steps to reproduce:**
  1. `wasmer app create --template static-website --owner <me> --name fps-cv --dir site --non-interactive` → `site/` contains `app.yaml` (`package: .`), `Staticfile` (`root: public`), `settings/config.toml`, `public/…`, `README.md` ("Run this command to deploy to Wasmer Edge: `wasmer deploy`") — no `wasmer.toml`.
  2. Put content in `public/`, then in CI: `wasmer deploy --non-interactive` with `WASMER_TOKEN` set.
- **Expected:** the template deploys as its README says, or `wasmer deploy` generates the missing manifest from `Staticfile` the way the interactive path presumably does.
- **Actual:**
  ```
  error: The app.yaml references a local package, but no wasmer.toml manifest was found in /home/runner/work/cv/cv/cv-forge/deploy/site - use --build-remote to deploy with a remote build.
  ```
  Adding this manifest makes both `wasmer run . --net` (local: `/` and `/health` → 200) and the deploy work:
  ```toml
  [dependencies]
  "wasmer/static-web-server" = "1"
  [fs]
  "/public" = "public"
  "/settings" = "settings"
  [[command]]
  name = "script"
  module = "wasmer/static-web-server:webserver"
  runner = "https://webc.org/runner/wasi"
  [command.annotations.wasi]
  main-args = ["-w", "/settings/config.toml"]
  ```
- **Proposed fix:** ship the `wasmer.toml` in the template (or have `wasmer deploy` synthesise it from `Staticfile` in non-interactive mode, as `--build-remote` apparently does server-side); say in the template README and the CDN tutorial which of the two files is authoritative.
- **Docs consulted:** template README; <https://docs.wasmer.io/edge/tutorials/cdn> (2026-09-14) — the manifest above is reconstructed from the runner/`fs` conventions, not copied from a documented example.
- **Evidence:** publish run `34865183944` in `francisco-perez-sorrosal/cv`, step "Deploy the static site" (message quoted verbatim); `deploy/site/wasmer.toml` in this repo.
- **Related:** none in the sibling ledger.

### F-005 — `setup-wasmer` action.yml documents only a bare `version` input, no format guidance
- **Target repo:** wasmerio/setup-wasmer
- **Area:** CI action
- **Severity:** paper-cut
- **Environment:** GitHub Actions, `wasmerio/setup-wasmer` tag `v3.1` (commit `24b15c95293d23f89c68bd40dac76338f773e924`, fetched 2026-09-13/14), used from `cv-forge`'s `.github/workflows/publish.yml` (M1.28) for the static-site deploy job.
- **Steps to reproduce:**
  1. `curl -s https://raw.githubusercontent.com/wasmerio/setup-wasmer/v3.1/action.yml`
  2. Read the full file (13 lines): `inputs: version: { default: '' }` is the only documented surface.
- **Expected:** the action's README or `action.yml` comment states what version strings are accepted (bare SemVer like `7.4.1`? a `v`-prefixed tag? a range like `7.x`?) and what installing with `version: ''` actually resolves to (latest release? a pinned default baked into the action's own release?).
- **Actual:** no such text exists in `action.yml`; the only way to know `version: '7.4.1'` (bare, unprefixed) works is to try it. `SYSTEMS_PLAN.md`'s own requirement ("CLI ≥ 7 pin") could not be satisfied with confidence from docs alone — pinned `7.4.1` (the current `wasmerio/wasmer` `latest` release tag `v7.4.1` at fetch time) based on inference from the release list, not from `setup-wasmer` documentation.
- **Proposed fix:** document the accepted `version` string format and the resolution behavior of `''` (empty/default) directly in `action.yml`'s `description:` field for that input, so `actionlint`/hover-tooling in editors surfaces it without a source read.
- **Docs consulted:** `action.yml` itself (no separate usage doc found at the repo root at this tag).
- **Evidence:** `.github/workflows/publish.yml` (this repo, M1.28) `Setup Wasmer CLI` step, pinned to the SHA above with `version: '7.4.1'`.
- **Related:** sdk-mcp F-039 (same action, "input undocumented; example pins a CLI too old for anybuild") -- this entry adds the specific missing-documentation detail sdk-mcp's F-039 flagged but did not itemize.
