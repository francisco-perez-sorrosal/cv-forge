---
id: dec-draft-21e53cfb
title: Migrate to the official mcp SDK 2.2.0 and pin pydantic below the WASIX ceiling
status: proposed
category: implementation
date: 2026-09-13
summary: Move from `mcp[cli]>=1.9.2,<2` to the official `mcp>=2.2,<3` (`FastMCP` → `MCPServer`), keeping the official SDK rather than switching to jlowin's independent `fastmcp` 3.x, and declare `pydantic>=2.12,<2.13.5` and `httpx` as explicit direct dependencies.
tags: [dependencies, mcp-sdk, api-version-drift, pydantic, wasix]
made_by: fperezsorrosal
agent_type: systems-architect
branch: cv-repo-split
pipeline_tier: full
affected_files:
  - pyproject.toml
  - src/cv_mcp_server/server.py
  - src/cv_mcp_server/main.py
  - src/cv_mcp_server/resources.py
  - src/cv_mcp_server/tools/data.py
affected_reqs: [REQ-09, REQ-13, REQ-16]
---

## Context

The project pins `mcp[cli]>=1.9.2,<2` and resolves to `1.15.0`. PyPI's current release is **2.2.0** — two major versions ahead — and the 1.x line is in security-fix-only maintenance. This is an `[API VERSION DRIFT]` of **Critical** priority: `mcp` is the core dependency through which the server's entire surface flows.

It is also not optional here. `anybuild`'s Python/MCP provider assumes the 2.x server shape (`python_framework = "mcp"`, `python_mcp_self_running`), and the MCP spec revision the SDK speaks (2026-07-28) is the one that removed the `initialize` handshake and `Mcp-Session-Id` — the statelessness that makes the Edge deployment sound. Migrating is a prerequisite of the deployment decision, not a discretionary cleanup.

Breaking changes that touch this codebase:

- `FastMCP` is renamed `MCPServer` (`from mcp.server.mcpserver import MCPServer`); the 1.x import path raises `ModuleNotFoundError`.
- `host`, `port`, `stateless_http`, `sse_path` and `json_response` move off the constructor onto `run()` / the app-factory methods. `server.py:50-52` constructs `FastMCP(..., stateless_http=..., host=..., port=...)`, which is exactly the removed shape.
- Resource URIs change from `AnyUrl` to plain `str`.
- `mcp.types` splits into a standalone `mcp-types` package (aliased for back-compat). `tools/data.py` imports `BlobResourceContents` and `EmbeddedResource` from it.
- `get_context()` is removed in favour of typed `Context` parameter injection. Not used here.
- Roots, Sampling and classic Logging are deprecated (SEP-2577). None used here — zero migration cost.
- `MCP_*` env-var/`.env` auto-reading is removed. This project reads its own env vars, so no impact.

Two dependency-declaration defects surface at the same time. `pydantic` is used directly and extensively across `models/*.py` (`BaseModel`, `Field`, `ConfigDict`) and in `resources.py`, but is not declared — it arrives transitively through `mcp[cli]`. And `httpx`, about to become load-bearing for the release fetcher, is in the same undeclared-transitive position.

The WASIX index caps `pydantic-core` at `2.46.4+wasix.2`, which caps `pydantic` at `<2.13.5`. PyPI's current `pydantic` is exactly `2.13.5` (verified 2026-09-13), so the ceiling binds *today*: the latest release is not installable on the target platform.

## Decision

Move to `mcp>=2.2,<3` (the official SDK, dropping the `[cli]` extra — `anybuild` silently strips PEP 508 extras when generating `cross-requirements.txt`, so depending on one is a trap).

Declare both currently-transitive-but-directly-used dependencies:

```toml
dependencies = [
  "mcp>=2.2,<3",
  # Upper bound is the WASIX pydantic-core ceiling (2.46.4+wasix.2), not a
  # compatibility concern. Raising it breaks the Wasmer Edge cross-install.
  "pydantic>=2.12,<2.13.5",
  "httpx>=0.28,<0.29",
  "jinja2>=3.1,<4",
  "pyyaml>=6.0,<7.0",
  "loguru>=0.7.3,<0.8",
]
```

Keep the **official** SDK rather than switching to jlowin's independent `fastmcp` 3.x. The two are separate projects sharing a name-history; `fastmcp` 3.x offers an OpenAPI provider, hot-reload file-system providers and middleware transforms — a richer surface whose advantages lie entirely in areas this server does not touch (17 resources and 16 tools, all synchronous reads over an in-memory model, no OpenAPI generation, no middleware). The WASIX/anybuild Python provider explicitly names `mcp`; no first-party evidence exists of `fastmcp` working under anybuild.

Add a `ci.yml` step that queries `python-registry.wasix.org` for the maximum published `pydantic-core` and fails when the `pydantic` pin could be relaxed or must tighten — converting a future silent build break into a scheduled signal.

Two 2.2.0 API details were **not** verified by research and must be checked against the live reference before implementation: whether the decorator API exposes `readOnlyHint` and the spec's `ttlMs`/`cacheScope` `CacheableResult` fields, and whether `AnyUrl` is still accepted for `BlobResourceContents.uri` (`tools/data.py:62`). Both are enhancements; the migration succeeds without either.

## Considered Options

### A. Official `mcp` 2.2.0 (chosen)

- **Pro**: required by the deployment path; speaks the current spec revision while still serving 2025-era clients from the same server; leaves 1.x's security-only maintenance status behind; the decorator API this codebase uses survives the migration.
- **Con**: a real breaking migration touching `server.py`, `main.py`, and the type imports in `tools/data.py`; two API details unverified.

### B. Stay on `mcp` 1.x

- **Pro**: no migration work at all.
- **Con**: blocks the Wasmer deployment (anybuild assumes the 2.x shape), leaves the server on a security-fix-only line, and misses the statelessness that makes horizontal Edge scaling sound. Every month of delay makes the migration larger.

### C. Switch to jlowin's `fastmcp` 3.4.5

- **Pro**: richer component/provider/transform architecture; active independent development under PrefectHQ.
- **Con**: the feature differential concentrates in capabilities this server does not use; no evidence of anybuild/WASIX compatibility; it would be a second migration on top of the first, for a benefit this codebase cannot currently name.

## Consequences

**Positive**
- The server speaks the current spec revision and remains backward compatible with 2025-era clients.
- `pydantic` and `httpx` stop being accidental transitive dependencies that could vanish on an upstream change.
- The `pydantic` upper bound is documented at the pin site with its actual reason, so a future reader does not "helpfully" relax it.
- Dropping `[cli]` removes an extras declaration that anybuild would silently discard.

**Negative**
- `pydantic` is pinned below its current release, so a security fix landing above `2.13.5` before the WASIX index catches up would force a choice between the fix and the platform. Tracked as a risk against the deployment decision.
- The migration must land before the data-layer rewrite (both touch `server.py`), constraining step ordering.

**Neutral**
- The `[cli]` extra provided a development convenience (`mcp dev`) not used by any task in `pyproject.toml`.

## Disconfirmation

Not required for `category: implementation`. Recorded anyway, because the pin is load-bearing for the deployment:

**Reversal trigger.** If a `pydantic` CVE lands above `2.13.5` and the WASIX index has not published a matching `pydantic-core` within two weeks, the deployment decision (`dec-draft-16b56698`) reverses to render.com rather than this pin being relaxed — the pin is a consequence of the platform, and the platform is the reversible half.
