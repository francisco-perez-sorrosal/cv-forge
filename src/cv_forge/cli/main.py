"""`cv-forge` command-line interface.

`main(argv: list[str] | None = None) -> int` is the whole contract: an
in-process entry point (never `sys.exit` on the happy path) so tests can call
it directly and callers -- including the `cv-forge = "cv_forge.cli.main:main"`
console script -- get an integer exit code either way. `argparse`'s own error
paths (`--help`, `--version`, bad `choices`) still raise `SystemExit`; `main`
is the only place that catches it and turns it back into a return value.

Five real commands (`render`, `validate`, `export-schemas`, `fetch-snapshot`,
`serve`) per `INTERFACE_DESIGN.md §1.1` -- this step implements `render` and
registers the other four as stubs that exit 2, so `--help` already shows the
full grammar (M1.14/M1.16 fill the stub bodies in).

No walk-up discovery: the old `PROJECT_ROOT = Path(__file__).parent.parent`
pattern is retired, not relocated (§1.2). A data directory is named
explicitly -- `--data-dir`, then `$CV_DATA_DIR` -- or `render`/`validate`
exit 2. `render`'s `-o/--out` has no documented default in `INTERFACE_DESIGN.md
§1.2`; the orchestrator resolved it to `rendered-cv/` (relative to the
current directory) since that already names the gitignored quick-render
workspace `scripts/render_cv.py` used before this CLI replaced it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cv_forge import __version__ as CV_FORGE_VERSION
from cv_forge.data.local import LocalDataDirError, load_local_dir
from cv_forge.data.snapshot import DataOrigin, LocalDir
from cv_forge.data.store import ResumeStore
from cv_forge.render.renderers import (
    render_html,
    render_latex,
    render_markdown,
    render_typst,
)

ASSET_STEM = "FranciscoPerezSorrosal_CV"
DEFAULT_RENDER_OUT = Path("rendered-cv")
LATEXMK = "latexmk"

_EXAMPLES = """\
EXAMPLES
  # Preview the CV as HTML from a local cv clone
  cv-forge render -f html --data-dir ../cv/cv-data -o ./out
  # Everything the publish workflow renders, the way CI does it
  cv-forge render -f all --data-dir ../cv/cv-data -o ./out --json
  # Check data before opening a PR (same findings as the cv PR gate)
  cv-forge validate --data-dir ../cv/cv-data
"""

_TOP_LEVEL_HELP = (
    "cv-forge — render, validate and serve Francisco "
    "Perez-Sorrosal's CV data.\n\n" + _EXAMPLES
)


@dataclass(frozen=True)
class FormatSpec:
    """One entry in the render format registry: source extension + renderer.

    `compiled=True` (only `pdf`) means the extension names the *compiled*
    artifact while `renderer` still produces LaTeX source -- `_render_format`
    is what bridges the two.
    """

    extension: str
    renderer: Callable[[ResumeStore], str]
    compiled: bool = False


_FORMATS: dict[str, FormatSpec] = {
    "md": FormatSpec("md", render_markdown),
    "html": FormatSpec("html", render_html),
    "tex": FormatSpec("tex", render_latex),
    "typst": FormatSpec("typ", render_typst),
    "pdf": FormatSpec("pdf", render_latex, compiled=True),
}
ALL_FORMATS = ("md", "html", "tex", "typst", "pdf")


# --- Entry point ---


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _exit_code(exc)

    if not hasattr(args, "func"):
        _print_no_command_help(parser)
        return 2

    try:
        return args.func(args)
    except SystemExit as exc:
        return _exit_code(exc)
    except Exception as exc:  # last-resort: no traceback for CLI users
        print(f"cv-forge: unexpected error: {exc}", file=sys.stderr)
        return 1


def _exit_code(exc: SystemExit) -> int:
    return exc.code if isinstance(exc.code, int) else 1


def _print_no_command_help(parser: argparse.ArgumentParser) -> None:
    print(_EXAMPLES, file=sys.stderr)
    print(f"Run '{parser.prog} --help' for all commands.", file=sys.stderr)


# --- Parser construction ---


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cv-forge",
        description=_TOP_LEVEL_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"cv-forge {CV_FORGE_VERSION}"
    )
    subparsers = parser.add_subparsers(dest="command")
    common = _common_options_parser()

    render_parser = subparsers.add_parser(
        "render", help="Render CV data to one or more output formats", parents=[common]
    )
    render_parser.add_argument(
        "-f",
        "--format",
        required=True,
        metavar="FMT",
        help="Comma list of formats (md,html,tex,typst,pdf) or 'all'",
    )
    render_parser.add_argument(
        "-o",
        "--out",
        default=None,
        metavar="DIR|-",
        help=f"Output directory (default: {DEFAULT_RENDER_OUT}), or '-' for stdout",
    )
    render_parser.add_argument("--data-dir", default=None, metavar="DIR")
    render_parser.set_defaults(func=_cmd_render)

    for name, summary in (
        ("validate", "Check a data directory against the schemas and cross-references"),
        ("export-schemas", "Generate schemas/*.schema.json from the Pydantic models"),
        ("fetch-snapshot", "Download a release's data assets into a directory"),
        ("serve", "Run the MCP server locally (stdio or streamable-http)"),
    ):
        stub = subparsers.add_parser(name, help=summary, parents=[common])
        stub.set_defaults(func=_not_implemented(name))

    return parser


def _common_options_parser() -> argparse.ArgumentParser:
    """Global options, attached to every subcommand via `parents=`.

    Reused as one instance across `add_parser(parents=[...])` calls --
    argparse's documented pattern for shared option groups.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--json", action="store_true", help="Emit a machine-readable JSON envelope"
    )
    parent.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress non-essential stderr output",
    )
    parent.add_argument(
        "-v", "--verbose", action="store_true", help="Increase stderr verbosity"
    )
    parent.add_argument(
        "--no-color", action="store_true", help="Disable ANSI color in stderr output"
    )
    return parent


def _not_implemented(name: str) -> Callable[[argparse.Namespace], int]:
    def _cmd(_args: argparse.Namespace) -> int:
        print(f"cv-forge: '{name}' is not implemented in this build.", file=sys.stderr)
        return 2

    return _cmd


# --- render ---


def _cmd_render(args: argparse.Namespace) -> int:
    formats = _resolve_formats(args.format)
    if formats is None:
        print(
            f"cv-forge: unknown format in '{args.format}' "
            f"(choose from {', '.join(_FORMATS)}, or 'all')",
            file=sys.stderr,
        )
        return 2

    if "pdf" in formats and shutil.which(LATEXMK) is None:
        _print_missing_latexmk_error()
        return 5

    data_dir = args.data_dir or os.environ.get("CV_DATA_DIR")
    if not data_dir:
        _print_no_data_dir_error()
        return 2

    try:
        snapshot = load_local_dir(Path(data_dir))
    except LocalDataDirError as exc:
        print(f"cv-forge: {exc}", file=sys.stderr)
        return 2
    store = ResumeStore(snapshot.resume, snapshot.semantics)

    if args.out == "-":
        return _render_to_stdout(formats, store, json_requested=args.json)

    out_dir = Path(args.out) if args.out else DEFAULT_RENDER_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        _output_entry(fmt, _render_format(fmt, store, out_dir)) for fmt in formats
    ]

    if args.json:
        _print_json_envelope("render", snapshot.origin, outputs)
    else:
        for output in outputs:
            print(output["path"])
    return 0


def _resolve_formats(raw: str) -> tuple[str, ...] | None:
    if raw == "all":
        return ALL_FORMATS
    formats = tuple(f.strip() for f in raw.split(","))
    if not formats or any(f not in _FORMATS for f in formats):
        return None
    return formats


def _render_to_stdout(
    formats: tuple[str, ...], store: ResumeStore, *, json_requested: bool
) -> int:
    if json_requested or len(formats) != 1 or formats[0] == "pdf":
        print(
            "cv-forge: -o - requires exactly one non-pdf format and no --json",
            file=sys.stderr,
        )
        return 2
    sys.stdout.write(_FORMATS[formats[0]].renderer(store))
    return 0


def _render_format(fmt: str, store: ResumeStore, out_dir: Path) -> Path:
    spec = _FORMATS[fmt]
    if spec.compiled:
        return _render_and_compile_pdf(store, out_dir)
    content = spec.renderer(store).encode("utf-8")
    path = out_dir / f"{ASSET_STEM}.{spec.extension}"
    path.write_bytes(content)
    return path


def _render_and_compile_pdf(store: ResumeStore, out_dir: Path) -> Path:
    """Render LaTeX, compile with `latexmk` in a scratch dir, copy the PDF out.

    Compiling outside `out_dir` keeps `latexmk`'s aux files (and any partial
    output from a failed run) from ever landing next to the other formats.
    """
    tex_source = render_latex(store)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tex_path = tmp_path / f"{ASSET_STEM}.tex"
        tex_path.write_text(tex_source, encoding="utf-8")
        result = subprocess.run(
            [
                LATEXMK,
                "-pdf",
                "-interaction=nonstopmode",
                f"-output-directory={tmp_path}",
                str(tex_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"latexmk failed (exit {result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}"
            )
        dest = out_dir / f"{ASSET_STEM}.pdf"
        shutil.copy2(tex_path.with_suffix(".pdf"), dest)
        return dest


def _output_entry(fmt: str, path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "format": fmt,
        "path": str(path),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _print_json_envelope(
    command: str,
    origin: DataOrigin,
    outputs: list[dict[str, object]],
    *,
    status: str = "ok",
    findings: list[dict[str, object]] | None = None,
) -> None:
    envelope = {
        "command": command,
        "status": status,
        "cv_forge_version": CV_FORGE_VERSION,
        "data_origin": _origin_kind(origin),
        "outputs": outputs,
        "findings": findings or [],
    }
    print(json.dumps(envelope))


def _origin_kind(origin: DataOrigin) -> dict[str, object]:
    """`render`'s data-dir ladder (§1.2) only ever resolves a `LocalDir`
    origin -- `serve` (M1.16) is the first command that can see
    `ReleaseAssets`/`BakedSnapshot`, which get their own mapping there."""
    match origin:
        case LocalDir(path=path):
            return {"kind": "local_dir", "path": str(path)}
        case _:
            raise AssertionError(
                f"unexpected origin from render's data-dir ladder: {origin!r}"
            )


def _print_no_data_dir_error() -> None:
    print(
        "cv-forge: no CV data directory found.\n"
        "  render needs resume.yaml; nothing resolved -- --data-dir not given, "
        "CV_DATA_DIR not set.\n"
        "  To fix:  cv-forge render -f html --data-dir /path/to/cv/cv-data\n"
        "    or:    export CV_DATA_DIR=/path/to/cv/cv-data\n"
        "    or:    cv-forge fetch-snapshot -o ./cv-data     "
        "# pulls the latest published data",
        file=sys.stderr,
    )


def _print_missing_latexmk_error() -> None:
    print(
        "cv-forge: cannot produce pdf -- latexmk is not on PATH.\n"
        "  -f pdf renders LaTeX and compiles it with latexmk (TinyTeX + moderncv).\n"
        "  To fix:  curl -sL https://yihui.org/tinytex/install-bin-unix.sh | sh\n"
        "    or:    cv-forge render -f tex          # source only, no compiler needed",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
