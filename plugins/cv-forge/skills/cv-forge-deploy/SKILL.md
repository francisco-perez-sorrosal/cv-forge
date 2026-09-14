---
name: cv-forge-deploy
description: >
  Deploys the cv-forge MCP server to Wasmer Edge and live-pokes /healthz and
  POST /mcp tools/list to prove the deploy landed. Use only when the
  maintainer explicitly invokes /cv-forge-deploy -- never on conversational
  phrases like "deploy the server" or "push the update", since this pushes a
  real workload to a production endpoint. Optional [app-name] argument
  selects the target Wasmer app (defaults to fps-cv-mcp).
argument-hint: "[app-name]"
allowed-tools: "Read, Bash(git status:*), Bash(git ls-files:*), Bash(wasmer:*), Bash(anybuild:*), Bash(curl:*)"
disable-model-invocation: true
---

# CV Forge Deploy

Stage and deploy the `cv-forge` MCP server, then prove it is live. A code
deploy never moves `release_tag` (only a new `cv` publish does that), so
`cv_forge_version` in the health body is the one field that distinguishes
"this deploy landed" from "the old instance is still serving".

## Locating the clone

`${user_config.cv_forge_path}` must be set and point at a `cv-forge` clone
(contains `scripts/deploy.sh` and `pyproject.toml`). **No degraded path** --
unlike `cv-data-edit`'s schema-only fallback, there is nothing this skill
can do without the real tree. If unset, stop with:

```
cv_forge_path is not set.
cv-forge-deploy needs a local clone of github.com/francisco-perez-sorrosal/cv-forge
to stage and deploy from. Set cv_forge_path in the plugin's configuration
(e.g. /Users/fperez/dev/cv-forge), or clone it: gh repo clone francisco-perez-sorrosal/cv-forge
```

(Same shape as `cv-data-edit`'s error ④, adapted to the field this skill
needs.)

## Workflow

1. **Preflight** -- in `cv_forge_path`: `git status` (clean working tree),
   `wasmer --version` (>= 7.0), `anybuild --version` (present on `PATH`).
   `scripts/deploy.sh <app-name> [--dry-run]` (M1.20's contract) re-checks
   the same conditions and exits non-zero with a named reason if any fail --
   this preflight is a maintainer-facing preview of that gate, not a
   substitute for it.
2. **Stage and deploy** -- `scripts/deploy.sh <app-name>` (`<app-name>`
   defaults to `fps-cv-mcp` when the `[app-name]` argument is absent). The
   script stages `git ls-files` output, never the raw working tree --
   `anybuild` does not honour `.gitignore`, so shipping the tree directly
   leaks build artifacts and can fail the upload outright (`FEEDBACK.md`
   F-004's sibling gotcha) -- then runs `anybuild` / `wasmer deploy`.
3. **Live check** -- exact `curl` invocations and expected shapes:
   [references/live-poke.md](references/live-poke.md). `GET /healthz`
   must report `status: "ok"` with `cv_forge_version` matching the tree
   just deployed; `POST /mcp` `tools/list` (no session header, per the
   stateless streamable-HTTP contract) must return the full tool count.
4. **Report** -- the display shape below.

Display shape (adapt values, keep the structure):

```
▸ cv-forge-deploy fps-cv-mcp
  Preflight · cv-forge @ /Users/fperez/dev/cv-forge
    ✓ working tree clean        ✓ wasmer 7.2.1  (>= 7.0 required)
  Stage    git ls-files → 312 files  +  fetch-snapshot --out .stage/cv-data  (tag 2026.09.13)
  Deploy   anybuild → wasmer deploy                                   1m47s  ✓
  Live check · https://fps-cv-mcp.wasmer.app
    GET  /healthz   200 · origin=release · tag=2026.09.13 · state=fresh · failures=0
                        cv_forge_version 1.1.0  ← matches the tree just deployed
    POST /mcp       tools/list → 16 · resources/list → 17
  Deployed.
```

## Failure reporting

If preflight fails, `scripts/deploy.sh` exits non-zero, or the live check
does not match (wrong `cv_forge_version`, non-200, tool/resource count
mismatch): name the failing step and its exact output, then stop. No
retry loop, no fallback deploy path -- REQ-20's "no degraded path" applies
to execution, not only to clone-location resolution.

## Wasmer feedback

This whole skill is a Wasmer surface end to end. Append one sentence per
friction item -- a confusing `anybuild` error, a slow `wasmer deploy`, a
health-check quirk -- to the repo-root `FEEDBACK.md`, following its `Entry
shape`. This is a standing user directive, not optional.
