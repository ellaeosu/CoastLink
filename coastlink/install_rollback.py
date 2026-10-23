"""Use the pinned preparer, then build only the instrumented rollback variant."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))


def load_script(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rollback_env(setup, cx):
    return cx.env(RECOMP_GEN='gen_eh_o2', RECOMP_OBJ='obj_r1', RECOMP_DLL='ssbu_game_r1.dll',
                  RECOMP_NRO_SUFFIX='_eh_o2r1', RECOMP_NRO_GEN_SUFFIX='_eh_o2',
                  RECOMP_SHIM='game_shim_r1.c', RECOMP_INLINE=setup.inline_flag(cx),
                  RECOMP_CFLAGS='-DR1_MARK', RECOMP_DATA_CFLAGS='-DR1_MARK')


def compile_rollback(setup, cx):
    cx.run('compile', [sys.executable, 'build_opt.py', 'main', str(cx.jobs)], env=rollback_env(setup, cx))


def modules_rollback(setup, cx):
    cx.run('nro', [sys.executable, 'build_opt.py', 'nro', str(cx.jobs)], env=rollback_env(setup, cx))


def link_rollback(setup, cx):
    if not cx.runtime_dir:
        raise setup.Fail('The verified prebuilt rollback runtime is required; retry its download.')
    manifest = json.loads((Path(cx.runtime_dir) / 'manifest.json').read_text())
    required = {'ssbu_native_rb.exe', 'SDL3.dll', 'ssbu_glslang.dll'}
    if not required.issubset(manifest['files']):
        raise setup.Fail('The runtime package is missing rollback support files.')
    for name, entry in manifest['files'].items():
        suffix = Path(name).suffix.lower()
        if suffix == '.dll' or name == 'ssbu_native_rb.exe':
            source, target = Path(cx.runtime_dir) / name, Path(cx.work) / name
            shutil.copy2(source, target)
            if setup.sha256_file(str(target)) != entry['sha256']:
                raise setup.Fail('Runtime checksum failed after copying ' + name)
    if not (Path(cx.work) / 'ssbu_game_r1.dll').is_file():
        raise setup.Fail('The rollback game library is missing.')
    setup.copy_ffmpeg(cx)
    setup.copy_logo(cx)
    setup.say('  rollback executable and support libraries ready; normal version omitted')


def run_build(parent, progress, preparer):
    if parent.a.dry_run:
        preparer.say('   would build ONLY rollback game, modules and runtime; normal compilation omitted')
        return
    setup = load_script('coastlink_upstream_setup', REPO / 'scripts' / 'setup.py')
    parser = argparse.ArgumentParser(add_help=False)
    for name in ('runtime', 'llvm', 'sdl3', 'vulkan-headers', 'glslang', 'suyu', 'opus', 'imgui'):
        parser.add_argument('--' + name)
    options, unknown = parser.parse_known_args(parent.setup_args)
    if unknown or not options.runtime:
        raise preparer.Stop('The verified prebuilt rollback runtime is required for this installer.')
    options.build, options.dump, options.jobs = preparer.BUILD, parent.dump, parent.jobs
    for name in ('exefs', 'romfs', 'sysdata', 'sdk_roots', 'modules'):
        setattr(options, name, None)
    options.target, options.nocrt, options.rollback = 'windows', True, True
    options.runtime_any_tree = options.no_inline = options.full_check = options.tools_only = False
    cx = setup.Ctx(options)
    shared = ('deps', 'stage', 'convert', 'modules', 'tables', 'lift', 'sdk')
    try:
        for step in shared:
            done = cx.state.setdefault('done', {})
            if step in done and step not in ('deps', 'stage'):
                preparer.say('   %s: prepared earlier, kept' % step)
                continue
            preparer.say('   %s: preparing...' % step)
            started = time.time()
            setup.RUNNERS[step](cx)
            done[step] = {'secs': time.time() - started, 'at': time.strftime('%Y-%m-%d %H:%M')}
            cx.save()
        recipe = (cx.state.get('game_version'), cx.state.get('runtime_exe'), 'rollback-only-v1')
        record = cx.state.setdefault('coastlink_rollback_only', {})
        if record.get('recipe') != list(recipe):
            record.clear()
            record.update(recipe=list(recipe), done={})
        completed = record.setdefault('done', {})
        actions = (
            ('compile', lambda: compile_rollback(setup, cx), Path(cx.work) / 'ssbu_game_r1.dll'),
            ('nro', lambda: modules_rollback(setup, cx), Path(cx.work) / 'nro_bin_eh_o2r1' / 'lua2cpp_common.dll'),
            ('link', lambda: link_rollback(setup, cx), Path(cx.work) / 'ssbu_native_rb.exe'),
            ('check', lambda: setup.step_check(cx), Path(cx.work) / 'ssbu_native_rb.exe'),
        )
        # The upstream self-tests resolve this function; run them against the
        # same rollback executable we ship, without needing a normal game DLL.
        setup.exe_name = lambda context: 'ssbu_native_rb.exe'
        for step, action, artifact in actions:
            if step in completed and artifact.is_file() and artifact.stat().st_size:
                preparer.say('   rollback %s: finished earlier, kept' % step)
                continue
            preparer.say('   rollback %s: starting (normal version skipped)' % step)
            progress.start(step)
            started = time.time()
            action()
            completed[step] = {'secs': time.time() - started}
            cx.save()
            progress.end(step, 'done', 'rollback only', time.time() - started)
    except setup.Fail as error:
        cx.save()
        raise preparer.Stop('Rollback-only build stopped: ' + str(error))


def main():
    preparer = load_script('coastlink_upstream_install', REPO / 'scripts' / 'install.py')
    preparer.step_build = lambda context, progress: run_build(context, progress, preparer)
    return preparer.main()


if __name__ == '__main__':
    raise SystemExit(main())
