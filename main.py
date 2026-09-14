"""Edge entrypoint. `anybuild`'s Python/MCP provider (`Anybuild`'s
`asgi_application = "main:app"`) detects this file by name and imports the
module-level `app` below; `python main.py` (its `commands.start`, and any
local invocation) uses the `__main__` guard instead. Both paths bind the
same ASGI app the same way, per the package-layout decision (.ai-state/decisions) that the Edge
entrypoint is never a bare file path pointing at a framework-internal
object -- it is this repo's own, explicit module.

This repo's importable code lives under `src/`, which is not on `sys.path`
for a plain `python main.py` (or an `import main` from the repo root) --
unlike `cv-forge`'s own console-script entry point, which reaches `src/`
through the installed package. The two-line guard below is the only thing
that makes this file portable between "run from a source checkout" (Edge,
where `anybuild` stages the whole repo tree) and "run after `pip install
-e .`" (neither breaks the other: inserting an already-resolvable `src/`
onto `sys.path` a second time is a no-op).

`app = create_app(build_provider_from_env(), stateless=True)` runs at
import time, deliberately: a misconfigured environment (no data directory
resolvable, a malformed `resume.yaml`) must fail the app's *startup*, not
its first request. `build_provider_from_env()` only reads local files at
this point (the baked snapshot or `$CV_DATA_DIR`) -- it does not make a
network call; the release-fetching refresh loop only starts once the ASGI
app's lifespan begins (see `cv_forge.mcp.app.create_app`), which happens
after this module has already been imported successfully.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = str(_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Deploy-time shim (see scripts/deploy.sh): a wasi-threads-suffixed copy of
# cffi's extension module that the WASIX index does not ship. Only exists in
# a staged Edge deploy; a plain checkout has no vendor/ directory.
_VENDOR = _ROOT / "vendor" / "wasix"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from cv_forge.data.bootstrap import build_provider_from_env  # noqa: E402
from cv_forge.mcp.app import create_app  # noqa: E402

app = create_app(build_provider_from_env(), stateless=True)

if __name__ == "__main__":
    import os

    import uvicorn

    from cv_forge.data.bootstrap import DEFAULT_PORT  # noqa: E402

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("FASTMCP_PORT", DEFAULT_PORT)))
    uvicorn.run(app, host=host, port=port, log_level="info")
