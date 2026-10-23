"""Settings persistence and runtime boundaries with disposable files only."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name) / 'build with spaces'

    def file(self, name, text):
        path = self.build / 'config' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_get_defaults_and_runtime_flags_never_create_files(self):
        data = settings.get_settings(self.build)
        self.assertEqual(data['graphics']['renderer'], 'vulkan')
        self.assertEqual(data['graphics']['rollback'], 'on')
        self.assertEqual(data['keyboard_bindings']['PLUS'], 'ENTER')
        self.assertEqual(data['xbox_bindings']['A'], 'default')
        self.assertEqual(settings.runtime_environment(self.build, 'host')['SSBU_SPEED'], '1')
        self.assertFalse(self.build.exists())

    def test_all_settings_round_trip_into_native_formats_without_removing_user_data(self):
        graphics = self.file('graphics.ini', '; keep graphics comment\nrenderer = vulkan\ncustom_debug = unchanged\nvolume = 10\n')
        controllers = self.file('controllers.ini', '; keep controller comment\n[general]\nlayout = auto\nignore = untouched-guid\n'
            '[type xbox]\nmap.A = east ; keep binding comment\nmap.B = south\ndeadzone = 0.2\nlayout = positional\n'
            '[device abcdef]\nname = My pad\nmap.ZL = button7\n[future section]\nfuture_value = preserved\n')
        data = settings.get_settings(self.build)
        self.assertTrue(any('device-specific' in note for note in data['notes']))
        self.assertEqual(data['controller']['deadzone'], '0.2')
        self.assertEqual(data['controller']['layout'], 'positional')
        data['graphics'].update(volume='72', resolution_scale='1.5', vsync='clock', shader_prepare='background')
        data['controller'].update(layout='labels', deadzone='0.12', keyboard_player='1')
        data['xbox_bindings'].update(A='south', B='default', LSTICK_LEFT='dpleft, leftx-')
        data['keyboard_bindings']['A'] = 'SPACE'
        data['launch'] = {'speed': 'unlimited', 'skip_movies': True}
        result = settings.save_settings(self.build, data)
        self.assertEqual(result['graphics']['volume'], '72')
        self.assertEqual(result['graphics']['resolution_scale'], '1.5')
        self.assertEqual(result['xbox_bindings']['A'], 'south')
        self.assertEqual(result['xbox_bindings']['B'], 'default')
        self.assertEqual(result['keyboard_bindings']['A'], 'SPACE')
        self.assertEqual(result['controller']['keyboard_player'], '1')
        self.assertEqual(result['controller']['layout'], 'labels')
        self.assertEqual(result['controller']['deadzone'], '0.12')
        self.assertEqual(result['launch']['speed'], 'unlimited')
        self.assertIn('; keep graphics comment', graphics.read_text())
        self.assertIn('custom_debug = unchanged', graphics.read_text())
        text = controllers.read_text()
        self.assertIn('; keep binding comment', text)
        self.assertIn('ignore = untouched-guid', text)
        self.assertIn('deadzone = 0.12', text)
        self.assertIn('[general]\nlayout = auto\nignore = untouched-guid\n', text)
        self.assertIn('[device abcdef]\nname = My pad\nmap.ZL = button7', text)
        self.assertIn('[future section]\nfuture_value = preserved', text)
        self.assertNotIn('map.b =', text.lower())

    def test_network_modes_always_use_normal_speed_and_preferences_are_strict(self):
        self.file('coastlink_settings.json', json.dumps({'launch': {'speed': 'unlimited', 'skip_movies': True}}))
        self.assertEqual(settings.runtime_environment(self.build, 'offline'), {'SSBU_SPEED': '0', 'SSBU_SKIP_MOVIES': '1'})
        for mode in ('host', 'join', 'lobby-host', 'lobby-join'):
            self.assertEqual(settings.runtime_environment(self.build, mode)['SSBU_SPEED'], '1')
        self.file('coastlink_settings.json', json.dumps({'launch': {'speed': 'fast', 'skip_movies': 'true', 'SSBU_SPEED': '0'}}))
        self.assertEqual(settings.runtime_environment(self.build, 'offline'), {'SSBU_SPEED': '1', 'SSBU_SKIP_MOVIES': '0'})
        self.file('coastlink_settings.json', 'broken json')
        self.assertEqual(settings.runtime_environment(self.build, 'offline')['SSBU_SPEED'], '1')

    def test_lower_input_delay_applies_online_only(self):
        self.assertEqual(settings.get_settings(self.build)['launch']['input_delay'], 'auto')
        for mode in ('host', 'lobby-join'):
            self.assertNotIn('SSBU_RB_NET_LATE', settings.runtime_environment(self.build, mode))
        result = settings.save_settings(self.build, {'launch': {'input_delay': 'lower'}})
        self.assertEqual(result['launch']['input_delay'], 'lower')
        for mode in ('host', 'join', 'lobby-host', 'lobby-join'):
            self.assertEqual(settings.runtime_environment(self.build, mode)['SSBU_RB_NET_LATE'], '1')
        self.assertNotIn('SSBU_RB_NET_LATE', settings.runtime_environment(self.build, 'offline'))
        self.file('coastlink_settings.json', json.dumps({'launch': {'input_delay': '-5'}}))
        self.assertEqual(settings.get_settings(self.build)['launch']['input_delay'], 'auto')
        self.assertNotIn('SSBU_RB_NET_LATE', settings.runtime_environment(self.build, 'host'))

    def test_audio_and_gpu_names_keep_literal_punctuation(self):
        name = 'Speakers [HDMI] #2 = Main; Output'
        result = settings.save_settings(self.build, {'graphics': {'audio_device': name, 'gpu': 'GPU #1 [NVIDIA]'}})
        self.assertEqual(result['graphics']['audio_device'], name)
        self.assertEqual(result['graphics']['gpu'], 'GPU #1 [NVIDIA]')
        self.assertEqual(settings.get_settings(self.build)['graphics']['audio_device'], name)
        settings.save_settings(self.build, {'graphics': {'volume': '65'}})
        self.assertEqual(settings.get_settings(self.build)['graphics']['audio_device'], name)

    def test_higher_delay_uses_runtime_plus_option_only_online(self):
        settings.save_settings(self.build, {'launch': {'input_delay': 'higher'}})
        self.assertNotIn('SSBU_RB_NET_DELAY_PLUS', settings.runtime_environment(self.build, 'offline'))
        for mode in ('host', 'join', 'lobby-host', 'lobby-join'):
            env = settings.runtime_environment(self.build, mode)
            self.assertEqual(env['SSBU_RB_NET_DELAY_PLUS'], '1')
            self.assertNotIn('SSBU_RB_NET_LATE', env)

    def test_concurrent_partial_saves_preserve_both_changes(self):
        settings.save_settings(self.build, {'graphics': {'volume': '10', 'mute_background': 'off'}})
        entered, release = threading.Event(), threading.Event()
        validate = settings._validate
        def hold_first(payload):
            if payload['graphics']['volume'] == '51' and payload['graphics']['mute_background'] == 'off':
                entered.set()
                self.assertTrue(release.wait(3))
            return validate(payload)
        with patch.object(settings, '_validate', side_effect=hold_first), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(settings.save_settings, self.build, {'graphics': {'volume': '51'}})
            self.assertTrue(entered.wait(3))
            second = pool.submit(settings.save_settings, self.build, {'graphics': {'mute_background': 'on'}})
            release.set()
            first.result(timeout=3)
            second.result(timeout=3)
        result = settings.get_settings(self.build)['graphics']
        self.assertEqual((result['volume'], result['mute_background']), ('51', 'on'))

    def test_invalid_payload_never_changes_any_file(self):
        graphics = self.file('graphics.ini', 'volume = 53\n')
        controller = self.file('controllers.ini', '[general]\nlayout = labels\n')
        before = (graphics.read_bytes(), controller.read_bytes())
        invalid = (
            {'graphics': {'resolution_scale': 'nan'}},
            {'graphics': {'width': '1920.5'}},
            {'graphics': {'rollback': 'off'}},
            {'graphics': {'gpu': 'auto\nrollback=off'}},
            {'graphics': {'invalid': 'foo'}},
            {'controller': {'deadzone': '0.99', 'outer_zone': '0.8'}},
            {'xbox_bindings': {'A': 'unknown-button'}},
            {'xbox_bindings': {'A': 'east,south,north,west,start'}},
            {'keyboard_bindings': {'A': 'F19'}},
            {'launch': {'speed': 'fast'}},
            {'launch': {'skip_movies': 'true'}},
            {'launch': {'SSBU_SPEED': '0'}},
            {'launch': {'input_delay': '0'}},
            {'other_group': {}},
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(settings.SettingsError):
                settings.save_settings(self.build, payload)
            self.assertEqual((graphics.read_bytes(), controller.read_bytes()), before)
            self.assertFalse((self.build / 'config' / 'coastlink_settings.json').exists())

    def test_duplicate_keys_are_not_left_to_override_the_saved_value(self):
        self.file('graphics.ini', 'volume = 10\nvolume = 20\n')
        controller = self.file('controllers.ini', '[type xbox]\nmap.A = east\nmap.A = north\n'
            '[general]\nlayout = labels\n[type xbox]\nmap.A = west\n')
        result = settings.save_settings(self.build, {'xbox_bindings': {'A': 'south'}, 'graphics': {'volume': '65'}})
        self.assertEqual(result['xbox_bindings']['A'], 'south')
        self.assertEqual(result['graphics']['volume'], '65')
        self.assertEqual(controller.read_text().lower().count('map.a ='), 1)

    def test_write_failure_restores_replaced_user_files(self):
        graphics = self.file('graphics.ini', '; graphics\nvolume = 17\n')
        controller = self.file('controllers.ini', '; controller\n[general]\nlayout = auto\n')
        before = (graphics.read_bytes(), controller.read_bytes())
        original = settings.os.replace
        calls = []
        def fail_second(source, target):
            calls.append(str(target))
            if len(calls) == 2:
                raise OSError('simulated settings write failure')
            return original(source, target)
        with patch.object(settings.os, 'replace', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'simulated'):
                settings.save_settings(self.build, {'graphics': {'volume': '88'}})
        self.assertEqual((graphics.read_bytes(), controller.read_bytes()), before)
        self.assertEqual(list((self.build / 'config').glob('*.tmp')), [])
        self.assertEqual(list((self.build / 'config').glob('*.restore')), [])

    def test_cli_accepts_powershell_utf8_bom_json_and_non_ascii_path(self):
        payload = Path(self.temp.name) / 'settings-é.json'
        payload.write_text(json.dumps({'controller': {'layout': 'labels'}, 'launch': {'speed': 'unlimited'}}), encoding='utf-8-sig')
        result = subprocess.run([sys.executable, '-B', str(Path(settings.__file__)), 'save', '--file', str(payload),
                    '--build-dir', str(self.build)], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['launch']['speed'], 'unlimited')
        self.assertEqual(settings.get_settings(self.build)['controller']['layout'], 'labels')


if __name__ == '__main__':
    unittest.main()
