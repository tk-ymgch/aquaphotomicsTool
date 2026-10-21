#!/usr/bin/env python3
"""Create a source/build/history/verification release without deleting originals.

Run only after committing the intended source and building/deploying it. This
script reads Git objects but never reads credential stores or calls remote APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PREFIX = "aquaphotomicsTool"
SOURCE_ZIP = f"{PREFIX}-source.zip"
BUILD_ZIP = f"{PREFIX}-build.zip"
BUNDLE = f"{PREFIX}-history.bundle"
VERIFICATION_ZIP = f"{PREFIX}-verification.zip"
MANIFEST = "release-manifest.json"
RESTORE_NOTE = "RESTORE_RELEASE.txt"
EXCLUDED_PARTS = {
    ".git", "node_modules", ".pnpm-store", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".venv", "venv", "python-test-deps",
}
SECRET_NAMES = {
    "id_rsa", "id_ed25519", "id_dsa", "credentials", "credentials.json",
    "credentials.ini", "secrets.json", "secrets.toml", "access.local.json",
    ".npmrc", ".pypirc", ".netrc",
}
SECRET_PARTS = {".aws", ".ssh", ".secrets"}


class ReleaseError(Exception):
    """An actionable error whose message contains no file contents/secrets."""


def git(repo: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-c", "core.quotePath=false", *arguments], cwd=repo,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode:
        # Git stderr can contain configuration/remote details. Do not echo it.
        raise ReleaseError(f"Git operation failed: {arguments[0]} (exit {completed.returncode}).")
    return completed.stdout


def is_excluded(name: str) -> bool:
    parts = PurePosixPath(name).parts
    lowered = [part.casefold() for part in parts]
    return (
        bool(set(lowered) & EXCLUDED_PARTS)
        or bool(lowered and lowered[0] in {"dist", "qa"})
        or any(part.endswith(".tsbuildinfo") or part.endswith(".pyc") for part in lowered)
        or (len(lowered) > 1 and lowered[:2] == [".openai", "local"])
    )


def safe_file(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(part in {"..", "."} for part in parts):
        raise ReleaseError(f"Unsafe archive path: {relative!r}.")
    path = root.joinpath(*parts)
    if path.is_symlink() or not path.is_file():
        raise ReleaseError(f"A required regular file is missing or is a symlink: {relative!r}.")
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ReleaseError(f"A file resolves outside its source root: {relative!r}.")
    return path


def check_name(relative: str) -> None:
    parts = [part.casefold() for part in PurePosixPath(relative).parts]
    name = parts[-1] if parts else ""
    environment_file = name == ".env" or (
        name.startswith(".env.") and not name.endswith((".example", ".sample", ".template"))
    )
    if (environment_file or name in SECRET_NAMES or set(parts) & SECRET_PARTS
            or name.endswith((".pem", ".key", ".p12", ".pfx", ".jks"))):
        raise ReleaseError(f"Secret-file check blocked the release: {relative!r}. No values were logged.")


def clean_head(repo: Path, expected: str | None = None) -> str:
    head = git(repo, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    if expected is not None and head != expected:
        raise ReleaseError("Source HEAD changed during archiving. Partial outputs were preserved.")
    if git(repo, "status", "--porcelain=v1", "--untracked-files=no"):
        raise ReleaseError("Tracked files have uncommitted changes. Commit the intended release first.")
    return head


def history_object_count(repo: Path) -> int:
    return len({line.partition(b" ")[0] for line in git(repo, "rev-list", "--objects", "--all", "HEAD").splitlines()})


def zip_files(destination: Path, root: Path, relative_files: list[str], note: str | None = None) -> int:
    # mode='x' refuses existing files and never truncates them.
    with zipfile.ZipFile(destination, mode="x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative in relative_files:
            path = safe_file(root, relative)
            check_name(relative)
            archive.write(path, arcname=relative)
        if note is not None:
            if RESTORE_NOTE in relative_files:
                raise ReleaseError(f"Generated restoration note collides with tracked {RESTORE_NOTE}.")
            archive.writestr(RESTORE_NOTE, note.encode("utf-8"))
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ReleaseError(f"ZIP integrity verification failed: {destination.name}.")
        return len(archive.infolist())


def describe(path: Path, entries: int, kind: str = "zip_entries") -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest(),
            "entry_count": entries, "entry_count_kind": kind}


def restoration_note(head: str) -> str:
    return f"""Aquaphotomics Workbench — release restoration

Source commit: {head}

1. Verify every artifact's size and SHA-256 against release-manifest.json.
2. To restore only the editable source, extract {SOURCE_ZIP} into a new empty
   directory. Relative paths, including python/, src/, scripts/, docs/, samples/,
   public/ and pnpm-lock.yaml, are preserved. No node_modules or .git is included.
3. To restore Git history instead, run:
     git clone {BUNDLE} aquaphotomicsTool-restored
     cd aquaphotomicsTool-restored
     git checkout {head}
   The bundle includes all refs and the archived HEAD. A detached checkout at the
   specified commit is expected. The standalone source ZIP also includes this note.
4. Read README.md and docs/ before installing the Node.js and pnpm versions from
   package.json. Run pnpm install --frozen-lockfile, then pnpm build.
   Python sources are synced to public/python by the build script.
5. {BUILD_ZIP} contains the already-built dist contents at the ZIP root.
   Extract into an empty deployment directory to inspect the saved build.
   Development sources, builds and Git history are separate artifacts.
6. The optional verification ZIP contains only browser verification JSON and JPG
   screenshots. QA dependencies and temporary Python packages are excluded.

No originals were deleted. No credentials or authentication stores were read.
Known credential-file names are rejected. This fresh source repository was
prepared without authentication credentials; this script does not audit history.
Deployment credentials and unrelated local runtimes are not part of restoration.
"""


def run(destination: Path) -> dict:
    repo = Path(__file__).resolve().parents[1]
    git_root = Path(git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    if git_root != repo:
        raise ReleaseError("The script must belong to the source repository root's scripts directory.")
    destination = destination.expanduser().resolve()
    # Keeping release outputs outside source/dist/qa prevents recursive archives.
    if destination.is_relative_to(repo):
        raise ReleaseError("Choose an output directory outside the source repository (for example ../output/aquaphotomics_v1).")
    names = [SOURCE_ZIP, BUILD_ZIP, BUNDLE, VERIFICATION_ZIP, MANIFEST]
    if destination.exists() and not destination.is_dir():
        raise ReleaseError("The output destination is not a directory.")
    for name in names:
        if (destination / name).exists():
            raise ReleaseError(f"Refusing to overwrite an existing output: {name}.")
    head = clean_head(repo)
    tracked = [value.decode("utf-8", errors="surrogateescape")
               for value in git(repo, "ls-files", "-z").split(b"\0") if value]
    source_files = sorted(name for name in tracked if not is_excluded(name))
    required = ["src/", "python/", "scripts/", "docs/", "samples/", "public/", "pnpm-lock.yaml"]
    for requirement in required:
        if not any(name.startswith(requirement) if requirement.endswith("/") else name == requirement for name in source_files):
            raise ReleaseError(f"Required tracked source is missing: {requirement}.")
    if RESTORE_NOTE in source_files:
        raise ReleaseError(f"Tracked {RESTORE_NOTE} conflicts with the generated restoration note.")
    for relative in source_files:
        check_name(relative)
        safe_file(repo, relative)
    reachable_objects = history_object_count(repo)
    dist = repo / "dist"
    if not (dist / "index.html").is_file():
        raise ReleaseError("dist/index.html is missing. Build the intended release before archiving.")
    build_files = sorted(path.relative_to(dist).as_posix() for path in dist.rglob("*") if path.is_file())
    verification_files: list[str] = []
    qa = repo / "qa"
    if qa.exists():
        verification_files = sorted(path.relative_to(repo).as_posix() for path in qa.rglob("*")
                                    if path.is_file() and not set(part.casefold() for part in path.relative_to(qa).parts) & EXCLUDED_PARTS
                                    and (path.name == "browser-export-verification.json" or path.suffix.casefold() in {".jpg", ".jpeg"}))
    # Validate all included files before creating the first artifact.
    for root, relatives in ((dist, build_files), (repo, verification_files)):
        for relative in relatives:
            check_name(relative)
            safe_file(root, relative)
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = [describe(destination / SOURCE_ZIP, zip_files(destination / SOURCE_ZIP, repo, source_files, restoration_note(head))),
                 describe(destination / BUILD_ZIP, zip_files(destination / BUILD_ZIP, dist, build_files))]
    with (destination / BUNDLE).open("xb") as output:
        created = subprocess.run(["git", "bundle", "create", "-", "--all", "HEAD"], cwd=repo,
                                 stdout=output, stderr=subprocess.PIPE, check=False)
    if created.returncode:
        raise ReleaseError("Could not create the Git bundle. Partial output was preserved.")
    git(repo, "bundle", "verify", str(destination / BUNDLE))
    artifacts.append(describe(destination / BUNDLE, reachable_objects, "reachable_git_objects"))
    if verification_files:
        artifacts.append(describe(destination / VERIFICATION_ZIP, zip_files(destination / VERIFICATION_ZIP, repo, verification_files)))
    clean_head(repo, head)
    manifest = {
        "schema_version": 1, "project": PREFIX,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "source_head": head,
        "source_tracked_files": len(source_files), "build_files": len(build_files),
        "verification_files": verification_files,
        "security_check": {"current_source_files": len(source_files),
                           "methods": ["known credential-file names rejected", "local credential/runtime directories excluded", "archive roots checked"],
                           "scope": "fresh tracked source, build, selected verification files",
                           "history_audit": False,
                           "note": "The fresh repository was prepared without authentication credentials. No credential stores or values are read."},
        "artifacts": artifacts,
        "restoration_note": f"{SOURCE_ZIP}/{RESTORE_NOTE}",
        "manifest_note": "Hashes describe the release artifacts; this manifest does not recursively hash itself.",
        "originals_preserved": True,
    }
    with (destination / MANIFEST).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", required=True, type=Path,
                        help="New/empty release directory outside the source repo; existing output files are never overwritten.")
    args = parser.parse_args()
    try:
        manifest = run(args.dest)
    except (ReleaseError, OSError, zipfile.BadZipFile) as error:
        print(f"Archive failed: {error}", file=sys.stderr)
        print("No local originals were removed. Partial outputs, if any, were preserved.", file=sys.stderr)
        return 1
    print(f"Archived source HEAD: {manifest['source_head']}")
    for artifact in manifest["artifacts"]:
        print(f"{artifact['file']}: {artifact['bytes']} bytes; {artifact['entry_count']} {artifact['entry_count_kind']}; SHA-256 {artifact['sha256']}")
    print(f"Manifest: {args.dest.resolve() / MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
