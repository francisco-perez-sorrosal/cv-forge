---
name: cv-publish
description: >
  Publishes a new CV release: tags the cv clone, watches the reusable
  publish.yml workflow run in cv-forge, and verifies the release assets and
  live site before reporting success. Use only when the maintainer explicitly
  invokes /cv-publish -- never on conversational phrases like "publish my
  CV" or "make a release", since a release is a one-way public act.
  Also handles a re-render of an existing tag (no data change) via the
  optional [tag] argument.
argument-hint: "[tag]"
allowed-tools: "Read, Bash(git status:*), Bash(git fetch:*), Bash(git tag:*), Bash(git push:*), Bash(gh workflow run:*), Bash(gh run list:*), Bash(gh run watch:*), Bash(gh release view:*), Bash(curl:*)"
disable-model-invocation: true
---

# CV Publish

Tag a new CV release (or re-render an existing one) and prove it landed --
release, workflow, and live site -- before saying so.

## Locating the clone

`${user_config.cv_repo_path}` must be set and contain `cv-data/resume.yaml`
(same check as `cv-data-edit`). If unset or not a `cv` clone, stop with the
same error shape `cv-data-edit` uses for `cv_repo_path`.

## Two invocation shapes

- **No argument** -- publish a new release: propose today's CalVer tag,
  confirm, push it, and let the tag push trigger `publish.yml`.
- **`[tag]` argument** -- re-render an existing release with no data change
  (`SYSTEMS_PLAN.md § Cross-Repo Contract §4`): `gh workflow run publish.yml
  --repo francisco-perez-sorrosal/cv -f tag=<tag>`. Skip the tag proposal and
  push; go straight to steps 4-7 below against that tag. This is the path
  for "the render broke, ship it again" -- it never creates a new tag.

## Workflow (new release)

1. **Preflight** -- `git status` (clean working tree), `git fetch && git
   status` (`main` == `origin/main`), propose today's `YYYY.MM.DD` tag
   (`git tag -l '<date>*'` decides whether to append `.1`, `.2`, ...),
   `gh auth status` (report the logged-in login).
2. **Confirm** -- the one gate, before anything is pushed: `Push it?
   [y/N]`. On anything but `y`, stop with nothing changed.
3. **Push** -- `git tag <tag> && git push origin <tag>`.
4. **Poll for the run** -- `gh run list --repo francisco-perez-sorrosal/cv
   --workflow publish.yml --limit 1 --json databaseId,createdAt`, retried
   every few seconds for up to 60 s (a tag push returns no run id). If
   nothing appears in that window, say so plainly and print
   `https://github.com/francisco-perez-sorrosal/cv/actions` instead of
   hanging.
5. **Watch** -- `gh run watch <run-id> --repo francisco-perez-sorrosal/cv
   --exit-status`. On failure, do not just say "publish failed" -- fall
   through to step 6 and report the *first* missing or mismatched asset (or
   the failing job/step) plus the run URL.
6. **Verify** -- exact commands and what "8/8 assets" means:
   [references/publish-verification.md](references/publish-verification.md).
7. **Report** -- the display shape below, always including the MCP
   staleness line (REQ-10's up-to-15-minute refresh window) so "I
   published" is never mistaken for "the server updated instantly".

Display shape (adapt values, keep the structure):

```
▸ cv-publish
  Preflight · cv @ /Users/fperez/dev/cv
    ✓ working tree clean        ✓ main == origin/main
    ✓ tag 2026.09.13 is free    ✓ gh auth: fperezsorrosal
  Proposed tag  2026.09.13      (CalVer, today, no same-day release exists)
  Push it? [y/N]
  ✓ pushed · publish.yml run 18234567 picked up after 6 s
  ⠋ rendering pdf,tex,typst,md,html …                              2m11s
  ✓ run succeeded
  Release 2026.09.13 — 8/8 assets, every sha256 == release.json
    resume.yaml 61.2 kB ✓   resume-semantics.yaml 14.8 kB ✓   …CV.pdf 198.4 kB ✓
    .tex ✓  .typ ✓  .md ✓  .html ✓   release.json 1.1 kB —
  Site   GET https://fps-cv.wasmer.app/  200 · tag 2026.09.13 in page   ✓
  MCP    serving 2026.09.12 — picks this up within 15 min (REQ-10), no action needed
```

## Failure reporting

If the run fails, or the asset/site verification in step 6 does not match:
name the *first* offending asset (or the failing job/step) and the run URL,
then stop. No automatic retry, no attempt to fix the workflow itself --
those are the maintainer's call.

## Wasmer feedback

Steps 6-7 poke the live Wasmer static site. If anything about the poke, the
`publish.yml` run, or the tooling is surprising, append one sentence per
item to the repo-root `FEEDBACK.md`, following its `Entry shape` -- this
ledger is a standing user directive, not optional.
