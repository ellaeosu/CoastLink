"""Import a Smash Ultimate save that a player has on their PC (a JKSV backup: a zip or a folder), so friends can all play
with the same save (for example the same 100% file). CoastLink never downloads or ships a save: the player picks the file.

The game keeps its save in build/saves/save (the save file system's root: save_data/system_data.bin, save_data/spirits ...;
SSBU_USERDATA, run_rollback.py). A JKSV backup holds the same root in a folder (usually named "100"). The current save is
copied to build/saves/backups/save-<time>/ first and can be put back. BCAT data (Spirit Board events) is not used by this
runtime and is skipped. GPL-3.0-or-later.
"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile

MARKER = "save_data/system_data.bin"
MAX_TOTAL, MAX_FILES = 256 * 1024 * 1024, 4000


class SaveError(ValueError):
    pass


def save_dir(build: Path) -> Path:
    return Path(build) / "saves" / "save"


def backups_dir(build: Path) -> Path:
    return Path(build) / "saves" / "backups"


def _root_in(names: list[str]) -> str:
    """The folder inside the backup that holds save_data/system_data.bin ("" = the top level)."""
    roots = sorted({n[: -len(MARKER)] for n in names if n.lower().endswith(MARKER) and (n == MARKER or n[-len(MARKER) - 1] == "/")},
                   key=len)
    if not roots:
        raise SaveError("This is not a Smash Ultimate save backup: it has no save_data/system_data.bin.")
    bcat = [r for r in roots if "bcat" in r.lower()]
    return ([r for r in roots if r not in bcat] or roots)[0]


def _safe(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return bool(parts) and not rel.startswith("/") and ":" not in rel and "\\" not in rel and \
        all(p not in ("", ".", "..") and not p.endswith((" ", ".")) for p in parts)


def _stage_zip(source: Path, into: Path) -> int:
    with zipfile.ZipFile(source) as archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_TOTAL:
            raise SaveError("This backup is far larger than a Smash save.")
        root = _root_in([i.filename.replace("\\", "/") for i in infos])
        count = 0
        for info in infos:
            name = info.filename.replace("\\", "/")
            if not name.startswith(root):
                continue
            rel = name[len(root):]
            if not _safe(rel):
                raise SaveError("Unsafe file name in the backup: " + rel)
            target = into / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
        return count


def _stage_folder(source: Path, into: Path) -> int:
    files = [p for p in source.rglob("*") if p.is_file()]
    if len(files) > MAX_FILES or sum(p.stat().st_size for p in files) > MAX_TOTAL:
        raise SaveError("This folder is far larger than a Smash save.")
    root = _root_in([p.relative_to(source).as_posix() for p in files])
    base = source / root if root else source
    count = 0
    for path in files:
        if base not in path.parents:
            continue
        target = into / path.relative_to(base)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def import_save(build: Path, source: Path) -> dict:
    build, source = Path(build), Path(source)
    if not source.exists():
        raise SaveError("That file is not there any more. Choose it again.")
    current = save_dir(build)
    current.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="save-import-", dir=current.parent))
    try:
        if source.is_dir():
            count = _stage_folder(source, staging)
        elif zipfile.is_zipfile(source):
            count = _stage_zip(source, staging)
        elif source.name.lower() == "system_data.bin":          # the progress file alone: the rest of the save stays
            if not 1024 <= source.stat().st_size <= 64 * 1024 * 1024:
                raise SaveError("That system_data.bin does not look like a Smash save.")
            if current.exists():
                shutil.copytree(current, staging, dirs_exist_ok=True)
            (staging / "save_data").mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staging / MARKER)
            count = 1
        else:
            raise SaveError("Choose the save backup's .zip, its folder, or its save_data/system_data.bin.")
        backup = None
        if current.exists():
            backup = backups_dir(build) / ("save-" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(current, backup)
            shutil.rmtree(current)
        os.replace(staging, current)
        return {"files": count, "backup": backup.name if backup else None, "path": str(current)}
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def list_backups(build: Path) -> list[dict]:
    root = backups_dir(build)
    rows = []
    for folder in sorted(root.glob("save-*"), reverse=True) if root.is_dir() else []:
        size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
        rows.append({"name": folder.name, "mb": round(size / 1048576, 1)})
    return rows


def restore_backup(build: Path, name: str) -> dict:
    folder = backups_dir(build) / name
    if not name.startswith("save-") or "/" in name or "\\" in name or not (folder / MARKER).is_file():
        raise SaveError("Unknown save backup.")
    return import_save(build, folder)
