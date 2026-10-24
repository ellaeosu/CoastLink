"""CoastLink.exe's backend: JSON lines on stdin / stdout, the existing CoastLink logic behind them.

  in:   {"id": 7, "cmd": "launch", "args": {...}}
  out:  {"id": 7, "ok": true, "result": ...}  or  {"id": 7, "ok": false, "error": "..."}
        {"event": "<name>", ...}               (progress, game and build output, controller input)

Every command runs on its own thread, so a long one (a download, a build) never blocks the others. Child processes are
started without a console window and their output becomes events. Nothing here reads key or game file contents.
GPL-3.0-or-later.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import traceback
import urllib.request

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import app_backend  # noqa: E402
import engine  # noqa: E402
import settings  # noqa: E402
import update_apply  # noqa: E402
import verify_match  # noqa: E402

REPO = HERE.parent
CREATE_NO_WINDOW, CREATE_NEW_CONSOLE = 0x08000000, 0x00000010
_out = threading.Lock()

if os.name == "nt":
    # This process has no console (CoastLink.exe starts it with CREATE_NO_WINDOW), so a console program it starts
    # (taskkill, ...) would open a window of its own: every child without explicit flags gets CREATE_NO_WINDOW.
    _popen_init = subprocess.Popen.__init__

    def _quiet_init(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = CREATE_NO_WINDOW
        _popen_init(self, *args, **kwargs)
    subprocess.Popen.__init__ = _quiet_init


def send(obj: dict):
    with _out:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def event(kind: str, **data):
    send({"event": kind, **data})


def build_dir() -> Path:
    return engine.build_path(REPO)


def python_exe() -> str:
    return sys.executable


def hidden_popen(command: list[str], **kw) -> subprocess.Popen:
    """A build or a game: its own console, hidden. The installer's compilers and the game inherit that console, so none of
    the hundreds of processes a build starts opens a window (with CREATE_NO_WINDOW each of them would get a new one)."""
    extra = {}
    if os.name == "nt":
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0                                    # SW_HIDE
        extra = {"creationflags": CREATE_NEW_CONSOLE, "startupinfo": info}
    return subprocess.Popen(command, cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1, **extra, **kw)


class Job:
    """A child process (the game through engine.py launch, or the build through engine.py install) whose lines become
    `<kind>` events and whose end becomes a `<kind>_end` event."""
    def __init__(self, kind: str, command: list[str]):
        self.kind, self.command = kind, command
        self.process = hidden_popen(command)
        self.started = datetime.now().isoformat(timespec="seconds")
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.process.stdout:
            line = line.rstrip("\r\n")
            if not line:
                continue
            payload = {"line": line}
            if line.startswith("STARTUP: "):
                payload["startup"] = line[9:]
            elif line.startswith("{") and line.endswith("}"):
                try:
                    payload["record"] = json.loads(line)
                except ValueError:
                    pass
            event(self.kind, **payload)
        code = self.process.wait()
        event(self.kind + "_end", code=code)

    def running(self) -> bool:
        return self.process.poll() is None

    def stop(self):
        if self.running():
            engine.terminate_owned_tree(self.process)


JOBS: dict[str, Job] = {}
COMMANDS = {}


def command(name):
    def register(fn):
        COMMANDS[name] = fn
        return fn
    return register


def running(kind: str) -> bool:
    job = JOBS.get(kind)
    return bool(job and job.running())


# ---------------------------------------------------------------- overview
@command("hello")
def hello(_):
    build = build_dir()
    return {"repo": str(REPO), "build_dir": str(build), "python": python_exe(), **app_backend.version_info(REPO),
            "status": engine.status(REPO), "memory": app_backend.memory_info()}


@command("status")
def status(_):
    build = build_dir()
    from pads import devices
    return {"status": engine.status(REPO), "checklist": app_backend.checklist(REPO, build, devices()),
            "shaders": app_backend.shader_status(build), "memory": app_backend.memory_info(),
            "game_running": running("game"), "build_running": running("build")}


@command("sessions")
def sessions(args):
    return app_backend.recent_sessions(build_dir(), int(args.get("limit", 8)))


@command("session.live")
def session_live(_):
    out = app_backend.live_session(build_dir())
    out["running"] = running("game")
    return out


# ---------------------------------------------------------------- settings
@command("settings.get")
def settings_get(_):
    return settings.get_settings(build_dir())


@command("settings.save")
def settings_save(args):
    return settings.save_settings(build_dir(), args["settings"])


# ---------------------------------------------------------------- play
@command("launch")
def launch(args):
    if running("game"):
        raise RuntimeError("A game is already running from CoastLink. Close it first.")
    mode = args.get("mode", "offline")
    if mode not in engine.MODES:
        raise ValueError("Choose Offline, Host, Join or Shared lobby.")
    if mode != "offline" and args.get("require_shaders", True):
        shaders = app_backend.shader_status(build_dir())
        if not shaders["done"]:
            raise RuntimeError("Shaders are not prepared yet. Launch offline once and let the preparation finish "
                               f"({shaders['read']} / {shaders['total']} so far), then go online.")
    cmd = [python_exe(), "-u", str(HERE / "engine.py"), "launch", "--mode", mode]
    for key in ("code", "server", "name"):
        if args.get(key):
            cmd += ["--" + key, str(args[key])]
    if os.name == "nt":                     # the game reads the GameCube adapter itself: CoastLink lets go of it first
        from pads import gca_live
        gca_live.stop()
    JOBS["game"] = Job("game", cmd)
    return {"started": True, "mode": mode}


@command("game.stop")
def game_stop(_):
    if running("game"):
        JOBS["game"].stop()
    return {"stopped": True}


@command("net.test")
def net_test(args):
    """Test connection: the lobby, its round trip, and who waits with this code (same version / another version)."""
    import net_check
    server = args.get("server") or engine.DEFAULT_SERVER
    code = str(args.get("code") or "public")
    game = engine.status(REPO).get("game_version") or "13.0.4"
    mine = engine.coastlink_version(REPO)
    result = net_check.lobby_probe(server, code, engine.online_build_id(REPO, game))
    result["version"] = mine
    if result.get("waiting_other_version"):
        result["other_versions"] = net_check.identify_other_versions(server, code, game, mine)
    return result


# ---------------------------------------------------------------- verify
@command("verify")
def verify(args):
    report = verify_match.verify_match(args["mine"], args["theirs"],
                                       runtime_a=args.get("mine_runtime") or app_backend.companion_evidence(args["mine"]),
                                       runtime_b=args.get("theirs_runtime") or app_backend.companion_evidence(args["theirs"]))
    return {"report": report, "text": verify_match.format_report(report)}


@command("verify.latest")
def verify_latest(_):
    build = build_dir()
    state = app_backend.newest(build, "coastlink_state_*.hash.txt")
    if not state:
        return {"state": None}
    stamp = state.name[len("coastlink_state_"):-len(".hash.txt")]
    runtime = app_backend.logs_dir(build) / ("coastlink_runtime_" + stamp + ".txt")
    evidence = app_backend.logs_dir(build) / ("coastlink_evidence_" + stamp + ".log")
    return {"state": str(state), "runtime": str(runtime) if runtime.is_file() else None,
            "evidence": str(evidence) if evidence.is_file() else None, "stamp": stamp}


# ---------------------------------------------------------------- logs
@command("logs.folder")
def logs_folder(_):
    path = app_backend.logs_dir(build_dir())
    path.mkdir(parents=True, exist_ok=True)
    return {"path": str(path)}


@command("logs.bundle")
def logs_bundle(_):
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    if not desktop.is_dir():
        desktop = app_backend.logs_dir(build_dir())
    target = desktop / ("CoastLink-logs-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip")
    return {"path": str(app_backend.bundle_logs(build_dir(), target))}


# ---------------------------------------------------------------- build (first-run setup, resume, repair)
@command("build.progress")
def build_progress(_):
    out = app_backend.build_progress(build_dir())
    out["running"] = running("build")
    return out


@command("build.size")
def build_size(_):
    return {"gb": app_backend.folder_size_gb(build_dir())}


@command("build.discover")
def build_discover(_):
    return engine.discover(REPO)


@command("build.start")
def build_start(args):
    if running("build"):
        raise RuntimeError("The build is already running.")
    if running("game"):
        raise RuntimeError("Close the game before building.")
    cmd = [python_exe(), "-u", str(HERE / "engine.py"), "install", "--jobs", str(int(args.get("jobs", 4)))]
    for key in ("base", "update", "keys", "dlc_folder"):
        if args.get(key):
            cmd += ["--" + key.replace("_", "-"), str(args[key])]
    JOBS["build"] = Job("build", cmd)
    return {"started": True}


@command("build.stop")
def build_stop(_):
    if running("build"):
        JOBS["build"].stop()
    return {"stopped": True, "resumable": True}


@command("cleanup")
def cleanup_cmd(args):
    import cleanup
    return {"removed" if not args.get("dry_run") else "would_remove": cleanup.cleanup(REPO, bool(args.get("dry_run")))}


@command("save.import")
def save_import_cmd(args):
    import save_import
    if running("game"):
        raise RuntimeError("Close the game first: it writes its save while it runs.")
    return save_import.import_save(build_dir(), Path(args["path"]))


@command("save.backups")
def save_backups(_):
    import save_import
    return save_import.list_backups(build_dir())


@command("save.restore")
def save_restore(args):
    import save_import
    if running("game"):
        raise RuntimeError("Close the game first: it writes its save while it runs.")
    return save_import.restore_backup(build_dir(), str(args.get("name", "")))


@command("shaders.status")
def shaders_status(_):
    return app_backend.shader_status(build_dir())


@command("shaders.clear")
def shaders_clear(_):
    if running("game"):
        raise RuntimeError("Close the game first.")
    return {"removed": app_backend.clear_shader_cache(build_dir())}


# ---------------------------------------------------------------- updates
def update_config() -> dict:
    return update_apply.load_config(REPO)


@command("update.config")
def update_config_cmd(args):
    if "settings" in args:
        return update_apply.save_config(REPO, args["settings"])
    return update_config()


def fetch(url: str, limit: int = 4 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "CoastLink/" + app_backend.version_info(REPO)["version"]})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("The update manifest is too large.")
    return data


@command("update.check")
def update_check(args):
    """The release feed's manifest and its signature, as text (the window checks the signature with the built-in key)."""
    url = args.get("url") or update_config()["feed"]
    if not url:
        raise ValueError("No update feed is set (config/update.json).")
    text = fetch(url).decode("utf-8")
    signature = fetch(url + ".sig").decode("ascii").strip()
    manifest = json.loads(text)
    return {"text": text, "signature": signature, "manifest": manifest, "installed": app_backend.version_info(REPO)["version"]}


@command("update.download")
def update_download(args):
    url, sha, size = args["url"], args["sha256"].lower(), int(args.get("size") or 0)
    target_dir = build_dir() / "coastlink_downloads"
    target_dir.mkdir(parents=True, exist_ok=True)
    name = Path(args.get("name") or url.rsplit("/", 1)[-1]).name
    target = target_dir / name
    part = target.with_name(name + ".part")
    digest, got = hashlib.sha256(), 0
    request = urllib.request.Request(url, headers={"User-Agent": "CoastLink"})
    with urllib.request.urlopen(request, timeout=30) as response, open(part, "wb") as out:
        total = int(response.headers.get("Content-Length") or size or 0)
        while chunk := response.read(1 << 16):
            out.write(chunk)
            digest.update(chunk)
            got += len(chunk)
            if size and got > size * 1.05 + 65536:
                raise ValueError("The download is larger than the release says.")
            event("download", name=name, done=got, total=total)
    if digest.hexdigest() != sha:
        part.unlink(missing_ok=True)
        raise ValueError("The download did not match its SHA-256 in the signed release. Nothing was installed.")
    os.replace(part, target)
    return {"path": str(target), "sha256": sha}


@command("update.apply")
def update_apply_cmd(args):
    if running("game") or running("build"):
        raise RuntimeError("Close the game and wait for the build before updating.")
    return update_apply.apply_update(REPO, Path(args["path"]), expected_sha256=args.get("sha256"))


@command("update.backups")
def update_backups(_):
    return update_apply.list_backups(REPO)


@command("update.rollback")
def update_rollback(args):
    if running("game"):
        raise RuntimeError("Close the game first.")
    return update_apply.roll_back(REPO, args.get("backup"))


# ---------------------------------------------------------------- controllers, audio devices
@command("pads.devices")
def pads_devices(_):
    from pads import devices
    return devices()


@command("pads.adapters")
def pads_adapters(_):
    from pads import gamecube_adapters
    return gamecube_adapters()


@command("pads.gca_live")
def pads_gca_live(args):
    """The Wii U-mode adapter's ports as controllers in the Controllers screen (on), or the adapter released (off)."""
    from pads import gca_live
    if not args.get("on"):
        gca_live.stop()
        return {"on": False}
    if running("game"):
        return {"on": False, "error": "The game is using the adapter: its ports show here when the game is closed."}
    return gca_live.start()


@command("pads.gca_test")
def pads_gca_test(args):
    """Test the GameCube adapter (Wii U mode, WinUSB) for a few seconds; ports stream as `gca` events."""
    from pads import gamecube_adapter_test
    if running("game"):
        raise RuntimeError("Close the game first: it is using the adapter.")
    return gamecube_adapter_test(lambda ports: event("gca", ports=ports), float(args.get("seconds", 15)))


@command("pads.gca_stop")
def pads_gca_stop(_):
    from pads import stop_gamecube_adapter_test
    stop_gamecube_adapter_test()
    return {"stopped": True}


@command("pads.game_report")
def pads_game_report(_):
    return app_backend.pad_report(build_dir())


@command("pads.watch")
def pads_watch(args):
    from pads import watcher
    watcher.set_watch(args.get("guid"), lambda state: event("pad", **state))
    return {"watching": args.get("guid")}


@command("pads.rumble")
def pads_rumble(args):
    from pads import rumble
    return {"ok": rumble(args["guid"], float(args.get("strength", 1.0)), int(args.get("ms", 400)))}


@command("pads.config")
def pads_config(args):
    import controller_config
    if "save" in args:
        return controller_config.save(build_dir(), args["save"])
    return controller_config.load(build_dir())


@command("pads.profiles")
def pads_profiles(args):
    import controller_config
    return controller_config.profiles(build_dir(), args)


@command("audio.devices")
def audio_devices(_):
    from pads import audio_devices as devices
    return devices()


# The PowerShell / .cmd launcher of 0.5.x, replaced by CoastLink.exe; removed once CoastLink.exe has started and the build
# is complete (upgrade in place: an update that failed halfway still leaves the old way to start).
LEGACY_LAUNCHER = ("Play CoastLink.cmd", "Install CoastLink.cmd", "Live Counter.cmd", "Clean old CoastLink.cmd",
                   "coastlink/CoastLink.ps1", "coastlink/Settings.ps1", "coastlink/LiveCounter.ps1",
                   "coastlink/Bootstrap.ps1", "coastlink/Cleanup.ps1")


@command("first_run_done")
def first_run_done(_):
    if not (REPO / "CoastLink.exe").is_file() or not engine.status(REPO)["ready"]:
        return {"removed": []}
    removed = []
    for name in LEGACY_LAUNCHER:
        path = REPO / name
        if path.is_file():
            path.unlink()
            removed.append(name)
    return {"removed": removed}


@command("quit")
def quit_cmd(_):
    os._exit(0)


def handle(message: dict):
    mid = message.get("id")
    try:
        fn = COMMANDS.get(message.get("cmd"))
        if not fn:
            raise ValueError("Unknown command: " + str(message.get("cmd")))
        send({"id": mid, "ok": True, "result": fn(message.get("args") or {})})
    except Exception as error:   # every failure goes back to the window as a readable message
        text = str(error) or error.__class__.__name__
        send({"id": mid, "ok": False, "error": text, "kind": error.__class__.__name__,
              "trace": traceback.format_exc(limit=4)})


def main():
    event("ready", version=app_backend.version_info(REPO)["version"], repo=str(REPO))
    workers = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            send({"event": "error", "error": "bad request: " + line[:200]})
            continue
        worker = threading.Thread(target=handle, args=(message,), daemon=True)
        worker.start()
        workers = [w for w in workers if w.is_alive()] + [worker]
    # the window closed its end: answer what is still in flight; a running game or build is left running (a build resumes)
    for worker in workers:
        worker.join(timeout=10)


if __name__ == "__main__":
    main()
