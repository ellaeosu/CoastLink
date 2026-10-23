"""Prelaunch preferences for the pinned native runtime; never launches the game."""
from __future__ import annotations

import argparse
from functools import wraps
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import threading

SETTINGS_LOCK = threading.RLock()


def synchronized(function):
    """Sidecar commands run concurrently; serialize settings read/modify/write transactions."""
    @wraps(function)
    def run(*args, **kwargs):
        with SETTINGS_LOCK:
            return function(*args, **kwargs)
    return run

CONTROLS = ('A', 'B', 'X', 'Y', 'L', 'R', 'ZL', 'ZR', 'PLUS', 'MINUS',
            'STICK_L', 'STICK_R', 'LEFT', 'UP', 'RIGHT', 'DOWN',
            'LSTICK_LEFT', 'LSTICK_UP', 'LSTICK_RIGHT', 'LSTICK_DOWN',
            'RSTICK_LEFT', 'RSTICK_UP', 'RSTICK_RIGHT', 'RSTICK_DOWN')
GRAPHICS_DEFAULTS = dict(renderer='vulkan', window='windowed', width='1280', height='720',
    vsync='auto', latency='normal', gpu='auto', console_mode='docked', resolution_scale='1',
    anisotropic_filtering='game', shader_wait='hold', shader_prepare='first_run', shader_load='start',
    profile='custom', frame_time_overlay='off', stats_overlay='off', menu='on', volume='auto',
    language='auto', runahead='off', rollback='on', audio_device='default', mute_background='off')
CONTROLLER_DEFAULTS = dict(layout='auto', deadzone='0.10', outer_zone='0.98', trigger_threshold='0.33',
                           rumble='on', rumble_strength='1', keyboard_player='auto')
KEYBOARD_DEFAULTS = dict(zip(CONTROLS, ('Z', 'X', 'C', 'V', 'Q', 'E', 'A', 'S', 'ENTER', 'BACKSPACE',
    'none', 'none', 'J', 'I', 'L', 'K', 'LEFT', 'UP', 'RIGHT', 'DOWN', 'none', 'none', 'none', 'none')))
GRAPHICS_CHOICES = dict(renderer=('vulkan', 'opengl'), window=('windowed', 'borderless', 'fullscreen'),
    vsync=('auto', 'display', 'clock', 'off', 'on', 'mailbox'), latency=('normal', 'low', 'lowest'),
    console_mode=('docked', 'handheld'), anisotropic_filtering=('game', '2', '4', '8', '16'),
    shader_wait=('hold', 'skip'), shader_prepare=('first_run', 'background', 'off'),
    shader_load=('start', 'loading'), profile=('custom', 'low'), frame_time_overlay=('off', 'on'),
    stats_overlay=('off', 'on'), menu=('off', 'on'), runahead=('off', 'on'), rollback=('on',), mute_background=('off', 'on'),
    language=('auto', 'ja', 'en-US', 'en-GB', 'fr', 'fr-CA', 'de', 'it', 'es', 'es-419',
              'zh-Hans', 'zh-Hant', 'ko', 'nl', 'ru'))
PAD_BUTTONS = frozenset(('south', 'east', 'west', 'north', 'back', 'guide', 'start', 'leftstick',
    'rightstick', 'leftshoulder', 'rightshoulder', 'dpup', 'dpdown', 'dpleft', 'dpright', 'misc1',
    'rightpaddle1', 'leftpaddle1', 'rightpaddle2', 'leftpaddle2', 'touchpad', 'misc2', 'misc3',
    'misc4', 'misc5', 'misc6', 'none'))
PAD_AXIS = re.compile(r'(?:leftx|lefty|rightx|righty|lefttrigger|righttrigger)[+-]?\Z')
RAW_SOURCE = re.compile(r'(?:button\d{1,4}|axis\d{1,4}[+-]?|hat\d{1,3}(?:up|right|down|left))\Z')
# Online rollback input delay: auto = the runtime covers the measured one-way trip (about 3 frames coast to coast);
# lower = one frame less (SSBU_RB_NET_LATE=1), leaving about one frame of lateness to rollback;
# higher = one frame more (SSBU_RB_NET_DELAY_PLUS=1), for a jittery connection
INPUT_DELAYS = ('auto', 'lower', 'higher')
KEY_SOURCE = re.compile(r'(?:[A-Z0-9]|LEFT|UP|RIGHT|DOWN|ENTER|BACKSPACE|SPACE|TAB|ESC|SHIFT|CTRL|ALT|'
                        r'F(?:[1-9]|1[0-2])|NUM[0-9]|0X[0-9A-F]{1,2}|NONE)\Z')


class SettingsError(ValueError):
    pass


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8-sig')
    except FileNotFoundError:
        return ''


def _sections(text: str, flat=False) -> dict[str, dict[str, str]]:
    sections = {'': {}}
    section = ''
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((';', '#')):
            continue
        if stripped.startswith('[') and ']' in stripped:
            if not flat:
                section = stripped[1:stripped.index(']')].strip().lower()
                sections.setdefault(section, {})
            continue
        key, separator, value = line.partition('=')
        if separator:
            # graphics.ini's native parser treats the whole value literally (sound/GPU names can contain # or ;).
            parsed = value if flat else re.split(r'\s+[;#]', value, maxsplit=1)[0]
            sections.setdefault(section, {})[key.strip().lower()] = parsed.strip()
    return sections


def _read_preferences(build: Path) -> dict:
    try:
        value = json.loads(_read(build / 'config' / 'coastlink_settings.json'))
        return value if isinstance(value, dict) else {}
    except (ValueError, OSError):
        return {}


@synchronized
def get_settings(build: Path) -> dict:
    """Read current INIs without creating folders, defaults or preference files."""
    build = Path(build).resolve()
    graphics = GRAPHICS_DEFAULTS.copy()
    graphics.update({key: value for key, value in _sections(_read(build / 'config' / 'graphics.ini'), flat=True)[''].items()
                     if key in graphics})
    graphics['rollback'] = 'on'
    sections = _sections(_read(build / 'config' / 'controllers.ini'))
    controller = CONTROLLER_DEFAULTS.copy()
    controller.update({key: value for key, value in sections.get('general', {}).items() if key in controller and key != 'keyboard_player'})
    keyboard = sections.get('keyboard', {})
    controller['keyboard_player'] = keyboard.get('player', 'auto')
    keyboard_bindings = {key: keyboard.get(key.lower(), default) for key, default in KEYBOARD_DEFAULTS.items()}
    # Missing map keys mean native layout defaults, rather than a fixed positional mapping.
    xbox = sections.get('type xbox', {})
    controller.update({key: value for key, value in xbox.items() if key in controller and key != 'keyboard_player'})
    xbox_bindings = {key: xbox.get('map.' + key.lower(), 'default') for key in CONTROLS}
    preferences = _read_preferences(build).get('launch', {})
    preferences = preferences if isinstance(preferences, dict) else {}
    launch = {'speed': preferences.get('speed') if preferences.get('speed') in ('normal', 'unlimited') else 'normal',
              'skip_movies': preferences.get('skip_movies') is True,
              'input_delay': preferences.get('input_delay') if preferences.get('input_delay') in INPUT_DELAYS else 'auto'}
    notes = []
    if any(section.startswith('device ') for section in sections):
        notes.append('Existing device-specific controller settings take priority over the Xbox profile. They are preserved; use F1 > Controls in the game to edit a specific device.')
    return dict(graphics=graphics, controller=controller, xbox_bindings=xbox_bindings,
                keyboard_bindings=keyboard_bindings, launch=launch, notes=notes, build_dir=str(build))


def _text(value, label: str) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise SettingsError(label + ' must be a setting value.')
    result = str(value).strip()
    if not result or len(result) > 256 or any(character in result for character in ('\r', '\n', '\0', ';', '#', '[', ']', '=')):
        raise SettingsError('Invalid value for ' + label + '.')
    return result


def _choice(value, allowed, label: str) -> str:
    text = _text(value, label)
    for option in allowed:
        if text.lower() == option.lower():
            return option
    raise SettingsError(label + ': choose ' + ', '.join(allowed) + '.')


def _literal_name(value, label: str) -> str:
    if not isinstance(value, str):
        raise SettingsError(label + ' must be a name.')
    value = value.strip()
    if not value or len(value.encode('utf-8')) > 127 or any(ord(character) < 32 for character in value):
        raise SettingsError('Invalid name for ' + label + '.')
    return value


def _number(value, minimum, maximum, label, integer=False) -> str:
    try:
        number = float(_text(value, label))
    except (ValueError, OverflowError):
        raise SettingsError('Invalid number for ' + label + '.') from None
    if not math.isfinite(number) or not minimum <= number <= maximum or (integer and number != int(number)):
        raise SettingsError(f'{label} must be between {minimum} and {maximum}' + (' (whole numbers).' if integer else '.'))
    return str(int(number)) if integer else format(number, '.6g')


def _pad_binding(value, label) -> str:
    text = _text(value, label).lower()
    if text == 'default':
        return text
    parts = [part.strip() for part in text.split(',')]
    if not 1 <= len(parts) <= 4 or any(part not in PAD_BUTTONS and not PAD_AXIS.fullmatch(part) and not RAW_SOURCE.fullmatch(part) for part in parts):
        raise SettingsError(label + ': use a controller button, axis, none or default (up to four sources).')
    return ', '.join(parts)


def _validate(payload: dict) -> dict:
    graphics = payload['graphics']
    for key in graphics:
        if key not in GRAPHICS_DEFAULTS:
            raise SettingsError('Unknown graphics setting: ' + key)
        if key in GRAPHICS_CHOICES:
            graphics[key] = _choice(graphics[key], GRAPHICS_CHOICES[key], key)
        elif key in ('width', 'height'):
            graphics[key] = _number(graphics[key], 320 if key == 'width' else 180, 16384, key, integer=True)
        elif key == 'resolution_scale':
            graphics[key] = _number(graphics[key], 0.25, 2, key)
        elif key == 'volume':
            graphics[key] = 'auto' if str(graphics[key]).lower() == 'auto' else _number(graphics[key], 0, 100, key, integer=True)
        else:
            graphics[key] = _literal_name(graphics[key], key)
    controller = payload['controller']
    for key in controller:
        if key not in CONTROLLER_DEFAULTS:
            raise SettingsError('Unknown controller setting: ' + key)
        if key == 'layout':
            controller[key] = _choice(controller[key], ('auto', 'positional', 'labels'), key)
        elif key == 'rumble':
            controller[key] = _choice(controller[key], ('on', 'off'), key)
        elif key == 'keyboard_player':
            controller[key] = _choice(controller[key], ('auto', 'none', '1', '2', '3', '4', '5', '6', '7', '8'), key)
        else:
            controller[key] = _number(controller[key], 0, 2 if key == 'rumble_strength' else 1, key)
    if float(controller['deadzone']) >= float(controller['outer_zone']):
        raise SettingsError('Stick dead zone must be smaller than the outer zone.')
    for group in ('xbox_bindings', 'keyboard_bindings'):
        for control, value in payload[group].items():
            if control not in CONTROLS:
                raise SettingsError('Unknown controller control: ' + control)
            if group == 'xbox_bindings':
                payload[group][control] = _pad_binding(value, control)
            else:
                text = _text(value, control).upper()
                if not KEY_SOURCE.fullmatch(text):
                    raise SettingsError(control + ': use a keyboard key or none.')
                payload[group][control] = 'none' if text == 'NONE' else text
    launch = payload['launch']
    if set(launch) != {'speed', 'skip_movies', 'input_delay'}:
        raise SettingsError('Unknown launch setting.')
    launch['speed'] = _choice(launch['speed'], ('normal', 'unlimited'), 'Game speed')
    launch['input_delay'] = _choice(launch['input_delay'], INPUT_DELAYS, 'Input delay')
    if not isinstance(launch['skip_movies'], bool):
        raise SettingsError('Skip movies must be true or false.')
    return payload


def _edit_ini(text: str, changes: dict[str, dict[str, str | None]], flat=False) -> str:
    """Change only requested keys; retain comments, unknown keys and other sections."""
    changes = {section.lower(): {key.lower(): value for key, value in values.items()} for section, values in changes.items()}
    pending = {section: dict(values) for section, values in changes.items()}
    current = ''
    seen_sections = {''}
    output = []

    def append_pending(section):
        for key, value in pending.get(section, {}).items():
            if value is not None:
                output.append(key + ' = ' + value)
        pending[section] = {}

    for line in text.splitlines():
        stripped = line.strip()
        if not flat and stripped.startswith('[') and ']' in stripped:
            append_pending(current)
            current = stripped[1:stripped.index(']')].strip().lower()
            seen_sections.add(current)
            output.append(line)
            continue
        key, separator, _ = line.partition('=')
        key = key.strip().lower()
        if separator and not stripped.startswith((';', '#')) and key in changes.get(current, {}):
            inline = None if flat else re.search(r'\s+([;#].*)$', line.partition('=')[2])
            value = pending.get(current, {}).pop(key, None)
            if inline:
                output.append(inline[1])
            if value is not None:
                output.append(key + ' = ' + value)
        else:
            output.append(line)
    append_pending(current)
    for section in changes:
        if section not in seen_sections:
            if section:
                output.extend(('', '[' + section + ']'))
            append_pending(section)
    return '\n'.join(output).rstrip() + '\n'


@synchronized
def _replace_files(changes: dict[Path, str]):
    staged = {}
    previous = {}
    replaced = []
    try:
        for path, text in changes.items():
            previous[path] = path.read_bytes() if path.exists() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
            staged[path] = Path(name)
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(text)
        for path, temporary in staged.items():
            os.replace(temporary, path)
            replaced.append(path)
    except OSError:
        for path in reversed(replaced):
            old = previous[path]
            if old is None:
                path.unlink(missing_ok=True)
            else:
                descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.restore', dir=path.parent)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(old)
                os.replace(name, path)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


@synchronized
def save_settings(build: Path, payload: dict) -> dict:
    """Validate the complete requested result before touching any settings file."""
    if not isinstance(payload, dict):
        raise SettingsError('Settings must be a JSON object.')
    groups = ('graphics', 'controller', 'xbox_bindings', 'keyboard_bindings', 'launch')
    unknown = set(payload) - set(groups) - {'notes', 'build_dir', 'schema'}
    if unknown:
        raise SettingsError('Unknown settings group: ' + ', '.join(sorted(unknown)))
    build = Path(build).resolve()
    merged = get_settings(build)
    for group in groups:
        if group not in payload:
            continue
        if not isinstance(payload[group], dict):
            raise SettingsError(group + ' must contain settings.')
        merged[group].update(payload[group])
    merged = _validate(merged)
    graphics_path = build / 'config' / 'graphics.ini'
    controllers_path = build / 'config' / 'controllers.ini'
    keyboard = dict(merged['keyboard_bindings'], player=merged['controller']['keyboard_player'])
    xbox = {'map.' + control: None if value == 'default' else value for control, value in merged['xbox_bindings'].items()}
    xbox.update({key: value for key, value in merged['controller'].items() if key != 'keyboard_player'})
    changes = {
        graphics_path: _edit_ini(_read(graphics_path), {'': merged['graphics']}, flat=True),
        controllers_path: _edit_ini(_read(controllers_path), {'keyboard': keyboard, 'type xbox': xbox}),
        build / 'config' / 'coastlink_settings.json': json.dumps({'schema': 1, 'launch': merged['launch']}, indent=2) + '\n',
    }
    # Only files whose text changes are written: a running game reloads controllers.ini and re-reads graphics.ini when
    # they change (the Audio screen saves mid-match), so an untouched file must keep its time stamp.
    _replace_files({path: text for path, text in changes.items() if text != _read(path)})
    return get_settings(build)


def runtime_environment(build: Path, mode: str) -> dict[str, str]:
    """Keep every network match at normal simulation speed, regardless of preference."""
    preferences = _read_preferences(Path(build)).get('launch', {})
    preferences = preferences if isinstance(preferences, dict) else {}
    speed = '0' if mode == 'offline' and preferences.get('speed') == 'unlimited' else '1'
    environment = {'SSBU_SPEED': speed, 'SSBU_SKIP_MOVIES': '1' if preferences.get('skip_movies') is True else '0'}
    if mode != 'offline' and preferences.get('input_delay') == 'lower':
        environment['SSBU_RB_NET_LATE'] = '1'
    elif mode != 'offline' and preferences.get('input_delay') == 'higher':
        environment['SSBU_RB_NET_DELAY_PLUS'] = '1'
    return environment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('get', 'save'):
        child = sub.add_parser(command)
        child.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
        child.add_argument('--build-dir')
        if command == 'save':
            child.add_argument('--file', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        from engine import build_path
        build = build_path(args.repo, args.build_dir)
        result = get_settings(build) if args.command == 'get' else save_settings(build, json.loads(args.file.read_text(encoding='utf-8-sig')))
        print(json.dumps(result))
        return 0
    except (SettingsError, ValueError, OSError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
