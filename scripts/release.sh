#!/bin/bash
#
# Release script for cv-forge.
#
# Bumps the single version source of truth (pyproject.toml's [project].version),
# propagates it into both plugin manifests, tags a SemVer release, and re-points
# the moving `vMAJOR` alias that cv-forge's own GitHub Actions and the cv-data
# repo's publish workflow pin against.
#
# Usage: scripts/release.sh <major|minor|patch|X.Y.Z> [--dry-run] [--no-push] [--allow-branch]
#
# Examples:
#   scripts/release.sh patch                 # 0.0.5 -> 0.0.6, commit+tag+push
#   scripts/release.sh minor --dry-run       # show what would change, do nothing
#   scripts/release.sh 1.0.0 --no-push       # commit+tag locally, push manually later

set -euo pipefail

MAIN_BRANCH="main"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $0 <major|minor|patch|X.Y.Z> [--dry-run] [--no-push] [--allow-branch]

  major|minor|patch  Bump the corresponding part of pyproject.toml's version.
  X.Y.Z               Set the version explicitly.

  --dry-run       Print every change and command without writing anything.
  --no-push       Commit and tag locally; skip the push step.
  --allow-branch  Proceed even when not on '$MAIN_BRANCH' (real runs only;
                  --dry-run never needs this).
EOF
}

# ---- Argument parsing ------------------------------------------------------

SPEC=""
DRY_RUN=0
NO_PUSH=0
ALLOW_BRANCH=0

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --dry-run) DRY_RUN=1 ;;
        --no-push) NO_PUSH=1 ;;
        --allow-branch) ALLOW_BRANCH=1 ;;
        -*) error "Unknown flag: $1" ;;
        *)
            [ -n "$SPEC" ] && error "Unexpected extra argument: $1"
            SPEC="$1"
            ;;
    esac
    shift
done

[ -n "$SPEC" ] || { usage; error "Version spec is required."; }

# ---- Preflight --------------------------------------------------------------

for cmd in python3 jq git gh pixi; do
    command -v "$cmd" >/dev/null 2>&1 || error "Required tool '$cmd' not found on PATH."
done

gh auth status >/dev/null 2>&1 || error "gh is not authenticated. Run 'gh auth login' first."

CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "$MAIN_BRANCH" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
        warning "Not on '$MAIN_BRANCH' (current: $CURRENT_BRANCH) — continuing, this is a dry run."
    elif [ "$ALLOW_BRANCH" -eq 1 ]; then
        warning "Not on '$MAIN_BRANCH' (current: $CURRENT_BRANCH) — proceeding per --allow-branch."
    else
        error "Not on '$MAIN_BRANCH' (current: $CURRENT_BRANCH). Re-run with --allow-branch if intentional."
    fi
fi

if [ "$DRY_RUN" -eq 0 ]; then
    git diff-index --quiet HEAD -- || error "Working directory is not clean. Commit or stash changes first."
fi

# ---- Version computation ----------------------------------------------------

CURRENT_VERSION=$(python3 - <<'PY'
import re, sys
with open("pyproject.toml") as f:
    content = f.read()
m = re.search(r'(?m)^version = "([^"]+)"$', content)
if not m:
    sys.exit("error: no top-level version = \"...\" line found in pyproject.toml")
print(m.group(1))
PY
) || error "Could not read current version from pyproject.toml."

NEW_VERSION=$(python3 - "$CURRENT_VERSION" "$SPEC" <<'PY'
import re, sys
current, spec = sys.argv[1], sys.argv[2]
m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current)
if not m:
    sys.exit(f"error: current version '{current}' is not X.Y.Z")
major, minor, patch = (int(x) for x in m.groups())
if re.fullmatch(r"\d+\.\d+\.\d+", spec):
    new = spec
elif spec == "major":
    new = f"{major + 1}.0.0"
elif spec == "minor":
    new = f"{major}.{minor + 1}.0"
elif spec == "patch":
    new = f"{major}.{minor}.{patch + 1}"
else:
    sys.exit(f"error: invalid spec '{spec}' (expected major|minor|patch|X.Y.Z)")
print(new)
PY
) || error "Could not compute new version."

TAG="v$NEW_VERSION"
MAJOR_ALIAS="v${NEW_VERSION%%.*}"

if git tag -l | grep -qx "$TAG"; then
    error "Tag $TAG already exists. Choose a different version."
fi

info "Version: $CURRENT_VERSION -> $NEW_VERSION (tag $TAG, alias $MAJOR_ALIAS)"

PLUGIN_MANIFESTS=(
    "plugins/cv/.claude-plugin/plugin.json"
    "plugins/cv-forge/.claude-plugin/plugin.json"
)

# ---- Dry run: report and stop -----------------------------------------------

if [ "$DRY_RUN" -eq 1 ]; then
    info "[DRY RUN] Would write version=\"$NEW_VERSION\" to: pyproject.toml"
    info "[DRY RUN] Would write __version__=\"$NEW_VERSION\" to: src/cv_forge/__init__.py"
    for manifest in "${PLUGIN_MANIFESTS[@]}"; do
        info "[DRY RUN] Would set \"version\": \"$NEW_VERSION\" in: $manifest"
    done
    info "[DRY RUN] Would run: pixi install (refreshes pixi.lock's own cv-forge version entry)"
    info "[DRY RUN] Would run: git add pyproject.toml pixi.lock ${PLUGIN_MANIFESTS[*]}"
    info "[DRY RUN] Would run: git commit -m \"chore(release): $TAG\""
    info "[DRY RUN] Would run: git tag $TAG"
    info "[DRY RUN] Would run: git tag -f $MAJOR_ALIAS $TAG"
    if [ "$NO_PUSH" -eq 0 ]; then
        info "[DRY RUN] Would run: git push origin $CURRENT_BRANCH $TAG && git push -f origin $MAJOR_ALIAS"
    else
        info "[DRY RUN] --no-push given: would skip the push step."
    fi
    info "[DRY RUN] $TAG would trigger .github/workflows/deploy-mcp.yml (v* tag) to redeploy the MCP server."
    info "[DRY RUN] No follow-up needed in bit-agora: marketplace entries carry no version field."
    exit 0
fi

# ---- Write version into pyproject.toml --------------------------------------

info "Updating pyproject.toml..."
python3 - "$NEW_VERSION" <<'PY'
import re, sys
new_version = sys.argv[1]
path = "pyproject.toml"
with open(path) as f:
    content = f.read()
new_content, count = re.subn(
    r'(?m)^version = "[^"]+"$', f'version = "{new_version}"', content, count=1
)
if count != 1:
    sys.exit(f"error: expected exactly one top-level version line in {path}, found {count}")
with open(path, "w") as f:
    f.write(new_content)
PY

# ---- Write version into the package constant ------------------------------
# src/cv_forge/__init__.py's __version__ is what the CLI's --version and the
# server's /healthz report when the distribution is not pip-installed (the
# Edge image stages the source tree, so dist-info is absent there).

PACKAGE_INIT="src/cv_forge/__init__.py"
info "Updating $PACKAGE_INIT..."
python3 - "$PACKAGE_INIT" "$NEW_VERSION" <<'PY'
import re, sys
path, new_version = sys.argv[1], sys.argv[2]
with open(path) as f:
    content = f.read()
new_content, count = re.subn(
    r'(?m)^__version__ = "[^"]+"$', f'__version__ = "{new_version}"', content, count=1
)
if count != 1:
    sys.exit(f"error: expected exactly one __version__ line in {path}, found {count}")
with open(path, "w") as f:
    f.write(new_content)
PY

# ---- Write version into both plugin manifests, right after "name" ----------

for manifest in "${PLUGIN_MANIFESTS[@]}"; do
    info "Updating $manifest..."
    # A text-line edit, not a json.load/json.dump round-trip: dumping with
    # indent=2 also expands short inline arrays (keywords, skills) onto
    # multiple lines, which would blow the diff far past "just the version"
    # (found manually while verifying this script — see LEARNINGS.md). Editing
    # the one "version"/"name" line in place preserves every other line
    # byte-for-byte and keeps the diff minimal, per this step's own done-when.
    python3 - "$manifest" "$NEW_VERSION" <<'PY'
import re, sys

path, new_version = sys.argv[1], sys.argv[2]
with open(path) as f:
    lines = f.readlines()

name_idx = version_idx = None
for i, line in enumerate(lines):
    if version_idx is None and re.match(r'^\s*"version"\s*:', line):
        version_idx = i
    if name_idx is None and re.match(r'^\s*"name"\s*:', line):
        name_idx = i

new_line = f'  "version": "{new_version}",\n'
if version_idx is not None:
    lines[version_idx] = new_line
elif name_idx is not None:
    lines.insert(name_idx + 1, new_line)
else:
    sys.exit(f'error: {path} has no top-level "name" key to anchor "version" after')

with open(path, "w") as f:
    f.writelines(lines)
PY
    jq empty "$manifest" || error "$manifest is not valid JSON after the version update."
done

# ---- Refresh pixi.lock (it carries cv-forge's own resolved version) --------

info "Running pixi install to refresh pixi.lock..."
pixi install >/dev/null || error "pixi install failed while refreshing pixi.lock."

# ---- Commit, tag, push -------------------------------------------------------

info "Committing version bump..."
git add pyproject.toml pixi.lock "$PACKAGE_INIT" "${PLUGIN_MANIFESTS[@]}"
git commit -m "chore(release): $TAG"

info "Tagging $TAG and re-pointing $MAJOR_ALIAS..."
git tag "$TAG"
git tag -f "$MAJOR_ALIAS" "$TAG"

if [ "$NO_PUSH" -eq 1 ]; then
    warning "--no-push given: commit and tags created locally, nothing pushed."
else
    info "Pushing commit and tags..."
    git push origin "$CURRENT_BRANCH" "$TAG"
    git push -f origin "$MAJOR_ALIAS"
fi

success "Release $TAG prepared."
info "This tag triggers .github/workflows/deploy-mcp.yml, which redeploys the MCP server to Wasmer Edge."
info "No follow-up needed in bit-agora: the plugins/cv and plugins/cv-forge marketplace entries carry no version field."
