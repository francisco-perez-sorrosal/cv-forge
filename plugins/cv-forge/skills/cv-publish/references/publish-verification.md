# Publish Verification

Exact commands for `cv-publish`'s step 6 (both invocation shapes converge
here once a tag and a completed run exist). Run every check; report the
*first* one that fails, not just the last.

## What "8/8 assets" means

Per `SYSTEMS_PLAN.md § Cross-Repo Contract §3`, a successful release carries
exactly these eight assets, byte-for-byte matching `release.json`'s
`assets` map:

1. `resume.yaml`
2. `resume-semantics.yaml`
3. `FranciscoPerezSorrosal_CV.pdf`
4. `FranciscoPerezSorrosal_CV.tex`
5. `FranciscoPerezSorrosal_CV.typ`
6. `FranciscoPerezSorrosal_CV.md`
7. `FranciscoPerezSorrosal_CV.html`
8. `release.json` (the manifest itself -- not verified against itself; it is
   the reference)

"8/8" means: all seven non-manifest assets are present as release assets,
and each one's `sha256` (computed locally) equals the value `release.json`
records for it. A count without the hash check is not verification --
GitHub can list a truncated or corrupted upload as "present".

## Commands

**1. List assets and confirm count:**

```sh
gh release view <tag> --repo francisco-perez-sorrosal/cv --json assets \
  --jq '.assets | length'
# expect: 8
```

**2. Fetch `release.json` and each asset, compare hashes:**

```sh
gh release view <tag> --repo francisco-perez-sorrosal/cv --json assets \
  --jq '.assets[].name'

curl -sL -o /tmp/release.json \
  "https://github.com/francisco-perez-sorrosal/cv/releases/download/<tag>/release.json"

for asset in resume.yaml resume-semantics.yaml \
             FranciscoPerezSorrosal_CV.pdf FranciscoPerezSorrosal_CV.tex \
             FranciscoPerezSorrosal_CV.typ FranciscoPerezSorrosal_CV.md \
             FranciscoPerezSorrosal_CV.html; do
  curl -sL -o "/tmp/$asset" \
    "https://github.com/francisco-perez-sorrosal/cv/releases/download/<tag>/$asset"
  local_sha=$(shasum -a 256 "/tmp/$asset" | cut -d' ' -f1)
  expected_sha=$(jq -r --arg n "$asset" '.assets[$n].sha256' /tmp/release.json)
  [ "$local_sha" = "$expected_sha" ] && echo "$asset OK" || echo "$asset MISMATCH ($local_sha != $expected_sha)"
done
```

Report file sizes from `release.json`'s `.assets[].size` alongside each
name, matching the display shape's `61.2 kB ✓` form (convert bytes to kB,
one decimal place).

**3. Confirm `release.json` itself is schema_version 1 and the tag matches:**

```sh
jq -r '.schema_version, .tag, .cv_forge_version' /tmp/release.json
# expect: 1, <tag>, and a semver string
```

**4. Confirm the live site reports the tag:**

```sh
curl -s -o /tmp/site.html -w '%{http_code}\n' https://fps-cv.wasmer.app/
grep -c "<tag>" /tmp/site.html
# expect: 200, and a non-zero grep count
```

If the site's HTML does not embed the tag by that exact string, check for a
`data-release-tag` attribute or footer text instead -- the CV HTML template
(`cv.html.j2`) is the source of truth for how the tag is rendered; do not
invent a match that is not actually there.

## On failure

Name the first mismatch found (asset name + expected vs. actual hash, or
"site returned 404", or "site shows tag 2026.09.12, expected 2026.09.13")
plus the workflow run URL from step 5 of the main skill. Do not report
partial success as success.
