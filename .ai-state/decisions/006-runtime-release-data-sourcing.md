---
id: dec-006
draft_id: dec-draft-45aafe55
title: MCP server sources CV data from cv GitHub Release assets via CvDataProvider, with a baked fallback
status: accepted
category: architectural
date: 2026-09-13
summary: A new `data/` layer replaces the import-time local-directory load. `CvDataProvider` starts from a snapshot baked into the deploy image, then refreshes from `cv`'s latest GitHub Release on a `release.json`-gated interval, swapping an immutable `CvDataSnapshot` atomically. The server renders every format it can compute and fetches only the compiled PDF.
tags: [data-layer, state-machine, caching, availability, mcp-server]
made_by: fperezsorrosal
agent_type: systems-architect
branch: cv-repo-split
pipeline_tier: full
affected_files:
  - src/cv_mcp_server/server.py
  - src/cv_mcp_server/store.py
  - src/cv_mcp_server/resources.py
  - src/cv_mcp_server/tools/data.py
affected_reqs: [REQ-09, REQ-10, REQ-11, REQ-12, REQ-13, REQ-14]
---

## Context

The server loads its data at *module import time*, from a directory found by walking up from `__file__` until a `pyproject.toml` appears:

```python
PROJECT_ROOT = find_project_root()
DATA_DIR = Path(os.environ.get("CV_DATA_DIR") or PROJECT_ROOT / "cv-data")
CV_PATH  = PROJECT_ROOT / "FranciscoPerezSorrosal_CV_English.pdf"
store    = ResumeStore.load(DATA_DIR)          # server.py:45
```

Every one of those three lines assumes the data lives inside the same checkout as the code. After the repo split, none of them hold: `cv-data/` is in a different repository and `FranciscoPerezSorrosal_CV_English.pdf` ceases to exist anywhere (the compiled PDF becomes a release asset). The `CV_PATH` failure is already latent and silent — `resources.py:26` returns `b""` when the file is missing, so `fps-cv://pdf` degrades to an empty blob with no diagnostic.

Constraints the design has to satisfy:

- **The Edge runtime cannot compile LaTeX or Typst.** WASIX Python has no TeX distribution and no `typst` binary, so the compiled PDF cannot be produced in-process. Every other format is a pure Jinja2 function of the parsed models and *can* be.
- **Wasmer Edge instances are ephemeral and horizontally multiplied with no session affinity.** Any cache is per-instance and short-lived.
- **Unauthenticated GitHub requests are limited to 60/hour per source IP,** and a conditional `304` still decrements the counter — ETag caching saves bandwidth, not quota. Instances sharing an egress IP share the budget.
- **There is no local Edge emulator.** A failure mode that only appears in production is expensive to diagnose; the design should minimise the number of ways the server can be broken-but-running.
- The data changes a few times a year. Freshness is worth very little; availability is worth a lot.

## Decision

Introduce `cv_forge/data/` with an explicit representation and one mutable holder.

**`CvDataSnapshot`** is a frozen value carrying `resume`, `semantics`, `origin` and `loaded_at`. `origin` is a sum type — `LocalDir(path)` | `ReleaseAssets(tag, published_at)` | `BakedSnapshot(staged_at, tag)` — rather than three correlated nullable fields, so "a release with a local path" is unrepresentable. `CvDataSnapshot.parse()` is the **only** constructor that accepts raw bytes; it validates through the Pydantic models and raises before an instance exists, so a partially-parsed snapshot cannot exist either.

**`CvDataProvider`** holds exactly one snapshot and owns the refresh policy. Its constructor takes a **non-optional** initial snapshot, so there is no `Empty` or `Loading` state and no tool, resource or template ever writes `if store is None` — one representation choice deleting a null check from every one of the ~32 call sites. Its state is a sum type: `Pinned(reason)` when no fetcher is configured, `Fresh(last_success_at, tag)`, or `Stale(last_success_at, last_error, consecutive_failures)`.

**Startup** loads the snapshot baked into the deploy image (materialised into the staging directory by `scripts/deploy.sh` from the current release, so it is never hand-maintained or committed). The server is answering requests before any network call is attempted; availability never depends on GitHub.

**Refresh** runs in the ASGI lifespan as a background task on a 15-minute interval. Each cycle fetches one small asset — `release.json`, the manifest each release carries — and re-fetches the YAML only when the tag differs from the current snapshot's. Steady state is four requests per hour per instance against a sixty-per-hour ceiling.

**Failure is degradation, never outage.** A network error, a timeout, or YAML that does not validate leaves the previous snapshot in place, increments `consecutive_failures`, and moves the state to `Stale`. Because `refresh_once` parses into a *new* snapshot before rebinding a single attribute, a bad release cannot produce a half-updated server. A `GET /healthz` reports `origin`, `release_tag`, `loaded_at`, `refresh_state` and `consecutive_failures`, returning 200 only when a validated snapshot is loaded.

**`CV_DATA_DIR`, when set, pins the provider**: local directory, no fetcher, `Pinned` state, no network. The same env var already exists as the documented override; development, tests and CI keep working offline and deterministically.

**Format policy: render what we can compute, fetch only what we cannot.** Markdown, LaTeX source, HTML and Typst source are rendered in-process from the snapshot — the renderers are needed for tailoring regardless, so this keeps them exercised on every request. The compiled PDF is lazily fetched from the release, cached against the tag, and — on failure — returned as a structured `ArtifactUnavailable` naming the asset and its direct download URL, replacing today's silent empty blob.

`ResumeStore` is narrowed to a read-only query object constructed from already-parsed models; the semantics-persistence path moves to the CLI as an explicit function taking a destination path. A store whose data came from a GitHub release has no meaningful `save()`, and removing the method removes the illegal state rather than documenting it.

## Considered Options

### A. Baked fallback + interval-gated release fetch (chosen)

- **Pro**: availability is independent of GitHub; publishing a CV never touches `cv-forge`; a malformed release cannot take the server down; quota cost is 4 req/h/instance; the state machine has three states and one mutation point.
- **Con**: up to one interval of staleness, with per-instance variance across Edge instances; a background task to supervise; the baked snapshot must be materialised at deploy time rather than committed.

### B. Bake data at deploy time only; no runtime fetch

- **Pro**: the simplest possible design — no fetcher, no background task, no cache, no states. Fully deterministic. Zero GitHub quota consumption.
- **Con**: every CV publish requires a `cv-forge` redeploy, which reintroduces exactly the cross-repo coupling the split exists to remove, and makes the maintainer's publish loop two operations in two repositories instead of one tag push. It also puts a Wasmer deploy (with its documented rough edges and no emulator) on the critical path of routine content changes.

### C. Fetch per request from `raw.githubusercontent.com`

- **Pro**: always current; no staleness window; no cache invalidation to reason about.
- **Con**: every MCP call becomes a network round trip, so the server's availability becomes GitHub's availability; the 60/hour ceiling is reached after 60 tool calls per hour per egress IP, which a single conversational session can plausibly hit; and a transient GitHub failure becomes a user-visible tool error rather than invisible staleness.

### D. Fetch all formats from release assets (server as a proxy)

- **Pro**: the served HTML/Markdown/LaTeX are byte-identical to the published artifacts, removing the drift noted in the Consequences below.
- **Con**: five more artifacts to fetch and cache, the renderers stop being exercised outside the tailoring path (so a renderer regression surfaces only at publish time), and the server gains a proxy's failure modes for output it could have computed locally in microseconds.

## Consequences

**Positive**
- A CV publish reaches every MCP client within one refresh interval with no deploy.
- The server cannot be taken down by a bad release, a GitHub outage, or a network partition — only made stale, visibly.
- `if store is None` never appears in the codebase.
- `fps-cv://pdf` stops lying: an unavailable PDF says so, with a URL.
- The provider is unit-testable with no network — a `None` fetcher makes the refresh machinery inert and a fake fetcher drives the whole state machine.

**Negative**
- `fps-cv://html` can drift from the published site when `cv-forge` templates change without a republish. Accepted; the republish dispatch (REQ-04) is one command away.
- The PDF is the one surface that can be genuinely unavailable, and it is unavailable by construction between first deploy and first release.
- Per-instance staleness variance means two clients can briefly see different CV versions. Acceptable for this data.

**Neutral**
- `httpx` becomes an explicit dependency. It is already in the closure via `mcp` and is pure Python, so the WASIX cross-install is unaffected.

## Disconfirmation

**Activation**: yes — the lens sweep fired on Security (no credentials in the fetch path: all assets are public, so the server needs no GitHub token), Performance (the `release.json` gate is what keeps the quota cost at 4 req/h rather than 12), and Simplicity (option B was genuinely considered and rejected on coupling, not on capability). Testability drove the `fetcher: ReleaseFetcher | None` parameter shape.

**Falsifier.** This decision is wrong if the refresh path is observed failing in production more often than it succeeds — concretely, if `/healthz` reports `consecutive_failures > 0` for more than 5% of sampled probes over a month. That would mean the fetch is unreliable enough that the baked snapshot is doing all the work, in which case option B is the honest design and the whole fetcher is dead weight pretending to be freshness.

A second, sharper falsifier: if GitHub rate-limiting is ever observed (HTTP 403 with a rate-limit header) at the 15-minute interval, the quota arithmetic in this ADR is wrong about egress-IP sharing on Edge and the interval — or the whole approach — must change.

**Steelmanned runner-up.** Option B (bake only, no runtime fetch) is the strongest rival and would be the right answer under a different publishing cadence. It has *zero* states, zero background tasks, zero cache-invalidation reasoning, zero quota exposure, and — crucially — no failure mode that is invisible in testing and only appears in a production runtime that has no emulator. Its single cost is that publishing becomes two operations. If the maintainer's real workflow already involves running the `cv-forge` plugin's deploy skill after every publish (which the plugin makes cheap), then that cost is nearly zero and option B dominates on every other axis. The case for A rests entirely on the claim that "publish the CV" should be one tag push — a workflow assertion, not a technical one.

**Reversal trigger.** Collapse to option B if either falsifier fires, or if the refresh loop is ever the cause of a production incident. The collapse is cheap by construction: delete the fetcher, pass `None`, and the provider degrades to `Pinned` with no other code change — the `fetcher: ReleaseFetcher | None` signature is the reversal seam, deliberately.
