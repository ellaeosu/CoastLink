"""Rollback-only setup/launch contract; never starts the real game."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import engine
import run_rollback


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        self.romfs = self.build / 'dump' / 'romfs'
        self.romfs.mkdir(parents=True)
        (self.build / 'state.json').write_text(json.dumps({'game_version': '13.0.4', 'dump': {'romfs': str(self.romfs)}}))

    def test_launch_uses_only_marked_artifacts_and_removes_inherited_game_settings(self):
        (self.build / 'sysdata' / 'fonts').mkdir(parents=True)
        command, env = run_rollback.game_command(self.build, ['SSBU_RB_NET=net', 'SSBU_RB_NET_PLAYER=1'],
                {'PATH': 'kept', 'SSBU_NRO_BIN': 'normal', 'RECOMP_DLL': 'normal'})
        self.assertEqual(Path(command[0]).name, 'ssbu_native_rb.exe')
        self.assertEqual(command[1:], [str(self.build / 'binaries' / '13.0.4' / 'main.elf'), '0'])
        self.assertEqual(env['SSBU_NRO_BIN'], 'nro_bin_eh_o2r1')
        self.assertEqual(env['SSBU_RB_NET_PLAYER'], '1')
        self.assertEqual(env['SSBU_ROMFS'], str(self.romfs))
        self.assertEqual(env['SSBU_USERDATA'], str(self.build / 'saves'))
        self.assertIn('SSBU_FONTS', env)
        self.assertNotIn('RECOMP_DLL', env)
        self.assertEqual(env['PATH'], 'kept')

    def test_moved_romfs_falls_back_to_current_build_and_unknown_setting_is_rejected(self):
        (self.build / 'state.json').write_text(json.dumps({'game_version': '13.0.4', 'dump': {'romfs': 'Z:/missing-old-folder'}}))
        _, env = run_rollback.game_command(self.build, [], {})
        self.assertEqual(env['SSBU_ROMFS'], str(self.romfs))
        self.assertEqual(env['SSBU_RB_NET'], '0')
        with self.assertRaises(engine.CoastlinkError):
            run_rollback.game_command(self.build, ['PATH=bad'], {})

    def test_user_setup_builds_only_marked_game_and_fighter_modules(self):
        spec = importlib.util.spec_from_file_location('coastlink_pinned_setup', engine.repo_path() / 'scripts' / 'setup.py')
        setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)
        work = self.build / 'work'
        work.mkdir()
        (work / 'ssbu_game_r1.dll').write_bytes(b'test')
        modules = work / 'nro_bin_eh_o2r1'
        modules.mkdir()
        (modules / 'lua2cpp_common.dll').write_bytes(b'test')
        calls = []
        cx = SimpleNamespace(posix=False, linux=False, mac=False, jobs=4, work=str(work),
                a=SimpleNamespace(rollback=True, rollback_only=True, no_inline=False, modules=None),
                env=lambda **values: values,
                run=lambda step, argv, **options: calls.append((step, argv, options)))
        with patch.object(setup, 'say'):
            setup.step_compile(cx)
            setup.step_nro(cx)
        self.assertEqual([call[0] for call in calls], ['compile', 'nro'])
        self.assertEqual(calls[0][2]['env']['RECOMP_OBJ'], 'obj_r1')
        self.assertEqual(calls[0][2]['env']['RECOMP_CFLAGS'], '-DR1_MARK')
        self.assertEqual(calls[1][2]['env']['RECOMP_NRO_SUFFIX'], '_eh_o2r1')
        self.assertEqual(calls[1][2]['env']['RECOMP_NRO_GEN_SUFFIX'], '_eh_o2')
        self.assertEqual(calls[1][2]['env']['RECOMP_CFLAGS'], '-DR1_MARK')


if __name__ == '__main__':
    unittest.main()
