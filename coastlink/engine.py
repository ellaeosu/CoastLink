"""Coastlink's installer and fail-closed rollback launcher.

Game packages and keys stay on the PC that supplies them. This module only wraps
the pinned OpenSmash-Ultimate build; it never claims that installation proves
internet performance. Machine-readable commands: discover and status.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import ntpath
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Iterable

UPSTREAM_COMMIT = "8532593a91f588800f7db84e5b13375e1393c23a"
TITLE_ID = "01006a800016e000"
DEFAULT_SERVER = "opensmash-lobby.duckdns.org:39500"
GAME_EXTENSIONS = {".nsp", ".xci", ".nsz", ".nca", ".xcz"}
MODES = ("offline", "host", "join", "lobby-host", "lobby-join")


class CoastlinkError(Exception):
    pass


def _lock_file(stream, *, unlock=False):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)


class BuildLock:
    """One installer owns a build folder across GUI and CLI processes.

    The file remains in place when unlocked. Unlinking an advisory lock file
    creates races on POSIX because another process can lock a different inode.
    """
    def __init__(self, build: Path):
        self.path = build / "coastlink.install.lock"
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            _lock_file(stream)
        except OSError as error:
            stream.close()
            raise CoastlinkError("This build is already being installed or compiled by another Coastlink window. Wait for it to finish, or stop that installer before resuming here.") from error
        self.stream = stream
        return self

    def __exit__(self, *_):
        try:
            _lock_file(self.stream, unlock=True)
        finally:
            self.stream.close()
            self.stream = None


def build_in_progress(build: Path) -> bool:
    path = build / "coastlink.install.lock"
    try:
        stream = path.open("r+b")
    except FileNotFoundError:
        return False
    except OSError:
        return True                       # conservative when access cannot be checked
    try:
        try:
            _lock_file(stream)
        except OSError:
            return True
        _lock_file(stream, unlock=True)
        return False
    finally:
        stream.close()


def repo_path() -> Path:
    return Path(__file__).resolve().parents[1]


def read_json(path: Path, default=None):
    try:
        return json.loads(io_path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        return default


def build_path(repo: Path, chosen: str | Path | None = None) -> Path:
    if chosen:
        return Path(os.path.expandvars(str(chosen))).expanduser().resolve()
    try:
        stored = (repo / "build_location.txt").read_text(encoding="utf-8-sig").strip().strip('"')
    except OSError:
        stored = ""
    return Path(os.path.expandvars(stored)).expanduser().resolve() if stored else repo / "build"


def verify_source_pin(repo: Path):
    metadata = read_json(repo / "SOURCE.json")
    if not isinstance(metadata, dict):
        raise CoastlinkError("The source version record is missing or unreadable. Extract a fresh Coastlink package before installing or playing.")
    recorded = metadata.get("upstream_commit", metadata.get("commit"))
    if recorded != UPSTREAM_COMMIT:
        raise CoastlinkError("This installer and its source package are different versions. Extract a fresh, matching Coastlink package.")


def windows_long_path(value: str) -> str:
    """Add the Windows extended prefix only when an absolute path needs it.

    Normalise before adding the prefix because the extended Win32 namespace
    deliberately does not resolve slashes, dot segments or UNC paths for us.
    This pure string helper can be tested on any operating system.
    """
    if value.startswith(("\\\\?\\", "\\\\.\\")):
        return value
    canonical = ntpath.normpath(value.replace("/", "\\"))
    if len(canonical.encode("utf-16-le")) // 2 < 260:
        return value
    drive, tail = ntpath.splitdrive(canonical)
    if drive.startswith("\\\\"):
        return "\\\\?\\UNC\\" + canonical[2:]
    if len(drive) == 2 and drive[1] == ":" and tail.startswith("\\"):
        return "\\\\?\\" + canonical
    return value


def io_path(value: str | os.PathLike) -> Path:
    path = Path(os.path.expandvars(os.fspath(value))).expanduser()
    if os.name == "nt":
        return Path(windows_long_path(os.path.abspath(path)))
    return path


def display_path(value: str | os.PathLike) -> str:
    text = os.fspath(value)
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    return text[4:] if text.startswith("\\\\?\\") else text


def _existing_file(value) -> Path | None:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        return None
    path = io_path(value)
    return path.resolve() if path.is_file() else None


def _package_files(root: Path, depth: int = 2) -> Iterable[Path]:
    """Search only a configured library, with a bounded depth and no junctions."""
    root = io_path(root)
    if not root.is_dir():
        return
    for current, dirs, names in os.walk(root, followlinks=False):
        rel_depth = len(Path(current).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if not io_path(Path(current, d)).is_symlink()) if rel_depth < depth else []
        for name in sorted(names):
            path = io_path(Path(current, name))
            if path.suffix.lower() in GAME_EXTENSIONS:
                yield path


def _base_rank(path: Path) -> tuple[int, int, str]:
    name = path.name.lower()
    exact = TITLE_ID in name
    familiar = "smash" in name and "ultimate" in name
    excluded = any(part in name for part in ("[upd]", "[dlc]", "01006a800016e800", "update"))
    if excluded or not (exact or familiar):
        return (-1, 0, name)
    # A plainly identified base takes precedence over a large update container.
    return (2 if exact else 1, path.stat().st_size, name)


def _game_version(path: Path | None) -> str | None:
    match = re.search(r"(?<!\d)(13\.0\.[45])(?!\d)", path.name) if path else None
    return match.group(1) if match else None


def discover(repo: Path, emulator_data: Path | None = None, build_dir=None) -> dict:
    data = emulator_data or Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Ryujinx"
    config = read_json(data / "Config.json", {})
    config = config if isinstance(config, dict) else {}
    libraries = config.get("game_dirs", [])
    libraries = libraries if isinstance(libraries, list) else []
    packages = []
    for folder in libraries:
        if isinstance(folder, str):
            packages.extend(_package_files(Path(os.path.expandvars(folder)).expanduser()))
    candidates = [(rank, path) for path in packages if (rank := _base_rank(path))[0] >= 0]
    base = max(candidates, key=lambda row: row[0])[1] if candidates else None
    title = data / "games" / TITLE_ID
    update_config = read_json(title / "updates.json", {})
    update_config = update_config if isinstance(update_config, dict) else {}
    update = _existing_file(update_config.get("selected"))
    if update is None:
        paths = update_config.get("paths", [])
        for item in paths if isinstance(paths, list) else []:
            if (candidate := _existing_file(item)) and _game_version(candidate):
                update = candidate
                break
    if update is None:
        update = next((path for path in packages if _game_version(path) and "01006a800016e800" in path.name.lower()), None)
    keys = _existing_file(data / "system" / "prod.keys")
    if keys is None:
        keys = _existing_file(Path.home() / ".switch" / "prod.keys")
    # The keys are located by filename only; no key file is opened here.
    dlc_config = read_json(title / "dlc.json", [])
    dlc_files = []
    missing_dlc_files = []
    for entry in dlc_config if isinstance(dlc_config, list) else []:
        if not isinstance(entry, dict):
            continue
        ncas = entry.get("dlc_nca_list", [])
        enabled = not ncas or any(isinstance(nca, dict) and nca.get("is_enabled", True) for nca in ncas)
        if enabled and entry.get("path"):
            if path := _existing_file(entry["path"]):
                dlc_files.append(str(path))
            else:
                missing_dlc_files.append(str(entry["path"]))
    dlc_files = sorted(set(dlc_files))
    parents = {display_path(Path(path).parent) for path in dlc_files}
    notes = []
    if not base:
        notes.append("Choose your base game package; it was not found in the configured Ryujinx libraries.")
    if not update:
        notes.append("Choose the matching Ultimate 13.0.4 or 13.0.5 update package.")
    if not keys:
        notes.append("Choose your prod.keys file; no key values are read or printed by Coastlink.")
    if missing_dlc_files:
        notes.append(f"{len(missing_dlc_files)} configured DLC package(s) are missing. Choose their current folder before installing.")
    return {"base": str(base) if base else None, "update": str(update) if update else None,
            "keys": str(keys) if keys else None, "dlc_files": dlc_files, "missing_dlc_files": missing_dlc_files,
            "dlc_folder": next(iter(parents)) if len(parents) == 1 else None,
            "game_version": _game_version(update), "emulator_data": str(data),
            "build_dir": str(build_path(repo, build_dir)), "notes": notes}


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def check_disk_reserve(build: Path, minimum_gib=4):
    """A resume-safe reserve; upstream separately checks remaining build inputs.

    A fresh rollback build can peak near 34 GiB including tools and its unpacked
    game. Do not charge that full amount again on resume after files exist.
    """
    probe = build
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free / (1024 ** 3)
    if free < minimum_gib:
        raise CoastlinkError(f"Only {free:.1f} GiB is free on the install drive. Keep at least {minimum_gib} GiB free before installing or resuming.")


def set_ini_values(path: Path, changes: dict[str, str]):
    """Update flat runtime settings atomically, keeping comments and other keys."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        text = ""
    pending = {key.lower(): str(value) for key, value in changes.items()}
    output = []
    seen = set()
    for line in text.splitlines():
        key, sep, _ = line.partition("=")
        name = key.strip().lower()
        if sep and name in pending and not name.startswith(("#", ";")):
            if name not in seen:
                output.append(f"{name} = {pending[name]}")
                seen.add(name)
        else:
            output.append(line)
    output.extend(f"{key} = {value}" for key, value in pending.items() if key not in seen)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(output) + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def status(repo: Path, chosen=None) -> dict:
    build = build_path(repo, chosen)
    work = build / "work"
    state = read_json(build / "state.json")
    missing = []
    if not isinstance(state, dict):
        state = {}
        missing.append("build/state.json (missing or unreadable build record)")
    version = state.get("game_version")
    if version not in ("13.0.4", "13.0.5"):
        missing.append("supported game version in the build record")
    for name in ("ssbu_native_rb.exe", "ssbu_game_r1.dll", "SDL3.dll", "ssbu_glslang.dll"):
        if not (work / name).is_file() or (work / name).stat().st_size == 0:
            missing.append("work/" + name)
    rb_modules = work / "nro_bin_eh_o2r1"
    modules = {path.name for path in rb_modules.glob("*.dll") if path.is_file() and path.stat().st_size > 0}
    module_map = read_json(work / "ro_study" / "nro_map.json", [])
    expected = {row["name"] + ".dll" for row in module_map
                if isinstance(row, dict) and isinstance(row.get("name"), str)
                and re.fullmatch(r"[A-Za-z0-9_]+", row["name"])} if isinstance(module_map, list) else set()
    if not modules:
        missing.append("work/nro_bin_eh_o2r1/*.dll (rollback fighter modules)")
    elif "lua2cpp_common.dll" not in modules:
        missing.append("work/nro_bin_eh_o2r1/lua2cpp_common.dll")
    if not expected:
        missing.append("work/ro_study/nro_map.json (expected fighter module list)")
    if expected - modules:
        missing.extend("work/nro_bin_eh_o2r1/" + name for name in sorted(expected - modules))
    if version and not (build / "binaries" / str(version) / "main.elf").is_file():
        missing.append("binaries/" + str(version) + "/main.elf")
    romfs = Path(state.get("dump", {}).get("romfs", "")) if isinstance(state.get("dump"), dict) else Path("")
    if not (romfs / "data.arc").is_file() and not (build / "dump" / "romfs" / "data.arc").is_file():
        missing.append("dump/romfs/data.arc")
    return {"ready": not missing, "missing": missing, "game_version": version,
            "rollback_modules": len(modules), "build_dir": str(build), "source_commit": UPSTREAM_COMMIT,
            "build_in_progress": build_in_progress(build)}


def install_command(repo: Path, *, base: Path, update: Path, keys: Path, dlc_files=(), build_dir=None, jobs=4, dry_run=False, python=None) -> list[str]:
    base, update, keys = map(io_path, (base, update, keys))
    for label, path in (("base game", base), ("update", update), ("prod.keys", keys)):
        if not path.is_file():
            raise CoastlinkError(f"The {label} file was not found. Choose it again.")
    if not 1 <= jobs <= 6:
        raise CoastlinkError("Build jobs must be between 1 and 6; 4 is the conservative default.")
    command = [str(python or sys.executable), "-u", str(repo / "scripts" / "install.py"),
               "--no-gui", "--no-self-update", "--no-shortcuts", "--rollback", "--jobs", str(jobs),
               "--build-dir", str(build_path(repo, build_dir)), "--base", str(base), "--update", str(update), "--keys", str(keys)]
    for path in sorted(set(map(str, map(io_path, dlc_files)))):
        if not Path(path).is_file():
            raise CoastlinkError("A selected DLC package is missing. Choose the DLC folder again.")
        command.extend(["--dlc", path])
    if dry_run:
        command.append("--dry-run")
    return command


def install(repo: Path, args) -> int:
    verify_source_pin(repo)
    with BuildLock(build_path(repo, args.build_dir)):
        return _install_locked(repo, args)


def prime_incremental_stamps(build: Path):
    """Record this pinned installer's inline mode before a fresh compilation.

    Upstream writes its mode stamp only after the whole DLL finishes. An
    interrupted first build otherwise mistakes its partial objects for old,
    non-inlined objects and discards them on every resume. Never label unknown
    pre-existing objects: upstream must decide whether those can be reused.
    install.py uses setup.py's default inlined mode; Coastlink does not offer
    the incompatible --no-inline option.
    """
    for name in ("obj_eh_o1", "obj_r1"):
        directory = build / "work" / name
        stamp = directory / "_inline.txt"
        if stamp.exists() or any(directory.glob("*.obj")):
            continue
        directory.mkdir(parents=True, exist_ok=True)
        stamp.write_text("1\n", encoding="ascii")


def _install_locked(repo: Path, args) -> int:
    found = discover(repo, args.emulator_data, args.build_dir)
    supplied = {name: getattr(args, name) or found[name] for name in ("base", "update", "keys")}
    if any(not value for value in supplied.values()):
        raise CoastlinkError("Choose the base game, a 13.0.4/13.0.5 update, and prod.keys before installing.")
    if args.dlc_folder and not io_path(args.dlc_folder).is_dir():
        raise CoastlinkError("The DLC folder was not found. Choose it again, or leave it blank.")
    if not args.dlc_folder and found["missing_dlc_files"]:
        raise CoastlinkError("Configured DLC packages are missing. Choose the folder containing your current DLC files; Coastlink will not silently omit them.")
    dlc = list(_package_files(io_path(args.dlc_folder), depth=2)) if args.dlc_folder else found["dlc_files"]
    command = install_command(repo, **{name: Path(value) for name, value in supplied.items()}, dlc_files=dlc,
                              build_dir=args.build_dir, jobs=args.jobs, dry_run=args.dry_run)
    build = build_path(repo, args.build_dir)
    if not args.dry_run:
        check_disk_reserve(build)
        prime_incremental_stamps(build)
    logs = build / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / ("coastlink_install_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".log")
    print("Building the local game and rollback modules. This first build can take a few hours; rerunning resumes it.", flush=True)
    print("Installer log: " + str(log_path), flush=True)
    # No shell interpolation; filenames containing spaces, brackets or accents stay single arguments.
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", bufsize=1,
                                   start_new_session=os.name != "nt")
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            code = process.wait()
        except KeyboardInterrupt:
            terminate_owned_tree(process)
            raise CoastlinkError("Installation stopped. Run Install again to resume.")
        finally:
            process.stdout.close()
    if code:
        raise CoastlinkError(f"The game build stopped (exit {code}). See {log_path}. Run Install again after fixing the last reported problem.")
    if args.dry_run:
        return 0
    ready = status(repo, args.build_dir)
    if not ready["ready"]:
        raise CoastlinkError("The build ended, but rollback files are incomplete: " + "; ".join(ready["missing"]))
    set_ini_values(build / "config" / "graphics.ini", {"rollback": "on", "online_mode": "off"})
    print("Coastlink is ready. Start with Offline, then host/join a two-player test.", flush=True)
    return 0


def coastlink_version(repo: Path) -> str:
    """The release number of SOURCE.json's version ("0.6.0-..." -> "0.6.0")."""
    version = str((read_json(repo / "SOURCE.json", {}) or {}).get("version", ""))
    match = re.match(r"\d+(?:\.\d+){1,3}", version)
    return match.group(0) if match else "0"


def online_build_id(repo: Path, game_version: str) -> str:
    """The runtime's build id (ssbu-recomp-ldn1-<game>) plus +cl<CoastLink version>; at most 40 characters."""
    return f"ssbu-recomp-ldn1-{game_version}+cl{coastlink_version(repo)}"[:40]


def launch_command(repo: Path, *, mode: str, code="", server=DEFAULT_SERVER, name="", build_dir=None, python=None, stamp=None) -> tuple[list[str], dict]:
    verify_source_pin(repo)
    if mode not in MODES:
        raise CoastlinkError("Choose Offline, Host or Join.")
    ready = status(repo, build_dir)
    if ready["build_in_progress"]:
        raise CoastlinkError("This build is still being installed or compiled. Wait for the installer to finish before playing.")
    if not ready["ready"]:
        raise CoastlinkError("Rollback is not installed completely. Run Install/Resume first. Missing: " + "; ".join(ready["missing"]))
    build = Path(ready["build_dir"])
    code = code.strip()
    if mode == "join" and not re.fullmatch(r"[0-9A-Za-z]{5}-?[0-9A-Za-z]{5}", code):
        raise CoastlinkError("Enter the host's 10-character room code (for example XXXXX-XXXXX).")
    if mode.startswith("lobby-"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", code):
            raise CoastlinkError("Use the same private lobby code on both PCs (4–64 letters, numbers, underscores or hyphens).")
        if not re.fullmatch(r"[A-Za-z0-9.-]+:\d{1,5}", server) or not 1 <= int(server.rsplit(":", 1)[1]) <= 65535:
            raise CoastlinkError("The lobby server must be a hostname and port, such as example.org:39500.")
    if any(ord(char) < 32 for char in name) or len(name) > 40:
        raise CoastlinkError("Player names must be at most 40 characters without line breaks.")
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    logs = build / "logs"
    record = {"mode": mode, "game_version": ready["game_version"], "source_commit": UPSTREAM_COMMIT,
              "game_log": str(logs / ("coastlink_game_" + stamp + ".log")),
              "state_log": str(logs / ("coastlink_state_" + stamp + ".hash.txt")),
              "runtime_log": str(logs / ("coastlink_runtime_" + stamp + ".txt")),
              "evidence_log": str(logs / ("coastlink_evidence_" + stamp + ".log"))}
    environment = {"SSBU_NRO_BIN": "nro_bin_eh_o2r1", "SSBU_ONLINE_LOG": "1"}
    if mode == "offline":
        environment.update(SSBU_ONLINE="off", SSBU_RB_NET="0")
    else:
        environment.update(SSBU_RB_NET="net", SSBU_RB_NET_PLAYER="1" if mode in ("join", "lobby-join") else "0",
                           SSBU_RB_NET_LOG=record["state_log"], SSBU_R1_LOG=record["runtime_log"])
        # The runtime chooses the delay from the measured round trip (2..3 frames on a direct coast-to-coast path, 8 if
        # only the relay works) and sends inputs over a direct UDP path when one validates (lobby mode).
        record["rollback_input_delay_frames"] = "auto"
        # The lobby pairs only players of one build id: with the CoastLink version in it, two versions never meet (no
        # desync between them); the runtime says "VERSION MISMATCH" when someone with this code runs another one.
        record["online_build"] = environment["SSBU_ONLINE_BUILD"] = online_build_id(repo, ready["game_version"])
        if mode == "host":
            environment["SSBU_ONLINE"] = "host"
        elif mode == "join":
            environment["SSBU_ONLINE"] = "join:" + code
        else:
            environment.update(SSBU_ONLINE=server, SSBU_ONLINE_CODE=code, SSBU_ONLINE_DIRECT="1")
    if name:
        environment["SSBU_ONLINE_NAME"] = name
        environment["SSBU_NICKNAME"] = name
    from settings import runtime_environment
    environment.update(runtime_environment(build, mode))
    command = [str(python or sys.executable), "-u", str(repo / "coastlink" / "run_rollback.py"), "--play", "--build", str(build), "--log", record["game_log"]]
    for key, value in environment.items():
        command.extend(["--env", key + "=" + value])
    return command, record


def rollback_fell_back(line: str) -> bool:
    lower = line.lower()
    return "[rbnet]" in lower and any(fragment in lower for fragment in (
        "rollback off for this match", "delay-based pacing", "no snapshot ring"))


def important_game_line(line: str) -> bool:
    lower = line.lower()
    return any(fragment in lower for fragment in ("[online]", "[rbnet]", "fatal", "unhandled exception", "error:", "rollback netcode on:"))


def startup_status(line: str) -> str | None:
    """Explain graphics work before the native window can show its first frame."""
    match = re.search(r"^nvn_vk_store: (\d+) % of data.arc read", line)
    if match:
        return f"Preparing graphics: reading game assets, {match[1]}%."
    if line.startswith("nvn_vk_store: data.arc read in") and "STOPPED" not in line:
        return "Game assets read. Preparing shaders for this PC..."
    match = re.search(r"^nvn_vk_prep: (?:start|progress): (\d+) of (\d+) containers read,.*? (\d+) of (\d+) done by the workers", line)
    if match:
        return f"Preparing shaders: {match[3]} jobs finished; {match[1]}/{match[2]} graphics files scanned."
    match = re.search(r"^nvn_vk_prep: (?:first-run|loading) screen: (\d+) %", line)
    if match:
        return f"Preparing shaders: {match[1]}%. Keep the game window open."
    if "FIRST-RUN PREPARATION FINISHED" in line or "SHADERS LOADED AT START:" in line:
        return "Graphics preparation finished. Starting the game..."
    return None


def terminate_owned_tree(process):
    """Stop only the subprocess tree created by this invocation, never by name."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        # The launch uses its own process group on POSIX; the distributed app is Windows.
        import signal
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


class LogFollower:
    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.pending = b""

    def read_lines(self) -> list[str]:
        try:
            with self.path.open("rb") as stream:
                if self.path.stat().st_size < self.offset:
                    self.offset, self.pending = 0, b""
                stream.seek(self.offset)
                block = stream.read(256 * 1024)
                self.offset = stream.tell()
        except (FileNotFoundError, PermissionError):
            return []
        rows = (self.pending + block).split(b"\n")
        self.pending = rows.pop()
        return [row.decode("utf-8", "replace").rstrip("\r") for row in rows]


def write_evidence(record: dict):
    """Keep the game's actual rollback/routing evidence separate from the UI log."""
    if not record.get("evidence_log"):
        return
    target = Path(record["evidence_log"])
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write("# Coastlink session evidence, original runtime and transport messages\n")
            out.write("# " + json.dumps({key: record.get(key) for key in ("mode", "source_commit", "game_version", "exit_code")}) + "\n")
            for field in ("runtime_log", "game_log"):
                path = Path(record[field]) if record.get(field) else None
                out.write("# " + field + "\n")
                if not path or not path.is_file():
                    out.write("# log unavailable\n")
                    continue
                with path.open(encoding="utf-8", errors="replace") as source:
                    for line in source:
                        # Ring reports can be mirrored to stdout; the verifier
                        # must see each report once, in the runtime's order.
                        if field == "runtime_log" or (important_game_line(line) and "[rbnet] report" not in line.lower()):
                            out.write(line.rstrip("\r\n") + "\n")
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_game_monitored(command: list[str], repo: Path, record: dict) -> int:
    process = subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", bufsize=1,
                               start_new_session=os.name != "nt")
    output = queue.Queue()

    def read_output():
        for line in process.stdout:
            output.put(line.rstrip("\r\n"))

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    follower = LogFollower(Path(record["game_log"]))

    def forward():
        while True:
            try:
                line = output.get_nowait()
            except queue.Empty:
                break
            print(line, flush=True)
        for line in follower.read_lines():
            startup = startup_status(line)
            if startup:
                print("STARTUP: " + startup, flush=True)
            elif important_game_line(line):
                print(line, flush=True)
            if record["mode"] != "offline" and rollback_fell_back(line):
                terminate_owned_tree(process)
                raise CoastlinkError("Rollback became unavailable on one of the PCs. Coastlink stopped this game instead of continuing with delay-based netplay. Close other programs, then retry; see the runtime log.")

    try:
        while process.poll() is None:
            forward()
            time.sleep(0.15)
        reader.join(timeout=1)
        forward()
        return process.returncode
    except KeyboardInterrupt:
        terminate_owned_tree(process)
        raise CoastlinkError("Game stopped.")
    finally:
        if process.poll() is None:
            terminate_owned_tree(process)
        reader.join(timeout=2)
        process.stdout.close()
        record["exit_code"] = process.returncode
        try:
            write_evidence(record)
        except OSError as error:
            record["evidence_error"] = str(error)
            print("Session evidence could not be saved: " + str(error), file=sys.stderr, flush=True)


def launch(repo: Path, args) -> int:
    command, record = launch_command(repo, mode=args.mode, code=args.code, server=args.server, name=args.name, build_dir=args.build_dir)
    build = build_path(repo, args.build_dir)
    check_disk_reserve(build)
    from runtime_update import apply_runtime_patch
    try:
        with BuildLock(build):
            repair = apply_runtime_patch(repo, build)
    except ValueError as error:
        raise CoastlinkError(str(error)) from error
    record["runtime_commit"] = repair["runtime_commit"]
    if repair["changed"]:
        print("Rollback runtime repaired. Your existing compiled game and saves are ready.", flush=True)
    if args.mode != "offline":
        print("Rollback input delay: automatic from the ping (about 3 frames on a direct coast-to-coast path). Inputs go directly between the two PCs when possible.", flush=True)
    # Validate first. Failed launches do not change the user's graphics settings.
    set_ini_values(build / "config" / "graphics.ini", {"rollback": "on", "online_mode": "off"})
    (build / "logs").mkdir(parents=True, exist_ok=True)
    atomic_json(build / "logs" / "coastlink_last_session.json", record)
    print(json.dumps(record), flush=True)
    try:
        return run_game_monitored(command, repo, record)
    finally:
        atomic_json(build / "logs" / "coastlink_last_session.json", record)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("discover", "status", "install", "launch"):
        child = sub.add_parser(name)
        child.add_argument("--repo", type=Path, default=repo_path())
        child.add_argument("--build-dir")
        if name in ("discover", "install"):
            child.add_argument("--emulator-data", type=Path)
        if name in ("discover", "status"):
            child.add_argument("--json", action="store_true", help="JSON is already the default output")
        if name == "install":
            for field in ("base", "update", "keys", "dlc-folder"):
                child.add_argument("--" + field)
            child.add_argument("--jobs", type=int, default=4)
            child.add_argument("--dry-run", action="store_true")
        elif name == "launch":
            child.add_argument("--mode", choices=MODES, required=True)
            child.add_argument("--code", default="")
            child.add_argument("--server", default=DEFAULT_SERVER)
            child.add_argument("--name", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "discover":
            print(json.dumps(discover(args.repo, args.emulator_data, args.build_dir)))
            return 0
        if args.command == "status":
            print(json.dumps(status(args.repo, args.build_dir)))
            return 0
        if args.command == "install":
            return install(args.repo, args)
        return launch(args.repo, args)
    except (CoastlinkError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
