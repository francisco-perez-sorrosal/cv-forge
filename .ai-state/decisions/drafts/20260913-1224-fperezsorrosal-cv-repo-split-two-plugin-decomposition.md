---
id: dec-draft-138f038b
title: Two Claude Code plugins under cv-forge/plugins — cv (consumer) and cv-forge (maintainer) — built from skills only
status: proposed
category: architectural
date: 2026-09-13
summary: >-
  The consumer plugin at `plugins/cv` ships a native `type: http` MCP declaration plus the two existing
  analysis skills; the maintainer plugin at `plugins/cv-forge` ships edit-validate-preview-PR,
  publish-and-verify and deploy-and-verify. Both live in the `cv-forge` repo and both are listed in the
  `bit-agora` marketplace. No agents, no hooks, no stored credentials, and `version` lives in exactly one place.
  The maintainer plugin takes two directory `userConfig` entries — `cv_repo_path` and the optional `cv_forge_path`.
tags: [claude-code, plugin, skills, marketplace, decomposition]
made_by: fperezsorrosal
agent_type: systems-architect
branch: cv-repo-split
pipeline_tier: full
affected_files:
  - .claude-plugin/plugin.json
  - .claude-plugin/mcp-local.json
  - skills/
  - config/cv_mcp.json
  - install.sh
affected_reqs: [REQ-17, REQ-18, REQ-19, REQ-20]
---

## Context

There is one plugin today: `cv`, declaring `mcpServers.fps_cv_mcp` as `{"command": "npx", "args": ["mcp-remote", "https://fps-cv.onrender.com/mcp"]}` and shipping two skills (`cv-analyst`, `cv-tailoring`). It serves *consumers* — people who want to read, summarise or tailor the CV.

Nothing serves the *maintainer*. Editing CV content is currently a GitHub Action (`claude-cv-improver.yml`) triggered by an issue comment, which checks out the repo, installs TinyTeX, and instructs Claude Code to edit the `.tex` file and open a PR. That workflow is being retired with the LaTeX source it operates on, and it has a structural weakness regardless: the maintainer reviews the change only after a bot has already authored a PR, never while it is being made. Publishing and deploying have no tooling at all — they are shell commands the maintainer must remember.

Three facts from the plugin-spec research shape the design:

- Claude Code declares remote HTTP MCP servers natively via `{"type": "http", "url": ...}`; `type` is *required* for non-stdio entries, and an entry with a `url` but no `type` is read as a stdio server. The `npx mcp-remote` wrapper is an older workaround with no remaining benefit — it costs a Node.js runtime dependency and a subprocess hop.
- One repository can host a marketplace, plugins under `plugins/<name>/`, and unrelated content (an MCP server's source, docs) as siblings. Plugin sources cannot reach outside their own directory, which is a safety boundary rather than a constraint here.
- Plugin agents cannot declare `hooks`, `mcpServers` or `permissionMode`, so an agent inherits whatever the plugin registers and cannot bring its own.

There is also a live defect: the `bit-agora` marketplace entry pins `version: "0.0.3"` while `plugin.json` says `0.0.5`, and the two official docs pages disagree about which wins when both are set.

## Decision

Ship two plugins as siblings under `cv-forge/plugins/`, both listed in `bit-agora`.

**`plugins/cv` — consumer-facing.** `plugin.json` declares the MCP server natively:

```json
"mcpServers": { "fps_cv_mcp": { "type": "http", "url": "https://fps-cv-mcp.wasmer.app/mcp" } }
```

The `npx mcp-remote` wrapper is dropped, removing a hard Node.js dependency for anyone installing the plugin. Skills `cv-analyst` and `cv-tailoring` move across unchanged in substance.

**`plugins/cv-forge` — maintainer-facing.** Three skills, no MCP server of its own (validation uses the mirrored schema files in the local `cv` clone, so the plugin works offline and has no runtime dependency on the deployed server):

- `cv-data-edit` — model-invocable. Edits `cv-data/*.yaml` in a local clone, validates against the clone's `schemas/`, renders a local preview via `cv-forge render`, **shows the diff for approval**, then branches and opens a PR. `allowed-tools`: `Read, Write, Edit, Grep, Glob, Bash(git:*), Bash(gh:*), Bash(cv-forge:*), Bash(check-jsonschema:*)`.
- `cv-publish` — `disable-model-invocation: true`. Proposes a CalVer tag, pushes it after confirmation, watches the run, and verifies release assets and the live site before reporting success. `allowed-tools`: `Read, Bash(git:*), Bash(gh:*), Bash(curl:*)`.
- `cv-forge-deploy` — `disable-model-invocation: true`. Runs the staged Wasmer deploy, then live-pokes `/healthz` and `POST /mcp` `tools/list`. `allowed-tools`: `Read, Bash(git:*), Bash(wasmer:*), Bash(anybuild:*), Bash(curl:*)`.

The plugin declares two `userConfig` entries, both directories: `cv_repo_path` for the local `cv` clone, and `cv_forge_path` (optional) for the local `cv-forge` checkout. **No credential is configured**: all GitHub operations run through the user's own `gh auth` session.

`cv_forge_path` exists because two of the three skills operate on the `cv-forge` tree rather than the `cv` clone — `cv-forge-deploy` runs `scripts/deploy.sh`, which stages `git ls-files` of `cv-forge` and preflights that tree's cleanliness (REQ-16, REQ-20), and `cv-data-edit`'s preview step invokes the `cv-forge` CLI, which resolves only if it is on `PATH`. Resolution order for the CLI is: bare command on `PATH`, else `pixi run -C ${user_config.cv_forge_path} cv-forge`. When `cv_forge_path` is unset and the command is not on `PATH`, `cv-data-edit` degrades explicitly — it validates against the clone's mirrored schemas and skips the render preview, saying so — while `cv-forge-deploy`, which has no degraded path, errors. (Adopted from the interface-designer's Challenge 1, 2026-09-13.)

**Skills only — no agents, no hooks.** Agents are rejected because both consequential loops derive their value from being *watched*: the edit loop's point is reviewing the diff together before a PR exists, and the deploy loop's point is that the live poke is the only proof available (there is no Edge emulator). Backgrounding either trades away the feature. Hooks are rejected for v1 because the skills already run validation as a visible step, whereas a `PreToolUse`/`PostToolUse` hook would fire in *every* session inside the `cv` clone — including ones the plugin is not driving — and would couple the plugin to the user's directory layout.

**Version lives in exactly one place.** `pyproject.toml`'s `[project].version` is the source; `scripts/release.sh` propagates it into both `plugin.json` files as part of the release commit; the `bit-agora` marketplace entries carry **no** `version` field at all. This sidesteps the documented precedence ambiguity entirely, since both readings of the spec agree that setting it in one place is sound.

Marketplace entries switch to the `git-subdir` source form pinned to the moving `v1` tag:

```json
{"source":"git-subdir","url":"https://github.com/francisco-perez-sorrosal/cv-forge","path":"plugins/cv","ref":"v1"}
```

## Considered Options

### A. Two plugins, skills only (chosen)

- **Pro**: consumer and maintainer surfaces have disjoint audiences, disjoint tool permissions, and disjoint update cadences — a recruiter installing `cv` should never see a skill that can push tags; the maintainer plugin's broad `Bash(git:*)`/`Bash(gh:*)` allowlist is never handed to a consumer; each can be listed and versioned independently.
- **Con**: two `plugin.json` files to keep in step; two marketplace entries; a maintainer installs both.

### B. One plugin with all five skills

- **Pro**: one manifest, one marketplace entry, one install.
- **Con**: every consumer would receive `cv-publish` and `cv-forge-deploy`, whose `allowed-tools` include `git`, `gh` and `wasmer`. Even with `disable-model-invocation`, that is a real capability surface shipped to an audience that has no use for it and no permission to use it. The blast radius argument alone settles this.

### C. Keep the "edit via PR" capability as a GitHub Action rather than a plugin skill

- **Pro**: it already exists and works, with a real authorization gate (`check-authorization.yml`); it is usable by anyone who can file an issue, not just by the maintainer with a plugin installed; it lives in the data repo, where data curation arguably belongs.
- **Con**: the review happens after the PR is authored, not while the edit is made — which is the part of the workflow with the most value. It also needs non-trivial reshaping (LaTeX→YAML, `latexmk`→`cv-forge render`), an `ANTHROPIC_API_KEY` secret in `cv`, and it would need to reach `cv-forge`'s render toolchain cross-repo. Retiring it removes a secret and a workflow from the data repo.

### D. Publish loop as a background plugin agent with `isolation: "worktree"`

- **Pro**: fire-and-forget for a pipeline that installs TinyTeX and compiles a PDF, which is not fast.
- **Con**: the verification step is the reason the skill exists (REQ-19: "ends with proof rather than a hopeful green check"). An unwatched verification is a log line nobody reads.

## Consequences

**Positive**
- Installing the consumer plugin no longer requires Node.js on the host; one subprocess hop and one npm dependency disappear.
- The maintainer's three loops become named, discoverable, permission-scoped operations instead of remembered shell commands.
- No credential is stored by either plugin; `gh auth` is the only identity in play.
- The `0.0.3`/`0.0.5` version drift is structurally prevented, not just fixed.

**Negative**
- The issue-triggered "suggest a CV edit" entry point disappears with `claude-cv-improver.yml`. Only someone with the maintainer plugin and `gh` auth can drive an edit through tooling; everyone else files an issue or a manual PR. Accepted — the workflow's authorization gate limited it to the maintainer anyway.
- Two manifests must stay in step. Mitigated by `release.sh` being the single writer.
- Repointing the marketplace before the plugins exist at the new path would break installs for `bit-agora` followers; sequencing (first publish green, then repoint) is an explicit migration step.

**Neutral**
- `.claude-plugin/mcp-local.json` (the stdio dev override) is no longer needed: a developer runs `pixi run mcps` and points a local `.mcp.json` at it, which is a documented step rather than a shipped file.

## Disconfirmation

**Activation**: no — the decomposition follows from the audience split and the permission surface; a lens sweep adds nothing the Security consideration above does not already carry.

**Falsifier.** This decision is wrong if the two plugins are never installed separately — that is, if every actual install over six months takes both. That would mean the audience split is imaginary and option B's single plugin was correct, with `disable-model-invocation` doing the real protective work.

A sharper falsifier for the skills-only half: if the maintainer routinely abandons a publish or deploy skill mid-run to do something else, the synchronous, watched design is wrong for the real workflow and option D's background agent should be revisited.

**Steelmanned runner-up.** Option C — keep an evolved GitHub Action for CV edits — deserves more weight than the decision gives it. It already exists and is battle-tested; it works from a phone; it requires no local clone, no plugin install, and no `gh` auth; and it puts data-curation automation in the data repository, which is arguably where it belongs. The plugin skill's advantage is narrow and specific: the maintainer sees the diff *while it is being formed* and can redirect mid-edit, rather than reviewing a finished bot PR. Whether that is worth retiring a working system depends entirely on how the maintainer actually edits — and the two are not mutually exclusive. Reinstating the Action later as a low-friction, issue-driven entry point remains open and would cost one workflow file plus one secret.

**Reversal trigger.** Merge into a single plugin if six months of installs show no separate use. Reinstate a YAML-targeting GitHub Action if a non-maintainer ever needs to propose a CV edit, or if the maintainer wants to file edits from a device without a clone.
