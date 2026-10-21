#!/usr/bin/env python3
"""Create a source/build/history/verification release without deleting originals.

Run only after committing the intended source and building/deploying it. This
script reads Git objects but never reads credential stores or calls remote APIs.
"""

from __future__ import annotations

import argparse
import base64
import binascii
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
        or bool(lowered and lowered[0] in {"dist", ".client-build", "qa"})
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


def read_manifest(root: Path, relative: str) -> dict:
    try:
        value = json.loads(safe_file(root, relative).read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        raise ReleaseError(f"Invalid hosting manifest: {relative}.") from error
    if not isinstance(value, dict) or not isinstance(value.get("project_id"), str) or not value["project_id"]:
        raise ReleaseError(f"Hosting manifest has no valid project_id: {relative}.")
    return value


def inspect_build(repo: Path, dist: Path) -> dict:
    """Recognize static releases or the authenticated, self-contained Worker."""
    source = read_manifest(repo, ".openai/hosting.json")
    if "static" in source:
        if not source["static"]:
            raise ReleaseError("A static hosting key must be configured, or removed for a Worker release.")
        safe_file(dist, "index.html")
        return {"mode": "static", "project_id": source["project_id"], "required_entries": ["index.html"]}

    packaged = read_manifest(dist, ".openai/hosting.json")
    if packaged["project_id"] != source["project_id"]:
        raise ReleaseError("Source and packaged hosting manifests have different project_id values.")
    if "static" in packaged:
        raise ReleaseError("A Worker release must not contain a static hosting setting.")
    expected = {"server/index.js", ".openai/hosting.json"}
    actual = {path.relative_to(dist).as_posix() for path in dist.rglob("*") if path.is_file()}
    if actual != expected or any((dist / name).exists() for name in ("static", "assets", "index.html")):
        raise ReleaseError("Worker dist must contain only server/index.js and .openai/hosting.json; public static outputs are not allowed.")
    try:
        module = safe_file(dist, "server/index.js").read_text(encoding="utf-8")
        marker = "\nconst assets = "
        ending = ";\nexport default createPasswordGate(assets);"
        start, finish = module.rfind(marker), module.rfind(ending)
        if start < 0 or finish <= start or module[finish + len(ending):].strip():
            raise ReleaseError("Worker must be the generated ESM entry with embedded assets and the password gate export.")
        assets = json.loads(module[start + len(marker):finish])
        if not isinstance(assets, dict) or "/index.html" not in assets:
            raise ReleaseError("Worker has no embedded application index.html.")
        embedded_bytes = 0
        for route, asset in assets.items():
            if (not isinstance(route, str) or not route.startswith("/") or "\\" in route
                    or ".." in PurePosixPath(route).parts or not isinstance(asset, dict)
                    or not isinstance(asset.get("type"), str) or not isinstance(asset.get("base64"), str)):
                raise ReleaseError("Worker contains an invalid embedded resource record.")
            embedded_bytes += len(base64.b64decode(asset["base64"], validate=True))
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise ReleaseError("Worker embedded resource map is not valid UTF-8/JSON/base64.") from error
    return {"mode": "worker", "project_id": source["project_id"],
            "required_entries": sorted(expected), "static_setting": False,
            "embedded_asset_count": len(assets), "embedded_asset_bytes": embedded_bytes,
            "embedded_routes": sorted(assets),
            "required_secret_names": ["SITE_PASSWORD_HASH", "SESSION_SIGNING_KEY"]}


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


def restoration_note(head: str, hosting: dict) -> str:
    if hosting["mode"] == "worker":
        deployment = f"""5. {BUILD_ZIP} contains the self-contained Worker ESM server/index.js and
   .openai/hosting.json at the ZIP root. All application resources are embedded
   inside the Worker. Deploy as a Worker, keeping the matching project_id and
   leaving the static hosting setting absent. Do not publish dist or .client-build
   through an ordinary static host: that would bypass the password gate.
6. Before restoring public access, configure SITE_PASSWORD_HASH and
   SESSION_SIGNING_KEY through the hosting platform's secret environment settings.
   No secret values or plaintext password are saved in these archives. Follow
   README.md for the required secret formats. Missing/invalid secret configuration
   intentionally returns HTTP 503 (fail closed); never add a public static fallback.
   After deployment, verify unauthenticated requests cannot obtain HTML, JavaScript,
   Python or wheel resources, and verify the login/logout flow.
"""
    else:
        deployment = f"""5. {BUILD_ZIP} contains a static build with index.html at the ZIP root.
   This recorded static mode does not provide the Worker's password enforcement.
   Consult the archived hosting manifest and project documentation before deployment;
   do not use static hosting to restore a password-protected Worker release.
"""
    return f"""Aquaphotomics Workbench — release restoration

Source commit: {head}
Hosting mode: {hosting['mode']}
Hosting project_id: {hosting['project_id']}

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
   pnpm dev and pnpm preview are frontend-only local development previews WITHOUT
   password authentication. Do not expose these development servers publicly.
{deployment}
The optional verification ZIP contains only browser verification JSON and JPG
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
    hosting = inspect_build(repo, dist)
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
    artifacts = [describe(destination / SOURCE_ZIP, zip_files(destination / SOURCE_ZIP, repo, source_files, restoration_note(head, hosting))),
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
        "schema_version": 2, "project": PREFIX,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "source_head": head,
        "source_tracked_files": len(source_files), "build_files": len(build_files),
        "hosting": hosting,
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
