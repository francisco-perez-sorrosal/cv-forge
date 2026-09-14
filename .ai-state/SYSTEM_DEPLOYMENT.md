# System Deployment

<!-- Living deployment architecture document. Maintained by pipeline agents via section ownership.
     Created by systems-architect, updated by implementer/cicd-engineer, validated by verifier/sentinel.
     Sections 1, 2, 3, 6, 7 (health checks), 9 are architect-owned.
     Sections 4, 5, 8, 10 are filled by the implementer / cicd-engineer. -->

## 1. Overview

| Attribute | Value |
|-----------|-------|
| **System** | cv-forge (MCP server + static CV site) and cv (published release artifacts) |
| **Primary runtime** | Wasmer Edge — WASIX CPython 3.13, built by `anybuild`, served by uvicorn |
| **Reverse proxy** | Wasmer Edge's own proxy (TLS and routing are platform-provided; no Caddy, no nginx) |
| **Database** | None. The only persistent state is the CV data, published as GitHub Release assets on `cv`. |
| **Deployment level** | Serverless edge (scale-to-zero), plus a static site and GitHub Releases |
| **Last verified** | 2026-09-13 by systems-architect (design target — nothing deployed to Wasmer yet) |

Three deployables and one decommission. The MCP server runs as a Wasmer Edge WASIX app (`fps-cv-mcp`) serving stateless streamable HTTP at `/mcp`, deployed from `cv-forge` by a staged `anybuild` build. The rendered HTML CV is published to a Wasmer static site (`fps-cv`) by the publish workflow, which is also what attaches the eight release assets to the GitHub Release on `cv`. The existing render.com service (`fps-cv.onrender.com`) stays live through the entire cutover and is decommissioned last, after the Wasmer endpoint has carried real traffic for at least a week.

The deployment's defining characteristic is that **there is no pre-deploy test environment**: no local Wasmer Edge emulator exists, so every honest end-to-end validation is a real deploy followed by a live probe. The architecture compensates structurally rather than technically — the old deployment is kept running, the cutover is a one-field URL change in the plugin manifest, and `/healthz` is designed as a verification surface rather than an afterthought.

## 2. System Context

![Deployment system context (L0) — CV consumers reaching the Wasmer MCP app and the Wasmer static site over HTTPS; the maintainer pushing a git tag that drives GitHub Actions, which uploads release assets and deploys the site; the MCP app fetching release.json, YAML and the PDF from GitHub Releases; the maintainer deploying the MCP app directly via the staged deploy script](diagrams/deployment-context/rendered/deployment-context.svg)

<details>
<summary>Diagram source: <code>diagrams/deployment-context/src/deployment-context.mmd</code></summary>

Regenerate with `mmdc -i .ai-state/diagrams/deployment-context/src/deployment-context.mmd -o .ai-state/diagrams/deployment-context/rendered/deployment-context.svg -b transparent`.

</details>

### External Dependencies

| Dependency | Type | Strong/Weak | Shared SLO? | Notes |
|-----------|------|-------------|-------------|-------|
| GitHub Releases (`cv`) | External | **Weak** | No | Source of the current CV data and the compiled PDF. An outage freezes freshness, not availability: the server keeps serving the last good snapshot, and the baked snapshot guarantees it always has one. Only `get_cv(format="pdf")` is genuinely degraded, and it degrades to a structured error carrying the direct download URL. |
| Wasmer Edge | Infrastructure | Strong | No | Hosts both apps. An outage takes the MCP endpoint and the CV page down. No multi-region failover is configured. |
| GitHub Actions | External | Weak | No | Publishing only. An outage delays a release; nothing already deployed is affected. |
| `python-registry.wasix.org` | External | Strong (build-time only) | No | Supplies WASIX wheels for `pydantic-core` and `pyyaml`. Unavailable at runtime is harmless; unavailable at build time blocks deploys. |
| TinyTeX / CTAN | External | Weak (build-time only) | No | PDF compilation in the publish workflow. Unavailable means no new PDF asset; the previous release's PDF stays reachable. |
| render.com | External | Weak (transitional) | No | The outgoing deployment. Live until decommissioned in the final cutover step. |

## 3. Service Topology

### Production (target)

![Service topology — Wasmer Edge hosting two apps: fps-cv-mcp running WASIX CPython 3.13 with uvicorn and mcp 2.2 MCPServer over a baked snapshot, exposing POST /mcp and /healthz and fetching release.json every 15 minutes and the PDF lazily from GitHub Releases; and fps-cv running wasmer/static-web-server over public/index.html for browsers](diagrams/deployment-topology/rendered/deployment-topology.svg)

<details>
<summary>Diagram source: <code>diagrams/deployment-topology/src/deployment-topology.mmd</code></summary>

Regenerate with `mmdc -i .ai-state/diagrams/deployment-topology/src/deployment-topology.mmd -o .ai-state/diagrams/deployment-topology/rendered/deployment-topology.svg -b transparent`.

</details>

| Service | Build | Endpoint | Health Check | Restart Policy |
|---------|-------|----------|--------------|----------------|
| `fps-cv-mcp` | `anybuild` → WASIX, from a `git ls-files` staging dir (`scripts/deploy.sh`) | `https://fps-cv-mcp.wasmer.app/mcp` (POST, stateless streamable HTTP) | `GET /healthz` | Platform-managed; ephemeral instances, scale-to-zero |
| `fps-cv` | `wasmer deploy` of a generated `public/` from the publish workflow | `https://fps-cv.wasmer.app/` | `GET /` returns 200 with the release tag present | Platform-managed |
| GitHub Release on `cv` | `gh release create` / `upload --clobber` in the publish workflow | `https://github.com/francisco-perez-sorrosal/cv/releases/latest/download/<asset>` | Asset presence + `release.json` parse, asserted by the publish run | N/A (static artifacts) |
| `fps-cv.onrender.com` | Buildpack (outgoing) | `https://fps-cv.onrender.com/mcp` | — | To be decommissioned after cutover |

**App names** (`fps-cv-mcp`, `fps-cv`) are proposed by the architecture, not yet reserved. They appear in the consumer plugin's MCP URL and in the publish workflow's `site-app` default; changing them later is a two-file edit.

### Development

No container topology. `CV_DATA_DIR=./cv-data cv-forge serve --transport http` serves locally from a checkout; `CV_DATA_DIR` pins the data provider so no network fetch occurs. `cv-forge render -f <fmt>` writes to a gitignored output directory.

## 4. Configuration

<!-- Owner: implementer / cicd-engineer. The architect records only the variables the
     architecture defines; the implementer completes defaults, sensitivity and per-environment
     differences once the code exists. -->

### Environment Variables (implementer-owned — built and verified against the code, M1.20)

**Correction (M1.20):** three statements below the previous draft made were wrong and are now fixed:
the refresh-interval variable is `CV_REFRESH_INTERVAL` (no `_SECONDS` suffix), the port default is
`10000` (`cv_forge.mcp.main.DEFAULT_PORT`), not `8000`, and `HOST` is a genuine environment variable
read at startup (`os.environ.get("HOST", "0.0.0.0")`), not a value pinned in code — Edge relies on
its default rather than an override.

| Variable | Default | Where read | Edge value (`app.yaml`) |
|----------|---------|------------|--------------------------|
| `CV_DATA_DIR` | unset | `data/bootstrap.py::initial_snapshot_from_env`/`build_provider_from_env` — when set, pins the provider to a local directory (no release fetch, `refresh_state: pinned`). Used by development, tests and CI. | unset (Edge always runs the fetch+baked-fallback path) |
| `CV_BAKED_DIR` | `<repo_root>/baked`, falling back to `<repo_root>/cv-data` if that path is not a directory | `data/bootstrap.py::baked_snapshot_dir` — the directory `scripts/deploy.sh` stages the fallback snapshot into before an image build | `baked` |
| `CV_RELEASE_REPO` | `francisco-perez-sorrosal/cv` | `data/bootstrap.py::build_provider_from_env` — repository whose latest release supplies the data | `francisco-perez-sorrosal/cv` |
| `CV_REFRESH_INTERVAL` | `900` (seconds) | `data/bootstrap.py::build_provider_from_env` — refresh-loop period; raising it is the first lever if GitHub rate-limiting is ever observed | `900` |
| `HOST` | `0.0.0.0` | `cli/main.py::_cmd_serve`, `main.py`'s `__main__` guard — a real env var, not a code-pinned constant. There is no `--host` CLI flag. | unset (default already correct) |
| `PORT` / `FASTMCP_PORT` | `10000` (`cv_forge.data.bootstrap.DEFAULT_PORT`), `PORT` checked first | `cli/main.py::_cmd_serve`, `main.py`'s `__main__` guard — `anybuild` injects `FASTMCP_PORT`, which the `mcp` SDK itself does not read; this project's own code resolves it explicitly | unset (Wasmer Edge assigns and injects the bind port itself) |
| `CV_TRUST_HOST` | unset (DNS-rebinding protection **on**) | `mcp/app.py::_transport_security` — `"1"` disables the SDK's Host/Origin allowlist entirely. Required on Edge: Wasmer's proxy terminates the public hostname in front of this app, so the SDK's own localhost-only defaults would 421 every request. | `"1"` |
| `CV_ALLOWED_ORIGINS` | unset | `mcp/app.py::_local_allowed_origins` — comma-separated list extending the local dev allowlist (e.g. a non-default dev frontend port). Irrelevant once `CV_TRUST_HOST=1` disables the check. | unset |

### Secrets Management

| Secret | Location | Purpose |
|--------|----------|---------|
| `WASMER_TOKEN` | `cv` repo secret | Static-site deploy from the publish workflow |
| `WASMER_TOKEN` | `cv-forge` repo secret | MCP app deploy from `deploy-mcp.yml`. May be the same token value; it is a second secret because it lives in a second repository. |

`GITHUB_TOKEN` is the caller's own, supplied by the `cv` workflow with `permissions: contents: write`; no token crosses the repository boundary. The MCP server itself holds **no** credentials — every asset it fetches is public.

### Environment Differences

[Implementer: complete once the code exists.]

## 5. Deployment Process

<!-- Owner: implementer / cicd-engineer. The architect supplies the intended flow and the
     two verification gates; the implementer fills exact commands and CI wiring. -->

![Deployment flow — from a clean working tree, assert the wasmer CLI is at least 7.0 or abort, stage git ls-files into a temp dir, materialise the fallback snapshot from the latest cv release, run anybuild from the staging dir, deploy, then gate on GET /healthz returning 200 and POST /mcp tools/list returning tools, rolling back to the previous app version on either failure](diagrams/deployment-flow/rendered/deployment-flow.svg)

<details>
<summary>Diagram source: <code>diagrams/deployment-flow/src/deployment-flow.mmd</code></summary>

Regenerate with `mmdc -i .ai-state/diagrams/deployment-flow/src/deployment-flow.mmd -o .ai-state/diagrams/deployment-flow/rendered/deployment-flow.svg -b transparent`.

</details>

The two non-negotiable properties of this flow, both derived from documented `anybuild` failure modes:

1. **Never run `anybuild` from the repository root.** It ignores `.gitignore`, excluding only `.venv`, `.git` and `__pycache__`, so it will ship local scratch directories into the image — and a large image fails the registry upload with a bare HTTP 500. Stage `git ls-files` output into a temp directory first.
2. **Assert `wasmer --version >= 7.0` before building.** On 6.1.0, `anybuild` 0.28.x shells out to a rejected `--volume` flag and its package upload fails with a bare HTTP 500. Also normalise `WASMER_BIN` to an absolute path: `anybuild` runs from the staging directory, so a relative binary path resolves there and fails with a bare "No such file or directory".

**Status (M1.32): artifacts present, not yet deployed.** `main.py`, `Anybuild`, `app.yaml`, `deploy/site/app.yaml`, `scripts/deploy.sh` and `.github/workflows/{deploy-mcp,publish,ci}.yml` all exist in the tree and are verified by static check (`bash -n`, a `--dry-run` staging run, `import main` with `CV_DATA_DIR` unset, `scripts/check_wasix_ceilings.py` clean) — no Wasmer app has been created yet (that is M3.1) and none of these have been exercised against the real platform. `deploy/site/app.yaml` in particular is a best-effort scaffold (no local Wasmer emulator exists to verify a static-site manifest against) and should be reconciled against whatever `wasmer app create fps-cv --template=static-website` actually produces at M3.1. This status line is superseded once M3 lands a real deploy.

### Rollback

`wasmer app rollback` to the previous app version. Because the cutover keeps render.com live and the consumer plugin's endpoint is a single JSON field, a failed migration is reverted by repointing that field — not by redeploying anything.

### CI/CD Integration

`.github/workflows/deploy-mcp.yml` (`v*` tag push or `workflow_dispatch`) checks out the tag, validates WASIX ceilings, and runs the same staged `anybuild`/`wasmer deploy` path as `scripts/deploy.sh` against `fps-cv-mcp`. `.github/workflows/publish.yml` is the reusable `workflow_call` `cv` invokes on its own CalVer tag push; its site-deploy step targets `fps-cv` and gates on the `cv-release-tag` meta tag (REQ-06). `.github/workflows/ci.yml` runs the test suite plus `scripts/check_wasix_ceilings.py` on every push/PR. None of the three has executed against a real Wasmer app yet — M3 is the first live run.

## 6. Failure Analysis

### Failure Mode Analysis

| Component | Risk | Likelihood | Impact / Mitigation | Outage Level |
|-----------|------|------------|---------------------|--------------|
| Data refresh | GitHub unreachable or rate-limited | Low | Provider keeps the current snapshot, increments `consecutive_failures`, state moves to `Stale`. `/healthz` still returns 200 and reports the staleness. No client-visible error. | Degraded (freshness only) |
| Data refresh | New release contains YAML that fails validation | Low | Parsed into a new snapshot *before* the swap, so the bad release is rejected and the previous snapshot stays live. Counted as a refresh failure. | Degraded (freshness only) |
| PDF artifact | Release PDF asset missing or unfetchable | Low | `ArtifactUnavailable` returned as a structured message naming the asset and its direct download URL. Every other format is still rendered in-process. | Partial (one tool surface) |
| MCP app | WASIX instance traps on a native extension | Low (no such dependency today) | Manifests as a bare HTTP 500 with **no traceback and no log line** — the documented WASIX signature. Diagnosis requires a staged instrumented probe. Prevention: check `python-registry.wasix.org` for a wheel before adding any native dependency. | Full |
| MCP app | Bound to loopback instead of `0.0.0.0` | Medium if unguarded | Instance unreachable behind the Edge proxy, and it also trips the SDK's DNS-rebinding allowlist. Prevented by `HOST` defaulting to `0.0.0.0` in code and by `CV_TRUST_HOST=1` on Edge (§4). | Full |
| MCP app | Port read from the wrong variable | Medium if unguarded | `anybuild` injects `FASTMCP_PORT`, which the SDK ignores, and the SDK's own default is `127.0.0.1:8000`. Prevented by resolving `("PORT", "FASTMCP_PORT")` explicitly. | Full |
| Build | `pydantic` pin raised above the WASIX ceiling | Medium over time | Cross-install fails at build time (loud, not silent). CI queries the WASIX index for the max `pydantic-core` and fails when the pin must move. The ceiling binds today: PyPI's current `pydantic` is `2.13.5`, and `<2.13.5` is required. | Build blocked |
| Build | Untracked files staged into the image | High if unmitigated | Bare HTTP 500 on registry upload. Prevented by the `git ls-files` staging step. | Deploy blocked |
| Build | `wasmer` CLI older than 7.0 | Medium | Two distinct failures, both with unhelpful messages. Prevented by an explicit version assertion that aborts with the reason. | Deploy blocked |
| Publish | TinyTeX package set diverges from local MacTeX | Medium | A broken or visually wrong PDF is the headline artifact. Mitigated by running the first publish with `draft: true` so the release is inspectable before it is public, and comparing the CI PDF against the local one (page count + text extraction) before promoting. | Artifact quality |
| Publish | Typst compilation | Medium | The `typst` CLI has never been exercised in this project (`COMPILERS["typst"]` is `None`). v1 publishes Typst *source* only; PDF compilation is a follow-up. | None (scoped out) |
| Static site | Deploy succeeds but the page is wrong or stale | Low | The publish run asserts `GET /` returns 200 **with the release tag present** and fails otherwise, so a green run means the page is genuinely live and current. | Site only |
| Cutover | render.com decommissioned too early | Medium | Recreating a deleted render.com service is manual. It is the last step in the migration and is deliberately separated from cutover by at least a week of live traffic. | Full, unrecoverable quickly |

### Dependency Classification

| Dependency | Type | Strong/Weak | Failure Impact |
|-----------|------|-------------|----------------|
| Wasmer Edge | Infrastructure | Strong | Both apps down |
| GitHub Releases | External | Weak | Freshness frozen; PDF tool degraded; everything else intact |
| GitHub Actions | External | Weak | Publishing delayed; nothing deployed is affected |
| WASIX package registry | Build-time | Strong | Deploys blocked; running instances unaffected |
| TinyTeX / CTAN | Build-time | Weak | No new PDF asset; the previous release's PDF stays reachable |

## 7. Monitoring & Observability

### Health Checks

| Service | Endpoint | Semantics |
|---------|----------|-----------|
| `fps-cv-mcp` | `GET /healthz` | **200 only when a validated snapshot is loaded**; 503 otherwise. Never an unconditional 200. Body: `{origin, release_tag, loaded_at, refresh_state, consecutive_failures}` — enough to answer "which release am I serving, and is my refresh working" without reading logs. |
| `fps-cv` | `GET /` | 200 with the release tag present in the page. Asserted by the publish run, not polled. |

### Logging

[Implementer: structured logging baseline. The refresh loop must log a cause **once per state transition**, not once per failed attempt — a 15-minute loop failing for a day would otherwise produce 96 identical lines.]

### Service Level Indicators

[Not defined. Traffic volume does not yet justify SLIs; `consecutive_failures` on `/healthz` is the one signal worth sampling.]

## 8. Scaling

Wasmer Edge manages instance count; there are no resource limits to configure and no vertical/horizontal decision to make. The architecturally relevant consequence is that instances are **ephemeral and horizontally multiplied with no session affinity**, which is why the transport is stateless (the 2026-07-28 MCP spec revision makes that the default) and why every cache is per-instance.

The one scaling-shaped constraint is GitHub's 60-requests-per-hour unauthenticated ceiling **per source IP**. At a 15-minute refresh interval each instance costs 4 requests/hour, leaving headroom for roughly 15 concurrent instances sharing an egress IP. If throttling is ever observed, lengthen `CV_REFRESH_INTERVAL` — an environment change, not a code change.

## 9. Decisions

Deployment decisions are recorded as ADRs in `.ai-state/decisions/`. This section provides quick cross-references. All entries are in-flight fragments under `decisions/drafts/` and promote to stable `dec-NNN` at merge-to-main.

| ADR | Decision | Impact on Deployment |
|-----|----------|---------------------|
| `dec-draft-16b56698` | Wasmer Edge for the MCP server and a Wasmer static site for the HTML CV; render.com decommissioned after verified cutover | Defines both deployables, the staged-deploy discipline, and the live-poke verification that replaces an absent pre-deploy gate |
| `dec-draft-45aafe55` | Runtime data via `CvDataProvider` — baked snapshot at startup, `release.json`-gated refresh, render-what-we-can / fetch-only-the-PDF | Makes availability independent of GitHub, defines `/healthz`'s body, and sets the refresh interval that bounds rate-limit exposure |
| `dec-draft-2fbed258` | Publish topology: reusable workflow owned by `cv-forge`, called from `cv`; pull-only schema mirror | Defines the release-asset contract the server fetches from, and keeps `WASMER_TOKEN` the only secret in either repository |
| `dec-draft-21e53cfb` | Migrate to `mcp` 2.2.0; pin `pydantic>=2.12,<2.13.5` | The pin is a deployment constraint, not a compatibility one — it exists because of the WASIX `pydantic-core` ceiling |
| `dec-draft-fb7c5d3f` | Drop MCPB and the MCP registry entry | Removes the local-distribution deployable entirely; Claude Desktop reaches the same remote endpoint as a custom connector |

## 10. Runbook Quick Reference

<!-- Owner: implementer / cicd-engineer. The architect seeds only the commands the
     architecture already determines; the implementer completes this once the code exists. -->

### Common Operations

| Task | Command |
|------|---------|
| Deploy the MCP server | `./scripts/deploy.sh` (from a clean `cv-forge` tree) |
| Check what the server is serving | `curl -sf https://fps-cv-mcp.wasmer.app/healthz` |
| Probe the MCP surface | `POST https://fps-cv-mcp.wasmer.app/mcp` with a `tools/list` request |
| Publish a new CV | `git tag 2026.MM.DD && git push --tags` (in the `cv` clone) |
| Re-render without a data change | `gh workflow run publish.yml --repo francisco-perez-sorrosal/cv -f tag=<tag>` |
| Roll back the MCP app | `wasmer app rollback` |
| Check the WASIX `pydantic-core` ceiling | `curl -s https://python-registry.wasix.org/simple/pydantic-core/` |

### Troubleshooting

| Symptom | Check | Fix |
|---------|-------|-----|
| Bare HTTP 500, no traceback, no logs | Whether any dependency ships a native extension without a WASIX wheel | Replace with a pure-Python equivalent; verify against `python-registry.wasix.org` before adding |
| Deploy fails on registry upload with HTTP 500 | Staging directory size; `wasmer --version` | Confirm the deploy staged only `git ls-files`; upgrade the `wasmer` CLI to ≥ 7.0 |
| Endpoint unreachable after a successful deploy | Bind host and port resolution | Host must be `0.0.0.0`; port must come from `PORT` or `FASTMCP_PORT` |
| `/healthz` reports `stale` with rising `consecutive_failures` | `last_error` in the response body | If rate-limited, raise `CV_REFRESH_INTERVAL`; if the release is malformed, fix and republish — the server is still serving the last good snapshot |
| `get_cv(format="pdf")` returns unavailable | Whether the latest release carries the PDF asset | Re-run the publish workflow; the error message carries the direct download URL to check |
| Published page shows an old CV | Whether the publish run's site-deploy step passed | Re-dispatch `publish.yml` with the current tag; the run fails if the live page does not answer with that tag |
