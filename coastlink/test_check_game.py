"""Contract tests for the optional real-game check; no actual game is run."""
import tempfile
import unittest
from pathlib import Path

import check_game
import engine
from test_verify_match import runtime, trace


class CheckGameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def record(self, lateness, n=120, rollbacks=None):
        folder = self.root / str(lateness)
        folder.mkdir(exist_ok=True)
        record = {key: str(folder / key) for key in ("game_log", "runtime_log", "state_log")}
        Path(record["state_log"]).write_text(trace(n))
        rt = runtime(n, ended=False)
        if rollbacks is None:
            rollbacks = 0 if lateness == 0 else 20
        rt = rt.replace("20 rollbacks", f"{rollbacks} rollbacks")
        Path(record["runtime_log"]).write_text(rt)
        Path(record["game_log"]).write_text(
            f"[rbnet] loop: remote pads arrive {lateness} frames after the frame that would send them\n"
            "debug end: 120 fight frames reached at presented frame 700 (SSBU_DEBUG_END): exit request, normal shutdown\n")
        return record

    def test_sample_is_scoped_and_requires_real_rewinds(self):
        report = check_game.evaluate(self.record(0), self.record(5))
        self.assertTrue(report["ok"])
        self.assertFalse(report["complete_match_verified"])
        self.assertFalse(report["internet_tested"])
        self.assertFalse(report["performance_tested"])
        self.assertEqual(report["comparison"]["matches"][0]["coverage"]["common_frames"], 100)

    def test_short_common_prefix_is_rejected(self):
        self.assertFalse(check_game.evaluate(self.record(0), self.record(5, n=99))["ok"])

    def test_unexercised_rollback_rejected(self):
        self.assertFalse(check_game.evaluate(self.record(0), self.record(5, rollbacks=0))["ok"])

    def test_mismatched_prefix_rejected(self):
        a, b = self.record(0), self.record(5)
        p = Path(b["state_log"])
        p.write_text(p.read_text().replace("f 45 h 000000000000002d", "f 45 h ffffffffffffffff"))
        self.assertFalse(check_game.evaluate(a, b)["ok"])

    def test_menu_miss_rejected(self):
        a, b = self.record(0), self.record(5)
        Path(b["game_log"]).write_text("booted, no match\n")
        self.assertFalse(check_game.evaluate(a, b)["ok"])

    def test_memory_fallback_rejected(self):
        a, b = self.record(0), self.record(5)
        p = Path(b["runtime_log"])
        p.write_text("r1: RB NET report: this match ran WITHOUT rollback (not enough memory for the ring: base not made); matches without the ring so far 1\n" + p.read_text())
        self.assertFalse(check_game.evaluate(a, b)["ok"])

    def test_native_save_must_be_initialized(self):
        with self.assertRaisesRegex(engine.CoastlinkError, "Play Offline once"):
            check_game.initialized_save(self.root)

    def test_game_command_is_offline_explicit_and_disposable(self):
        (self.root / "tests").mkdir()
        (self.root / "tests" / "seq_n4_det.txt").write_text("@fight\n")
        save = self.root / "disposable" / "reference"
        command, _ = check_game.make_command(self.root, self.root / "build", save, self.root,
                                             lateness=5, version="13.0.4")
        env = dict(command[i + 1].split("=", 1) for i, v in enumerate(command) if v == "--env")
        self.assertEqual(env["SSBU_ONLINE"], "off")
        self.assertEqual(env["SSBU_RB_NET"], "loop,5")
        self.assertEqual(env["SSBU_DEBUG_END"], "120")
        self.assertEqual(env["SSBU_RB_NET_BOT"], "7")
        self.assertEqual(env["SSBU_RB_NET_LOOP_BOT2"], "11")
        self.assertIn(str(save), command)
        self.assertNotIn("--play", command)
        self.assertIn("ssbu_native_rb.exe", command)

    def test_timeout_and_lateness_bounds(self):
        with self.assertRaises(ValueError):
            check_game.make_command(self.root, self.root, self.root, self.root, lateness=5, version="13.0.4", timeout=181)
        with self.assertRaises(ValueError):
            check_game.make_command(self.root, self.root, self.root, self.root, lateness=12, version="13.0.4")

    def test_matching_prefix_does_not_hide_corruption_outside_prefix(self):
        a, b = self.record(0), self.record(5)
        p = Path(b["state_log"])
        p.write_text(p.read_text() + "f 120 h ffffffffffffffff\n")
        self.assertFalse(check_game.evaluate(a, b)["ok"])


if __name__ == "__main__":
    unittest.main()
