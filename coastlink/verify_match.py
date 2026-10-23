"""Compare finalized rollback traces without treating absent evidence as success.

Only the exact formats emitted by rb_net.c / rb_rollback.c at the pinned source
revision are parsed. The hashes cover recorded fighter fields and pad reads,
not every byte of the game state. A match completion claim needs runtime reports.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

HEADER = re.compile(r"m ([1-9]\d*) id ([0-9a-fA-F]{1,16})$")
FRAME = re.compile(r"f ([1-9]\d*) h ([0-9a-fA-F]{1,16})$")
NUMBER = r"-?\d+(?:\.\d+)?"
TIMING_LABELS = {
    "work per tick (real pass + its rollback, without waits)",
    "work per tick without rollback",
    "work per tick with rollback",
    "time between real passes (tick to tick)",
}
TIMING = re.compile(
    rf"r1: RB NET TIMING (.+): (\d+), mean ({NUMBER}) median ({NUMBER}) "
    rf"p90 ({NUMBER}) p99 ({NUMBER}) max ({NUMBER}) ms; over 16\.67 ms: "
    rf"(\d+) \(({NUMBER})%\)$"
)
SUMMARY = re.compile(
    rf"\[rbnet\] report \(match (\d+), id ([0-9a-fA-F]+)\): (\d+) frames; delay (\d+); "
    rf"round trip mean ({NUMBER}) ms \(best ({NUMBER}), (\d+) samples\); "
    rf"clock offset estimate ({NUMBER}) ms, time-sync corrections (\d+)$"
)
PADS = re.compile(
    r"\[rbnet\] report: pads given (\d+), predicted (\d+) \(([^)]+)%\), mispredictions (\d+); "
    r"finalized frames (\d+); checksums compared (\d+), DESYNCS (\d+) \(first (-?\d+)\)$"
)
REAL = re.compile(
    r"r1: RB NET report: (\d+) real frames, (\d+) rollbacks, (\d+) frames run again "
    r"\(k: .*\); rollbacks impossible \(state not in the ring\) (\d+)$"
)
STALLS = re.compile(
    rf"r1: RB NET report: stalls for the other player (\d+) \(({NUMBER}) ms in all; "
    rf"(\d+) of them because the ring was short of memory\); captures failed (\d+), "
    rf"re-run captures not needed (\d+); load mean ({NUMBER}) ms; peer silent (\d+)$"
)
PAD_CHECK = re.compile(
    r"\[rbnet\] report: pad check of the final simulations: (\d+) pad values differ "
    r"from the final ones \(first frame (-?\d+)\)$"
)
ENDED = re.compile(r"(?:r1: RB NET:|\[rbnet\]) match (\d+) over: .+$")
TRAFFIC = re.compile(
    r"\[online\] traffic: out (\d+) relayed \+ (\d+) direct, in (\d+) relayed \+ (\d+) direct; "
    r"(\d+) peer\(s\)(?:, first (direct|relayed))?$"
)


def parse_trace(text: str) -> dict[str, Any]:
    matches: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    current = None
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("d "):
            continue
        m = HEADER.fullmatch(line)
        if m:
            number, ident = int(m[1]), m[2].lower().zfill(8)
            if number in matches:
                errors.append(f"line {line_number}: repeated match header {number}")
            else:
                matches[number] = {"id": ident, "frames": {}, "duplicate_frames": 0}
            current = number
            continue
        m = FRAME.fullmatch(line)
        if m:
            if current is None:
                errors.append(f"line {line_number}: frame before a match header")
                continue
            frame, value = int(m[1]), int(m[2], 16)
            match = matches[current]
            frames = match["frames"]
            if frame in frames:
                match["duplicate_frames"] += 1
                if frames[frame] != value:
                    errors.append(f"line {line_number}: conflicting duplicate of match {current}, frame {frame}")
            else:
                frames[frame] = value
            continue
        errors.append(f"line {line_number}: unrecognized checksum trace record")
    if not matches:
        errors.append("no match headers recorded")
    return {"matches": matches, "errors": errors}


def parse_runtime(text: str) -> dict[str, Any]:
    """Read reports, retaining absent metrics as absent rather than zero."""
    matches: dict[int, dict[str, Any]] = {}
    pending: dict[str, Any] = {"timing": {}}
    active = None
    errors: list[str] = []
    route = None
    for raw in text.splitlines():
        line = raw.strip()
        m = REAL.fullmatch(line)
        if m:
            pending.update(real_frames=int(m[1]), rollbacks=int(m[2]), replayed_frames=int(m[3]),
                           unavailable_rollback_states=int(m[4]))
            continue
        m = STALLS.fullmatch(line)
        if m:
            pending.update(stall_count=int(m[1]), stall_total_ms=float(m[2]), memory_stalls=int(m[3]),
                           capture_failures=int(m[4]), load_mean_ms=float(m[6]), peer_silent_count=int(m[7]))
            continue
        if line.startswith("r1: RB NET report: this match ran WITHOUT rollback "):
            pending["rollback_disabled"] = True
            continue
        m = TIMING.fullmatch(line)
        if m and m[1] in TIMING_LABELS:
            pending["timing"][m[1]] = {
                "samples": int(m[2]), "mean_ms": float(m[3]), "median_ms": float(m[4]),
                "p90_ms": float(m[5]), "p95_ms": None, "p99_ms": float(m[6]),
                "max_ms": float(m[7]), "over_budget_count": int(m[8]),
                "over_budget_percent": float(m[9]), "budget_ms": 1000 / 60,
                "p95_unavailable_reason": "The runtime report does not record p95 or raw durations.",
            }
            continue
        m = SUMMARY.fullmatch(line)
        if m:
            active = int(m[1])
            if active in matches:
                errors.append(f"repeated runtime report for match {active}")
            pending.update(id=m[2].lower().zfill(8), reported_frames=int(m[3]), input_delay_frames=int(m[4]),
                           round_trip_mean_ms=float(m[5]), round_trip_best_ms=float(m[6]), rtt_samples=int(m[7]),
                           clock_offset_ms=float(m[8]), time_sync_corrections=int(m[9]), ended=False)
            matches[active] = pending
            pending = {"timing": {}}
            continue
        m = PADS.fullmatch(line)
        if m and active in matches:
            matches[active].update(predicted_pad_reads=int(m[2]), mispredictions=int(m[4]),
                                   finalized_frames=int(m[5]), compared_checksums=int(m[6]),
                                   desyncs=int(m[7]), first_desync_frame=int(m[8]))
            continue
        m = PAD_CHECK.fullmatch(line)
        if m and active in matches:
            matches[active].update(incorrect_final_pad_values=int(m[1]), first_incorrect_pad_frame=int(m[2]))
            continue
        m = ENDED.fullmatch(line)
        if m and int(m[1]) in matches:
            matches[int(m[1])]["ended"] = True
            continue
        m = TRAFFIC.fullmatch(line)
        if m:
            route = dict(zip(("out_relayed", "out_direct", "in_relayed", "in_direct", "peers"),
                             (int(m[i]) for i in range(1, 6))))
            route["last_first_peer_route"] = m[6]
        if line.startswith("[rbnet] DESYNC: frame ") or line.startswith("[rbnet] PAD CHECK: frame "):
            errors.append("runtime recorded a desync or incorrect finalized pad")
    return {"matches": matches, "errors": errors, "last_traffic_counters": route}


def compare_texts(a_text: str, b_text: str, *, min_frames: int = 120,
                  runtime_a: str | None = None, runtime_b: str | None = None) -> dict[str, Any]:
    if min_frames < 1:
        raise ValueError("min_frames must be positive")
    a, b = parse_trace(a_text), parse_trace(b_text)
    runtimes = [parse_runtime(text) if text is not None else None for text in (runtime_a, runtime_b)]
    errors = [f"{side}: {error}" for side, data in (("A", a), ("B", b)) for error in data["errors"]]
    errors += [f"{side} runtime: {error}" for side, data in zip(("A", "B"), runtimes)
               if data for error in data["errors"]]
    records = []
    numbers = sorted(set(a["matches"]) | set(b["matches"]))
    all_covered = bool(numbers)
    all_states_match = bool(numbers)
    all_complete = bool(numbers)
    rollback_unavailable = False
    for number in numbers:
        am, bm = a["matches"].get(number), b["matches"].get(number)
        af, bf = (am or {}).get("frames", {}), (bm or {}).get("frames", {})
        common = sorted(set(af) & set(bf))
        different = [f for f in common if af[f] != bf[f]]
        coverage_errors = []
        if not am or not bm:
            coverage_errors.append("match is absent from one trace")
        if am and bm and am["id"] != bm["id"]:
            coverage_errors.append("match identifiers differ")
        if set(af) != set(bf):
            coverage_errors.append("recorded frame coverage differs")
        if len(common) < min_frames:
            coverage_errors.append(f"only {len(common)} common frames; at least {min_frames} required")
        for side, frames in (("A", af), ("B", bf)):
            if not frames or min(frames) != 1 or max(frames) != len(frames):
                coverage_errors.append(f"{side} coverage must be contiguous from frame 1")
        execution = []
        rollback_active: dict[str, bool | None] = {"a": None, "b": None}
        completed = True
        for side, trace, rt in zip(("A", "B"), (am, bm), runtimes):
            rm = rt["matches"].get(number) if rt else None
            if not rm:
                completed = False
                execution.append(f"{side}: completion runtime report unavailable")
                continue
            if "real_frames" in rm:
                rollback_active[side.lower()] = not rm.get("rollback_disabled", False)
            if not trace or rm["id"] != trace["id"]:
                completed = False
                execution.append(f"{side}: runtime match id differs from the checksum trace")
            frame_count = len((trace or {}).get("frames", {}))
            if not rm.get("ended") or not (frame_count == rm.get("real_frames") == rm.get("reported_frames") == rm.get("finalized_frames")):
                completed = False
                execution.append(f"{side}: ended report does not cover every executed and finalized frame")
            if rm.get("rollback_disabled"):
                completed = False
                rollback_unavailable = True
                execution.append(f"{side}: runtime reports rollback disabled for this match")
            if rm.get("unavailable_rollback_states", 0) or rm.get("desyncs", 0) or rm.get("incorrect_final_pad_values", 0):
                execution.append(f"{side}: runtime reports a rollback correctness failure")
                all_states_match = False
        covered = not coverage_errors
        states_match = bool(common) and not different
        all_covered &= covered
        all_states_match &= states_match
        all_complete &= completed and covered
        records.append({
            "match": number, "id_a": (am or {}).get("id"), "id_b": (bm or {}).get("id"),
            "coverage": {"ok": covered, "frames_a": len(af), "frames_b": len(bf), "common_frames": len(common),
                         "common_first": common[0] if common else None, "common_last": common[-1] if common else None,
                         "missing_from_a_count": len(set(bf) - set(af)), "missing_from_b_count": len(set(af) - set(bf)),
                         "errors": coverage_errors},
            "state": {"recorded_checksums_match": states_match, "different_frames": len(different),
                      "first_difference": different[0] if different else None},
            "execution": {"complete_match_evidenced": completed, "rollback_active": rollback_active, "notes": execution},
        })
    ok = all_covered and all_states_match and not errors and not rollback_unavailable
    complete = ok and all_complete
    verdict = ("rollback_unavailable" if rollback_unavailable else
               "complete_recorded_match_verified" if complete else "recorded_checksums_match" if ok
               else "mismatch" if not all_states_match and numbers else "insufficient_evidence")
    # Incomplete execution and state mismatch are reported independently; partial
    # overlaps can contain equal hashes while the coverage still fails.
    return {
        "schema_version": 1, "ok": ok, "verdict": verdict,
        "complete_match_verified": complete, "coverage_ok": all_covered,
        "rollback_unavailable": rollback_unavailable,
        "recorded_states_match": all_states_match, "minimum_common_frames": min_frames,
        "scope": "Recorded finalized fighter-field and pad-read checksums; not a full-memory equivalence proof or a latency benchmark.",
        "errors": errors, "matches": records,
        "runtime": {"a": runtimes[0], "b": runtimes[1]},
        "limitations": [
            "No Parsec comparison or coast-to-coast performance conclusion is inferred.",
            "Without ended runtime reports, matching trace coverage does not prove a complete match finished.",
            "Timing reports expose p90 and p99, not p95; budget exceedances are not automatically visible hitches.",
        ],
    }


def verify_match(hash_a: str | Path, hash_b: str | Path, *, min_frames: int = 120,
                 runtime_a: str | Path | None = None, runtime_b: str | Path | None = None) -> dict[str, Any]:
    paths = [Path(hash_a), Path(hash_b)]
    if paths[0].resolve() == paths[1].resolve() or (paths[0].exists() and paths[1].exists() and paths[0].samefile(paths[1])):
        raise ValueError("Choose checksum logs from two different PCs, not the same file twice.")
    read = lambda path: Path(path).read_text(encoding="utf-8", errors="replace") if path is not None else None
    return compare_texts(read(paths[0]), read(paths[1]), min_frames=min_frames,
                         runtime_a=read(runtime_a), runtime_b=read(runtime_b))


def format_report(report: dict[str, Any]) -> str:
    lines = [report["verdict"].replace("_", " ").capitalize(), report["scope"]]
    for match in report["matches"]:
        c, s = match["coverage"], match["state"]
        lines.append(f"Match {match['match']}: {c['common_frames']} common frames; "
                     f"coverage {'adequate' if c['ok'] else 'incomplete'}; "
                     f"{s['different_frames']} differing recorded checksums.")
        lines.extend("  " + note for note in c["errors"] + match["execution"]["notes"])
    lines.extend("Error: " + error for error in report["errors"])
    if not report["complete_match_verified"]:
        lines.append("A complete match has not been verified.")
    lines.append("This does not establish that performance is better than Parsec.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hash_a", type=Path)
    parser.add_argument("hash_b", type=Path)
    parser.add_argument("--runtime-a", type=Path)
    parser.add_argument("--runtime-b", type=Path)
    parser.add_argument("--min-frames", type=int, default=120)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = verify_match(args.hash_a, args.hash_b, min_frames=args.min_frames,
                              runtime_a=args.runtime_a, runtime_b=args.runtime_b)
    except (OSError, ValueError) as exc:
        report = {"schema_version": 1, "ok": False, "verdict": "input_error", "complete_match_verified": False,
                  "errors": [str(exc)]}
        print(json.dumps(report, indent=2) if args.json else "Could not verify: " + str(exc))
        return 2
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
