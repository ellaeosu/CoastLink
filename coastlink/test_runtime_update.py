import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runtime_update


class RuntimeRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='CoastLinkRuntimeTest_')
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        self.build = Path(self.temp.name) / 'custom build'
        self.payload = self.repo / 'coastlink' / 'runtime_patch'
        self.work = self.build / 'work'
        self.payload.mkdir(parents=True)
        self.work.mkdir(parents=True)
        self.pairs = {}
        for name in ('ssbu_native_rb.exe', 'ssbu_glslang.dll'):
            old, new = ('old-' + name).encode(), ('new-' + name).encode()
            (self.work / name).write_bytes(old)
            (self.payload / name).write_bytes(new)
            self.pairs[name] = tuple(hashlib.sha256(data).hexdigest() for data in (old, new))
        guard = patch.object(runtime_update, 'REPLACEMENTS', self.pairs)
        guard.start()
        self.addCleanup(guard.stop)
        for name in ('ssbu_game_r1.dll', 'nro_bin_eh_o2r1/character.dll', '../saves/user.save', '../config/graphics.ini'):
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'PRESERVE')

    def apply(self):
        return runtime_update.apply_runtime_patch(self.repo, self.build)

    def test_verified_repair_preserves_game_modules_saves_settings_and_can_repeat(self):
        result = self.apply()
        self.assertEqual(result['changed'], 2)
        for name, pair in self.pairs.items():
            self.assertEqual(runtime_update.digest(self.work / name), pair[1])
            self.assertEqual(runtime_update.digest(Path(result['backup']) / name), pair[0])
        for name in ('ssbu_game_r1.dll', 'nro_bin_eh_o2r1/character.dll', '../saves/user.save', '../config/graphics.ini'):
            self.assertEqual((self.work / name).read_bytes(), b'PRESERVE')
        self.assertEqual(self.apply()['changed'], 0)

    def test_either_earlier_build_is_upgraded(self):
        earlier = b'earlier-ssbu_native_rb.exe'
        (self.work / 'ssbu_native_rb.exe').write_bytes(earlier)
        old, new = self.pairs['ssbu_native_rb.exe']
        self.pairs['ssbu_native_rb.exe'] = ((old, hashlib.sha256(earlier).hexdigest()), new)
        result = self.apply()
        self.assertEqual(result['changed'], 2)
        self.assertEqual(runtime_update.digest(self.work / 'ssbu_native_rb.exe'), new)
        self.assertEqual((Path(result['backup']) / 'ssbu_native_rb.exe').read_bytes(), earlier)

    def test_corrupt_payload_refused_before_any_replacement(self):
        (self.payload / 'ssbu_glslang.dll').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.apply()
        self.assertEqual(runtime_update.digest(self.work / 'ssbu_native_rb.exe'), self.pairs['ssbu_native_rb.exe'][0])

    def test_unknown_installed_runtime_is_preserved(self):
        (self.work / 'ssbu_native_rb.exe').write_bytes(b'custom')
        with self.assertRaisesRegex(ValueError, 'different build'):
            self.apply()
        self.assertEqual((self.work / 'ssbu_native_rb.exe').read_bytes(), b'custom')

    def test_second_file_failure_restores_first_file(self):
        actual = os.replace
        def fail_second(source, target):
            if Path(source).name == 'ssbu_glslang.dll':
                raise PermissionError('locked graphics runtime')
            return actual(source, target)
        with patch.object(runtime_update.os, 'replace', side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, 'original files were preserved'):
                self.apply()
        for name, pair in self.pairs.items():
            self.assertEqual(runtime_update.digest(self.work / name), pair[0])

    def test_low_disk_space_refused(self):
        with patch.object(runtime_update.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 1})()):
            with self.assertRaisesRegex(ValueError, '128 MB'):
                self.apply()
        self.assertFalse((self.build / 'coastlink_runtime_backups').exists())


if __name__ == '__main__':
    unittest.main()
