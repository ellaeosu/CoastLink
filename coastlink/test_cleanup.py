"""Cleanup boundaries, tested only with disposable fake installations."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cleanup
import engine


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'CoastLink'
        self.repo.mkdir()
        (self.repo / 'SOURCE.json').write_text(json.dumps({'product': 'CoastLink', 'upstream_commit': engine.UPSTREAM_COMMIT}))
        self.work = self.repo / 'build' / 'work'
        self.work.mkdir(parents=True)

    def file(self, relative):
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test')
        return path

    def test_removes_only_explicit_normal_artifacts_and_preserves_rollback_inputs(self):
        old = [self.file('obj_eh_o1/part.obj'), self.file('nro_bin_eh_o2/common.dll'), self.file('ssbu_native.exe')]
        kept = [self.file(name) for name in ('obj_r1/partial.obj', 'obj_nro_eh_o2r1/common.obj',
                'nro_bin_eh_o2r1/common.dll', 'gen_nro_eh_o2/shared.c', 'gen_eh_o2/source.c',
                'ssbu_game_r1.dll', 'game.nsp', 'prod.keys', '../saves/user.save', '../dump/romfs/data.arc')]
        preview = cleanup.cleanup(self.repo, dry_run=True)
        self.assertEqual(len(preview), 3)
        self.assertTrue(all(path.exists() for path in old))
        self.assertEqual(cleanup.cleanup(self.repo), preview)
        self.assertTrue(all(not path.exists() for path in old))
        self.assertTrue(all(path.exists() for path in kept))
        self.assertEqual(cleanup.cleanup(self.repo), [])

    def test_unrecognized_install_is_rejected(self):
        (self.repo / 'SOURCE.json').write_text('{}')
        old = self.file('obj_eh_o1/partial.obj')
        with self.assertRaises(engine.CoastlinkError):
            cleanup.cleanup(self.repo)
        self.assertTrue(old.exists())

    def test_protected_data_aborts_all_deletion(self):
        old = self.file('obj_eh_o1/partial.obj')
        protected = self.file('obj_nro_eh_o2/game.nsp')
        with self.assertRaisesRegex(engine.CoastlinkError, 'nothing was removed'):
            cleanup.cleanup(self.repo)
        self.assertTrue(old.exists())
        self.assertTrue(protected.exists())

    def test_active_build_is_rejected_without_deletion(self):
        old = self.file('obj_eh_o1/partial.obj')
        with engine.BuildLock(self.repo / 'build'):
            result = subprocess.run([sys.executable, '-B', str(Path(cleanup.__file__)), '--repo', str(self.repo)],
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('already being installed', result.stdout)
        self.assertTrue(old.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows junction boundary')
    def test_junction_never_deletes_its_target(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        kept = outside / 'partial.obj'
        kept.write_bytes(b'test')
        junction = self.work / 'obj_eh_o1'
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(junction), str(outside)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.addCleanup(os.rmdir, junction)
        with self.assertRaisesRegex(engine.CoastlinkError, 'linked'):
            cleanup.cleanup(self.repo)
        self.assertTrue(kept.exists())


if __name__ == '__main__':
    unittest.main()
