"""Game-free regression checks for Coastlink's evidence report."""
import tempfile
import unittest
from pathlib import Path

from verify_match import compare_texts, parse_runtime, verify_match


def trace(n=120, ident="12345678", number=1):
    return f"m {number} id {ident}\n" + "".join(f"f {f} h {f:016x}\n" for f in range(1, n + 1))


def runtime(n=120, ident="12345678", number=1, desyncs=0, ended=True):
    text = (
        f"r1: RB NET report: {n} real frames, 20 rollbacks, 32 frames run again "
        "(k: 1 10, 2 8, 3 2, 4 0, 5 0, 6 0, 7 0, more 0); rollbacks impossible (state not in the ring) 0\n"
        "r1: RB NET TIMING time between real passes (tick to tick): 119, mean 16.80 median 16.67 p90 17.00 p99 20.00 max 23.00 ms; over 16.67 ms: 70 (58.82%)\n"
        f"[rbnet] report (match {number}, id {ident}): {n} frames; delay 2; round trip mean 100.0 ms (best 80.0, 50 samples); clock offset estimate 0.5 ms, time-sync corrections 2\n"
        f"[rbnet] report: pads given 240, predicted 130 (54.2%), mispredictions 20; finalized frames {n}; checksums compared 40, DESYNCS {desyncs} (first -1)\n"
        "[rbnet] report: pad check of the final simulations: 0 pad values differ from the final ones (first frame -1)\n"
    )
    return text + (f"r1: RB NET: match {number} over: ring emptied, session reset for the next match\n" if ended else "")


class VerifyTests(unittest.TestCase):
    def test_empty_never_passes(self):
        r = compare_texts("", "")
        self.assertFalse(r["ok"])
        self.assertFalse(r["complete_match_verified"])

    def test_short_overlap_rejected(self):
        self.assertFalse(compare_texts(trace(2), trace(1))["ok"])

    def test_adequate_matching_recorded_frames_are_scoped(self):
        r = compare_texts(trace(), trace())
        self.assertTrue(r["ok"])
        self.assertEqual(r["verdict"], "recorded_checksums_match")
        self.assertFalse(r["complete_match_verified"])

    def test_one_sided_truncation_is_coverage_failure(self):
        r = compare_texts(trace(121), trace())
        self.assertFalse(r["ok"])
        self.assertTrue(r["matches"][0]["state"]["recorded_checksums_match"])
        self.assertFalse(r["coverage_ok"])

    def test_same_hole_in_both_logs_rejected(self):
        t = trace(121).replace("f 60 h 000000000000003c\n", "")
        self.assertFalse(compare_texts(t, t)["ok"])

    def test_frame_numbers_must_start_at_one(self):
        t = trace(121).replace("f 1 h 0000000000000001\n", "")
        self.assertFalse(compare_texts(t, t)["ok"])

    def test_conflicting_duplicate_rejected(self):
        t = trace() + "f 120 h ffffffffffffffff\n"
        self.assertFalse(compare_texts(t, trace())["ok"])

    def test_identical_duplicate_not_a_conflict(self):
        self.assertTrue(compare_texts(trace() + "f 120 h 78\n", trace())["ok"])

    def test_malformed_frame_rejected(self):
        self.assertFalse(compare_texts(trace() + "f nope h a\n", trace())["ok"])

    def test_missing_header_rejected(self):
        t = trace().split("\n", 1)[1]
        self.assertFalse(compare_texts(t, t)["ok"])

    def test_different_match_identifiers_rejected(self):
        self.assertFalse(compare_texts(trace(), trace(ident="87654321"))["ok"])

    def test_different_frames_report_first_mismatch(self):
        t = trace().replace("f 75 h 000000000000004b", "f 75 h 000000000000004c")
        r = compare_texts(t, trace())
        self.assertFalse(r["ok"])
        self.assertEqual(r["matches"][0]["state"]["first_difference"], 75)

    def test_missing_match_in_one_side_rejected(self):
        self.assertFalse(compare_texts(trace() + trace(number=2), trace())["ok"])

    def test_repeated_match_header_rejected(self):
        self.assertFalse(compare_texts(trace() + trace(), trace())["ok"])

    def test_detail_records_ignored(self):
        self.assertTrue(compare_texts(trace() + "d 120 p1 0 p2 0\n", trace())["ok"])

    def test_configurable_minimum(self):
        self.assertTrue(compare_texts(trace(3), trace(3), min_frames=3)["ok"])
        with self.assertRaises(ValueError):
            compare_texts(trace(), trace(), min_frames=0)

    def test_complete_report_requires_all_frames_and_end(self):
        r = compare_texts(trace(), trace(), runtime_a=runtime(), runtime_b=runtime())
        self.assertTrue(r["complete_match_verified"])
        self.assertEqual(r["verdict"], "complete_recorded_match_verified")

    def test_runtime_unended_does_not_claim_complete_match(self):
        r = compare_texts(trace(), trace(), runtime_a=runtime(ended=False), runtime_b=runtime())
        self.assertFalse(r["complete_match_verified"])

    def test_runtime_missing_final_frames_does_not_claim_complete_match(self):
        r = compare_texts(trace(), trace(), runtime_a=runtime(121), runtime_b=runtime())
        self.assertFalse(r["complete_match_verified"])

    def test_runtime_wrong_id_does_not_claim_complete_match(self):
        r = compare_texts(trace(), trace(), runtime_a=runtime(ident="87654321"), runtime_b=runtime())
        self.assertFalse(r["complete_match_verified"])

    def test_runtime_desync_cannot_pass_matching_trace(self):
        r = compare_texts(trace(), trace(), runtime_a=runtime(desyncs=1), runtime_b=runtime())
        self.assertFalse(r["ok"])

    def test_runtime_failure_line_cannot_pass_matching_trace(self):
        r = compare_texts(trace(), trace(), runtime_a="[rbnet] DESYNC: frame 7 checksum here ab, the other game ac\n")
        self.assertFalse(r["ok"])

    def test_memory_fallback_cannot_pass_as_working_rollback(self):
        rt = "r1: RB NET report: this match ran WITHOUT rollback (not enough memory for the ring: base not made); matches without the ring so far 1\n" + runtime()
        r = compare_texts(trace(), trace(), runtime_a=rt, runtime_b=runtime())
        self.assertFalse(r["ok"])
        self.assertEqual(r["verdict"], "rollback_unavailable")
        self.assertFalse(r["matches"][0]["execution"]["rollback_active"]["a"])
        self.assertFalse(r["complete_match_verified"])

    def test_impossible_rollback_state_cannot_pass(self):
        rt = runtime().replace("state not in the ring) 0", "state not in the ring) 1")
        self.assertFalse(compare_texts(trace(), trace(), runtime_a=rt, runtime_b=runtime())["ok"])

    def test_incorrect_final_pad_cannot_pass(self):
        rt = runtime().replace("0 pad values differ", "1 pad values differ")
        self.assertFalse(compare_texts(trace(), trace(), runtime_a=rt, runtime_b=runtime())["ok"])

    def test_exact_traffic_metrics_parsed(self):
        r = parse_runtime("[online] traffic: out 2 relayed + 90 direct, in 3 relayed + 88 direct; 1 peer(s), first direct\n")
        self.assertEqual(r["last_traffic_counters"]["out_direct"], 90)
        self.assertEqual(r["last_traffic_counters"]["last_first_peer_route"], "direct")

    def test_very_large_frame_number_is_rejected_without_large_allocation(self):
        t = trace() + "f 99999999999999999999 h 1\n"
        self.assertFalse(compare_texts(t, t)["ok"])

    def test_metrics_keep_p95_absent(self):
        metric = parse_runtime(runtime())["matches"][1]["timing"]["time between real passes (tick to tick)"]
        self.assertIsNone(metric["p95_ms"])
        self.assertEqual(metric["p99_ms"], 20.0)
        self.assertEqual(metric["over_budget_count"], 70)
        self.assertNotIn("hitch_count", metric)

    def test_unrecognized_metrics_are_not_invented(self):
        r = parse_runtime("arbitrary ping 1 ms fps 60\n")
        self.assertEqual(r["matches"], {})
        self.assertIsNone(r["last_traffic_counters"])

    def test_multiple_completed_matches(self):
        t = trace() + trace(number=2, ident="87654321")
        rt = runtime() + runtime(number=2, ident="87654321")
        r = compare_texts(t, t, runtime_a=rt, runtime_b=rt)
        self.assertTrue(r["complete_match_verified"])
        self.assertEqual(len(r["matches"]), 2)

    def test_same_file_selected_twice_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "a.hash.txt"
            p.write_text(trace())
            with self.assertRaises(ValueError):
                verify_match(p, p)

    def test_reading_two_files(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a", Path(folder) / "b"
            a.write_text(trace())
            b.write_text(trace())
            self.assertTrue(verify_match(a, b)["ok"])


if __name__ == "__main__":
    unittest.main()
