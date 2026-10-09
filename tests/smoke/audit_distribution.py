"""Audit built archives against a clean tracked snapshot without extracting them."""

from __future__ import annotations

import argparse
import ast
import configparser
from email import message_from_bytes
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import zipfile


def _git(checkout: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True)
    if result.returncode:
        raise ValueError("git_snapshot_unavailable")
    return result.stdout


def _tracked_sources(checkout: Path) -> tuple[dict[str, bytes], str]:
    if subprocess.run(["git", "-C", str(checkout), "diff", "--quiet", "HEAD", "--", "src/python"],
                      capture_output=True).returncode:
        raise ValueError("tracked_checkout_modified")
    if _git(checkout, "ls-files", "--others", "--exclude-standard", "--", "src/python"):
        raise ValueError("untracked_source_files")
    names = _git(checkout, "ls-files", "-z", "--", "src/python").decode().split("\0")
    files = {name.removeprefix("src/python/"): _git(checkout, "show", f"HEAD:{name}")
             for name in names if name}
    return files, _git(checkout, "rev-parse", "HEAD").decode().strip()


def _safe_name(name: str) -> None:
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or any(part in {".", "..", ""} for part in name.rstrip("/").split("/")):
        raise ValueError("unsafe_archive_member")


def _wheel_files(path: Path) -> dict[str, bytes]:
    rows = {}
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            _safe_name(member.filename)
            if member.is_dir():
                continue
            if member.filename in rows:
                raise ValueError("duplicate_archive_member")
            mode = member.external_attr >> 16
            if mode & 0o170000 == 0o120000:
                raise ValueError("unsupported_archive_member")
            rows[member.filename] = archive.read(member)
    return rows


def _sdist_files(path: Path, prefix: str) -> dict[str, bytes]:
    rows = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            _safe_name(member.name)
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("unsupported_archive_member")
            if not member.name.startswith(prefix + "/"):
                raise ValueError("unexpected_sdist_root")
            name = member.name[len(prefix) + 1:]
            if name in rows:
                raise ValueError("duplicate_archive_member")
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError("unreadable_archive_member")
            with handle:
                rows[name] = handle.read()
    return rows


def _version(sources: dict[str, bytes]) -> str:
    tree = ast.parse(sources["videoedit/_version.py"])
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__version__"
                                                for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and value:
                return value
    raise ValueError("package_version_unavailable")


def _runtime_bytes(rows: dict[str, bytes], expected: dict[str, bytes]) -> None:
    for name, data in expected.items():
        if name not in rows:
            raise ValueError("missing_runtime_file")
        if rows[name] != data:
            raise ValueError("runtime_bytes_mismatch")


def audit_distribution(checkout: Path, wheel: Path, sdist: Path) -> dict:
    sources, commit = _tracked_sources(checkout)
    runtime = {name: data for name, data in sources.items() if name.startswith("videoedit/")}
    if not runtime:
        raise ValueError("runtime_snapshot_empty")
    version = _version(sources)
    metadata_dir = f"videoedit-{version}.dist-info/"
    metadata_files = {metadata_dir + name for name in ("METADATA", "WHEEL", "RECORD", "entry_points.txt",
                                                     "top_level.txt", "licenses/LICENSE")}
    wheel_rows = _wheel_files(wheel)
    if set(wheel_rows) - set(runtime) - metadata_files:
        raise ValueError("unexpected_wheel_member")
    _runtime_bytes(wheel_rows, runtime)
    metadata = message_from_bytes(wheel_rows.get(metadata_dir + "METADATA", b""))
    if metadata.get("Name") != "videoedit" or metadata.get("Version") != version:
        raise ValueError("metadata_version_mismatch")
    if not {metadata_dir + name for name in ("WHEEL", "RECORD")} <= set(wheel_rows):
        raise ValueError("missing_wheel_metadata")
    entrypoints = configparser.ConfigParser()
    entrypoints.read_string(wheel_rows.get(metadata_dir + "entry_points.txt", b"").decode())
    if entrypoints.get("console_scripts", "videoedit", fallback="") != "videoedit.cli:main":
        raise ValueError("invalid_console_entrypoint")
    if wheel_rows.get(metadata_dir + "licenses/LICENSE") != sources.get("LICENSE"):
        raise ValueError("license_bytes_mismatch")

    sdist_rows = _sdist_files(sdist, f"videoedit-{version}")
    generated = {"PKG-INFO", "setup.cfg"} | {"videoedit.egg-info/" + name for name in (
        "PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt")}
    if set(sdist_rows) - set(sources) - generated:
        raise ValueError("unexpected_sdist_member")
    _runtime_bytes(sdist_rows, sources)
    source_metadata = message_from_bytes(sdist_rows.get("PKG-INFO", b""))
    if source_metadata.get("Name") != "videoedit" or source_metadata.get("Version") != version:
        raise ValueError("metadata_version_mismatch")
    return {"schema_version": "videoedit.distribution_audit.v1", "status": "ok", "commit": commit,
            "version": version, "runtime_files": len(runtime), "wheel_files": len(wheel_rows),
            "sdist_files": len(sdist_rows), "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "sdist_sha256": hashlib.sha256(sdist.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(audit_distribution(args.checkout, args.wheel, args.sdist), indent=2))
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, tarfile.TarError, configparser.Error, SyntaxError) as error:
        print(f"distribution audit failed: {error}" if isinstance(error, ValueError) else
              f"distribution audit failed: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
