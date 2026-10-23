"""Optional local Ultimate rollback sample; never an Internet/performance proof.

Runs the pinned project's documented loop bot twice, with 0 and 5 frames of
simulated remote-input lateness. Each run uses a separate copy of an initialized
native save. The first 100 finalized frame checksums must match, the delayed run
must actually rewind, and both must reach the 120-fight-frame scripted stop.
Menu recognition is heuristic: failure to reach the fight is inconclusive.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import engine
from verify_match import compare_texts, parse_runtime, parse_trace

SCOPE = ("A short, local simulated rollback sample using Ultimate. It does not verify a complete match, "
         "Internet connectivity, coast-to-coast performance, input latency, or improvement over Parsec.")
COMPARE_FRAMES = 100
STOP_FRAMES = 120


def sequence_path(repo: Path, version: str, profile: str) -> Path:
    if profile == "basic":
        return repo / "tests" / "seq_n4_det.txt"
    if profile == "all-fighters":
        return repo / "tests" / ("seq_completo_1305.txt" if version == "13.0.5" else "seq_completo.txt")
    raise engine.CoastlinkError("Choose the basic or all-fighters menu profile.")


def initialized_save(build: Path) -> Path:
    source = build / "saves"
    marker = source / "save" / "save_data" / "system_data.bin"
    if not marker.is_file() or marker.stat().st_size == 0:
        raise engine.CoastlinkError("Play Offline once, finish the first-run prompts and close the game before this check. "
                                    "An initialized native save is required; Ryujinx saves are not used automatically.")
    # Refuse redirections before recursively copying a user's save tree.
    for current, dirs, files in os.walk(source, followlinks=False):
        for item in [Path(current), *(Path(current, name) for name in dirs + files)]:
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise engine.CoastlinkError("The native save contains a link or junction. The check only copies ordinary save folders.")
    return source


def make_command(repo: Path, build: Path, userdata: Path, log_dir: Path, *, lateness: int,
                 version: str, profile: str = "basic", timeout: int = 180) -> tuple[list[str], dict]:
    if lateness not in (0, 5) or not 30 <= timeout <= 180:
        raise ValueError("Use lateness 0/5 and a 30–180 second timeout.")
    seq = sequence_path(repo, version, profile)
    if not seq.is_file():
        raise engine.CoastlinkError("The pinned scripted menu sequence is missing. Extract a fresh CoastLink package.")
    tag = f"loop{lateness}"
    record = {name: str(log_dir / f"{tag}.{suffix}") for name, suffix in
              (("game_log", "game.log"), ("runtime_log", "runtime.txt"), ("state_log", "hash.txt"))}
    flags = {
        "SSBU_ONLINE": "off", "SSBU_RB_NET": f"loop,{lateness}", "SSBU_RB_NET_PLAYER": "0",
        "SSBU_RB_NET_BOT": "7", "SSBU_RB_NET_LOOP_BOT2": "11", "SSBU_RB_NET_LOOP_SEED": "1234",
        "SSBU_RB_NET_DELAY": "2", "SSBU_RB_NET_PACE": "0", "SSBU_NRO_BIN": "nro_bin_eh_o2r1",
        "SSBU_SKIP_MOVIES": "1", "SSBU_SPEED": "0", "SSBU_AUDIO_MUTE": "1", "SSBU_VK_PREP": "0",
        "SSBU_DETERMINISTIC": "1", "SSBU_FIXED_SEED": "1234", "SSBU_SHOW": "0",
        "SSBU_DEBUG_MATCH": "p1=mario,p2=donkey,p2=human,stage=end,stock=3,items=off,hazards=off",
        "SSBU_DEBUG_END": str(STOP_FRAMES), "SSBU_RB_NET_LOG": record["state_log"],
        "SSBU_R1_LOG": record["runtime_log"],
    }
    command = [sys.executable, "-u", str(repo / "scripts" / "run.py"), "--build", str(build),
               "--userdata", str(userdata), "--exe", "ssbu_native_rb.exe", "--seconds", str(timeout),
               "--seq", str(seq), "--log", record["game_log"]]
    for key, value in flags.items():
        command.extend(["--env", key + "=" + value])
    return command, record


def evaluate(reference: dict, delayed: dict) -> dict:
    """Inspect real recorded files; a short overlap or unused rollback never passes."""
    issues = []
    prefixes = []
    observations = []
    for label, record, expected_lateness in (("reference", reference, 0), ("delayed", delayed, 5)):
        text = {key: Path(record[key]).read_text(encoding="utf-8", errors="replace")
                for key in ("game_log", "runtime_log", "state_log")}
        trace, runtime = parse_trace(text["state_log"]), parse_runtime(text["runtime_log"])
        issues.extend(f"{label}: {error}" for error in trace["errors"] + runtime["errors"])
        if len(trace["matches"]) != 1 or len(runtime["matches"]) != 1:
            issues.append(f"{label}: exactly one recorded sample and one runtime report are required")
        tm = trace["matches"].get(1, {})
        rm = runtime["matches"].get(1, {})
        frames = tm.get("frames", {})
        if not frames or min(frames) != 1 or max(frames) != len(frames) or len(frames) < COMPARE_FRAMES:
            issues.append(f"{label}: fewer than {COMPARE_FRAMES} contiguous finalized frames from frame 1")
        if rm.get("id") != tm.get("id"):
            issues.append(f"{label}: trace and runtime identifiers disagree")
        if not 1 <= rm.get("real_frames", 0) <= STOP_FRAMES or rm.get("finalized_frames") != len(frames):
            issues.append(f"{label}: executed/finalized sample coverage is inconsistent")
        if rm.get("rollback_disabled") or rm.get("unavailable_rollback_states", 0) or rm.get("desyncs", 0) or rm.get("incorrect_final_pad_values", 0):
            issues.append(f"{label}: runtime reports disabled rollback or a correctness failure")
        if label == "reference" and rm.get("rollbacks") != 0:
            issues.append("reference: the zero-lateness run unexpectedly rolled back")
        if label == "delayed" and (rm.get("rollbacks", 0) < 1 or rm.get("replayed_frames", 0) < 1):
            issues.append("delayed: no actual rollback and replay was recorded")
        expected = f"[rbnet] loop: remote pads arrive {expected_lateness} frames after the frame that would send them"
        if expected not in text["game_log"]:
            issues.append(f"{label}: requested loop simulation was not confirmed by the runtime")
        if not re.search(rf"debug end: {STOP_FRAMES} fight frames reached at presented frame \d+ \(SSBU_DEBUG_END\): exit request, normal shutdown", text["game_log"]):
            issues.append(f"{label}: scripted {STOP_FRAMES}-fight-frame stop was not reached (menu recognition may have missed)")
        if "GUEST TRAP" in text["game_log"] or "HOST EXCEPTION" in text["game_log"]:
            issues.append(f"{label}: the game reported a trap or host exception")
        prefixes.append("m 1 id " + tm.get("id", "0") + "\n" + "".join(
            f"f {f} h {frames[f]:016x}\n" for f in range(1, COMPARE_FRAMES + 1) if f in frames))
        observations.append({"run": label, "finalized_frames_recorded": len(frames),
                             "runtime": rm, "files": record})
    comparison = compare_texts(*prefixes, min_frames=COMPARE_FRAMES)
    if not comparison["ok"]:
        issues.append("The explicitly bounded first 100 finalized frames do not pass the strict checksum comparison.")
    return {"schema_version": 1, "ok": not issues, "verdict": "local_sample_matched" if not issues else "inconclusive_or_failed",
            "scope": SCOPE, "compared_prefix_frames": COMPARE_FRAMES,
            "runs": observations, "comparison": comparison, "issues": issues,
            "complete_match_verified": False, "internet_tested": False, "performance_tested": False}


def run_check(repo: Path, *, chosen=None, profile="basic", timeout=180) -> dict:
    engine.verify_source_pin(repo)
    ready = engine.status(repo, chosen)
    if not ready["ready"]:
        raise engine.CoastlinkError("Finish the rollback build before running the local check.")
    build = Path(ready["build_dir"])
    source = initialized_save(build)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_dir = build / "logs" / ("coastlink_local_check_" + stamp)
    # The same lock as the installer: no build can replace DLLs during this check.
    with engine.BuildLock(build):
        engine.check_disk_reserve(build)
        log_dir.mkdir(parents=True, exist_ok=False)
        print("Local check: two short Ultimate runs using disposable copies of the native save.", flush=True)
        print("Each run stops at 120 fight frames, with a 180-second maximum. Menu detection can be inconclusive.", flush=True)
        records = []
        with tempfile.TemporaryDirectory(prefix="disposable_saves_", dir=log_dir) as temporary:
            root = Path(temporary).resolve()
            if root.parent != log_dir.resolve():
                raise engine.CoastlinkError("The disposable save folder is outside the check folder.")
            for lateness in (0, 5):
                userdata = root / f"loop{lateness}"
                shutil.copytree(source, userdata, ignore=shutil.ignore_patterns("*.work.*"))
                command, record = make_command(repo, build, userdata, log_dir, lateness=lateness,
                                               version=ready["game_version"], profile=profile, timeout=timeout)
                print(f"Running {'reference' if lateness == 0 else 'delayed-input rollback'} sample...", flush=True)
                with (log_dir / f"loop{lateness}.launcher.log").open("w", encoding="utf-8") as output:
                    process = subprocess.Popen(command, cwd=repo, stdout=output, stderr=subprocess.STDOUT,
                                               start_new_session=os.name != "nt")
                    try:
                        code = process.wait(timeout=timeout)
                    except (subprocess.TimeoutExpired, KeyboardInterrupt):
                        engine.terminate_owned_tree(process)
                        raise engine.CoastlinkError("Local check stopped or timed out. No success is claimed; try the other menu profile after checking Offline play.")
                if code:
                    raise engine.CoastlinkError(f"The local sample exited with code {code}. No success is claimed; logs: {log_dir}")
                records.append(record)
        try:
            report = evaluate(*records)
        except OSError as exc:
            raise engine.CoastlinkError(f"Local check produced incomplete evidence; no success is claimed. Logs: {log_dir}") from exc
        engine.atomic_json(log_dir / "result.json", report)
        report["report_path"] = str(log_dir / "result.json")
        return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=engine.repo_path())
    parser.add_argument("--build-dir")
    parser.add_argument("--profile", choices=("basic", "all-fighters"), default="basic")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    try:
        if not 30 <= args.timeout <= 180:
            raise engine.CoastlinkError("Timeout must be between 30 and 180 seconds per sample.")
        report = run_check(args.repo, chosen=args.build_dir, profile=args.profile, timeout=args.timeout)
    except (engine.CoastlinkError, OSError, ValueError) as exc:
        print("Local check inconclusive: " + str(exc), flush=True)
        print(SCOPE, flush=True)
        return 2
    print("Local simulated sample matched." if report["ok"] else "Local check inconclusive or failed.", flush=True)
    for issue in report["issues"]:
        print("- " + issue, flush=True)
    print(SCOPE, flush=True)
    print("Report: " + report["report_path"], flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
