import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import app_backend
import controller_config
import engine
import update_apply

GAME_LOG = """[online] match: matched with Kai (10.13.7.10) for a rollback match: this game is player 1
[rbnet] transport: direct UDP (validated path; relay backup every 100 ms); direct RTT 94 ms; data out 1 direct / 1 relay
[rbnet] match 1 (id 2fe49683) start at frame 0: local player 1, input delay 4 frames (round trip 96.1 ms, best 94.0 ms)
nvn_vk_prep: progress: 300 of 521 containers read, 1 variations
[rbnet] report (match 1, id 2fe49683): 10722 frames; delay 4; round trip mean 97.5 ms (best 89.4, 2168 samples); clock offset estimate 15.0 ms
[rbnet] report: pads given 22542, predicted 4624 (20.5%), mispredictions 341; finalized frames 10722; checksums compared 9353, DESYNCS 0 (first -1)
[rbnet] match 2 (id 3b78ad31) start at frame 0: local player 1, input delay 3 frames (round trip 90.0 ms, best 89.0 ms)
nvn_vk_prep: report (finished): 521 of 521 containers read, 42382 variations
"""
RUNTIME = "r1: RB NET: frame 600: 38 rollbacks (133 frames again), 7 stalls (50 ms), round trip 98 ms, delay 4, remote pads up to 603\n"


class LogParsingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        (self.build / "logs").mkdir()

    def write(self, name, text):
        path = self.build / "logs" / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_session_summary_reads_opponent_matches_ping_and_sync(self):
        log = self.write("coastlink_game_20261022_132438_245813.log", GAME_LOG)
        row = app_backend.session_summary(log)
        self.assertEqual(row["opponent"], "Kai")
        self.assertEqual(row["matches"], 2)
        self.assertEqual(row["avg_ping_ms"], 98)
        self.assertEqual(row["sync"], "match")
        self.assertEqual(row["stamp"], "20261022_132438")

    def test_offline_session_is_not_listed_and_desync_is_flagged(self):
        self.write("coastlink_game_20261022_100000_1.log", "graphics options: read\n")
        self.write("coastlink_game_20261022_110000_1.log", GAME_LOG.replace("DESYNCS 0", "DESYNCS 3"))
        rows = app_backend.recent_sessions(self.build)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sync"], "check")

    def test_live_session_numbers(self):
        self.write("coastlink_game_20261022_132438_245813.log", GAME_LOG)
        self.write("coastlink_runtime_20261022_132438_245813.txt", RUNTIME)
        live = app_backend.live_session(self.build)
        self.assertEqual((live["route"], live["input_delay"], live["rollbacks"], live["stalls"]), ("direct", 4, 38, 7))
        self.assertEqual(live["ping_ms"], 98)

    def test_shader_status_uses_the_newest_report(self):
        self.write("coastlink_game_20261022_132438_245813.log", GAME_LOG)
        status = app_backend.shader_status(self.build)
        self.assertTrue(status["done"])
        self.assertEqual((status["read"], status["total"]), (521, 521))

    def test_bundle_holds_only_the_newest_sessions(self):
        self.write("coastlink_game_20261022_132438_1.log", GAME_LOG)
        self.write("coastlink_runtime_20261022_132438_1.txt", RUNTIME)
        old = self.write("coastlink_game_20201010_101010_1.log", "old")
        os.utime(old, (1, 1))
        target = app_backend.bundle_logs(self.build, self.build / "out.zip", sessions=1)
        names = zipfile.ZipFile(target).namelist()
        self.assertIn("coastlink_runtime_20261022_132438_1.txt", names)
        self.assertNotIn("coastlink_game_20201010_101010_1.log", names)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "coastlink").mkdir()
        (self.repo / "coastlink" / "engine.py").write_text("old engine")
        (self.repo / "SOURCE.json").write_text(json.dumps({"product": "CoastLink", "version": "0.5.3", "upstream_commit": engine.UPSTREAM_COMMIT}))
        (self.repo / "build" / "saves").mkdir(parents=True)
        (self.repo / "build" / "saves" / "user.save").write_bytes(b"KEEP")

    def make(self, files, *, manifest_extra=None, tamper=None):
        manifest = {"product": "CoastLink", "version": "0.6.0", "upstream_commit": engine.UPSTREAM_COMMIT,
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        manifest.update(manifest_extra or {})
        path = self.repo / "update.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, tamper if tamper and name == "coastlink/engine.py" else data)
            archive.writestr(update_apply.MANIFEST, json.dumps(manifest))
        return path

    def test_apply_backs_up_and_roll_back_restores(self):
        path = self.make({"coastlink/engine.py": b"new engine", "coastlink/new_module.py": b"x", "CoastLink.exe": b"MZ new"})
        result = update_apply.apply_update(self.repo, path)
        self.assertEqual(result["changed"], 3)
        self.assertTrue(result["restart_app"])
        self.assertEqual((self.repo / "coastlink" / "engine.py").read_bytes(), b"new engine")
        self.assertEqual((self.repo / "CoastLink.exe.new").read_bytes(), b"MZ new")
        self.assertEqual((self.repo / "build" / "saves" / "user.save").read_bytes(), b"KEEP")
        update_apply.roll_back(self.repo)
        self.assertEqual((self.repo / "coastlink" / "engine.py").read_text(), "old engine")
        self.assertFalse((self.repo / "coastlink" / "new_module.py").exists())

    def test_tampered_or_foreign_files_are_refused_before_any_write(self):
        with self.assertRaisesRegex(update_apply.UpdateError, "Checksum failed"):
            update_apply.apply_update(self.repo, self.make({"coastlink/engine.py": b"new"}, tamper=b"evil"))
        self.assertEqual((self.repo / "coastlink" / "engine.py").read_text(), "old engine")
        for bad in ("build/saves/user.save", "deps/python/python.exe", "../outside.py", "C:/x.py", "game.nsp", "other/thing.py"):
            with self.assertRaises(update_apply.UpdateError, msg=bad):
                update_apply.canonical(bad)

    def test_wrong_product_or_whole_file_hash_refused(self):
        with self.assertRaisesRegex(update_apply.UpdateError, "not for this CoastLink"):
            update_apply.apply_update(self.repo, self.make({"coastlink/engine.py": b"n"}, manifest_extra={"upstream_commit": "0" * 40}))
        with self.assertRaisesRegex(update_apply.UpdateError, "SHA-256"):
            update_apply.apply_update(self.repo, self.make({"coastlink/engine.py": b"n"}), expected_sha256="0" * 64)

    def test_feed_from_repo_name_and_https_only(self):
        config = update_apply.save_config(self.repo, {"repo": "someone/coastlink"})
        self.assertTrue(config["feed"].startswith("https://github.com/someone/coastlink/releases/latest/download/"))
        with self.assertRaises(update_apply.UpdateError):
            update_apply.save_config(self.repo, {"feed": "http://insecure.example/feed.json"})


class ControllerConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        (self.build / "config").mkdir()
        (self.build / "config" / "controllers.ini").write_text("; keep me\n[general]\ndeadzone = 0.10\n[future]\nx = 1\n")

    def test_players_and_device_bindings_round_trip_keeping_other_sections(self):
        guid = "03000000de280000ff11000000007801"
        controller_config.save(self.build, {"players": {"1": guid, "2": "none"}, "devices": {guid: {"map.A": "south", "deadzone": "0.15"}}})
        loaded = controller_config.load(self.build)
        self.assertEqual(loaded["players"]["1"], guid)
        self.assertEqual(loaded["players"]["2"], "none")
        self.assertEqual(loaded["devices"][guid]["map.a"], "south")
        text = (self.build / "config" / "controllers.ini").read_text()
        self.assertIn("; keep me", text)
        self.assertIn("[future]", text)

    def test_bad_values_refused(self):
        with self.assertRaises(Exception):
            controller_config.save(self.build, {"players": {"9": "auto"}})
        with self.assertRaises(Exception):
            controller_config.save(self.build, {"devices": {"03000000de280000ff11000000007801": {"map.A": "laser"}}})

    def test_profiles_save_load_delete(self):
        guid, other = "03000000de280000ff11000000007801", "030000005e0400008e02000000007801"
        controller_config.save(self.build, {"devices": {guid: {"map.B": "north"}}})
        self.assertEqual(controller_config.profiles(self.build, {"action": "save", "name": "Main", "guid": guid})["profiles"], ["Main"])
        controller_config.profiles(self.build, {"action": "load", "name": "Main", "guid": other})
        self.assertEqual(controller_config.load(self.build)["devices"][other]["map.b"], "north")
        self.assertEqual(controller_config.profiles(self.build, {"action": "delete", "name": "Main"})["profiles"], [])

    def test_type_profiles_and_native_defaults_are_available_without_writing(self):
        file = self.build / 'config' / 'controllers.ini'
        file.write_text('[general]\ndeadzone = 0.12\n[type xbox]\nmap.A = south\nlayout = labels\n')
        before = file.read_bytes()
        cfg = controller_config.load(self.build)
        self.assertEqual(cfg['types']['xbox']['map.a'], 'south')
        self.assertEqual(cfg['general']['deadzone'], '0.12')
        self.assertEqual(cfg['general']['outer_zone'], '0.98')
        self.assertEqual(file.read_bytes(), before)

    def test_default_binding_removes_override_and_bad_ranges_do_not_save(self):
        guid = '03000000de280000ff11000000007801'
        controller_config.save(self.build, {'devices': {guid: {'map.A': 'north'}}})
        result = controller_config.save(self.build, {'devices': {guid: {'map.A': 'default'}}})
        self.assertNotIn('map.a', result['devices'][guid])
        file = self.build / 'config' / 'controllers.ini'
        before = file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'dead zone'):
            controller_config.save(self.build, {'devices': {guid: {'deadzone': '0.9', 'outer_zone': '0.5'}}})
        self.assertEqual(file.read_bytes(), before)

    def test_profile_restore_replaces_stale_mappings_and_keeps_stick_axes(self):
        guid, other = '03000000de280000ff11000000007801', '030000005e0400008e02000000007801'
        controller_config.save(self.build, {'devices': {guid: {'axis.LX': 'rightx', 'invert.LY': 'on', 'map.A': 'south'}}})
        controller_config.profiles(self.build, {'action': 'save', 'name': 'Stick setup', 'guid': guid})
        controller_config.save(self.build, {'devices': {other: {'map.B': 'north', 'rumble': 'off'}}})
        controller_config.profiles(self.build, {'action': 'load', 'name': 'Stick setup', 'guid': other})
        cfg = controller_config.load(self.build)['devices'][other]
        self.assertEqual(cfg['axis.lx'], 'rightx')
        self.assertEqual(cfg['invert.ly'], 'on')
        self.assertEqual(cfg['map.a'], 'south')
        self.assertNotIn('map.b', cfg)
        self.assertNotIn('rumble', cfg)
        controller_config.profiles(self.build, {'action': 'save', 'name': 'Defaults', 'guid': '0' * 32})
        controller_config.profiles(self.build, {'action': 'load', 'name': 'Defaults', 'guid': other})
        self.assertEqual(controller_config.load(self.build)['devices'][other], {})


class ShaderCacheTests(unittest.TestCase):
    def test_clear_only_shader_folders_and_invalidate_old_preparation_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            (build / 'logs').mkdir()
            old = build / 'logs' / 'coastlink_game_old.log'
            old.write_text('nvn_vk_prep: report (finished): 521 of 521 containers read\n')
            for name in ('vk', 'shaders'):
                target = build / 'cache' / name
                target.mkdir(parents=True)
                (target / 'shader.bin').write_bytes(b'cache')
            keep = build / 'cache' / 'my-notes.txt'
            keep.write_bytes(b'keep me')
            self.assertTrue(app_backend.shader_status(build)['done'])
            self.assertEqual(app_backend.clear_shader_cache(build), 2)
            self.assertEqual(keep.read_bytes(), b'keep me')
            self.assertFalse(app_backend.shader_status(build)['done'])
            new = build / 'logs' / 'coastlink_game_new.log'
            new.write_text('nvn_vk_prep: FINISHED: 521 of 521 containers read\n')
            cleared = json.loads((build / 'config' / 'coastlink_shader_cache.json').read_text())['cleared_at']
            os.utime(new, (cleared + 1, cleared + 1))
            self.assertTrue(app_backend.shader_status(build)['done'])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction protection')
    def test_linked_cache_is_refused_before_any_cache_is_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build, outside = root / 'build', root / 'outside'
            (build / 'cache' / 'vk').mkdir(parents=True)
            first = build / 'cache' / 'vk' / 'keep.bin'
            first.write_bytes(b'keep')
            outside.mkdir()
            external = outside / 'keep.bin'
            external.write_bytes(b'outside')
            junction = build / 'cache' / 'shaders'
            result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(junction), str(outside)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            try:
                with self.assertRaisesRegex(ValueError, 'junction'):
                    app_backend.clear_shader_cache(build)
                self.assertEqual(first.read_bytes(), b'keep')
                self.assertEqual(external.read_bytes(), b'outside')
            finally:
                os.rmdir(junction)


class SidecarProtocolTests(unittest.TestCase):
    def test_hello_answer_and_unknown_command_error_over_json_lines(self):
        here = Path(__file__).resolve().parent
        process = subprocess.run([sys.executable, "-u", str(here / "sidecar.py")], input='{"id":1,"cmd":"logs.folder"}\n{"id":2,"cmd":"nope"}\n',
                                 capture_output=True, text=True, timeout=60, cwd=here.parent)
        lines = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
        self.assertEqual(lines[0]["event"], "ready")
        answers = {line["id"]: line for line in lines if "id" in line}
        self.assertTrue(answers[1]["ok"])
        self.assertFalse(answers[2]["ok"])
        self.assertIn("Unknown command", answers[2]["error"])

    def test_verify_infers_each_pcs_adjacent_evidence_and_respects_explicit_paths(self):
        from test_verify_match import trace, runtime
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = []
            for computer in ('mine', 'friend'):
                folder = root / computer
                folder.mkdir()
                hash_file = folder / 'coastlink_state_20261023_120000_123456.hash.txt'
                hash_file.write_text(trace())
                (folder / 'coastlink_evidence_20261023_120000_123456.log').write_text(runtime())
                # A raw, incomplete runtime must not take precedence over complete combined evidence.
                (folder / 'coastlink_runtime_20261023_120000_123456.txt').write_text('partial runtime')
                state.append(str(hash_file))
            explicit = root / 'explicit-incomplete.txt'
            explicit.write_text('partial runtime')
            requests = [
                {'id': 1, 'cmd': 'verify', 'args': {'mine': state[0], 'theirs': state[1]}},
                {'id': 2, 'cmd': 'verify', 'args': {'mine': state[0], 'theirs': state[1], 'theirs_runtime': str(explicit)}},
            ]
            process = subprocess.run([sys.executable, '-B', str(Path(__file__).parent / 'sidecar.py')],
                                     input='\n'.join(map(json.dumps, requests)) + '\n', capture_output=True, text=True, timeout=20)
            answers = {line['id']: line for line in map(json.loads, process.stdout.splitlines()) if 'id' in line}
            self.assertTrue(answers[1]['ok'], answers[1])
            self.assertTrue(answers[1]['result']['report']['complete_match_verified'])
            self.assertFalse(answers[2]['result']['report']['complete_match_verified'])


class FakeLobby:
    """JOIN -> WELCOME, PING -> PONG with the counts net_relay.c's lobby sends (players of this build and code, of this code)."""
    def __init__(self):
        import socket, struct, threading
        self.struct = struct
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.clients = {}                      # cookie -> (code, build)
        self.next = 1
        threading.Thread(target=self.run, daemon=True).start()

    def cookie(self):
        self.next += 1
        return self.next

    def add(self, code, build):
        self.clients[self.cookie()] = (code, build)

    def run(self):
        s = self.struct
        while True:
            try:
                p, at = self.sock.recvfrom(2048)
            except OSError:
                return
            kind = p[3]
            if kind == 1:
                code, build = p[12:44].rstrip(b"\0").decode(), p[76:116].rstrip(b"\0").decode()
                cookie = self.cookie()
                self.clients[cookie] = (code, build)
                self.sock.sendto(b"SU\x01\x02" + p[4:12] + s.pack(">IQ", 0x0A0D0001, cookie), at)
            elif kind == 4:
                code, build = self.clients[s.unpack_from(">Q", p, 4)[0]]
                same = sum(1 for c in self.clients.values() if c == (code, build))
                all_code = sum(1 for c in self.clients.values() if c[0] == code)
                self.sock.sendto(b"SU\x01\x05" + p[12:20] + s.pack(">HHHH", same, 0, 0, all_code), at)
            elif kind == 7:
                self.clients.pop(s.unpack_from(">Q", p, 4)[0], None)


class NetCheckTests(unittest.TestCase):
    def test_probe_sees_same_and_other_versions_and_names_the_other_version(self):
        import net_check
        lobby = FakeLobby()
        server = f"127.0.0.1:{lobby.port}"
        mine = "ssbu-recomp-ldn1-13.0.4+cl0.6.0"
        lobby.add("tuesday", mine)
        lobby.add("tuesday", "ssbu-recomp-ldn1-13.0.4")         # a friend still on 0.5.x
        result = net_check.lobby_probe(server, "tuesday", mine)
        self.assertTrue(result["reachable"])
        self.assertEqual((result["waiting_same_version"], result["waiting_other_version"]), (1, 1))
        self.assertEqual(net_check.identify_other_versions(server, "tuesday", "13.0.4", "0.6.0"), ["0.5.x or older"])
        self.assertEqual(net_check.lobby_probe(server, "other-code", mine)["waiting_same_version"], 0)

    def test_unreachable_lobby_is_a_readable_answer(self):
        import net_check
        import socket
        free = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        result = net_check.lobby_probe(f"127.0.0.1:{port}", "x", "b", timeout=1.0)
        self.assertFalse(result["reachable"])
        self.assertIn("No answer", result["error"])


class AudioSettingsTests(unittest.TestCase):
    def test_audio_keys_saved_and_untouched_files_keep_their_time(self):
        import settings
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            settings.save_settings(build, {"graphics": {"volume": "40"}})
            controllers = build / "config" / "controllers.ini"
            before = controllers.stat().st_mtime_ns
            os.utime(controllers, ns=(before - 10_000_000_000, before - 10_000_000_000))
            stamp = controllers.stat().st_mtime_ns
            settings.save_settings(build, {"graphics": {"volume": "55", "mute_background": "on", "audio_device": "Speakers (USB AUDIO  CODEC)"}})
            graphics = settings.get_settings(build)["graphics"]
            self.assertEqual((graphics["volume"], graphics["mute_background"], graphics["audio_device"]), ("55", "on", "Speakers (USB AUDIO  CODEC)"))
            self.assertEqual(controllers.stat().st_mtime_ns, stamp)
            with self.assertRaises(settings.SettingsError):
                settings.save_settings(build, {"graphics": {"mute_background": "maybe"}})


class GameCubeDiagnosticsTests(unittest.TestCase):
    def test_adapter_report_ports_and_buttons(self):
        import pads
        report = bytes([0x21] + [0x10, 0x01 | 0x80, 0x02 | 0x01, 128, 128, 128, 128, 30, 30] + [0x00] * 9
                       + [0x20, 0, 0x08, 1, 2, 3, 4, 5, 6] + [0x00] * 9)
        ports = pads.parse_gca_report(report)
        self.assertEqual([p["connected"] for p in ports], [True, False, True, False])
        self.assertEqual(ports[0]["pressed"], ["A", "Up", "Start", "Z"])
        self.assertTrue(ports[2]["wireless"])
        self.assertEqual(ports[2]["pressed"], ["L"])
        self.assertIsNone(pads.parse_gca_report(b"\x22" + bytes(36)))
        self.assertIsNone(pads.parse_gca_report(b"\x21"))

    def test_models_from_type_and_usb_ids(self):
        import pads
        self.assertEqual(pads.model_key(3, 0x045E, 0x0B12, "Xbox Series X Controller"), "xboxseries")
        self.assertEqual(pads.model_key(3, 0x045E, 0x02EA, "Xbox One"), "xboxone")
        self.assertEqual(pads.model_key(1, 0x0079, 0x1843, "Mayflash"), "gamecube")
        self.assertEqual(pads.model_key(6, 0x054C, 0x0CE6, "DualSense"), "ps5")
        self.assertEqual(pads.model_key(1, 0x1234, 0x5678, "Pad", gamepad=False), "joystick")

    def test_game_report_keeps_the_controller_lines_of_the_newest_log(self):
        with tempfile.TemporaryDirectory() as temp:
            logs = Path(temp) / "logs"
            logs.mkdir()
            (logs / "coastlink_game_20261024_120000_000001.log").write_text(
                "nvn_vk: device 0\nnn::pad: SDL 3.4.18 ready (no video); x\n"
                "nn::gca: the adapter is found but WinUSB cannot claim it (error 5): another program has it open.\n"
                "nn::pad: connected \"GameCube Controller (port 1)\" (gamepad, GameCube) GUID 0300 -> player 2\nrandom line\n", encoding="utf-8")
            report = app_backend.pad_report(Path(temp))
        self.assertEqual(report["stamp"], "20261024_120000")
        self.assertEqual(len(report["lines"]), 3)
        self.assertIn("WinUSB cannot claim", report["lines"][1])


class SaveImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.build = self.root / "build"
        old = self.build / "saves" / "save" / "save_data"
        old.mkdir(parents=True)
        (old / "system_data.bin").write_bytes(b"old progress")

    def tearDown(self):
        self.temp.cleanup()

    def jksv_zip(self, entries):
        path = self.root / "backup.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return path

    def test_jksv_backup_replaces_the_save_keeps_a_backup_and_skips_bcat(self):
        import save_import
        path = self.jksv_zip({"Super Smash Bros. Ultimate/100/save_data/system_data.bin": b"all unlocked",
                              "Super Smash Bros. Ultimate/100/save_data/spirits/a.bin": b"spirit",
                              "BCAT/Super Smash Bros. Ultimate/BCAT/event.bin": b"bcat"})
        result = save_import.import_save(self.build, path)
        save = self.build / "saves" / "save"
        self.assertEqual((save / "save_data" / "system_data.bin").read_bytes(), b"all unlocked")
        self.assertTrue((save / "save_data" / "spirits" / "a.bin").is_file())
        self.assertFalse(any("event.bin" in p.name for p in save.rglob("*")))
        self.assertEqual(result["files"], 2)
        backups = save_import.list_backups(self.build)
        self.assertEqual(len(backups), 1)
        save_import.restore_backup(self.build, backups[0]["name"])
        self.assertEqual((save / "save_data" / "system_data.bin").read_bytes(), b"old progress")

    def test_a_lone_system_data_bin_replaces_only_the_progress_file(self):
        import save_import
        keep = self.build / "saves" / "save" / "save_data" / "mii" / "m.bin"
        keep.parent.mkdir(parents=True)
        keep.write_bytes(b"my mii")
        lone = self.root / "system_data.bin"
        lone.write_bytes(b"P" * 4096)
        save_import.import_save(self.build, lone)
        self.assertEqual((self.build / "saves" / "save" / "save_data" / "system_data.bin").read_bytes(), b"P" * 4096)
        self.assertEqual(keep.read_bytes(), b"my mii")
        self.assertEqual(len(save_import.list_backups(self.build)), 1)

    def test_not_a_save_and_unsafe_names_are_refused_without_touching_the_save(self):
        import save_import
        with self.assertRaises(save_import.SaveError):
            save_import.import_save(self.build, self.jksv_zip({"readme.txt": b"hi"}))
        with self.assertRaises(save_import.SaveError):
            save_import.import_save(self.build, self.jksv_zip({"100/save_data/system_data.bin": b"x", "100/../evil.bin": b"x"}))
        self.assertEqual((self.build / "saves" / "save" / "save_data" / "system_data.bin").read_bytes(), b"old progress")
        with self.assertRaises(save_import.SaveError):
            save_import.restore_backup(self.build, "../save")


if __name__ == "__main__":
    unittest.main()
