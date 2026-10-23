"""Remove only obsolete, normal CoastLink artifacts from a recognized install."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat

import engine

LEGACY = ('obj_eh_o1', 'obj_nro_eh_o2', 'nro_bin_eh_o2',
          'ssbu_native.exe', 'ssbu_game_eh_o1.dll', 'ssbu_game_eh_o1.lib', 'ssbu_game_eh_o1.exp')
PROTECTED = engine.GAME_EXTENSIONS | {'.keys', '.sav', '.save', '.elf', '.arc'}


def check_path(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise engine.CoastlinkError('Cleanup refuses linked folders or files: ' + str(path))
    return info


def cleanup(repo, dry_run=False):
    repo = Path(os.path.abspath(repo))
    check_path(repo)
    engine.verify_source_pin(repo)
    if engine.read_json(repo / 'SOURCE.json', {}).get('product') != 'CoastLink':
        raise engine.CoastlinkError('Select a recognized CoastLink installation folder.')
    build = repo / 'build'
    if not build.exists():
        return []
    check_path(build)
    work = build / 'work'
    if not work.exists():
        return []
    check_path(work)
    with engine.BuildLock(build):
        targets = []
        for name in LEGACY:
            path = work / name
            if not os.path.lexists(path):
                continue
            check_path(path)
            # Verify every resolved absolute target before any recursive deletion.
            if path.resolve().parent != work.resolve():
                raise engine.CoastlinkError('Cleanup target escaped the selected build folder.')
            if path.is_dir():
                for current, directories, files in os.walk(path, followlinks=False):
                    for item in directories + files:
                        child = Path(current) / item
                        check_path(child)
                        if child.suffix.lower() in PROTECTED:
                            raise engine.CoastlinkError('Game or save data was found inside an obsolete cache; nothing was removed.')
            targets.append(path)
        # Validate every target before deleting any target.
        if not dry_run:
            for path in targets:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        return [str(path.relative_to(repo)) for path in targets]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps({'removed' if not args.dry_run else 'would_remove': cleanup(args.repo, args.dry_run)}))
    except (engine.CoastlinkError, OSError, ValueError) as error:
        print(str(error))
        raise SystemExit(2)
