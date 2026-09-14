# Architecture

<!-- Design-target architecture document. Abstracts above concrete code to define the space of valid
     implementations. Component names may be abstract; file paths are illustrative; planned components
     are included with Status markers. For code-verified developer navigation, see docs/architecture.md.
     Maintained by pipeline agents via section ownership.
     Created by systems-architect, updated by implementer, validated by verifier/sentinel. -->

## 1. Overview

| Attribute | Value |
|-----------|-------|
| **System** | cv-forge (machinery) + cv (data) |
| **Type** | MCP server + document renderer + CLI + two Claude Code plugins, across two repositories |
| **Language / Framework** | Python 3.13 / `mcp` 2.x (`MCPServer`), Jinja2, Pydantic v2 |
| **Architecture pattern** | Layered package with a pure core (`models`, `render`) and a single impure edge (`data`), driven by two adapters (`mcp`, `cli`); repository-level split along the data/machinery seam |
| **Source stage** | Phase 5 creation / Pipeline `cv-repo-split` |
| **Current as of** | `dec-draft-21e53cfb` (asserted 2026-09-13) — draft-stage mark. The decision corpus contains no finalized `dec-NNN` records yet; all eight fragments authored by this pipeline are folded into §1–§3 above. Re-assert to the highest finalized id once `scripts/finalize_adrs.py` runs at merge-to-main. |
| **Last verified** | 2026-09-13 by systems-architect |

The system turns one structured YAML description of a CV into every form a consumer might want it in — an MCP tool surface for agents, five rendered document formats for humans, and a public web page — while keeping the CV *content* in a repository that contains nothing else. The content lives in `cv`; everything that reads, renders, serves or publishes it lives in `cv-forge`. The two are joined by exactly two pinned artifacts (a reusable GitHub workflow reference and a mirrored JSON Schema pair) and one runtime data path (GitHub Release assets), with no credential crossing the boundary in either direction.

Inside `cv-forge` the governing rule is a one-line layering claim: **`models` and `render` know nothing about paths or the network; `data` owns both; `mcp` and `cli` are the two drivers.** That rule is what makes the renderer usable identically from a laptop and from CI, and what makes the MCP server's data source swappable between a local directory and a GitHub release without any other module noticing.

## 2. System Context

![System Context (L0) — maintainer and CV consumer outside the boundary; the cv data repo calling cv-forge's publish workflow and pulling mirrored schemas; cv GitHub Releases holding the eight published assets; Wasmer Edge hosting the MCP app and the static CV site and fetching from Releases at runtime; the bit-agora marketplace sourcing both plugins from cv-forge at ref v1](diagrams/architecture/rendered/context.svg)

<details>
<summary>Diagram source: <code>diagrams/architecture/src/architecture.c4</code></summary>

The LikeC4 model backs both the context (L0) and components (L1) views. Regenerate with the repo's pre-commit `diagram-regen` hook, or manually:

```
likec4 gen d2 .ai-state/diagrams/architecture/src -o .ai-state/diagrams/architecture/rendered/
d2 .ai-state/diagrams/architecture/rendered/context.d2    .ai-state/diagrams/architecture/rendered/context.svg
d2 .ai-state/diagrams/architecture/rendered/components.d2 .ai-state/diagrams/architecture/rendered/components.svg
```

</details>

> **Component detail:** [Components](#3-components) · **Deployment view:** [`SYSTEM_DEPLOYMENT.md`](SYSTEM_DEPLOYMENT.md)

## 3. Components

![Components (L1) — inside cv-forge: models and render as the pure core, data as the only layer touching paths or the network, mcp and cli as the two drivers, schemas generated from models, publish.yml invoking the cli and uploading release assets, and the two plugins attaching to the mcp surface and the cli respectively](diagrams/architecture/rendered/components.svg)

<!-- aac:generated source=.ai-state/diagrams/architecture/src/architecture.c4 view=components last-regen=2026-09-13 -->

### 3a. Structural components

| Component | Responsibility | Status | Key Files |
|-----------|---------------|--------|-----------|
| models | Pydantic definitions of `Resume`, `SemanticOverlay` and `TailoringSpec` — the shape of the data and the source of the exported JSON Schemas. No I/O, no paths, no network. | Built | target `src/cv_forge/models/`; today `src/cv_mcp_server/models/{resume,semantics,tailoring}.py` |
| render | Jinja2 renderers and templates producing markdown, LaTeX (moderncv), HTML and Typst (moderner-cv), full and tailored. Pure functions of a store. | Built | target `src/cv_forge/render/`; today `src/cv_mcp_server/renderers.py`, `src/cv_mcp_server/templates/` |
| data-store | `ResumeStore` — read-only query layer over a parsed `Resume` and `SemanticOverlay`: entry index, cross-reference validation, the query methods every tool reads through. Narrowed by this work: its loading and semantics-persistence responsibilities move out (to data-source and cli respectively). | Built | target `src/cv_forge/data/store.py`; today `src/cv_mcp_server/store.py` |
| data-source | `CvDataSnapshot` (immutable, parsed at the boundary), `CvDataProvider` (the one mutable holder, owns refresh and state), `ReleaseFetcher`/`ArtifactCache` (GitHub release access), `load_local_dir`. The only code that knows about filesystem paths or sockets. See `dec-draft-45aafe55`. | Designed | `src/cv_forge/data/{snapshot,provider,release,local}.py` |
| mcp | `MCPServer` construction, ASGI app factory and lifespan, 17 `fps-cv://` resources, 16 tools, and the `/healthz` surface. Reads the current snapshot per call; never holds it across an await. | Built | target `src/cv_forge/mcp/`; today `src/cv_mcp_server/{server,resources}.py`, `src/cv_mcp_server/tools/` (`app.py` and `/healthz` are new) |
| cli | The `cv-forge` console script: `render`, `validate`, `export-schemas`, `fetch-snapshot`. The single render path shared by the maintainer, CI and the maintainer plugin. | Built | target `src/cv_forge/cli/main.py`; today `scripts/render_cv.py`, a path-relative script outside the package (`validate`, `export-schemas` and `fetch-snapshot` are new; `--snapshot`/`--symlink` are retired) |
| schemas | Generated JSON Schema pair exported from the models, committed and drift-checked in CI. Source of truth for the copy mirrored into `cv`. See `dec-draft-2fbed258`. | Designed | `schemas/{resume,semantics}.schema.json` |
| publish-workflow | Reusable `workflow_call` pipeline owned by `cv-forge` and invoked by `cv`: render every format, compile the PDF, build `release.json`, upload eight assets, deploy the static site, verify it answered. | Designed | `.github/workflows/publish.yml` |
| plugin-cv | Consumer-facing Claude Code plugin: native `{"type":"http"}` MCP declaration plus the `cv-analyst` and `cv-tailoring` skills. See `dec-draft-138f038b`. | Built | target `plugins/cv/`; today `.claude-plugin/plugin.json`, `skills/cv-analyst/`, `skills/cv-tailoring/` |
| plugin-cv-forge | Maintainer-facing Claude Code plugin: `cv-data-edit` (edit → validate → preview → PR), `cv-publish` and `cv-forge-deploy` (both user-invocable only). No stored credentials — uses the operator's own `gh` session. | Designed | `plugins/cv-forge/` |

### 3b. Capabilities

| Capability | Responsibility | Status | Key Files |
|-----------|---------------|--------|-----------|
| Job-targeted tailoring | Reorder sections, filter entries and override the profile for a specific job description, rendering to LaTeX or Typst for compilation. | Built | `models/tailoring.py`, `render/renderers.py`, `mcp/tools/data.py` |
| Semantic enrichment | Topic taxonomy, cross-entry relationships and skill proficiency layered over the structured resume, surfaced through query tools and enriched markdown/HTML/Typst renders. | Built | `models/semantics.py`, `data/store.py`, `mcp/tools/semantic.py` |
| Release-sourced data serving | Serve CV content that follows `cv`'s latest release without redeploying: baked snapshot at startup, `release.json`-gated refresh, atomic swap, degradation to stale rather than failure. | Designed | `data/`, `mcp/app.py` |
| One-render-path publishing | The maintainer's local preview and the CI publish run are the same code path over the same data, so local output is evidence about published output. | Designed | `cli/main.py`, `.github/workflows/publish.yml` |
| Cross-repo contract | Two pinned artifacts (`publish.yml@v1`, mirrored schemas) and one runtime data path, with no credential crossing the boundary. | Designed | `.github/workflows/publish.yml`, `schemas/` |

<!-- aac:end -->

## 4. Interfaces

| Interface | Type | Provider | Consumer(s) | Contract |
|-----------|------|----------|-------------|----------|
| `publish.yml` | GitHub reusable workflow | publish-workflow | `cv` repo | `workflow_call`; inputs `ref`, `data-path`, `formats`, `deploy-site`, `site-app`, `draft`; secret `WASMER_TOKEN`; caller supplies `permissions: contents: write` and its own `GITHUB_TOKEN` |
| Release assets | HTTPS redirect | `cv` GitHub Releases | data, browsers, plugin skills | Eight stable version-free names under `releases/latest/download/`; `release.json` schema v1, additive-only |
| `schemas/*.schema.json` | JSON Schema 2020-12 | schemas | `cv` CI, editors, plugin skills | Generated from the models; mirrored copy in `cv` drift-checked against the pinned `v1` ref |
| `fps-cv://*` | MCP resources | mcp | MCP clients | 17 URIs across rendered output, structured JSON, schemas, template catalog and links |
| MCP tools | MCP tools | mcp | MCP clients | 16 tools (data, query, semantic, tailoring, summarize); `get_cv(format="pdf")` may return a structured unavailable outcome |
| `GET /healthz` | HTTP | mcp | Wasmer, deploy verification, maintainer | 200 only with a validated snapshot loaded; body carries `origin`, `release_tag`, `loaded_at`, `refresh_state`, `consecutive_failures`; 503 otherwise |
| `cv-forge` CLI | Console script | cli | maintainer, CI, plugin skills | `render -f <fmt> [-o dir]`, `validate <dir>`, `export-schemas`, `fetch-snapshot` |
| MCP endpoint declaration | JSON | plugin-cv | Claude Code | `{"type":"http","url":"https://fps-cv-mcp.wasmer.app/mcp"}` — `type` is required; an entry with a `url` and no `type` is read as stdio |

## 5. Data Flow

### Serving the current CV

![MCP server data flow — the lifespan loads the baked snapshot and starts accepting requests before any network call, then a 15-minute refresh loop fetches release.json and re-fetches YAML only when the tag changed; markdown is rendered in-process from the snapshot while the PDF is lazily fetched from the release and cached by tag](diagrams/data-refresh-flow/rendered/data-refresh-flow.svg)

The load-bearing property is that the server is answering before the first fetch is attempted. `CvDataProvider`'s constructor takes a non-optional snapshot, so no `Empty` or `Loading` state exists and availability never depends on GitHub. A refresh parses into a new immutable snapshot before rebinding a single attribute, so a malformed release degrades freshness rather than availability.

### Publishing a new CV

![Publish flow — a CalVer tag push on cv invokes cv-forge's reusable publish workflow, which checks out both repos, renders every format, compiles the PDF, builds release.json, uploads eight assets to the release, deploys the HTML to the Wasmer static site, and fails unless the live site answers with the tag](diagrams/publish-flow/rendered/publish-flow.svg)

## 6. Dependencies

| Dependency | Version | Purpose | Criticality |
|-----------|---------|---------|-------------|
| `mcp` (official SDK) | `>=2.2,<3` | MCP server, transports, type model | Critical |
| `pydantic` | `>=2.12,<2.13.5` | Data model and validation. Upper bound is the WASIX `pydantic-core` ceiling (`2.46.4`), not a compatibility concern — see `dec-draft-21e53cfb` | Critical |
| `jinja2` | `>=3.1,<4` | All rendering paths | Critical |
| `pyyaml` | `>=6.0,<7.0` | Parsing the CV data files | Critical |
| `httpx` | `>=0.28,<0.29` | Release fetching; already in the closure via `mcp` | Critical (degrades to baked snapshot on failure) |
| `loguru` | `>=0.7.3,<0.8` | Logging | Non-critical |
| `starlette` / `uvicorn` | via `mcp` | ASGI app and server | Critical |
| `check-jsonschema` | `0.38.0` | `cv` repo CI validation (not a `cv-forge` runtime dependency) | Non-critical |
| TinyTeX + `moderncv` | CI-installed | PDF compilation in the publish workflow | Critical to publishing, absent at runtime |
| `typst` CLI | CI-installed | Typst compilation (source-only in v1) | Non-critical |
| `anybuild` + `wasmer` CLI | `0.28.x` / `>=7` | Edge build and deploy | Critical to deployment |

## 7. Constraints

| Constraint | Type | Rationale |
|-----------|------|-----------|
| `pydantic < 2.13.5` | Compatibility | The WASIX package index caps `pydantic-core` at `2.46.4+wasix.2`; raising the pin breaks the Edge cross-install. The ceiling binds today — PyPI's current `pydantic` is `2.13.5`. |
| No LaTeX or Typst compiler in the deployed runtime | Technical | WASIX Python has no TeX distribution. The compiled PDF must be produced in CI and fetched, which is why the server renders every format it can compute and fetches only the PDF. |
| Unauthenticated GitHub requests: 60/hour per source IP, and a `304` still decrements | Performance | Drives the `release.json`-gated refresh (4 req/h/instance) rather than per-request fetching or pure ETag caching. |
| Edge instances are ephemeral and horizontally multiplied with no session affinity | Technical | The transport must be stateless (which the 2026-07-28 spec revision makes the default) and any cache is per-instance. |
| No local Wasmer Edge emulator exists | Technical | Deployment verification is a live poke against a real deploy, not a pre-deploy gate. The previous deployment stays live through cutover. |
| `anybuild` ignores `.gitignore` and requires `wasmer` CLI `>= 7` | Technical | Deploys must stage `git ls-files` output into a temp directory and assert the CLI version; running `anybuild` from the repo root ships untracked files and can fail the upload with a bare HTTP 500. |
| No credential crosses the repository boundary | Security | Both repositories pull; neither pushes. Eliminates a long-lived cross-repo PAT and its rotation burden. See `dec-draft-2fbed258`. |
| No rendered artifact is committed to either repository | Technical | Published artifacts live only as GitHub Release assets, so there is exactly one place to look for "the current CV". |
| Unit tests must pass with no `cv` checkout present | Quality | The machinery repo's suite cannot depend on a second repository; real-data tests are gated behind `CV_DATA_DIR` and the `integration` marker. |

## 8. Decisions

<!-- aac:authored owner=systems-architect last-reviewed=2026-09-13 -->

Architectural decisions are recorded as ADRs in [`.ai-state/decisions/`](decisions/). The canonical, auto-generated cross-reference is `DECISIONS_INDEX.md`, regenerated at finalize. In-flight pipeline ADRs live as fragments under [`decisions/drafts/`](decisions/drafts/) and are promoted to stable `dec-NNN` at merge-to-main by `scripts/finalize_adrs.py`.

Eight fragments were authored by the `cv-repo-split` pipeline: the repo-split boundary (`dec-draft-893c5497`), the `cv_forge` package layout (`dec-draft-8cc49ae3`), runtime release-sourced data (`dec-draft-45aafe55`), the cross-repo publish topology (`dec-draft-2fbed258`), dropping MCPB and the registry entry (`dec-draft-fb7c5d3f`), the two-plugin decomposition (`dec-draft-138f038b`), Wasmer Edge deployment (`dec-draft-16b56698`), and the `mcp` 2.x SDK migration (`dec-draft-21e53cfb`).

<!-- aac:end -->
