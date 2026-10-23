"""Launch just the checked rollback executable; no normal-build dependency."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import engine


def game_command(build, extra, environment=None):
    build = Path(build).resolve()
    work = build / 'work'
    state = json.loads((build / 'state.json').read_text())
    romfs = Path(state['dump']['romfs'])
    if not romfs.is_dir():
        romfs = build / 'dump' / 'romfs'
    env = {key: value for key, value in (os.environ if environment is None else environment).items()
           if not key.startswith(('SSBU_', 'RECOMP_'))}
    env.update(SSBU_ROMFS=str(romfs), SSBU_USERDATA=str(build / 'saves'),
               SSBU_NRO_BIN='nro_bin_eh_o2r1', SSBU_ONLINE='off', SSBU_RB_NET='0')
    for directory, name in (('fonts', 'SSBU_FONTS'), ('zoneinfo', 'SSBU_TZDIR')):
        path = build / 'sysdata' / directory
        if path.is_dir():
            env[name] = str(path)
    for item in extra:
        key, separator, value = item.partition('=')
        if not separator or not key.startswith('SSBU_'):
            raise engine.CoastlinkError('Invalid runtime setting.')
        env[key] = value
    return [str(work / 'ssbu_native_rb.exe'), str(build / 'binaries' / state['game_version'] / 'main.elf'), '0'], env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--play', action='store_true')
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--log', required=True, type=Path)
    parser.add_argument('--env', action='append', default=[])
    args = parser.parse_args()
    ready = engine.status(engine.repo_path(), args.build)
    if not ready['ready'] or ready['build_in_progress']:
        raise engine.CoastlinkError('The rollback build is incomplete or still compiling.')
    command, env = game_command(args.build, args.env)
    for path in (args.build / 'saves', args.build / 'cache', args.log.parent):
        path.mkdir(parents=True, exist_ok=True)
    with args.log.open('wb') as log:
        return subprocess.run(command, cwd=args.build / 'work', env=env, stdout=log, stderr=subprocess.STDOUT).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (engine.CoastlinkError, OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
