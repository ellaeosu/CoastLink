"""Install a CoastLink update archive (from the release feed or a file), keep backups, roll back.

The archive holds CoastLink's own files only, listed with their SHA-256 in coastlink/UPDATE.sha256.json (the format the
0.4/0.5 updater used). Every name is checked against an allowlist of CoastLink's code locations and every file against its
checksum before anything is written; replaced files go to build/coastlink_runtime_backups/launcher-<time>/ first. Game data,
compiled libraries, tools, settings, shader caches and saves are never in an update and are never touched. CoastLink.exe
cannot replace itself while it runs: it is written as CoastLink.exe.new and the app swaps it on restart.
GPL-3.0-or-later.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import urllib.parse
import zipfile

import engine

MANIFEST = "coastlink/UPDATE.sha256.json"
MAX_FILE, MAX_TOTAL, MAX_FILES = 64 * 1024 * 1024, 160 * 1024 * 1024, 2000
TOP_FILES = {"CoastLink.exe", "WebView2Loader.dll", "SOURCE.json", "START HERE.txt", "README.md", "LICENSE"}
PREFIXES = ("coastlink/", "launcher/", "scripts/")
REFUSED_PARTS = {"build", "deps", "config", "saves"}
REFUSED_SUFFIXES = engine.GAME_EXTENSIONS | {".keys", ".sav", ".save", ".elf", ".arc"}
CONFIG_NAME = "config/update.json"
DEFAULT_CONFIG = {"repo": "", "feed": "", "check_on_launch": True}
BUNDLED_CONFIG = "launcher/update_source.json"
REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³"
}


class UpdateError(ValueError):
    pass


# ---------------------------------------------------------------- the release feed setting
def _raw_config(repo: Path) -> dict:
    data = engine.read_json(repo / CONFIG_NAME, {}) or {}
    if not isinstance(data, dict):
        data = {}
    config = dict(DEFAULT_CONFIG)
    config.update({k: data[k] for k in DEFAULT_CONFIG if k in data})
    # A public release ships its default separately from user settings. Updates
    # can change that default while custom feeds and repositories stay intact.
    if not config["repo"] and not config["feed"]:
        bundled = engine.read_json(repo / BUNDLED_CONFIG, {}) or {}
        default_repo = bundled.get("repo") if isinstance(bundled, dict) else None
        if isinstance(default_repo, str) and REPO_NAME.fullmatch(default_repo):
            config["repo"] = default_repo
    return config


def load_config(repo: Path) -> dict:
    config = _raw_config(repo)
    if not config["feed"] and isinstance(config["repo"], str) and REPO_NAME.fullmatch(config["repo"]):
        config["feed"] = f"https://github.com/{config['repo']}/releases/latest/download/coastlink-release.json"
    return config


def save_config(repo: Path, changes: dict) -> dict:
    # Store only an explicit feed. load_config() derives a URL for display; saving
    # that derived URL would pin the previous repository after the user changes it.
    config = _raw_config(repo)
    if "repo" in changes and "feed" not in changes and str(changes["repo"]).strip() != config["repo"]:
        config["feed"] = ""
    for key in DEFAULT_CONFIG:
        if key in changes:
            config[key] = bool(changes[key]) if key == "check_on_launch" else str(changes[key]).strip()
    if config["repo"] and not REPO_NAME.fullmatch(config["repo"]):
        raise UpdateError("The release repository must be owner/name on GitHub.")
    parsed = urllib.parse.urlsplit(config["feed"])
    if config["feed"] and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment):
        raise UpdateError("The update feed must be an https:// address.")
    engine.atomic_json(repo / CONFIG_NAME, config)
    return load_config(repo)


# ---------------------------------------------------------------- the archive
def canonical(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 240 or "\\" in name or name.startswith("/") or ":" in name:
        raise UpdateError("Unsafe path in the update: " + repr(name))
    if name.startswith("CoastLink/"):
        name = name[len("CoastLink/"):]
    parts = name.split("/")
    if any(p in ("", ".", "..") or p.endswith((".", " ")) or any(ord(c) < 32 for c in p)
           or p.split(".", 1)[0].upper() in RESERVED_NAMES for p in parts):
        raise UpdateError("Unsafe path in the update: " + name)
    if parts[0].lower() in REFUSED_PARTS or PurePosixPath(name).suffix.lower() in REFUSED_SUFFIXES:
        raise UpdateError("This update tries to change game data or settings: " + name)
    if name != MANIFEST and name not in TOP_FILES and not name.startswith(PREFIXES):
        raise UpdateError("This update contains a file outside CoastLink's own code: " + name)
    return name


def read_archive(path: Path, expected_sha256: str | None = None) -> tuple[dict, dict[str, bytes]]:
    if Path(path).stat().st_size > MAX_TOTAL:
        raise UpdateError("The update archive is too large.")
    data = Path(path).read_bytes()
    if len(data) > MAX_TOTAL:
        raise UpdateError("The update archive is too large.")
    if expected_sha256 and hashlib.sha256(data).hexdigest() != expected_sha256.lower():
        raise UpdateError("The update file does not match its SHA-256. Nothing was installed.")
    entries: dict[str, bytes] = {}
    total = 0
    try:
        archive_file = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise UpdateError("The selected file is not a complete CoastLink update ZIP.") from error
    with archive_file as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES:
            raise UpdateError("Too many files in the update.")
        for info in infos:
            if info.is_dir():
                continue
            name = canonical(info.filename)
            if name.lower() in (n.lower() for n in entries):
                raise UpdateError("Duplicate file in the update: " + name)
            total += info.file_size
            if info.file_size > MAX_FILE or total > MAX_TOTAL:
                raise UpdateError("The update expands beyond its allowed size.")
            entries[name] = archive.read(info)
    if MANIFEST not in entries:
        raise UpdateError("The update's checksum list is missing.")
    try:
        manifest = json.loads(entries.pop(MANIFEST).decode("utf-8-sig"))
    except (ValueError, UnicodeError) as error:
        raise UpdateError("The update's checksum list is invalid.") from error
    if not isinstance(manifest, dict):
        raise UpdateError("The update's checksum list is invalid.")
    if manifest.get("product") != "CoastLink" or manifest.get("upstream_commit") != engine.UPSTREAM_COMMIT:
        raise UpdateError("This update is not for this CoastLink (different product or game source version).")
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", version):
        raise UpdateError("The update has no valid version.")
    hashes = manifest.get("files")
    if not isinstance(hashes, dict) or not hashes or len(hashes) != len(entries) or set(map(canonical, hashes)) != set(entries):
        raise UpdateError("The update's files do not match its checksum list.")
    for name, digest in hashes.items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest) or \
                hashlib.sha256(entries[canonical(name)]).hexdigest() != digest.lower():
            raise UpdateError("Checksum failed for " + name + ". Nothing was installed.")
    return manifest, entries


# ---------------------------------------------------------------- install / roll back
def backups_root(repo: Path) -> Path:
    return engine.build_path(repo) / "coastlink_runtime_backups"


def _target(repo: Path, name: str, *, stage_exe=True) -> Path:
    root = repo.resolve()
    if name == "CoastLink.exe" and stage_exe:
        name = "CoastLink.exe.new"               # the running app swaps it in on restart
    candidate = root / name
    # Reject directory junctions and file links before reading backups as well
    # as before writing; an allowed-looking code path must not alias saves/keys.
    for part in (candidate, *candidate.parents):
        if part == root:
            break
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise UpdateError("An update path uses a link or junction: " + name)
    path = candidate.resolve()
    if root not in path.parents:
        raise UpdateError("An update path escaped the CoastLink folder: " + name)
    return path


def _write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def apply_update(repo: Path, archive: Path, expected_sha256: str | None = None) -> dict:
    repo = Path(repo).resolve()
    manifest, entries = read_archive(archive, expected_sha256)
    # Resolve every destination before the first backup or write. A rejected
    # later path must never leave an earlier file partially updated.
    originals = {name: _target(repo, name, stage_exe=False) for name in entries}
    for name in entries:
        _target(repo, name)
    changed = {name: data for name, data in entries.items()
               if name == "CoastLink.exe" or not originals[name].is_file() or originals[name].read_bytes() != data}
    if not changed:
        return {"version": manifest["version"], "changed": 0, "backup": None, "restart_app": False, "restart_backend": False}
    if shutil.disk_usage(repo).free < sum(map(len, changed.values())) * 3 + 64 * 1024 * 1024:
        raise UpdateError("Not enough free disk space for the update and its backup.")
    backup = backups_root(repo) / ("launcher-" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    record = {"version_from": engine.read_json(repo / "SOURCE.json", {}).get("version"), "version_to": manifest["version"], "files": {}}
    for name in changed:                                   # every backup first, then every write
        current = originals[name]
        record["files"][name] = current.is_file()
        if current.is_file():
            (backup / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current, backup / name)
    backup.mkdir(parents=True, exist_ok=True)
    engine.atomic_json(backup / "update.json", record)
    written = []
    try:
        for name, data in changed.items():
            _write(_target(repo, name), data)
            written.append(name)
    except (OSError, UpdateError) as error:
        try:
            roll_back(repo, backup.name)
        except (OSError, UpdateError) as restore_error:
            raise UpdateError("The update stopped and could not restore every file. Its backup was kept at " + str(backup) + ". " + str(restore_error)) from error
        raise UpdateError("The update could not replace its files (close the game and retry); everything was restored. " + str(error)) from error
    return {"version": manifest["version"], "changed": len(changed), "backup": backup.name,
            "restart_app": "CoastLink.exe" in changed, "restart_backend": any(n.startswith("coastlink/") for n in changed)}


def list_backups(repo: Path) -> list[dict]:
    root = backups_root(repo)
    rows = []
    for folder in sorted(root.glob("launcher-*"), reverse=True) if root.is_dir() else []:
        record = engine.read_json(folder / "update.json", {}) or {}
        rows.append({"backup": folder.name, "from": record.get("version_from"), "to": record.get("version_to"),
                     "files": len(record.get("files", {}))})
    return rows


def roll_back(repo: Path, backup_name: str | None = None) -> dict:
    repo = Path(repo)
    rows = list_backups(repo)
    if not rows:
        raise UpdateError("There is no update to roll back.")
    name = backup_name or rows[0]["backup"]
    if not re.fullmatch(r"launcher-[0-9_]+", name):
        raise UpdateError("Unknown backup.")
    folder = backups_root(repo) / name
    root = backups_root(repo).resolve()
    if folder.is_symlink() or getattr(folder, "is_junction", lambda: False)() or root not in folder.resolve().parents:
        raise UpdateError("The update backup path is unsafe.")
    record = engine.read_json(folder / "update.json", {}) or {}
    if not isinstance(record, dict) or not isinstance(record.get("files"), dict) or not record["files"]:
        raise UpdateError("The update backup record is missing or invalid.")
    for file, existed in record["files"].items():
        canonical(file)
        _target(repo, file)
        if not isinstance(existed, bool):
            raise UpdateError("The update backup record is invalid.")
        saved = folder / file
        if existed and (not saved.is_file() or folder.resolve() not in saved.resolve().parents):
            raise UpdateError("A file is missing from the update backup: " + file)
    for file, existed in record.get("files", {}).items():
        file = canonical(file)
        if existed:
            _write(_target(repo, file), (folder / file).read_bytes())
        else:
            _target(repo, file).unlink(missing_ok=True)
    shutil.rmtree(folder, ignore_errors=True)
    return {"restored": record.get("version_from"), "files": len(record.get("files", {})),
            "restart_app": "CoastLink.exe" in record.get("files", {}), "restart_backend": True}
