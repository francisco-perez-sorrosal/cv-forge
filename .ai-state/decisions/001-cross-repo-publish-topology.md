---
id: dec-001
draft_id: dec-draft-2fbed258
title: Publish via a cv-forge-owned reusable workflow called from cv, with a pull-only schema mirror
status: accepted
category: architectural
date: 2026-09-13
summary: A tag push on `cv` calls `cv-forge`'s reusable `publish.yml@v1`, which renders every format, attaches eight stable-named assets to a GitHub Release on `cv`, and deploys the HTML to a Wasmer static site. JSON Schemas are generated in `cv-forge` and mirrored into `cv`, synced by pull and drift-checked in CI. Neither repository ever pushes into the other.
tags: [ci-cd, cross-repo, release, schema, github-actions, contract]
made_by: fperezsorrosal
agent_type: systems-architect
branch: cv-repo-split
pipeline_tier: full
affected_files:
  - .github/workflows/
  - schemas/
  - src/cv_mcp_server/models/
affected_reqs: [REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-08]
---

## Context

Splitting the repositories (`dec-005`) creates two problems that must be solved together, because the obvious solution to each is a credential.

**Rendering lives in the wrong repo for the trigger.** The natural trigger for "publish a new CV" is a tag on `cv`, where the data lives. But every tool needed to render it — `pixi`, the Jinja2 templates, TinyTeX, `typst` — lives in `cv-forge`. Either `cv` grows a full Python toolchain (undoing the split), or it reaches into `cv-forge`.

**Schema validation needs the models, which are code.** `cv`'s CI should reject malformed YAML, but the shape is defined by Pydantic models in `cv-forge`. Installing the Python package in `cv`'s CI would make the data repo depend on a machinery release.

The lazy answer to both is a Personal Access Token: `cv-forge` pushes schema-sync PRs into `cv`, or fires a `repository_dispatch`. That introduces a long-lived credential with write access to a public repository, stored in a second repository, with no rotation story — for a project whose entire published surface is a CV.

Two further facts constrain the design. GitHub's `releases/latest/download/<name>` redirect resolves through the web tier rather than the REST API, so a stable *filename* gives a stable URL for free, with no API call and no rate-limit exposure. And the compiled PDF is the one artifact nothing downstream can regenerate (the Edge runtime has no TeX), so it must be produced exactly once, in CI, and stored.

## Decision

**Publishing: `cv` calls, `cv-forge` executes.** `cv-forge` owns `.github/workflows/publish.yml` as a `workflow_call` reusable workflow. `cv`'s own `publish.yml` is roughly fifteen lines and contains exactly one line of coupling:

```yaml
uses: francisco-perez-sorrosal/cv-forge/.github/workflows/publish.yml@v1
```

`v1` is a moving major tag in `cv-forge`, re-pointed by `scripts/release.sh` on each `v1.x.y` release. Breaking input changes require `v2` and a one-line edit in `cv`. Inputs: `ref`, `data-path`, `formats`, `deploy-site`, `site-app`, `draft`. Secret: `WASMER_TOKEN`. The caller supplies `permissions: contents: write`, so the release is created with the caller's own `GITHUB_TOKEN` — no token crosses the boundary.

**Versioning: CalVer for data, SemVer for machinery.** `cv` tags are `YYYY.MM.DD` (`.N` for same-day re-releases), with no `v` prefix, because a CV release is a date, not a feature version. `cv-forge` tags are `vMAJOR.MINOR.PATCH` plus the moving `v1`.

**Assets: eight stable, version-free names** — `resume.yaml`, `resume-semantics.yaml`, `FranciscoPerezSorrosal_CV.{pdf,tex,typ,md,html}`, and `release.json`. The `latest` alias is GitHub's own "latest release" pointer, not a separate tag. `release.json` is the contract's version token: `{schema_version, tag, published_at, cv_forge_version, assets{name: {size, sha256}}}`, additive-only, consumed by the MCP server's refresh gate.

**Re-render without a data change** is `workflow_dispatch` on `cv`'s `publish.yml` with a `tag` input defaulting to the current latest release. It re-runs the same reusable workflow with the *current* pinned machinery and uploads with `--clobber` onto the existing release. The tag, the release and the `latest` pointer are unchanged. A template improvement therefore reaches published artifacts without inventing a fake data version.

**Schemas: generated in `cv-forge`, mirrored into `cv`, synced by pull.** `cv-forge export-schemas` writes `schemas/{resume,semantics}.schema.json` from `Resume.model_json_schema()` / `SemanticOverlay.model_json_schema()`; `ci.yml` regenerates and diffs them, failing on drift, so the committed schema can never diverge from the models. `cv` carries byte-copies under `schemas/`, validated against with `check-jsonschema` (a standalone CLI, no project install). `cv`'s `validate.yml` additionally fetches the upstream pair anonymously from `raw.githubusercontent.com/.../cv-forge/v1/schemas/` and fails on any difference, so a stale mirror is a red check rather than silent wrongness. Syncing is maintainer-initiated: the plugin skill, or a `workflow_dispatch` job in `cv` that curls the upstream files and opens a PR with `cv`'s own token.

**Consequently, no cross-repo credential exists.** `cv` pulls a workflow and pulls schemas; `cv-forge` pulls data from public release assets. The only secrets are a `WASMER_TOKEN` in each repository for its own deploy target.

## Considered Options

### A. `cv` calls a `cv-forge`-owned reusable workflow; both repos pull (chosen)

- **Pro**: the trigger lives where the data lives and the tooling lives where the tooling lives; the sync surface is two pinned strings; zero cross-repo credentials, therefore zero rotation burden and no blast radius from a leak; the `@v1` pin means `cv`'s publishing behaviour only changes when someone deliberately moves the tag.
- **Con**: schema sync is manual; a `cv` PR can be blocked by a drift the maintainer has not yet synced; the reusable-workflow contract is a real interface that can break.

### B. `cv-forge` pushes: schema-sync PRs and/or `repository_dispatch`, driven by a PAT

- **Pro**: fully automatic — a schema change propagates without human action, and a `cv-forge` release could re-publish the CV artifacts on its own.
- **Con**: a long-lived write-scoped PAT stored in a second repository, for a benefit measured in "the maintainer runs one command a few times a year." The automation buys convenience proportional to schema-change frequency, which for a stable CV model is close to zero.

### C. `cv` vendors the renderer (installs the Python package in its own CI)

- **Pro**: no reusable-workflow contract at all; `cv` is self-sufficient.
- **Con**: the data repo acquires a `pyproject.toml`, a lockfile, a `pixi` environment, TinyTeX and `typst` — i.e. it becomes the monorepo the split rejected, with the added indignity of a version-pin to a package it does not own.

### D. Publishing runs entirely in `cv-forge`, triggered by polling or a schedule

- **Pro**: one repository owns the whole pipeline; no `workflow_call` contract.
- **Con**: releases must be created on `cv` (that is where consumers look for them), which needs a write credential — so this collapses into option B — or they move to `cv-forge`, which decouples the release from the data version that produced it.

## Consequences

**Positive**
- One tag push publishes the CV to GitHub Releases and the live site, with the run failing if the site does not actually answer.
- `cv`'s CI is a `check-jsonschema` invocation and two `curl`s — readable in full on one screen.
- The stable asset names mean every consumer URL is written once and never regenerated.
- `--clobber` republish makes renderer improvements deployable without polluting the data's version history.

**Negative**
- Schema drift is caught rather than prevented; a `cv` PR can be blocked until the maintainer syncs. Deliberate: a loud block beats validating against a schema the tooling no longer speaks.
- The moving `v1` tag means a `cv-forge` release can change `cv`'s publishing behaviour without a commit in `cv`. Mitigated by SemVer discipline: input-breaking changes get `v2`.
- Two `WASMER_TOKEN` secrets exist (one per repo), which is two rotations rather than one.

**Neutral**
- `cv` has no lockfile, so its CI is not reproducible in the strict sense — it pins `check-jsonschema` by version in the workflow instead.

## Disconfirmation

**Activation**: yes — the Security lens fired and drove the decisive constraint (no long-lived cross-repo credential), which is what eliminated option B despite its convenience advantage. The Simplicity lens ratified the pull-only shape: two pinned strings is the smallest contract that satisfies both problems.

**Falsifier.** This decision is wrong if the schema mirror goes stale often enough to be a recurring nuisance — concretely, if more than one `cv` PR per quarter is blocked by REQ-02's drift check. That frequency would mean the models are changing fast enough that automation earns its credential, and option B becomes correct.

A second falsifier: if the `@v1` moving tag ever breaks a `cv` publish without a deliberate `cv-forge` release, the pin is too loose and should become an immutable `vX.Y.Z` (at the cost of a `cv` commit per machinery release).

**Steelmanned runner-up.** Option B is stronger than the "credentials are bad" framing suggests. A fine-grained PAT scoped to a single public repository with `contents:write` and `pull_requests:write` is a well-understood, widely-used GitHub pattern; the blast radius of a leak on a repository whose entire content is a *published CV* is close to nil, and GitHub's fine-grained tokens support expiry. In exchange, schema drift becomes structurally impossible rather than merely detectable, and the maintainer never has to remember a sync step. The honest case for A over B is that the automation solves a problem that occurs a handful of times per year, and every stored credential is a thing that must be remembered, rotated, and reasoned about forever — an asymmetry of ongoing cost against episodic convenience.

**Reversal trigger.** Introduce a fine-grained PAT and automate the schema sync (option B, partially) if the drift check blocks more than one `cv` PR per quarter for two consecutive quarters. Note that the reversal is additive and non-breaking: the pull-based drift check stays useful as a verification step even once a push-based sync exists.
