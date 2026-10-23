"""Integration-boundary tests using temporary fake game installations only."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import engine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "source with spaces"
        self.repo.mkdir()
        self.build = self.repo / "build"
        self.json(self.repo / "SOURCE.json", {"upstream_commit": engine.UPSTREAM_COMMIT})

    def file(self, path, content=b"test"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def json(self, path, content):
        return self.file(path, json.dumps(content).encode())

    def make_ready(self):
        work = self.build / "work"
        for name in ("ssbu_native.exe", "ssbu_native_rb.exe", "ssbu_game_eh_o1.dll", "ssbu_game_r1.dll", "SDL3.dll", "ssbu_glslang.dll"):
            self.file(work / name)
        for folder in ("nro_bin_eh_o2", "nro_bin_eh_o2r1"):
            self.file(work / folder / "lua2cpp_common.dll")
            self.file(work / folder / "lua2cpp_mario.dll")
        self.json(work / "ro_study" / "nro_map.json", [{"name": "lua2cpp_common"}, {"name": "lua2cpp_mario"}])
        self.file(self.build / "binaries" / "13.0.4" / "main.elf")
        self.file(self.build / "dump" / "romfs" / "data.arc")
        self.json(self.build / "state.json", {"game_version": "13.0.4", "dump": {"romfs": str(self.build / "dump" / "romfs")}})

    def env(self, command):
        return dict(command[index + 1].split("=", 1) for index, value in enumerate(command) if value == "--env")

    def test_fresh_compile_records_inline_mode_before_partial_work(self):
        engine.prime_incremental_stamps(self.build)
        for name in ("obj_eh_o1", "obj_r1"):
            directory = self.build / "work" / name
            self.assertEqual((directory / "_inline.txt").read_text().strip(), "1")
            self.file(directory / "partial.obj")
        engine.prime_incremental_stamps(self.build)
        self.assertTrue((self.build / "work" / "obj_eh_o1" / "partial.obj").is_file())

    def test_existing_unknown_compile_mode_is_never_relabeled(self):
        directory = self.build / "work" / "obj_eh_o1"
        self.file(directory / "partial.obj")
        engine.prime_incremental_stamps(self.build)
        self.assertFalse((directory / "_inline.txt").exists())
        self.file(directory / "_inline.txt", b"0\n")
        engine.prime_incremental_stamps(self.build)
        self.assertEqual((directory / "_inline.txt").read_text().strip(), "0")

    def test_discovers_selected_update_outside_library_and_dlc(self):
        data = self.repo / "emulator"
        library = self.repo / "library [games]"
        base = self.file(library / "Super Smash Bros Ultimate[01006A800016E000][v0].nsp")
        self.file(library / "Super Smash Ultimate [UPD].nsp", b"x" * 100)
        update = self.file(self.repo / "separate" / "Ultimate [13.0.4] [UPD].nsp")
        keys = self.file(data / "system" / "prod.keys", b"SECRET_NEVER_PRINT_THIS")
        dlc = self.file(self.repo / "DLC" / "fighter.nsp")
        disabled = self.file(self.repo / "DLC" / "disabled.nsp")
        self.json(data / "Config.json", {"game_dirs": [str(library)]})
        self.json(data / "games" / engine.TITLE_ID / "updates.json", {"selected": str(update)})
        self.json(data / "games" / engine.TITLE_ID / "dlc.json", [
            {"path": str(dlc), "dlc_nca_list": [{"is_enabled": True}]},
            {"path": str(disabled), "dlc_nca_list": [{"is_enabled": False}]},
        ])
        with patch.object(Path, "read_text", autospec=True, side_effect=Path.read_text) as reader:
            found = engine.discover(self.repo, data)
        self.assertEqual(found["base"], str(base.resolve()))
        self.assertEqual(found["update"], str(update.resolve()))
        self.assertEqual(found["keys"], str(keys.resolve()))
        self.assertEqual(found["game_version"], "13.0.4")
        self.assertEqual(found["dlc_files"], [str(dlc.resolve())])
        self.assertNotIn("SECRET", json.dumps(found))
        self.assertNotIn(keys, [call.args[0] for call in reader.call_args_list])

    def test_missing_or_malformed_emulator_config_returns_choices(self):
        found = engine.discover(self.repo, self.repo / "no emulator")
        self.assertIsNone(found["base"])
        self.assertIsNone(found["update"])
        self.assertGreaterEqual(len(found["notes"]), 2)

    def test_update_falls_back_to_existing_supported_path(self):
        data = self.repo / "emulator"
        update = self.file(self.repo / "update 13.0.5.nsp")
        self.json(data / "games" / engine.TITLE_ID / "updates.json", {"selected": "missing", "paths": [str(update)]})
        found = engine.discover(self.repo, data)
        self.assertEqual(found["update"], str(update.resolve()))
        self.assertEqual(found["game_version"], "13.0.5")

    def test_ready_requires_rollback_pair_and_modules(self):
        self.make_ready()
        self.assertTrue(engine.status(self.repo)["ready"])
        (self.build / "work" / "ssbu_game_r1.dll").unlink()
        result = engine.status(self.repo)
        self.assertFalse(result["ready"])
        self.assertIn("work/ssbu_game_r1.dll", result["missing"])

    def test_ready_rejects_incomplete_or_zero_byte_module(self):
        self.make_ready()
        self.file(self.build / "work" / "nro_bin_eh_o2r1" / "lua2cpp_mario.dll", b"")
        result = engine.status(self.repo)
        self.assertFalse(result["ready"])
        self.assertIn("work/nro_bin_eh_o2r1/lua2cpp_mario.dll", result["missing"])

    def test_ready_tolerates_moved_romfs_with_local_copy(self):
        self.make_ready()
        self.json(self.build / "state.json", {"game_version": "13.0.4", "dump": {"romfs": "now missing"}})
        self.assertTrue(engine.status(self.repo)["ready"])

    def test_launch_hard_fails_instead_of_regular_game_fallback(self):
        self.make_ready()
        (self.build / "work" / "ssbu_native_rb.exe").unlink()
        with self.assertRaisesRegex(engine.CoastlinkError, "Rollback is not installed"):
            engine.launch_command(self.repo, mode="host")
        self.assertFalse((self.build / "config" / "graphics.ini").exists())

    def test_host_and_join_have_opposite_roles_and_explicit_runtime_flags(self):
        self.make_ready()
        host, _ = engine.launch_command(self.repo, mode="host", stamp="host")
        join, _ = engine.launch_command(self.repo, mode="join", code="ABCDE-12345", stamp="join")
        self.assertEqual(self.env(host)["SSBU_RB_NET_PLAYER"], "0")
        self.assertEqual(self.env(join)["SSBU_RB_NET_PLAYER"], "1")
        self.assertEqual(self.env(host)["SSBU_RB_NET"], "net")
        self.assertEqual(self.env(join)["SSBU_ONLINE"], "join:ABCDE-12345")
        self.assertEqual(self.env(host)["SSBU_NRO_BIN"], "nro_bin_eh_o2r1")
        self.assertNotIn("SSBU_RB_NET_DELAY", self.env(host))      # (the runtime chooses it from the round trip)
        self.assertNotIn("SSBU_RB_NET_DELAY", self.env(join))
        self.assertNotIn("SSBU_RB_NET_DETAIL", self.env(host))
        self.assertIn("--play", host)
        self.assertTrue(self.env(host)["SSBU_RB_NET_LOG"].endswith(".hash.txt"))

    def test_online_build_id_carries_the_coastlink_version(self):
        self.make_ready()
        source = json.loads((self.repo / "SOURCE.json").read_text())
        source["version"] = "0.6.0-launcher-preview"
        (self.repo / "SOURCE.json").write_text(json.dumps(source))
        host, record = engine.launch_command(self.repo, mode="lobby-host", code="private_group")
        self.assertTrue(self.env(host)["SSBU_ONLINE_BUILD"].endswith("+cl0.6.0"))
        self.assertLessEqual(len(self.env(host)["SSBU_ONLINE_BUILD"]), 40)
        self.assertEqual(record["online_build"], self.env(host)["SSBU_ONLINE_BUILD"])
        offline, _ = engine.launch_command(self.repo, mode="offline")
        self.assertNotIn("SSBU_ONLINE_BUILD", self.env(offline))

    def test_lobby_mode_keeps_explicit_joiner_role(self):
        self.make_ready()
        host, _ = engine.launch_command(self.repo, mode="lobby-host", code="private_group")
        join, _ = engine.launch_command(self.repo, mode="lobby-join", code="private_group")
        self.assertEqual(self.env(host)["SSBU_ONLINE_CODE"], self.env(join)["SSBU_ONLINE_CODE"])
        self.assertEqual(self.env(host)["SSBU_RB_NET_PLAYER"], "0")
        self.assertEqual(self.env(join)["SSBU_RB_NET_PLAYER"], "1")
        self.assertEqual(self.env(join)["SSBU_ONLINE_DIRECT"], "1")

    def test_offline_disables_network_and_net_handshake(self):
        self.make_ready()
        command, _ = engine.launch_command(self.repo, mode="offline")
        self.assertEqual(self.env(command)["SSBU_ONLINE"], "off")
        self.assertEqual(self.env(command)["SSBU_RB_NET"], "0")
        self.assertNotIn("SSBU_RB_NET_DELAY", self.env(command))

    def test_saved_unlimited_speed_is_offline_only_in_actual_launch_arguments(self):
        self.make_ready()
        self.json(self.build / "config" / "coastlink_settings.json",
                  {"schema": 1, "launch": {"speed": "unlimited", "skip_movies": True}})
        offline, _ = engine.launch_command(self.repo, mode="offline")
        self.assertEqual(self.env(offline)["SSBU_SPEED"], "0")
        for mode in ("host", "join", "lobby-host", "lobby-join"):
            command, _ = engine.launch_command(self.repo, mode=mode, code="ABCDE-12345")
            self.assertEqual(self.env(command)["SSBU_SPEED"], "1", mode)
            self.assertEqual(self.env(command)["SSBU_SKIP_MOVIES"], "1", mode)
            self.assertEqual(self.env(command)["SSBU_RB_NET"], "net", mode)

    def test_rejects_invalid_codes_and_server_before_game_start(self):
        self.make_ready()
        for values in ({"mode": "join", "code": ""}, {"mode": "join", "code": "bad\ncode"},
                       {"mode": "lobby-join", "code": "ok_code", "server": "server:99999"}):
            with self.assertRaises(engine.CoastlinkError):
                engine.launch_command(self.repo, **values)

    def test_ini_changes_preserve_unrelated_settings_and_remove_duplicate_keys(self):
        ini = self.file(self.build / "config" / "graphics.ini", b"# My settings\nvolume = 0.6\nrollback = off\nrollback = off\nonline_mode = lobby\n")
        engine.set_ini_values(ini, {"rollback": "on", "online_mode": "off"})
        text = ini.read_text()
        self.assertIn("volume = 0.6", text)
        self.assertIn("# My settings", text)
        self.assertEqual(text.count("rollback = on"), 1)
        self.assertNotIn("rollback = off", text)
        self.assertIn("online_mode = off", text)

    def test_install_is_pinned_rollback_resume_and_shell_safe(self):
        base = self.file(self.repo / "game [base].nsp")
        update = self.file(self.repo / "game 13.0.4 [update].nsp")
        keys = self.file(self.repo / "prod.keys")
        command = engine.install_command(self.repo, base=base, update=update, keys=keys, jobs=4, dry_run=True)
        self.assertIn("--no-self-update", command)
        self.assertIn("--no-shortcuts", command)
        self.assertIn("--rollback", command)
        self.assertIn("--dry-run", command)
        self.assertIn(str(base), command)
        self.assertIn(str(update), command)
        self.assertNotIn("--runtime-any-tree", command)

    def test_install_rejects_missing_input_and_oversubscribed_jobs(self):
        item = self.file(self.repo / "exists")
        with self.assertRaises(engine.CoastlinkError):
            engine.install_command(self.repo, base=self.repo / "absent", update=item, keys=item)
        with self.assertRaises(engine.CoastlinkError):
            engine.install_command(self.repo, base=item, update=item, keys=item, jobs=12)

    def test_launch_refuses_mismatched_source_package(self):
        self.make_ready()
        self.json(self.repo / "SOURCE.json", {"upstream_commit": "different"})
        with self.assertRaisesRegex(engine.CoastlinkError, "different versions"):
            engine.launch_command(self.repo, mode="host")

    def test_launch_refuses_missing_source_record(self):
        self.make_ready()
        (self.repo / "SOURCE.json").unlink()
        with self.assertRaisesRegex(engine.CoastlinkError, "source version record"):
            engine.launch_command(self.repo, mode="host")

    def test_ready_accepts_rollback_without_unused_normal_version(self):
        self.make_ready()
        for path in (self.build / "work" / "nro_bin_eh_o2").glob("*.dll"):
            path.unlink()
        for name in ("ssbu_native.exe", "ssbu_game_eh_o1.dll"):
            (self.build / "work" / name).unlink()
        self.assertTrue(engine.status(self.repo)["ready"])
        command, _ = engine.launch_command(self.repo, mode="host")
        self.assertIn(str(self.repo / "coastlink" / "run_rollback.py"), command)

    def test_ready_rejects_missing_expected_module_map(self):
        self.make_ready()
        (self.build / "work" / "ro_study" / "nro_map.json").unlink()
        self.assertFalse(engine.status(self.repo)["ready"])

    def test_disk_reserve_is_resume_safe(self):
        with patch("engine.shutil.disk_usage", return_value=argparse.Namespace(free=5 * 1024**3)):
            engine.check_disk_reserve(self.build)
        with patch("engine.shutil.disk_usage", return_value=argparse.Namespace(free=3 * 1024**3)):
            with self.assertRaisesRegex(engine.CoastlinkError, "Keep at least 4 GiB"):
                engine.check_disk_reserve(self.build)

    def test_build_location_is_honored(self):
        location = self.repo / "another drive folder"
        self.file(self.repo / "build_location.txt", (str(location) + "\n").encode())
        self.assertEqual(engine.build_path(self.repo), location.resolve())
        self.assertEqual(engine.build_path(self.repo, self.build), self.build.resolve())

    def test_game_log_is_forwarded_live_without_frame_trace_flood(self):
        game_log = self.repo / "game.log"
        script = "from pathlib import Path; import time; p=Path(" + repr(str(game_log)) + "); p.write_text('nvn_vk_store: 63 % of data.arc read, 93080 zstd frames\\nnvn_vk_prep: progress: 109 of 521 containers read, 1273 variations, 644 of 1273 done by the workers, 40.0 s\\n[online] host: ROOM CODE ABCDE-12345\\nper-frame secret noise\\n[rbnet] both games have the ring\\n'); time.sleep(.4)"
        output = io.StringIO()
        with redirect_stdout(output):
            result = engine.run_game_monitored([sys.executable, "-u", "-c", script], self.repo,
                                               {"game_log": str(game_log), "mode": "host"})
        self.assertEqual(result, 0)
        self.assertIn("ROOM CODE ABCDE-12345", output.getvalue())
        self.assertIn("both games have the ring", output.getvalue())
        self.assertIn("STARTUP: Preparing graphics: reading game assets, 63%.", output.getvalue())
        self.assertIn("644 jobs finished; 109/521 graphics files scanned.", output.getvalue())
        self.assertNotIn("per-frame secret noise", output.getvalue())

    def test_memory_fallback_stops_only_owned_subprocess(self):
        game_log = self.repo / "fallback.log"
        script = "from pathlib import Path; import time; Path(" + repr(str(game_log)) + ").write_text('[rbnet] rollback OFF for this match (not enough memory)\\n'); time.sleep(20)"
        started = time.monotonic()
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(engine.CoastlinkError, "stopped this game"):
                engine.run_game_monitored([sys.executable, "-u", "-c", script], self.repo,
                                          {"game_log": str(game_log), "mode": "host"})
        self.assertLess(time.monotonic() - started, 10)

    def test_peer_without_ring_is_also_rejected(self):
        self.assertTrue(engine.rollback_fell_back("[rbnet] after the start barrier: the other game has no snapshot ring: delay-based pacing"))
        self.assertFalse(engine.rollback_fell_back("[rbnet] after the start barrier: both games have the ring"))

    def test_log_follower_preserves_partial_lines_and_handles_truncation(self):
        path = self.file(self.repo / "follow.log", b"[online] ROOM")
        follower = engine.LogFollower(path)
        self.assertEqual(follower.read_lines(), [])
        with path.open("ab") as stream:
            stream.write(b" CODE ABCDE-12345\n")
        self.assertEqual(follower.read_lines(), ["[online] ROOM CODE ABCDE-12345"])
        path.write_bytes(b"reset\n")
        self.assertEqual(follower.read_lines(), ["reset"])

    def test_evidence_merges_actual_runtime_and_route_without_frame_noise(self):
        runtime = self.file(self.repo / "runtime.txt", b"r1: R2 ring: frames 120, report\n[rbnet] report (match 1): frames 120\n")
        game = self.file(self.repo / "game.txt", b"[online] direct 80 ms\nper-frame noise\n[rbnet] both games have the ring\n[rbnet] report (match 1): frames 120\n")
        evidence = self.repo / "evidence.txt"
        engine.write_evidence({"mode": "host", "runtime_log": str(runtime), "game_log": str(game), "evidence_log": str(evidence)})
        content = evidence.read_text()
        self.assertIn("r1: R2 ring: frames 120", content)
        self.assertIn("[online] direct 80 ms", content)
        self.assertIn("[rbnet] both games have the ring", content)
        self.assertEqual(content.count("[rbnet] report (match 1)"), 1)
        self.assertNotIn("per-frame noise", content)

    def test_build_lock_blocks_a_separate_process_and_retry_succeeds(self):
        script = ("import sys; from pathlib import Path; sys.path.insert(0, " + repr(str(Path(engine.__file__).parent)) + "); import engine\n"
                  "try:\n"
                  "    with engine.BuildLock(Path(sys.argv[1])):\n"
                  "        print('ACQUIRED')\n"
                  "except engine.CoastlinkError as error:\n"
                  "    print(str(error))\n"
                  "    sys.exit(23)\n")
        def attempt():
            return subprocess.run([sys.executable, "-B", "-c", script, str(self.build)], capture_output=True, text=True, timeout=10)
        self.assertFalse(engine.build_in_progress(self.build))
        with engine.BuildLock(self.build):
            blocked = attempt()
            self.assertEqual(blocked.returncode, 23, blocked.stdout + blocked.stderr)
            self.assertIn("another Coastlink window", blocked.stdout)
            self.assertTrue(engine.status(self.repo)["build_in_progress"])
        self.assertFalse(engine.status(self.repo)["build_in_progress"])
        retried = attempt()
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertIn("ACQUIRED", retried.stdout)
        self.assertTrue((self.build / "coastlink.install.lock").is_file())

    def test_installer_holds_build_lock_and_releases_it_on_failure(self):
        args = argparse.Namespace(build_dir=None)
        def failed_install(repo, actual_args):
            self.assertTrue(engine.build_in_progress(self.build))
            raise engine.CoastlinkError("simulated compiler failure")
        with patch("engine._install_locked", side_effect=failed_install):
            with self.assertRaisesRegex(engine.CoastlinkError, "simulated compiler failure"):
                engine.install(self.repo, args)
        self.assertFalse(engine.build_in_progress(self.build))
        with engine.BuildLock(self.build):
            self.assertTrue(engine.build_in_progress(self.build))

    def test_launch_refuses_a_build_currently_being_compiled(self):
        self.make_ready()
        with engine.BuildLock(self.build):
            with self.assertRaisesRegex(engine.CoastlinkError, "still being installed or compiled"):
                engine.launch_command(self.repo, mode="host")

    def test_windows_long_path_strings_preserve_short_paths_and_prefix_absolute_paths(self):
        short = r"C:\Games\Ultimate.nsp"
        self.assertEqual(engine.windows_long_path(short), short)
        local = "C:\\" + "folder\\" * 40 + "game.nsp"
        self.assertEqual(engine.windows_long_path(local), "\\\\?\\" + local)
        unc = "\\\\server\\share\\" + "folder\\" * 40 + "game.nsp"
        self.assertEqual(engine.windows_long_path(unc), "\\\\?\\UNC\\" + unc[2:])
        extended = "\\\\?\\" + local
        self.assertEqual(engine.windows_long_path(extended), extended)
        relative = "folder\\" * 40 + "game.nsp"
        self.assertEqual(engine.windows_long_path(relative), relative)

    def test_windows_long_path_canonicalizes_before_prefix_and_counts_utf16(self):
        raw = "C:/games/./" + "folder/" * 40 + "../game.nsp"
        converted = engine.windows_long_path(raw)
        self.assertTrue(converted.startswith("\\\\?\\C:\\games\\"))
        self.assertNotIn("/", converted)
        self.assertNotIn("..", converted)
        unicode_path = "C:\\" + "\U0001f3ae" * 130 + ".nsp"
        self.assertLess(len(unicode_path), 260)
        self.assertTrue(engine.windows_long_path(unicode_path).startswith("\\\\?\\"))

    @unittest.skipUnless(os.name == "nt", "Windows extended-path filesystem test")
    def test_real_overlong_dlc_is_discovered_enumerated_and_passed_to_installer(self):
        # Explicitly extended test root lets cleanup remove long generated paths
        # even on Windows installations where global long-path support is off.
        extended_root = Path("\\\\?\\" + str(self.repo.resolve()))
        self.addCleanup(shutil.rmtree, extended_root)
        folder = self.repo / ("a" * 100) / ("b" * 100)
        extended_folder = extended_root / ("a" * 100) / ("b" * 100)
        extended_folder.mkdir(parents=True)
        name = "DLC costume " + "c" * 80 + " [01006A800016F001].nsp"
        extended_file = extended_folder / name
        extended_file.write_bytes(b"test package")
        plain_file = folder / name
        self.assertGreater(len(str(plain_file)), 260)
        located = engine._existing_file(str(plain_file))
        self.assertIsNotNone(located)
        self.assertTrue(str(located).startswith("\\\\?\\"))
        packages = list(engine._package_files(folder))
        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0], located)
        data = self.repo / "emulator"
        self.json(data / "games" / engine.TITLE_ID / "dlc.json", [{"path": str(plain_file), "dlc_nca_list": [{"is_enabled": True}]}])
        found = engine.discover(self.repo, data)
        self.assertEqual(found["dlc_files"], [str(located)])
        self.assertEqual(found["missing_dlc_files"], [])
        base = self.file(self.repo / "base.nsp")
        update = self.file(self.repo / "update 13.0.4.nsp")
        keys = self.file(self.repo / "prod.keys")
        command = engine.install_command(self.repo, base=base, update=update, keys=keys, dlc_files=[plain_file])
        self.assertEqual(command[command.index("--dlc") + 1], str(located))

    def test_missing_configured_dlc_is_reported_and_not_silently_omitted(self):
        data = self.repo / "emulator"
        missing = self.repo / "missing DLC.nsp"
        self.json(data / "games" / engine.TITLE_ID / "dlc.json", [{"path": str(missing)}])
        found = engine.discover(self.repo, data)
        self.assertEqual(found["missing_dlc_files"], [str(missing)])
        self.assertIn("missing", " ".join(found["notes"]))
        args = argparse.Namespace(emulator_data=data, build_dir=None, base=str(self.file(self.repo / "base.nsp")),
                                  update=str(self.file(self.repo / "update.nsp")), keys=str(self.file(self.repo / "prod.keys")), dlc_folder=None)
        with patch("engine.subprocess.Popen") as process:
            with self.assertRaisesRegex(engine.CoastlinkError, "will not silently omit"):
                engine._install_locked(self.repo, args)
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
