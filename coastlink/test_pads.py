"""SDL boundary tests without a game or physical controller."""
import ctypes
import unittest
from unittest.mock import patch

import pads

GUID = '03000000de280000ff11000000007801'
OTHER = '030000005e0400008e02000000007801'


class FakeSdl:
    def __init__(self, lib):
        self.lib = lib
    def call(self, fn):
        return fn(self.lib)


class FakeLib:
    def __init__(self):
        self.ids = [1, 2]
        self.pressed = set()
        self.opened, self.closed, self.rumbles = [], [], []
    def SDL_UpdateJoysticks(self): pass
    def SDL_UpdateGamepads(self): pass
    def SDL_GetJoysticks(self, count):
        ctypes.cast(count, ctypes.POINTER(ctypes.c_int))[0] = len(self.ids)
        return self.ids
    def SDL_GetJoystickNameForID(self, jid): return b'Mayflash port'
    def SDL_IsGamepad(self, jid): return True
    def SDL_GetGamepadTypeForID(self, jid): return 2
    def SDL_GetJoystickVendorForID(self, jid): return 0x0079
    def SDL_GetJoystickProductForID(self, jid): return 0x1843
    def SDL_OpenJoystick(self, jid): return jid
    def SDL_CloseJoystick(self, handle): pass
    def SDL_GetNumJoystickButtons(self, handle): return 4
    def SDL_GetJoystickButton(self, handle, index): return handle in self.pressed and index == 0
    def SDL_GetGamepadButton(self, handle, index): return False
    def SDL_GetGamepadAxis(self, handle, index): return 0
    def SDL_OpenGamepad(self, jid):
        self.opened.append(jid)
        return jid + 100
    def SDL_CloseGamepad(self, handle): self.closed.append(handle)
    def SDL_RumbleGamepad(self, handle, low, high, ms):
        self.rumbles.append((handle, low, high, ms))
        return True
    def SDL_free(self, pointer): pass


class PadTests(unittest.TestCase):
    def tearDown(self):
        pads._activated_adapter_ports.clear()
        pads._rumble_pads.clear()

    def test_sdl_type_keys_match_native_type_profiles(self):
        self.assertEqual([pads.type_key(n) for n in (2, 3, 4, 6, 7, 10, 11, 0)],
                         ['xbox', 'xbox', 'playstation', 'playstation', 'switch', 'switch', 'gamecube', 'generic'])
        self.assertEqual(pads.type_key(2, False), 'joystick')
        self.assertIn('misc6', pads.BUTTONS)

    def test_identical_guid_controllers_do_not_share_explicit_slot(self):
        rows = [{'guid': GUID}, {'guid': GUID}, {'guid': OTHER}]
        assigned = pads.assign_players(rows, {'players': {'1': GUID, '2': 'auto', '3': GUID}})
        self.assertEqual([row['player'] for row in assigned], [1, 3, 2])
        assigned = pads.assign_players(rows, {'players': {str(n): 'none' for n in range(1, 9)}})
        self.assertEqual([row['player'] for row in assigned], [None, None, None])

    def test_pc_adapter_empty_ports_wait_for_a_button_then_keep_press_order(self):
        lib = FakeLib()
        with patch.object(pads, '_guid', return_value=GUID):
            rows = pads._list(lib)
            self.assertTrue(all(row['waiting_for_input'] for row in rows))
            self.assertTrue(all(row['player'] is None for row in pads.assign_players(rows, {})))
            lib.pressed = {2}
            rows = pads.assign_players(pads._list(lib), {})
            self.assertEqual([row['player'] for row in rows], [None, 1])
            lib.pressed = {1}
            rows = pads.assign_players(pads._list(lib), {})
            self.assertEqual([row['player'] for row in rows], [2, 1])

    def test_rumble_reopens_after_hotplug_and_two_hundred_percent_changes_high_motor(self):
        lib = FakeLib()
        row = {'id': 1, 'guid': GUID, 'gamepad': True}
        with patch.object(pads, 'sdl', return_value=FakeSdl(lib)), patch.object(pads, '_list', return_value=[row]):
            self.assertTrue(pads.rumble(GUID, 1, 400))
            first = lib.rumbles[-1]
            row['id'] = 2
            self.assertTrue(pads.rumble(GUID, 2, 450))
            second = lib.rumbles[-1]
        self.assertEqual(lib.opened, [1, 2])
        self.assertIn(101, lib.closed)
        self.assertEqual(second[0], 102)
        self.assertGreater(second[2], first[2])
        with self.assertRaises(ValueError): pads.rumble(GUID, float('nan'))

    def test_live_watch_reopens_same_guid_on_new_instance_and_releases_handles(self):
        lib = FakeLib()
        watcher = pads._Watcher()
        watcher.guid, watcher.emit = GUID, lambda value: None
        calls = 0
        class WatchSdl(FakeSdl):
            def call(self, fn):
                nonlocal calls
                value = super().call(fn)
                calls += 1
                if calls == 2:
                    watcher.guid = None
                return value
        rows = [[{'id': 1, 'guid': GUID, 'gamepad': True}], [{'id': 2, 'guid': GUID, 'gamepad': True}]]
        with patch.object(pads, 'sdl', return_value=WatchSdl(lib)), patch.object(pads, '_list', side_effect=rows):
            watcher._loop()
        self.assertEqual(lib.opened, [1, 2])
        self.assertEqual(lib.closed, [101, 102])


if __name__ == '__main__':
    unittest.main()
