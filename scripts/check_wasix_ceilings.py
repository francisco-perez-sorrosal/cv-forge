#!/usr/bin/env python3
"""Check that this project's native-extension dependency pins are exactly
synced with the Wasmer Edge (WASIX) cross-install index.

Wasmer Edge builds this project by cross-installing wheels from
``python-registry.wasix.org`` for the ``cp313`` / ``wasix_wasm32`` target.
Any native-extension package this project depends on can only ever be
upgraded as far as that index allows — a `pyproject.toml` pin that drifts
above the WASIX ceiling resolves fine on a developer's machine (which
installs from PyPI) and then breaks the Wasmer build with an opaque
failure. See ``.ai-state/SYSTEM_DEPLOYMENT.md`` (Risk Assessment /
Failure Analysis, "pydantic pin drifted") for the incident this guards
against.

This script reads the *resolved* linux-64 versions of the tracked
packages out of ``pixi.lock`` and compares each one against the highest
``cp313`` wheel currently published on the WASIX index. Any mismatch —
in either direction — is a signal that ``pyproject.toml``'s pin needs a
maintainer's attention:

* resolved > WASIX max  -- the pin allows a version WASIX cannot build.
  The ceiling in ``pyproject.toml`` MUST be tightened (or the lockfile
  re-solved) before the next Wasmer deploy.
* resolved < WASIX max  -- WASIX has caught up and now publishes a newer
  compatible build than the pin allows. The ceiling COULD be relaxed.
* resolved == WASIX max -- synced. Nothing to do.

Usage:
    python scripts/check_wasix_ceilings.py [--lock-file pixi.lock] [--json]

Exit codes:
    0  All tracked packages are exactly synced with the WASIX ceiling.
    1  At least one package's resolved version exceeds the WASIX ceiling
       (critical -- the next Wasmer build is expected to fail).
    2  No package exceeds the ceiling, but at least one pin could be
       relaxed (informational -- WASIX now supports a newer version).
    3  Could not complete the check (network error, package missing from
       the lockfile or the WASIX index, or a malformed lockfile).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote

try:
    import yaml
except ImportError:  # pragma: no cover - guarded at runtime, not exercised in CI
    yaml = None

WASIX_INDEX_URL = "https://python-registry.wasix.org/simple/{name}/"
TARGET_PLATFORM = "linux-64"
TARGET_PY_TAG = "cp313"
TARGET_WHEEL_PLATFORM = "wasix_wasm32"
TRACKED_PACKAGES = ("pydantic-core", "cryptography", "cffi")

EXIT_OK = 0
EXIT_CEILING_EXCEEDED = 1
EXIT_CEILING_STALE = 2
EXIT_ERROR = 3


def _parse_version(version: str) -> tuple[int, ...]:
    """Numeric-tuple comparison key; drops any local segment (`+wasix.N`)."""
    base = version.split("+", 1)[0]
    parts: list[int] = []
    for chunk in base.split("."):
        match = re.match(r"\d+", chunk)
        parts.append(int(match.group()) if match else 0)
    return tuple(parts)


def resolved_versions(lock_path: Path, packages: tuple[str, ...]) -> dict[str, str]:
    """Resolved version of each tracked package on TARGET_PLATFORM, per pixi.lock."""
    if yaml is None:
        raise RuntimeError("pyyaml is required to parse pixi.lock (pip install pyyaml)")
    doc = yaml.safe_load(lock_path.read_text())

    try:
        platform_refs = doc["environments"]["default"]["packages"][TARGET_PLATFORM]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f"pixi.lock has no environments.default.packages.{TARGET_PLATFORM}"
        ) from exc

    urls_in_platform = {
        ref["pypi"] for ref in platform_refs if isinstance(ref, dict) and "pypi" in ref
    }

    records_by_url = {
        rec["pypi"]: rec
        for rec in doc.get("packages", [])
        if isinstance(rec, dict) and "pypi" in rec
    }

    found: dict[str, str] = {}
    for url in urls_in_platform:
        rec = records_by_url.get(url)
        if rec and rec.get("name") in packages:
            found[rec["name"]] = rec["version"]
    return found


def wasix_max_version(package: str, timeout: float = 15.0) -> str | None:
    """Highest version with a cp313/wasix_wasm32 wheel on the WASIX index, or None."""
    url = WASIX_INDEX_URL.format(name=package)
    request = urllib.request.Request(
        url, headers={"User-Agent": "check-wasix-ceilings/1"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")

    candidates: list[str] = []
    for href in re.findall(r'href="([^"]+)"', html):
        filename = unquote(href).rsplit("/", 1)[-1].split("#", 1)[0]
        if not filename.endswith(".whl"):
            continue
        stem_parts = filename[: -len(".whl")].split("-")
        if len(stem_parts) != 5:
            continue
        _name, version, py_tag, _abi_tag, wheel_platform = stem_parts
        if py_tag == TARGET_PY_TAG and wheel_platform == TARGET_WHEEL_PLATFORM:
            candidates.append(version)

    if not candidates:
        return None
    return max(candidates, key=_parse_version)


def check(lock_path: Path, packages: tuple[str, ...] = TRACKED_PACKAGES) -> dict:
    """Run the full check; returns a JSON-serializable report dict."""
    findings = []
    resolved = resolved_versions(lock_path, packages)

    for package in packages:
        entry: dict[str, object] = {"package": package}
        local_version = resolved.get(package)
        if local_version is None:
            entry.update(
                status="error", reason="not found in pixi.lock linux-64 packages"
            )
            findings.append(entry)
            continue
        entry["resolved_version"] = local_version

        try:
            wasix_max = wasix_max_version(package)
        except (urllib.error.URLError, TimeoutError) as exc:
            entry.update(status="error", reason=f"WASIX index query failed: {exc}")
            findings.append(entry)
            continue

        if wasix_max is None:
            entry.update(
                status="error",
                reason="no cp313/wasix_wasm32 wheel found on WASIX index",
            )
            findings.append(entry)
            continue
        entry["wasix_max_version"] = wasix_max

        local_key = _parse_version(local_version)
        wasix_key = _parse_version(wasix_max)
        if local_key > wasix_key:
            entry["status"] = "ceiling_exceeded"
        elif local_key < wasix_key:
            entry["status"] = "ceiling_stale"
        else:
            entry["status"] = "ok"
        findings.append(entry)

    statuses = {f["status"] for f in findings}
    if "error" in statuses:
        exit_code = EXIT_ERROR
    elif "ceiling_exceeded" in statuses:
        exit_code = EXIT_CEILING_EXCEEDED
    elif "ceiling_stale" in statuses:
        exit_code = EXIT_CEILING_STALE
    else:
        exit_code = EXIT_OK

    return {"findings": findings, "exit_code": exit_code}


def _render_human(report: dict) -> str:
    lines = []
    for entry in report["findings"]:
        status = entry["status"]
        package = entry["package"]
        if status == "error":
            lines.append(f"[ERROR] {package}: {entry['reason']}")
        elif status == "ok":
            lines.append(
                f"[OK] {package}: resolved={entry['resolved_version']} "
                f"== wasix_max={entry['wasix_max_version']}"
            )
        elif status == "ceiling_exceeded":
            lines.append(
                f"[CEILING EXCEEDED] {package}: resolved={entry['resolved_version']} "
                f"> wasix_max={entry['wasix_max_version']} -- tighten the pyproject.toml pin"
            )
        elif status == "ceiling_stale":
            lines.append(
                f"[CEILING STALE] {package}: resolved={entry['resolved_version']} "
                f"< wasix_max={entry['wasix_max_version']} -- the pin could be relaxed"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "pixi.lock",
        help="Path to pixi.lock (default: repo-root pixi.lock)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )
    args = parser.parse_args(argv)

    try:
        report = check(args.lock_file)
    except (RuntimeError, OSError) as exc:
        if args.json:
            print(
                json.dumps({"findings": [], "exit_code": EXIT_ERROR, "error": str(exc)})
            )
        else:
            print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_render_human(report))

    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
