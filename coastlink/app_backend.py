"""What the CoastLink app shows, read from the existing build, logs and settings (no game process is started here).

Pure functions over files, so they are tested without a game (test_app_backend.py); coastlink/sidecar.py serves them to the
window. GPL-3.0-or-later.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import stat
import time
import zipfile

import engine

STAMP = re.compile(r"(\d{8}_\d{6})")


def read_text(path: Path, limit: int | None = None) -> str:
    """A log as text; with limit, only its last `limit` bytes (logs grow to megabytes)."""
    try:
        with open(path, "rb") as stream:
            if limit:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - limit))
            return stream.read().decode("utf-8", "replace")
    except OSError:
        return ""


def version_info(repo: Path) -> dict:
    source = engine.read_json(repo / "SOURCE.json", {}) or {}
    return {"version": source.get("version", "unknown"), "runtime_commit": source.get("runtime_commit", ""),
            "upstream_commit": source.get("upstream_commit", ""), "app_version": os.environ.get("COASTLINK_APP_VERSION", "")}


def memory_info() -> dict:
    """Total and free physical memory in GB (Windows; zeros elsewhere)."""
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong),
                    ("page_total", ctypes.c_ulonglong), ("page_free", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong),
                    ("virtual_free", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError
    except (AttributeError, OSError):
        return {"total_gb": 0.0, "free_gb": 0.0, "commit_free_gb": 0.0}
    gb = 1024 ** 3
    return {"total_gb": round(status.total / gb, 1), "free_gb": round(status.free / gb, 1), "commit_free_gb": round(status.page_free / gb, 1)}


def logs_dir(build: Path) -> Path:
    return build / "logs"


def newest(build: Path, pattern: str) -> Path | None:
    files = sorted(logs_dir(build).glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def companion_evidence(state_file: str | Path) -> Path | None:
    """Find only the same launch's adjacent evidence, never an unrelated newest session."""
    path = Path(state_file)
    match = re.fullmatch(r"coastlink_state_(.+)\.hash\.txt", path.name)
    if not match:
        return None
    stamp = match[1]
    for name in ("coastlink_evidence_" + stamp + ".log", "coastlink_runtime_" + stamp + ".txt"):
        candidate = path.with_name(name)
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


# ---------------------------------------------------------------- shaders (the game's own preparation, from its log)
PREP_DONE = re.compile(r"nvn_vk_prep: (?:report \(finished\)|FINISHED)[^:]*: (\d+) of (\d+) containers read")
PREP_PROGRESS = re.compile(r"nvn_vk_prep: (?:start|progress): (\d+) of (\d+) containers read")


def shader_status(build: Path) -> dict:
    """Shader preparation as the newest game log that reached it reports it: done when every container was read."""
    invalidated = engine.read_json(build / "config" / "coastlink_shader_cache.json", {}) or {}
    cleared_at = invalidated.get("cleared_at", 0) if isinstance(invalidated, dict) else 0
    cleared_at = cleared_at if isinstance(cleared_at, (int, float)) else 0
    for log in sorted(logs_dir(build).glob("coastlink_game_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:6]:
        if log.stat().st_mtime <= cleared_at:
            continue
        text = read_text(log)
        done = PREP_DONE.findall(text)
        if done:
            read, total = map(int, done[-1])
            return {"done": read >= total > 0, "read": read, "total": total, "log": log.name}
        progress = PREP_PROGRESS.findall(text)
        if progress:
            read, total = map(int, progress[-1])
            return {"done": False, "read": read, "total": total, "log": log.name}
    return {"done": False, "read": 0, "total": 0, "log": None}


def shader_cache_paths(build: Path) -> list[Path]:
    """The game's shader/pipeline caches (made again on the next start; never game data)."""
    cache = build / "cache"
    return [cache / name for name in ("vk", "vk_containers", "vk_containers2", "shaders")
            if os.path.lexists(cache / name)] if cache.is_dir() else []


def clear_shader_cache(build: Path) -> int:
    build = Path(os.path.abspath(build))
    cache = build / "cache"
    candidates = shader_cache_paths(build)
    def reject_link(path):
        if os.path.lexists(path):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Shader cache cleanup refuses linked files or junction folders: " + str(path))
    reject_link(build)
    reject_link(cache)
    for path in candidates:
        reject_link(path)
        if path.resolve().parent != cache.resolve():
            raise ValueError("Shader cache escaped the selected build folder.")
        if path.is_dir():
            for current, directories, files in os.walk(path, followlinks=False):
                for name in directories + files:
                    reject_link(Path(current) / name)
    # Invalidate old successful logs before removing any cache. Online must wait for a new preparation pass.
    engine.atomic_json(build / "config" / "coastlink_shader_cache.json", {"cleared_at": time.time()})
    for path in candidates:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    return len(candidates)


# ---------------------------------------------------------------- sessions (from the logs every launch writes)
MATCHED = re.compile(r"\[online\] match: matched with (.+?) \(10\.13")
HELLO_OTHER = re.compile(r"rollback messages go to (\d+\.\d+\.\d+\.\d+)")
MATCH_START = re.compile(r"\[rbnet\] match (\d+) \(id ([0-9a-f]+)\) start at frame \d+: local player (\d), input delay (\d+) frames \(round trip ([\d.]+) ms")
REPORT = re.compile(r"\[rbnet\] report \(match (\d+), id ([0-9a-f]+)\): (\d+) frames; delay (\d+); round trip mean ([\d.]+) ms")
DESYNCS = re.compile(r"checksums compared (\d+), DESYNCS (\d+)")
TRANSPORT = re.compile(r"\[rbnet\] transport: (direct UDP|lobby relay).*?; direct RTT (?:last )?(\d+) ms")


def session_summary(game_log: Path) -> dict | None:
    """One launch: opponent, matches, mean round trip, sync verdict; None for an offline launch or one with no match."""
    text = read_text(game_log)
    starts = MATCH_START.findall(text)
    if not starts:
        return None
    opponent = MATCHED.findall(text)
    reports = {}
    for match, mid, frames, delay, rtt in REPORT.findall(text):
        reports[(match, mid)] = (int(frames), float(rtt))          # (each match reports again as it goes: the last one wins)
    desyncs = [(int(c), int(d)) for c, d in DESYNCS.findall(text)]
    compared = desyncs[-1][0] if desyncs else 0
    bad = max((d for _, d in desyncs), default=0)
    rtts = [rtt for _, rtt in reports.values()] or [float(s[4]) for s in starts]
    stamp = STAMP.search(game_log.name)
    return {"log": game_log.name, "stamp": stamp.group(1) if stamp else "", "opponent": opponent[-1] if opponent else "Opponent",
            "matches": len({(s[0], s[1]) for s in starts}), "avg_ping_ms": round(sum(rtts) / len(rtts)) if rtts else None,
            "checksums": compared, "desyncs": bad, "sync": "match" if compared and not bad else "check" if bad else "unknown",
            "mtime": game_log.stat().st_mtime}


def recent_sessions(build: Path, limit: int = 8) -> list[dict]:
    rows = []
    for log in sorted(logs_dir(build).glob("coastlink_game_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]:
        row = session_summary(log)
        if row:
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


RB_FRAME = re.compile(r"RB NET: frame (\d+): (\d+) rollbacks \((\d+) frames again\), (\d+) stalls \((\d+) ms\), round trip (-?\d+) ms, delay (\d+)")


def live_session(build: Path, game_log: Path | None = None, runtime_log: Path | None = None) -> dict:
    """The running (or last) session's numbers, from the end of its logs."""
    game_log = game_log or newest(build, "coastlink_game_*.log")
    if not game_log:
        return {"active": False}
    stamp = STAMP.search(game_log.name)
    runtime_log = runtime_log or (logs_dir(build) / ("coastlink_runtime_" + game_log.name[len("coastlink_game_"):-4] + ".txt"))
    text, runtime = read_text(game_log, 2_000_000), read_text(runtime_log, 400_000)
    starts = MATCH_START.findall(text)
    transport = TRANSPORT.findall(text)
    frames = RB_FRAME.findall(runtime)
    opponent = MATCHED.findall(text)
    out = {"active": True, "log": game_log.name, "stamp": stamp.group(1) if stamp else "", "matches": len(starts),
           "opponent": opponent[-1] if opponent else None, "route": None, "ping_ms": None, "input_delay": None,
           "local_player": None, "rollbacks": 0, "stalls": 0, "stall_ms": 0, "frame": 0, "desyncs": 0}
    if transport:
        route, rtt = transport[-1]
        out["route"] = "direct" if route == "direct UDP" else "relay"
        out["ping_ms"] = int(rtt)
    if starts:
        out["local_player"] = int(starts[-1][2])
        out["input_delay"] = int(starts[-1][3])
        out["ping_ms"] = out["ping_ms"] or round(float(starts[-1][4]))
    if frames:
        f = frames[-1]
        out.update(frame=int(f[0]), rollbacks=int(f[1]), stalls=int(f[3]), stall_ms=int(f[4]), input_delay=int(f[6]))
        if int(f[5]) > 0:
            out["ping_ms"] = int(f[5])
    desyncs = DESYNCS.findall(text)
    if desyncs:
        out["desyncs"] = max(int(d) for _, d in desyncs)
    return out


def bundle_logs(build: Path, destination: Path, sessions: int = 2) -> Path:
    """The newest sessions' logs in one zip (no game files)."""
    logs = logs_dir(build)
    stamps = []
    for log in sorted(logs.glob("coastlink_game_*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        m = STAMP.search(log.name)
        if m and m.group(1) not in stamps:
            stamps.append(m.group(1))
        if len(stamps) >= sessions:
            break
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in logs.iterdir():
            if path.is_file() and (any(s in path.name for s in stamps) or path.name == "coastlink_last_session.json"):
                archive.write(path, path.name)
        freeze = build / "work" / "ssbu_native_rb_freeze.txt"
        if freeze.is_file():
            archive.writestr("newest-part-of-ssbu_native_rb_freeze.txt", read_text(freeze, 2_000_000))
    return destination


# ---------------------------------------------------------------- build progress (was LiveCounter.ps1)
def build_progress(build: Path) -> dict:
    work = build / "work"

    def count(folder: str, recursive: bool = False) -> int:
        base = work / folder
        return sum(1 for _ in (base.rglob("*.obj") if recursive else base.glob("*.obj"))) if base.is_dir() else 0

    main, support, fighters = count("obj_r1"), count("obj_r1_data", True), count("obj_nro_eh_o2r1", True)
    names = [row.get("name") for row in engine.read_json(work / "ro_study" / "nro_map.json", []) or []
             if isinstance(row, dict) and re.fullmatch(r"[A-Za-z0-9_]+", str(row.get("name", "")))]
    complete = sum(1 for n in names if (work / "nro_bin_eh_o2r1" / (n + ".dll")).is_file() and (work / "nro_bin_eh_o2r1" / (n + ".dll")).stat().st_size > 0)
    state = engine.read_json(build / "state.json", {}) or {}
    done = state.get("done", {}) if isinstance(state.get("done"), dict) else {}
    stage, step = "Main game", 8
    if done.get("compile"):
        stage, step = "Fighter modules", 9
    if done.get("nro"):
        stage, step = "Linking", 10
    if done.get("link"):
        stage, step = "Final checks", 11
    finished = bool(done.get("check"))
    main_total = 1161                                              # (the rollback build's main-game objects, 13.0.4)
    return {"main": main, "main_total": main_total, "support": support, "fighter_files": fighters,
            "modules_done": complete, "modules_total": len(names), "stage": "Build finished" if finished else stage,
            "step": 11 if finished else step, "steps": 11, "finished": finished, "in_progress": engine.build_in_progress(build)}


def folder_size_gb(path: Path) -> float:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return round(total / 1024 ** 3, 1)


# ---------------------------------------------------------------- before you play
def checklist(repo: Path, build: Path, devices: list[dict] | None = None) -> list[dict]:
    status = engine.status(repo, build)
    shaders = shader_status(build)
    memory = memory_info()
    rows = [{"id": "build", "label": "Rollback build", "ok": status["ready"], "level": "ok" if status["ready"] else "bad",
             "detail": "Complete" if status["ready"] else ("Building" if status["build_in_progress"] else "Not finished")}]
    rows.append({"id": "shaders", "label": "Shaders", "ok": shaders["done"], "level": "ok" if shaders["done"] else "warn",
                 "detail": f"{shaders['read']} / {shaders['total']}" if shaders["total"] else "Prepared on first launch"})
    if devices is not None:
        pad = next((d for d in devices if d.get("player") == 1), None)
        rows.append({"id": "pad", "label": "Player 1 controller", "ok": bool(pad), "level": "ok" if pad else "warn",
                     "detail": pad["name"] if pad else "None found (keyboard works)"})
    low = memory["total_gb"] and (memory["total_gb"] < 16.5 or memory["free_gb"] < 6)
    rows.append({"id": "memory", "label": "Memory", "ok": not low, "level": "warn" if low else "ok",
                 "detail": f"{memory['total_gb']:.1f} GB · " + ("close apps" if low else "OK")})
    return rows
