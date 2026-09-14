#!/usr/bin/env bash
# Deploy cv-forge's MCP server to Wasmer Edge from a staged, git-tracked-only
# copy of the repo.
#
# anybuild's Python provider ships the *entire* project directory into the
# app image and only excludes `.venv`, `.git`, `__pycache__` -- it does not
# honour `.gitignore` (RESEARCH_FINDINGS_deploy-mcp-wasmer.md § Q3; sibling
# FEEDBACK.md: anybuild ignores .gitignore). Never invoke `anybuild` from the repo root: stage
# `git ls-files` output into a temp directory first, every time.
#
# The `wasmer` CLI must be >= 7.0.0 -- 6.1.0 fails two different, unhelpful
# ways: anybuild shells out to a `--volume` flag the older CLI rejects, and
# even past that, package upload dies with a bare HTTP 500 (sibling
# FEEDBACK.md: wasmer CLI < 7 fails with anybuild). Both are silent about *why*; this preflight
# names it instead.
#
# Usage: scripts/deploy.sh <app-name> [--dry-run] [--allow-dirty]
#   <app-name>      Wasmer app name (e.g. fps-cv-mcp). Required.
#   --dry-run       Stage everything, print the staged file list and the
#                    env block, then stop -- no anybuild/wasmer invocation.
#   --allow-dirty   Skip the clean-working-tree preflight check.

set -euo pipefail

APP_NAME=""
DRY_RUN=0
ALLOW_DIRTY=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --allow-dirty) ALLOW_DIRTY=1 ;;
        --*)
            echo "deploy.sh: unknown flag '$arg'" >&2
            exit 2
            ;;
        *)
            APP_NAME="$arg"
            ;;
    esac
done

if [ -z "$APP_NAME" ]; then
    echo "deploy.sh: missing <app-name>." >&2
    echo "Usage: scripts/deploy.sh <app-name> [--dry-run] [--allow-dirty]" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

fail() {
    echo "deploy.sh: preflight failed -- $1" >&2
    exit 1
}

# --- preflight ---------------------------------------------------------

WASMER_BIN="${WASMER_BIN:-$(command -v wasmer || true)}"
[ -n "$WASMER_BIN" ] || fail "wasmer CLI not found on PATH (need >= 7.0.0: curl https://get.wasmer.io -sSfL | sh)"
WASMER_VERSION="$("$WASMER_BIN" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
WASMER_MAJOR="${WASMER_VERSION%%.*}"
if [ -z "$WASMER_MAJOR" ] || [ "$WASMER_MAJOR" -lt 7 ] 2>/dev/null; then
    fail "wasmer CLI is ${WASMER_VERSION:-unparseable}, need >= 7.0.0 (anybuild shells out to a --volume flag rejected below 7.x; upgrade with: wasmer self-update)"
fi
# anybuild runs from the staging dir, so a relative WASMER_BIN would resolve
# there instead of here and fail with a bare "No such file or directory".
WASMER_BIN="$(cd "$(dirname "$WASMER_BIN")" && pwd)/$(basename "$WASMER_BIN")"

ANYBUILD="${ANYBUILD_BIN:-}"
if [ -z "$ANYBUILD" ]; then
    if command -v anybuild >/dev/null 2>&1; then
        ANYBUILD="$(command -v anybuild)"
    elif [ -x "$HOME/.anybuild/bin/anybuild" ]; then
        ANYBUILD="$HOME/.anybuild/bin/anybuild"
    else
        fail "anybuild not found on PATH or ~/.anybuild/bin (curl -fsSL https://anybuild.run/install | sh)"
    fi
fi

if [ "$ALLOW_DIRTY" -ne 1 ] && [ -n "$(git status --porcelain)" ]; then
    fail "working tree is not clean (commit/stash changes, or pass --allow-dirty)"
fi

if [ -f scripts/check_wasix_ceilings.py ]; then
    # The check parses pixi.lock with pyyaml, a pixi-managed dependency --
    # run it through pixi so it sees the same interpreter/deps as the rest
    # of this project's tooling, not whatever bare `python3` resolves to.
    if command -v pixi >/dev/null 2>&1; then
        pixi run -e dev python3 scripts/check_wasix_ceilings.py \
            || fail "WASIX dependency ceiling check failed (scripts/check_wasix_ceilings.py)"
    else
        python3 scripts/check_wasix_ceilings.py \
            || fail "WASIX dependency ceiling check failed (scripts/check_wasix_ceilings.py)"
    fi
fi

# --- stage ---------------------------------------------------------------

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/cv-forge-deploy.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

git ls-files -z | tar --null -T - -cf - | tar -xf - -C "$STAGE"

# Materialize the baked fallback data directory the server falls back to
# when CV_DATA_DIR is unset (data/bootstrap.py::baked_snapshot_dir). Prefer
# a real release; while no `cv` release exists yet, copy this worktree's
# own cv-data/ -- printing which path was taken either way, since silently
# picking one would hide a real "no release yet" signal from the operator.
BAKED_DIR="$STAGE/baked"
if command -v cv-forge >/dev/null 2>&1 \
    && cv-forge fetch-snapshot -o "$BAKED_DIR" >/dev/null 2>&1; then
    echo "deploy.sh: baked fallback fetched from the latest cv release into $BAKED_DIR"
else
    echo "deploy.sh: no cv release reachable yet -- copying local cv-data/ as the baked fallback"
    rm -rf "$BAKED_DIR"
    cp -R cv-data "$BAKED_DIR"
fi

STAGED_COUNT="$(find "$STAGE" -type f | wc -l | tr -d ' ')"
echo "deploy.sh: staged $STAGED_COUNT files (git-tracked + baked/) in $STAGE"

if [ "$DRY_RUN" -eq 1 ]; then
    echo "--- staged files ---"
    (cd "$STAGE" && find . -type f | sed 's|^\./||' | sort)
    echo "--- env ---"
    printf '%s\n' \
        "CV_RELEASE_REPO=francisco-perez-sorrosal/cv" \
        "CV_REFRESH_INTERVAL=900" \
        "CV_BAKED_DIR=baked" \
        "CV_TRUST_HOST=1"
    echo "deploy.sh: dry run -- stopping before anybuild/wasmer deploy"
    exit 0
fi

# --- deploy ----------------------------------------------------------------

cd "$STAGE"
"$ANYBUILD" --platform=wasmer \
    --wasmer-bin "$WASMER_BIN" \
    --wasmer-app-owner francisco-perez-sorrosal \
    --wasmer-app-name "$APP_NAME"
