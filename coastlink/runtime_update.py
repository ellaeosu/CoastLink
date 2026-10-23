"""Apply the pinned host-only rollback repair; never touch compiled game data."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

COMMIT = '169b467a653ab239faa7310e990f369442cbae14+coastlink-rb4'
# name: (the installed builds it may replace (original install, 0.4.1 repair, 0.5.x), the new build)
REPLACEMENTS = {
    'ssbu_native_rb.exe': (('b6ec23de51a7b4f9b0f790bdda95e14e2c88b1993ac8304c7afa004de4b5f68f',
                            '9db56434c09e6936135f7ae4e760a49b3b4e4524a594e500bbc909e15a5bfb61',
                            '4b8eeadab30277a5ca907e430c7fb9dc9a9b22830cf0f839d54e4e30fc77965f',
                            'cf56d86217487ba364d86fc5c052c2981e21b0242c92b9ec0005f5e601d1bd9c',
                            'c6a906d90f67256af3d8f95580a65d7b2704aedfd5f7bbc5eda304f2efea23fe',
                            '6600e5bf33d818e83612f9b72344bd90ccdf07a0d08a0abca8141ce1687371cc',
                            'be6209f22fe0020ec904e748dfa2a3892249d7b45e245920cd5077ad135941e6'),
                           '3fc3fc15bfb502eb37f56e405ae727b44626209acfe22a1fc9b18f4999c0a758'),
    'ssbu_glslang.dll': (('5ffbbd3caa74f8a0c3ad72a6b6e3eb707b53c657cd8384fd928aab08e462165c',
                          'c661baa1816878a84758ab9d3ef533bbfcef53a8effdfa1adc98f813d8742a2e'),
                         'df157cdfd1fba75cb187eb5db4868de03e2e76fc83f0785c5a0097d0385d3a50'),
}


def replaceable(name: str) -> tuple:
    old = REPLACEMENTS[name][0]
    return old if isinstance(old, tuple) else (old,)


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def no_links(path: Path):
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('The runtime repair cannot use linked files or junction folders: ' + str(item))


def apply_runtime_patch(repo: Path, build: Path) -> dict:
    """Verify every file before writes; caller owns the build's installation lock."""
    repo, build = Path(repo).absolute(), Path(build).absolute()
    payload = repo / 'coastlink' / 'runtime_patch'
    work = build / 'work'
    for path in (payload, work):
        no_links(path)
    changes = []
    for name, (_, new) in REPLACEMENTS.items():
        target, source = work / name, payload / name
        no_links(target)
        no_links(source)
        if not target.is_file() or not source.is_file():
            raise ValueError('The rollback repair is incomplete. Run CoastLink Rollback Update again. Missing: ' + name)
        if digest(source) != new:
            raise ValueError('The rollback repair checksum failed: ' + name)
        installed = digest(target)
        if installed != new and installed not in replaceable(name):
            raise ValueError('The installed runtime is a different build; it was preserved: ' + name)
        if installed != new:
            changes.append(name)
    if not changes:
        return {'changed': 0, 'runtime_commit': COMMIT}
    if shutil.disk_usage(build).free < 128 * 1024 * 1024:
        raise ValueError('The rollback repair needs 128 MB free for verified backups.')
    backup_parent = build / 'coastlink_runtime_backups'
    no_links(backup_parent)
    backup_parent.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('%Y%m%d_%H%M%S_'), dir=backup_parent))
    committed = []
    try:
        with tempfile.TemporaryDirectory(prefix='.coastlink-runtime-', dir=build) as staging:
            staging = Path(staging)
            for name in changes:
                shutil.copy2(work / name, backup / name)
                shutil.copy2(payload / name, staging / name)
                if digest(backup / name) not in replaceable(name) or digest(staging / name) != REPLACEMENTS[name][1]:
                    raise ValueError('A runtime file changed while preparing the repair; no update was installed.')
            try:
                for name in changes:
                    os.replace(staging / name, work / name)
                    committed.append(name)
                if any(digest(work / name) != REPLACEMENTS[name][1] for name in changes):
                    raise ValueError('Runtime repair verification failed.')
            except Exception:
                for name in reversed(committed):
                    restore = staging / ('restore-' + name)
                    shutil.copy2(backup / name, restore)
                    os.replace(restore, work / name)
                raise
    except OSError as error:
        raise ValueError('Close Smash on this PC, then retry. The runtime repair could not replace its files; original files were preserved. Backup: ' + str(backup)) from error
    evidence = {'runtime_commit': COMMIT, 'changed': len(changes), 'backup': str(backup),
                'files': {name: REPLACEMENTS[name][1] for name in REPLACEMENTS}}
    (backup / 'repair.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence
