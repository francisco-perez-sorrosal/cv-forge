---
id: dec-005
draft_id: dec-draft-893c5497
title: Split the dual-branch cv repository into cv (data-only) and cv-forge (machinery)
status: accepted
category: architectural
date: 2026-09-13
summary: The `main`/`mcp` dual-branch repository becomes two repositories — `cv` holding only the YAML CV data plus mirrored schemas and two thin workflows, and `cv-forge` holding the models, renderer, CLI, MCP server, plugins and publishing machinery. Both keep full history.
tags: [repo-structure, migration, git-history, boundaries]
made_by: fperezsorrosal
agent_type: systems-architect
branch: cv-repo-split
pipeline_tier: full
affected_files:
  - cv-data/
  - src/cv_mcp_server/
  - .github/workflows/
  - README.md
  - CLAUDE.md
affected_reqs: [REQ-01, REQ-02, REQ-03, REQ-15]
---

## Context

The repository currently serves two unrelated purposes from two branches of one remote: `main` carries a hand-written LaTeX CV and its compiled PDF; `mcp` carries a Python MCP server, a Jinja2 renderer, two Claude Code skills, a plugin manifest, an MCPB build subsystem, and — rebased on top of `main` — the same LaTeX files it has superseded. Keeping the two in sync costs two dedicated GitHub Actions workflows (`auto-rebase-mcp.yml`, `rebase-status-check.yml`), a 568-line document explaining them (`README_CICD.md`), and a standing supply of rebase conflicts. The branch-sync machinery exists solely to reconcile a structure that has no reason to exist.

The two concerns also change on different clocks and by different means. CV content changes a few times a year, is edited by a human (or an agent acting for one) and needs review-before-merge. The machinery changes on an engineering cadence, has a test suite, and needs CI. Their only genuine dependency is that the machinery reads the data.

A third signal: `origin/HEAD` still points at a `master` branch last touched 2025-03-20, so `git clone` lands anyone on an 18-month-old snapshot — a live, user-facing defect independent of the split but fixable in the same pass.

The codebase inventory verified that `cv-data/` contains nothing but the two YAML files, and that `cv-data/resume.yaml` is a complete, line-by-line-verified superset of the hand-written `.tex` (patents, PhD narrative with all seven citation counts, all 35 course/certificate entries, conference roles, memberships, book review, quote, and the hand-tuned `moderncv` styling macros, which are copied verbatim into `_preamble.tex.j2`). The `.tex` can therefore be retired rather than migrated.

## Decision

Create `github.com/francisco-perez-sorrosal/cv-forge` for the machinery and reduce `github.com/francisco-perez-sorrosal/cv` to data only.

`cv` keeps `cv-data/*.yaml`, gains `schemas/*.schema.json` (mirrored, see `dec-001`), two thin workflows (validate on PR, publish on tag), a short README, a data-conventions-only `CLAUDE.md`, a hand-written `.gitignore`, and the LICENSE. It contains no Python, no lockfile, no rendered artifact, and no LaTeX source.

`cv-forge` keeps everything else and gains the reusable publish workflow, the Wasmer deploy configuration, and the two Claude Code plugins.

**History is preserved in both.** `cv-forge` is created by pushing the `mcp` lineage (via the `cv-repo-split` branch) to the new remote and then deleting `cv-data/` in a follow-up commit — the machinery's full development history survives, and the YAML's history riding along in it is harmless (public, non-sensitive, a few hundred KB). `cv`'s `main` keeps its own history and *gains* the YAML edit history through a one-time `git filter-repo --path cv-data/` extraction from the `mcp` lineage, merged with `--allow-unrelated-histories`.

The dual-branch machinery is deleted with the structure it served: `auto-rebase-mcp.yml`, `rebase-status-check.yml`, `README_CICD.md`, and the `mcp` branch itself.

Migration ordering, the two points of no return, and the rollback posture per phase live in `SYSTEMS_PLAN.md § Migration & Cutover Plan`. The branch cleanup (`master`, `x`, `meh`, two `research/*`, five `claude/issue-5-*`, one backup branch) and the `origin/HEAD` repoint ride along in the final phase, with `track-user` and `registry-pub` inspected before deletion.

## Considered Options

### A. Two repositories with full history in both (chosen)

- **Pro**: each repository has one reason to change; `git blame` survives on both the YAML's evolution and the renderer's 100+ commits of iterative work; the branch-sync subsystem is deleted rather than reworked; the data repo becomes approachable to a non-engineer (or an agent) with no toolchain.
- **Con**: two repositories to keep in mind; a cross-repo contract must be designed and kept minimal; the `cv` history rewrite is irreversible without a recorded pre-rewrite SHA.

### B. Keep one repository, restructure into a monorepo with `data/` and `machinery/` directories

- **Pro**: no cross-repo contract at all; one CI configuration; no history surgery.
- **Con**: does not solve the actual problem. The data repo's whole value is that it is *not* a software project — a monorepo keeps `pyproject.toml`, `pixi.lock`, `tests/` and a CI matrix sitting next to the two files a CV editor cares about, and every data PR still triggers (or must be path-filtered out of) the machinery's CI. It also keeps the publish trigger ambiguous: is a tag a data release or a machinery release?

### C. Two repositories, fresh start (no history)

- **Pro**: simplest mechanically; no `filter-repo`, no unrelated-histories merge, no risk to `main`.
- **Con**: discards the archaeological record the inventory found to be substantial on both sides — the renderer's iterative development and the YAML's content evolution. The cost of preserving it is one scripted extraction; the cost of discarding it is permanent.

## Consequences

**Positive**
- The branch-sync subsystem and its 568 lines of documentation are deleted outright.
- A data edit becomes a one-file PR with a schema check, needing no local Python, no `pixi`, and no LaTeX installation.
- The machinery gets a name that describes it (`cv-forge`) and a CI configuration that is only ever triggered by machinery changes.
- `git clone` lands on a current branch for the first time since 2025-03-20.

**Negative**
- The cross-repo contract is now a thing that exists and can rot. Mitigated by keeping it to exactly two pinned strings and drift-checking one of them in CI (`dec-001`).
- A change spanning both repositories (e.g. a new YAML field plus the renderer that consumes it) is now two PRs in a required order: schema and renderer first, data second.
- `cv-forge`'s history carries `cv-data/` blobs that no longer exist in its tree. Accepted as harmless bloat.

**Neutral**
- The `.ai-state/` corpus travels with `cv-forge`, since every artifact in it documents work on the tooling.

## Disconfirmation

**Activation**: no — the split boundary was locked with the user at intake; the lens sweep was run over the *mechanism* (history strategy, which files land where) rather than the decision itself, and changed nothing.

**Falsifier.** This decision is wrong if, within two publishing cycles, a routine CV content change requires a coordinated PR in `cv-forge` — that is, if the data cannot evolve without the machinery evolving with it. The concrete signal: any `cv` PR that cannot pass `validate.yml` without a matching `cv-forge` schema change. One such occurrence is an additive-evolution bug; a second is evidence that the boundary was drawn in the wrong place and that the schema is too tightly coupled to the renderer's needs.

**Steelmanned runner-up.** Option B (monorepo with a directory split) is stronger than it first appears. It achieves most of the conceptual separation with *zero* cross-repo contract, no history surgery, and no irreversible step — and GitHub's `paths:` filters make "only run machinery CI on machinery changes" a two-line configuration. The genuine cost it pays is not technical but cognitive: the data directory sits inside a Python project, so the editing experience for the one artifact that matters most (the CV) is permanently framed as "editing a file in a software repo." If the maintainer's actual editing workflow turns out to run through the `cv-forge` plugin anyway — never touching a bare `cv` clone — then that cognitive cost never materialises and option B was the cheaper correct answer.

**Reversal trigger.** Re-merge the repositories if, after six months, (a) more than half of `cv` PRs also required a `cv-forge` PR, or (b) the cross-repo contract has needed more than two breaking revisions. Reversal is mechanically easy in this direction — `cv-forge` can absorb `cv-data/` with a subtree merge that keeps both histories — which is itself part of why option A was affordable to try.
