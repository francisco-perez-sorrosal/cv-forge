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

# Untracked files are ignored on purpose: staging copies `git ls-files` only, so
# they can never reach the image; only tracked-but-uncommitted changes matter.
if [ "$ALLOW_DIRTY" -ne 1 ] && [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    fail "working tree has uncommitted tracked changes (commit/stash them, or pass --allow-dirty)"
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
CV_DATA_REPO="${CV_RELEASE_REPO:-francisco-perez-sorrosal/cv}"
CV_DATA_REF="${CV_DATA_REF:-main}"
if command -v cv-forge >/dev/null 2>&1 \
    && cv-forge fetch-snapshot -o "$BAKED_DIR" >/dev/null 2>&1; then
    echo "deploy.sh: baked fallback fetched from the latest cv release into $BAKED_DIR"
elif [ -n "${CV_DATA_DIR:-}" ] && [ -f "$CV_DATA_DIR/resume.yaml" ]; then
    echo "deploy.sh: no cv release reachable -- copying CV_DATA_DIR ($CV_DATA_DIR) as the baked fallback"
    rm -rf "$BAKED_DIR"
    cp -R "$CV_DATA_DIR" "$BAKED_DIR"
elif [ -f cv-data/resume.yaml ]; then
    echo "deploy.sh: no cv release reachable -- copying local cv-data/ as the baked fallback"
    rm -rf "$BAKED_DIR"
    cp -R cv-data "$BAKED_DIR"
else
    # The data repo is public: a shallow clone needs no token and works in CI
    # before the first release exists. Only cv-data/ is kept.
    echo "deploy.sh: no cv release and no local data -- cloning $CV_DATA_REPO@$CV_DATA_REF for the baked fallback"
    CLONE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cv-data-clone.XXXXXX")"
    git clone --quiet --depth 1 --branch "$CV_DATA_REF" "https://github.com/$CV_DATA_REPO.git" "$CLONE_DIR" \
        || fail "could not clone $CV_DATA_REPO@$CV_DATA_REF for the baked fallback"
    [ -f "$CLONE_DIR/cv-data/resume.yaml" ] || fail "$CV_DATA_REPO@$CV_DATA_REF has no cv-data/resume.yaml"
    rm -rf "$BAKED_DIR"
    cp -R "$CLONE_DIR/cv-data" "$BAKED_DIR"
    rm -rf "$CLONE_DIR"
fi

# Vendor a threads-ABI copy of cffi's extension module. The WASIX index ships
# `_cffi_backend.cpython-313-wasm32-wasi.so` (non-threads suffix) while the
# Edge interpreter is a wasi-threads build that only looks for
# `...-wasi-threads.so` -- so `cryptography` (pulled in by the MCP SDK and
# imported at module load) dies with "No module named '_cffi_backend'" on
# Edge. `main.py` puts vendor/wasix first on sys.path. See FEEDBACK.md:
# cffi wheel built for the wrong WASIX ABI. Remove once the index ships a
# threads-suffixed wheel.
CFFI_VERSION="$(grep -A1 '^  name: cffi$' pixi.lock | grep 'version:' | head -1 | awk '{print $2}')"
VENDOR_DIR="$STAGE/vendor/wasix"
mkdir -p "$VENDOR_DIR"
if command -v uvx >/dev/null 2>&1; then
    UVX="uvx"
else
    UVX="pixi run -e dev uvx"
fi
$UVX pip install "cffi==${CFFI_VERSION}" --target "$VENDOR_DIR" \
    --platform wasix_wasm32 --only-binary=:all: --python-version=3.13 \
    --extra-index-url https://python-registry.wasix.org/simple --no-deps -q \
    || fail "could not cross-install cffi==${CFFI_VERSION} for the vendor shim"
CFFI_SO="$(find "$VENDOR_DIR" -maxdepth 1 -name '_cffi_backend.cpython-313-wasm32-wasi.so' | head -1)"
[ -n "$CFFI_SO" ] || fail "cffi wheel did not contain _cffi_backend.cpython-313-wasm32-wasi.so"
cp "$CFFI_SO" "$VENDOR_DIR/_cffi_backend.cpython-313-wasm32-wasi-threads.so"
echo "deploy.sh: vendored cffi ${CFFI_VERSION} backend with a wasi-threads suffix into vendor/wasix/"

STAGED_COUNT="$(find "$STAGE" -type f | wc -l | tr -d ' ')"
echo "deploy.sh: staged $STAGED_COUNT files (git-tracked + baked/ + vendor/) in $STAGE"

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
