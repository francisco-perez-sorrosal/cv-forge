# Git/`gh` Cookbook for `cv-data-edit`

Exact command sequences for the confirm-and-execute step of the workflow in
`SKILL.md`, plus how to read `cv-forge validate --json` findings and recover
from the two ways this can go wrong. All commands run with `cwd` set to
`${user_config.cv_repo_path}` unless noted otherwise.

## 1. Preflight (before showing the confirmation gate)

```sh
git status --porcelain          # must be empty except the file(s) just edited
git fetch origin
git rev-list --left-right --count main...origin/main   # "0  0" == up to date
```

If `main` is behind `origin/main`, say so in the gate display (`Branch main
· clean · 2 behind origin`) rather than silently branching from a stale
base — the branch step below still branches from local `main`, so update it
first: `git switch main && git pull --ff-only origin main`.

## 2. Branch, commit, push (only after `[y]`)

```sh
slug=yahoo-title            # short, derived from the change; no spaces
date=$(date +%Y%m%d)
branch="cv-data/${slug}-${date}"
git switch -c "$branch"
# on a name collision (rare — same slug, same day):
# git switch -c "${branch}-2"

git add cv-data/resume.yaml            # add exactly the files intended
git commit -m "data: update Yahoo position title"   # no AI-authorship trailer

git push -u origin "$branch"
```

## 3. Open the PR

```sh
gh pr create \
  --repo francisco-perez-sorrosal/cv \
  --base main --head "$branch" \
  --title "data: update Yahoo position title" \
  --body "$(cat <<'EOF'
## What changed
work[2].position: "Senior Research Engineer" -> "Principal Research Engineer"

## Why
<one line from the user's request>

## Validation
cv-forge validate --data-dir cv-data
ok · 0 findings

## Preview
md (18.4 kB)
EOF
)"
```

Print the returned PR URL verbatim in the close-out line — never paraphrase
or shorten it.

```sh
gh pr view "$branch" --repo francisco-perez-sorrosal/cv --json url,state
```

confirms the PR landed before reporting success.

## 4. Reading `cv-forge validate --json` findings

```sh
cv-forge validate --data-dir cv-data --json
```

```json
{ "command": "validate", "status": "failed", "cv_forge_version": "1.1.0",
  "data_origin": { "kind": "local_dir", "path": "/Users/fperez/dev/cv/cv-data" },
  "outputs": [],
  "findings": [
    { "severity": "error", "code": "xref.unknown_institution",
      "pointer": "/work/3/institution_id",
      "message": "\"inst-yahooo\" is not a declared institution id",
      "hint": "did you mean \"inst-yahoo\"?" }
  ] }
```

- `status` is `"ok"` or `"failed"` — branch on this, not the exit code, when
  parsing `--json` output (the exit code is still 3 on failure, useful for
  scripting but redundant once you have the envelope).
- `code` prefix tells you the fix: `schema.*` — the value itself is
  malformed (edit the field); `xref.*` — the value doesn't match a declared
  id (edit the field to an id from `hint`, or add the missing institution).
- `pointer` is a JSON Pointer into the parsed document — `/work/3/institution_id`
  means index 3 (0-based) of the `work` array.
- Report every finding, not just the first — fix them all before
  re-validating, since a partial fix-and-rerun loop wastes turns.
- The `check-jsonschema` fallback (degraded path) has no equivalent
  envelope — it prints one line per schema violation to stderr and exits
  non-zero on failure, with no `xref.*` coverage (see `SKILL.md`'s Data
  conventions section). State which validator ran in the display either
  way.

## 5. Conflict recovery

**Push rejected (`origin/main` moved since the branch was cut):**

```sh
git fetch origin
git rebase origin/main
# resolve conflicts in cv-data/*.yaml if any, then:
git add cv-data/resume.yaml && git rebase --continue
git push --force-with-lease origin "$branch"
```

Never `git push --force` (unqualified) — `--force-with-lease` refuses the
push if someone else also pushed to the branch, which a bare `--force`
would silently overwrite.

**Branch name collision on `git switch -c`:**

```sh
git switch -c "${branch}-2"
```

Append `-2`, `-3`, … — don't reuse or overwrite an existing same-day branch
without asking, since it may hold someone else's in-flight edit.

**PR already exists for this branch:**

```sh
gh pr view "$branch" --repo francisco-perez-sorrosal/cv --json url,state
```

If `state` is `"OPEN"`, report its URL instead of creating a duplicate; if
`"MERGED"` or `"CLOSED"`, the branch name collided with a completed change —
use a fresh slug and branch instead of reopening.

**Working tree not clean at preflight:**

Stop and show `git status --porcelain` to the user rather than stashing or
discarding — an edit already in progress in `cv_repo_path` might be theirs,
not this skill's.
