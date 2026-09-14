---
name: cv-data-edit
description: >
  Edits Francisco Perez-Sorrosal's CV data (`cv-data/*.yaml`) in a local clone
  of the `cv` repo, validates it, renders a preview, and opens a pull request
  after showing the diff. Use when the user wants to change, add or remove CV
  content -- a title, a date, a new role, a patent, a publication, a skill. Do
  NOT use to read or summarise the CV (that is cv-analyst) or to adapt it to a
  job posting (that is cv-tailoring) -- neither of those edits the source
  data. Do NOT publish or tag: that is the separate /cv-publish skill.
  Trigger phrases: "update my CV", "change my title", "add this job", "fix
  the date on", "edit resume.yaml".
argument-hint: <what to change>
allowed-tools: Read, Edit, Grep, Glob, Bash(git status:*), Bash(git diff:*), Bash(git switch:*), Bash(git add:*), Bash(git commit:*), Bash(git push:*), Bash(gh pr create:*), Bash(gh pr view:*), Bash(cv-forge:*), Bash(check-jsonschema:*)
---

# CV Data Edit

Edit `cv-data/*.yaml` in a local `cv` clone, prove the edit is valid and
renders correctly, then open a reviewable PR -- never push straight to
`main`.

## Locating the clones

`${user_config.cv_repo_path}` must be set and contain `cv-data/resume.yaml`.
If unset, ask once and tell the user to persist it in the plugin's
configuration. If set but not a `cv` clone (`cv-data/resume.yaml` and
`schemas/resume.schema.json` both absent), stop with:

```
cv_repo_path points at <path>, which is not a cv clone.
Looked for: cv-data/resume.yaml, schemas/resume.schema.json -- neither is present.
To fix: set cv_repo_path to your local clone of github.com/francisco-perez-sorrosal/cv
        (e.g. /Users/fperez/dev/cv), or clone it: gh repo clone francisco-perez-sorrosal/cv
```

`${user_config.cv_forge_path}` is optional and only needed for the preview
step below.

## Resolving `cv-forge`

Try, in order: (1) bare `cv-forge` on `PATH`; (2) `pixi run -C
${user_config.cv_forge_path} cv-forge` when `cv_forge_path` is set. If
neither resolves, **degrade explicitly** -- validate with
`check-jsonschema --schemafile <cv_repo_path>/schemas/resume.schema.json
<cv_repo_path>/cv-data/resume.yaml` (and the semantics schema the same way)
and state to the user, in the display, that the render preview is skipped
because `cv-forge` could not be found -- never skip it silently.

## Data conventions

- **Entry IDs**: `<type>-<slug>`, e.g. `work-yahoo-kgs-2023`,
  `patent-em-2019`, `pub-htl-acl-2019`. Every entry that can be referenced
  by the semantic overlay carries one (`ResumeEntry.id` in
  `src/cv_forge/models/resume.py`). Keep new IDs unique and in this shape.
- **Cross-references**: `work[]`/`education[]`/`certificates[]` entries
  carry `institution_id`, which must name a declared `institutions[].id`.
  `cv-forge validate` checks this (`xref.unknown_institution`, with a
  did-you-mean hint) -- the fallback `check-jsonschema` path does **not**,
  since JSON Schema has no foreign-key concept.
- **Chronological order**: within `work`/`education`/`certificates`, most
  recent entry first.
- **Date shape**: `start_date`/`end_date` on `work`, `education`,
  `certificates` is `YYYY` or `YYYY-MM` (checked by `cv-forge validate` as
  `schema.invalid_date_format`); `conferences[].start_date` uses full
  `YYYY-MM-DD` and is a different family -- don't reuse its shape elsewhere.
- **Semantic overlay** (`cv-data/resume-semantics.yaml`): every `entry_id`,
  `source_id`/`target_id` (relationships), and topic-annotation `entry_id`
  must name an id that exists in `resume.yaml`. This is **not** one of
  `cv-forge validate`'s findings today -- it surfaces only as a load-time
  warning log from `ResumeStore`. If you edit or remove an entry that the
  overlay references, grep `cv-data/resume-semantics.yaml` for its id and
  update or remove the reference yourself.

## Workflow

1. **Edit** — make the requested change with `Edit`, scoped to the smallest
   diff that satisfies the request.
2. **Validate** — run `cv-forge validate --data-dir <cv_repo_path>/cv-data`
   (or the `check-jsonschema` fallback). Any finding stops here: report it
   with its `pointer`/`hint`, fix, and re-validate before moving on.
3. **Preview** — `cv-forge render -f md -o <tmpdir> --data-dir
   <cv_repo_path>/cv-data` (skip per the degraded-path rule above if
   `cv-forge` can't be resolved).
4. **Diff** — `git diff` the changed file(s).
5. **Confirm** — one gate, enumerating every side effect before it happens.
   Nothing before this step touches the working tree's git state.

Display shape (adapt values, keep the structure):

```
▸ cv-data-edit · change the Yahoo position title
  Data     /Users/fperez/dev/cv/cv-data          (cv_repo_path)
  Branch   main · clean · up to date with origin
  1/4  edit      cv-data/resume.yaml  →  work[2].position
  2/4  validate  cv-forge validate --data-dir cv-data      ok · 0 findings
  3/4  preview   cv-forge render -f md -o /tmp/cv-preview  md · 18.4 kB
       --- a/cv-data/resume.yaml
       +++ b/cv-data/resume.yaml
       @@ work[2] — Yahoo Inc., 2023–
       -    position: Senior Research Engineer
       +    position: Principal Research Engineer
  4/4  Open a pull request? This will:
         branch   cv-data/yahoo-title-20260913     (new, from origin/main)
         commit   data: update Yahoo position title
         push     origin
         PR       francisco-perez-sorrosal/cv ← base main
       [y] do it   [d] show the rendered preview   [e] keep editing   [n] stop
```

Degraded-path variant of step 3 (state the skip, do not silently omit it):

```
  3/4  preview   skipped -- cv-forge not found (cv_forge_path unset, not on PATH);
                 validated with check-jsonschema instead
```

On `[y]`: branch `cv-data/<slug>-<YYYYMMDD>` (append `-2` on name collision,
from `origin/main`); commit `data: <one-line summary>` — **no AI-authorship
trailer**, the maintainer owns the commit; push `origin`; open the PR with
body sections *What changed* / *Why* / *Validation* (command + result) /
*Preview* (formats rendered). See
[references/git-gh-cookbook.md](references/git-gh-cookbook.md) for the
exact command sequences, conflict recovery, and how to read `cv-forge
validate --json` output.

Close-out, always stated so the maintainer knows what happens next:

```
PR #42 -- https://github.com/francisco-perez-sorrosal/cv/pull/42.
Merging does not publish; run /cv-publish when you want a release.
```
