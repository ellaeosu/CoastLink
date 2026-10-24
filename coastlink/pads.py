"""Controllers and audio devices for the CoastLink app, through the game's own SDL3.dll (build/work), so device names and
GUIDs are the ones the game uses in controllers.ini. Every SDL call runs on one thread (SDL is not called concurrently).
No window is created. GPL-3.0-or-later.
"""
from __future__ import annotations

import ctypes
import math
import os
import queue
import threading
import time
from pathlib import Path

import engine

SDL_INIT_AUDIO, SDL_INIT_JOYSTICK, SDL_INIT_GAMEPAD = 0x10, 0x200, 0x2000
BUTTONS = ["south", "east", "west", "north", "back", "guide", "start", "leftstick", "rightstick", "leftshoulder",
           "rightshoulder", "dpup", "dpdown", "dpleft", "dpright", "misc1", "rightpaddle1", "leftpaddle1", "rightpaddle2",
           "leftpaddle2", "touchpad", "misc2", "misc3", "misc4", "misc5", "misc6"]
AXES = ["leftx", "lefty", "rightx", "righty", "lefttrigger", "righttrigger"]
KINDS = {0: "Unknown", 1: "Standard", 2: "Xbox 360", 3: "Xbox One", 4: "PlayStation 3", 5: "PlayStation 4", 6: "PlayStation 5",
         7: "Switch Pro", 8: "Joy-Con (L)", 9: "Joy-Con (R)", 10: "Joy-Con pair", 11: "GameCube"}


class GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_uint8 * 16)]


class _Sdl:
    """The SDL thread: callers queue functions and wait for their results."""
    def __init__(self):
        self.tasks: queue.Queue = queue.Queue()
        self.lib = None
        self.error = None
        self.ready = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="sdl").start()
        self.ready.wait(10)

    def _load(self):
        build = engine.build_path(engine.repo_path())
        for candidate in (build / "work" / "SDL3.dll", engine.repo_path() / "deps" / "SDL3.dll"):
            if candidate.is_file():
                lib = ctypes.CDLL(str(candidate))
                break
        else:
            raise OSError("SDL3.dll was not found (it comes with the game build)")
        lib.SDL_Init.argtypes = [ctypes.c_uint32]; lib.SDL_Init.restype = ctypes.c_bool
        lib.SDL_GetError.restype = ctypes.c_char_p
        lib.SDL_GetJoysticks.argtypes = [ctypes.POINTER(ctypes.c_int)]; lib.SDL_GetJoysticks.restype = ctypes.POINTER(ctypes.c_uint32)
        lib.SDL_GetJoystickNameForID.argtypes = [ctypes.c_uint32]; lib.SDL_GetJoystickNameForID.restype = ctypes.c_char_p
        lib.SDL_GetJoystickGUIDForID.argtypes = [ctypes.c_uint32]; lib.SDL_GetJoystickGUIDForID.restype = GUID
        lib.SDL_GUIDToString.argtypes = [GUID, ctypes.c_char_p, ctypes.c_int]
        lib.SDL_IsGamepad.argtypes = [ctypes.c_uint32]; lib.SDL_IsGamepad.restype = ctypes.c_bool
        lib.SDL_GetGamepadTypeForID.argtypes = [ctypes.c_uint32]; lib.SDL_GetGamepadTypeForID.restype = ctypes.c_int
        lib.SDL_GetJoystickVendorForID.argtypes = [ctypes.c_uint32]; lib.SDL_GetJoystickVendorForID.restype = ctypes.c_uint16
        lib.SDL_GetJoystickProductForID.argtypes = [ctypes.c_uint32]; lib.SDL_GetJoystickProductForID.restype = ctypes.c_uint16
        lib.SDL_OpenGamepad.argtypes = [ctypes.c_uint32]; lib.SDL_OpenGamepad.restype = ctypes.c_void_p
        lib.SDL_CloseGamepad.argtypes = [ctypes.c_void_p]
        lib.SDL_GetGamepadButton.argtypes = [ctypes.c_void_p, ctypes.c_int]; lib.SDL_GetGamepadButton.restype = ctypes.c_bool
        lib.SDL_GetGamepadAxis.argtypes = [ctypes.c_void_p, ctypes.c_int]; lib.SDL_GetGamepadAxis.restype = ctypes.c_int16
        lib.SDL_RumbleGamepad.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32]; lib.SDL_RumbleGamepad.restype = ctypes.c_bool
        lib.SDL_OpenJoystick.argtypes = [ctypes.c_uint32]; lib.SDL_OpenJoystick.restype = ctypes.c_void_p
        lib.SDL_CloseJoystick.argtypes = [ctypes.c_void_p]
        lib.SDL_GetNumJoystickButtons.argtypes = [ctypes.c_void_p]; lib.SDL_GetNumJoystickButtons.restype = ctypes.c_int
        lib.SDL_GetNumJoystickAxes.argtypes = [ctypes.c_void_p]; lib.SDL_GetNumJoystickAxes.restype = ctypes.c_int
        lib.SDL_GetNumJoystickHats.argtypes = [ctypes.c_void_p]; lib.SDL_GetNumJoystickHats.restype = ctypes.c_int
        lib.SDL_GetJoystickButton.argtypes = [ctypes.c_void_p, ctypes.c_int]; lib.SDL_GetJoystickButton.restype = ctypes.c_bool
        lib.SDL_GetJoystickAxis.argtypes = [ctypes.c_void_p, ctypes.c_int]; lib.SDL_GetJoystickAxis.restype = ctypes.c_int16
        lib.SDL_GetJoystickHat.argtypes = [ctypes.c_void_p, ctypes.c_int]; lib.SDL_GetJoystickHat.restype = ctypes.c_uint8
        lib.SDL_UpdateJoysticks.argtypes = []
        lib.SDL_UpdateGamepads.argtypes = []
        lib.SDL_free.argtypes = [ctypes.c_void_p]
        lib.SDL_SetHint.argtypes = [ctypes.c_char_p, ctypes.c_char_p]; lib.SDL_SetHint.restype = ctypes.c_bool
        lib.SDL_InitSubSystem.argtypes = [ctypes.c_uint32]; lib.SDL_InitSubSystem.restype = ctypes.c_bool
        lib.SDL_GetAudioPlaybackDevices.argtypes = [ctypes.POINTER(ctypes.c_int)]; lib.SDL_GetAudioPlaybackDevices.restype = ctypes.POINTER(ctypes.c_uint32)
        lib.SDL_GetAudioDeviceName.argtypes = [ctypes.c_uint32]; lib.SDL_GetAudioDeviceName.restype = ctypes.c_char_p
        # GameCube adapters in PC mode are read the Windows way, as the game does (nnpad_sdl.c gamecube_pc = windows)
        lib.SDL_SetHint(b"SDL_HIDAPI_IGNORE_DEVICES", b"0x0079/0x1843,0x0079/0x1844,0x0079/0x1846")
        lib.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")    # (the game window, not ours, has the focus while testing)
        if not lib.SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMEPAD):
            raise OSError("SDL could not start: " + (lib.SDL_GetError() or b"").decode(errors="replace"))
        return lib

    def _run(self):
        try:
            self.lib = self._load()
        except OSError as error:
            self.error = str(error)
        self.ready.set()
        while True:
            fn, result = self.tasks.get()
            try:
                result.put((True, fn(self.lib) if self.lib else None))
            except Exception as error:
                result.put((False, error))

    def call(self, fn, timeout=5.0):
        if self.error:
            raise OSError(self.error)
        result: queue.Queue = queue.Queue()
        self.tasks.put((fn, result))
        ok, value = result.get(timeout=timeout)
        if not ok:
            raise value
        return value


_sdl: _Sdl | None = None
_sdl_lock = threading.Lock()


def sdl() -> _Sdl:
    global _sdl
    with _sdl_lock:
        if _sdl is None:
            _sdl = _Sdl()
        return _sdl


def _guid(lib, jid) -> str:
    buf = ctypes.create_string_buffer(64)
    lib.SDL_GUIDToString(lib.SDL_GetJoystickGUIDForID(jid), buf, 64)
    return buf.value.decode()


def type_key(gamepad_type: int, gamepad: bool = True) -> str:
    if not gamepad:
        return "joystick"
    return ({2: "xbox", 3: "xbox", 4: "playstation", 5: "playstation", 6: "playstation",
             7: "switch", 8: "switch", 9: "switch", 10: "switch", 11: "gamecube"}).get(gamepad_type, "generic")


GAMECUBE_IDS = {(0x0079, 0x1843), (0x0079, 0x1844), (0x0079, 0x1846), (0x057E, 0x0337)}   # Mayflash PC mode, Nintendo WUP-028
XBOX_SERIES_IDS = {0x0B12, 0x0B13, 0x0B20, 0x0B21, 0x0B22}                                    # Microsoft Xbox Series X|S pads


def model_key(gamepad_type: int, vendor: int, product: int, name: str, gamepad: bool = True) -> str:
    """Which controller to draw in the app's live preview (the SDL type, refined by the USB vendor/product ids)."""
    if not gamepad:
        return "joystick"
    if (vendor, product) in GAMECUBE_IDS or gamepad_type == 11 or "gamecube" in name.lower():
        return "gamecube"
    if gamepad_type == 3:
        return "xboxseries" if vendor == 0x045E and product in XBOX_SERIES_IDS else "xboxone"
    return {2: "xbox360", 4: "ps3", 5: "ps4", 6: "ps5", 7: "switchpro", 8: "joyconl", 9: "joyconr",
            10: "joyconpair"}.get(gamepad_type, "generic")


_activated_adapter_ports: dict[int, int] = {}  # SDL instance IDs; only touched on the SDL thread.


def _list(lib) -> list[dict]:
    lib.SDL_UpdateJoysticks()
    lib.SDL_UpdateGamepads()
    count = ctypes.c_int(0)
    ids = lib.SDL_GetJoysticks(ctypes.byref(count))
    rows = []
    for i in range(count.value):
        jid = ids[i]
        name = (lib.SDL_GetJoystickNameForID(jid) or b"Controller").decode(errors="replace")
        pad = lib.SDL_IsGamepad(jid)
        kind = lib.SDL_GetGamepadTypeForID(jid) if pad else 0
        vendor, product = lib.SDL_GetJoystickVendorForID(jid), lib.SDL_GetJoystickProductForID(jid)
        pc_adapter = vendor == 0x0079 and product in (0x1843, 0x1844, 0x1846)
        if pc_adapter and int(jid) not in _activated_adapter_ports:
            joystick = lib.SDL_OpenJoystick(jid)
            try:
                if joystick and any(lib.SDL_GetJoystickButton(joystick, button) for button in range(lib.SDL_GetNumJoystickButtons(joystick))):
                    _activated_adapter_ports[int(jid)] = max(_activated_adapter_ports.values(), default=0) + 1
            finally:
                if joystick:
                    lib.SDL_CloseJoystick(joystick)
        rows.append({"id": int(jid), "guid": _guid(lib, jid), "name": name, "gamepad": bool(pad),
                     "kind": KINDS.get(kind, "Controller") if pad else "Joystick", "type_key": type_key(kind, bool(pad)),
                     "model": model_key(kind, vendor, product, name, bool(pad)), "vendor": vendor, "product": product,
                     "waiting_for_input": pc_adapter and int(jid) not in _activated_adapter_ports,
                     "activation_order": _activated_adapter_ports.get(int(jid), 0)})
    if ids:
        lib.SDL_free(ids)
    present = {row["id"] for row in rows}
    for jid in list(_activated_adapter_ports):
        if jid not in present:
            del _activated_adapter_ports[jid]
    return rows


def assign_players(rows: list[dict], config: dict) -> list[dict]:
    """Preview native configured slots without giving duplicate-GUID pads the same player."""
    players = {number: str(config.get("players", {}).get(str(number), "auto")).lower() for number in range(1, 9)}
    occupied = set()
    for row in rows:
        row["player"] = None
    # Activated adapter ports retain their first-button order, rather than empty port numbers taking slots.
    ordered = sorted(enumerate(rows), key=lambda item: (item[1].get("activation_order", 0), item[0]))
    for _, row in ordered:
        if row.get("waiting_for_input") or row.get("ignored"):
            continue
        guid = row["guid"].lower()
        desired = next((number for number, target in players.items() if target == guid and number not in occupied), None)
        if desired is None:
            desired = next((number for number, target in players.items() if target == "auto" and number not in occupied), None)
        row["player"] = desired
        if desired is not None:
            occupied.add(desired)
    return rows


def devices() -> list[dict]:
    """Connected controllers, with the player each one is assigned to in controllers.ini (or the order the game uses)."""
    try:
        rows = sdl().call(_list)
    except (OSError, queue.Empty):
        return []
    import controller_config
    return assign_players(rows, controller_config.load(engine.build_path(engine.repo_path())))


class _Watcher:
    """One controller's live state at ~60 Hz, sent as events while the Controllers screen is open."""
    def __init__(self):
        self.guid = None
        self.emit = None
        self.thread = None
        self.lock = threading.Lock()

    def set_watch(self, guid, emit):
        with self.lock:
            self.guid, self.emit = guid, emit
            if guid and not (self.thread and self.thread.is_alive()):
                self.thread = threading.Thread(target=self._loop, daemon=True, name="pad-watch")
                self.thread.start()

    def _loop(self):
        handle = {"guid": None, "id": None, "pad": None, "joy": None}
        last = None

        def sample(lib):
            row = next((row for row in _list(lib) if row["guid"] == self.guid), None)
            instance_id = row["id"] if row else None
            if handle["guid"] != self.guid or handle["id"] != instance_id:
                if handle["pad"]:
                    lib.SDL_CloseGamepad(handle["pad"])
                if handle["joy"]:
                    lib.SDL_CloseJoystick(handle["joy"])
                handle.update(guid=self.guid, id=instance_id, pad=None, joy=None)
                if row:
                    if row["gamepad"]:
                        handle["pad"] = lib.SDL_OpenGamepad(row["id"])
                    else:
                        handle["joy"] = lib.SDL_OpenJoystick(row["id"])
            lib.SDL_UpdateJoysticks()
            if handle["pad"]:
                pad = handle["pad"]
                return {"guid": self.guid, "connected": True, "buttons": [b for i, b in enumerate(BUTTONS) if lib.SDL_GetGamepadButton(pad, i)],
                        "axes": {a: lib.SDL_GetGamepadAxis(pad, i) for i, a in enumerate(AXES)}, "raw": False}
            if handle["joy"]:
                joy = handle["joy"]
                hats = []
                for h in range(lib.SDL_GetNumJoystickHats(joy)):
                    v = lib.SDL_GetJoystickHat(joy, h)
                    hats += [f"hat{h}{d}" for bit, d in ((1, "up"), (2, "right"), (4, "down"), (8, "left")) if v & bit]
                return {"guid": self.guid, "connected": True, "buttons": [f"button{i}" for i in range(lib.SDL_GetNumJoystickButtons(joy)) if lib.SDL_GetJoystickButton(joy, i)] + hats,
                        "axes": {f"axis{i}": lib.SDL_GetJoystickAxis(joy, i) for i in range(lib.SDL_GetNumJoystickAxes(joy))}, "raw": True}
            return {"guid": self.guid, "connected": False}

        while self.guid:
            try:
                state = sdl().call(sample)
                key = (state.get("guid"), state.get("connected"), tuple(state.get("buttons", ())), tuple((k, v // 512) for k, v in state.get("axes", {}).items()))
                if key != last and self.emit:
                    last = key
                    self.emit(state)
            except (OSError, queue.Empty):
                time.sleep(1)
            time.sleep(1 / 60)
        def close(lib):
            if handle["pad"]:
                lib.SDL_CloseGamepad(handle["pad"])
            if handle["joy"]:
                lib.SDL_CloseJoystick(handle["joy"])
        try:
            sdl().call(close)
        except (OSError, queue.Empty):
            pass
        # A fast screen/device switch may have requested a new watch while the old thread was closing handles.
        with self.lock:
            if self.guid:
                self.thread = threading.Thread(target=self._loop, daemon=True, name="pad-watch")
                self.thread.start()
            else:
                self.thread = None


watcher = _Watcher()


_rumble_pads: dict[str, tuple[int, int]] = {}  # instance ID, handle (only touched on the SDL thread).


def rumble(guid: str, strength: float = 1.0, ms: int = 400) -> bool:
    """strength 0..2 as controllers.ini rumble_strength (1 = full); the high band at half the low one, as the game does."""
    if not math.isfinite(strength) or not 0 <= strength <= 2 or not 0 <= ms <= 5000:
        raise ValueError("Choose rumble strength 0–200% and a test lasting at most five seconds.")
    level = min(0xFFFF, int(0xFFFF * strength))
    high = min(0xFFFF, int(0x7FFF * strength))

    def go(lib):
        row = next((row for row in _list(lib) if row["guid"] == guid and row["gamepad"]), None)
        cached = _rumble_pads.get(guid)
        if cached and (not row or cached[0] != row["id"]):
            lib.SDL_CloseGamepad(cached[1])
            _rumble_pads.pop(guid, None)
        if row and guid not in _rumble_pads:
            handle = lib.SDL_OpenGamepad(row["id"])
            if handle:
                _rumble_pads[guid] = (row["id"], handle)
        pad = _rumble_pads.get(guid)
        return bool(pad and lib.SDL_RumbleGamepad(pad[1], level, high, ms))
    return sdl().call(go)


def gamecube_adapters() -> list[dict]:
    """GameCube adapters Windows sees, and whether the game can use them:
    Wii U / Switch mode (057E:0337) needs the WinUSB driver (Zadig), PC mode (Mayflash 0079:1843/1844/1846) needs nothing.
    Read from the device list (SetupAPI); nothing is installed or changed."""
    if os.name != "nt":
        return []
    from ctypes import wintypes
    setup = ctypes.WinDLL("setupapi", use_last_error=True)

    class DevInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("guid", ctypes.c_byte * 16), ("inst", wintypes.DWORD), ("reserved", ctypes.c_void_p)]
    setup.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setup.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    setup.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DevInfo)]
    setup.SetupDiGetDeviceInstanceIdW.argtypes = [ctypes.c_void_p, ctypes.POINTER(DevInfo), wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    setup.SetupDiGetDeviceRegistryPropertyW.argtypes = [ctypes.c_void_p, ctypes.POINTER(DevInfo), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                                        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    setup.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    DIGCF_PRESENT, DIGCF_ALLCLASSES, SPDRP_SERVICE = 0x2, 0x4, 0x4
    handle = setup.SetupDiGetClassDevsW(None, "USB", None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if not handle or handle == ctypes.c_void_p(-1).value:
        return []
    found = []
    try:
        index = 0
        while True:
            info = DevInfo()
            info.size = ctypes.sizeof(DevInfo)
            if not setup.SetupDiEnumDeviceInfo(handle, index, ctypes.byref(info)):
                break
            index += 1
            buf = ctypes.create_unicode_buffer(512)
            if not setup.SetupDiGetDeviceInstanceIdW(handle, ctypes.byref(info), buf, 512, None):
                continue
            ident = buf.value.upper()
            service = ctypes.create_unicode_buffer(128)
            setup.SetupDiGetDeviceRegistryPropertyW(handle, ctypes.byref(info), SPDRP_SERVICE, None, service, ctypes.sizeof(service), None)
            winusb = service.value.lower() == "winusb"
            if "VID_057E&PID_0337" in ident:
                found.append({"mode": "wiiu", "driver": service.value or "none", "usable": winusb,
                              "advice": "GameCube adapter in Wii U mode with WinUSB: ready (read directly, like Slippi). Each port is that player."
                              if winusb else
                              f"GameCube adapter in Wii U mode with the \"{service.value or 'no'}\" driver, not WinUSB: flip the switch to PC mode, "
                              "or install WinUSB for \"WUP-028\" with Zadig."})
            elif "VID_0079&PID_184" in ident and any(f"PID_{p}" in ident for p in ("1843", "1844", "1846")):
                found.append({"mode": "pc", "driver": service.value or "HID", "usable": not winusb,
                              "advice": "GameCube adapter in PC mode has the WinUSB driver, so Windows can't read it as a controller. "
                              "Flip the switch to Wii U (and give WinUSB to \"WUP-028\" in Zadig if it isn't already), "
                              "or uninstall this device's driver in Device Manager to use PC mode."
                              if winusb else
                              "GameCube adapter in PC mode: press a button on a controller to give it a player slot (empty ports are skipped)."})
    finally:
        setup.SetupDiDestroyDeviceInfoList(handle)
    return found


GCA_BUTTONS = (("A", 1, 0x01), ("B", 1, 0x02), ("X", 1, 0x04), ("Y", 1, 0x08), ("Left", 1, 0x10), ("Right", 1, 0x20),
               ("Down", 1, 0x40), ("Up", 1, 0x80), ("Start", 2, 0x01), ("Z", 2, 0x02), ("R", 2, 0x04), ("L", 2, 0x08))
_gca_stop = threading.Event()


def parse_gca_report(report: bytes) -> list[dict] | None:
    """The adapter's 37-byte report (0x21, then 4 ports of 9 bytes: status, buttons 1, buttons 2, stick x / y, c-stick x / y,
    trigger L / R; status 0x10 wired / 0x20 WaveBird = a controller is there), as nnpad_gca.c reads it."""
    if len(report) < 37 or report[0] != 0x21:
        return None
    ports = []
    for p in range(4):
        s = report[1 + 9 * p: 10 + 9 * p]
        ports.append({"port": p + 1, "connected": bool(s[0] & 0x30), "wireless": bool(s[0] & 0x20),
                      "pressed": [name for name, byte, mask in GCA_BUTTONS if s[byte] & mask] if s[0] & 0x30 else [],
                      "stick": [s[3], s[4]], "cstick": [s[5], s[6]], "triggers": [s[7], s[8]]})
    return ports


def gamecube_adapter_test(emit, seconds: float = 15.0) -> dict:
    """Read the GameCube adapter in Wii U / Switch mode (WinUSB) for a few seconds, the way the game does (nnpad_gca.c), and
    report every port live through emit(ports). The adapter is released at the end (WinUSB lets one program have it)."""
    if os.name != "nt":
        return {"ok": False, "error": "Only on Windows."}
    from ctypes import wintypes
    setup = ctypes.WinDLL("setupapi", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        winusb = ctypes.WinDLL("winusb", use_last_error=True)
    except OSError:
        return {"ok": False, "error": "Windows' WinUSB library is missing."}

    class Guid(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]

    class IfaceData(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("guid", Guid), ("flags", wintypes.DWORD), ("reserved", ctypes.c_void_p)]
    usb_device = Guid(0xA5DCBF10, 0x6530, 0x11D2, (ctypes.c_ubyte * 8)(0x90, 0x1F, 0x00, 0xC0, 0x4F, 0xB9, 0x51, 0xED))
    setup.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setup.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(Guid), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    setup.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Guid), wintypes.DWORD, ctypes.POINTER(IfaceData)]
    setup.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(IfaceData), ctypes.c_void_p, wintypes.DWORD,
                                                       ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    setup.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    paths = []
    info = setup.SetupDiGetClassDevsW(ctypes.byref(usb_device), None, None, 0x12)      # DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    if info and info != ctypes.c_void_p(-1).value:
        try:
            index = 0
            while True:
                data = IfaceData()
                data.size = ctypes.sizeof(IfaceData)
                if not setup.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(usb_device), index, ctypes.byref(data)):
                    break
                index += 1
                need = wintypes.DWORD(0)
                setup.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(data), None, 0, ctypes.byref(need), None)
                buf = ctypes.create_string_buffer(max(need.value, 8))
                ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                if setup.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(data), buf, need.value, None, None):
                    path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
                    if "vid_057e&pid_0337" in path.lower():
                        paths.append(path)
        finally:
            setup.SetupDiDestroyDeviceInfoList(info)
    if not paths:
        return {"ok": False, "error": "No GameCube adapter in Wii U / Switch mode is plugged in (flip its switch to Wii U), "
                                      "or it has no WinUSB driver (Zadig: WinUSB on \"WUP-028\")."}
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    winusb.WinUsb_Initialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    winusb.WinUsb_Free.argtypes = [ctypes.c_void_p]
    winusb.WinUsb_SetPipePolicy.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p]
    winusb.WinUsb_WritePipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p]
    winusb.WinUsb_ReadPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p]
    busy = ("The adapter has WinUSB but another program has it open: close Dolphin / Slippi and the game, or in Steam "
            "turn off Settings > Controller > GameCube Configuration Support")
    # read | write, share read | write, OPEN_EXISTING, FILE_FLAG_OVERLAPPED (WinUSB wants it) | normal
    handle = kernel.CreateFileW(paths[0], 0xC0000000, 0x3, None, 3, 0x40000080, None)
    if not handle or handle == ctypes.c_void_p(-1).value:
        code = ctypes.get_last_error()
        return {"ok": False, "error": f"{busy} (Windows error {code})." if code in (5, 32, 170)
                else f"The adapter could not be opened (Windows error {code}). Unplug it and plug it in again."}
    usb = ctypes.c_void_p()
    try:
        if not winusb.WinUsb_Initialize(handle, ctypes.byref(usb)):
            code = ctypes.get_last_error()
            usb = ctypes.c_void_p()
            return {"ok": False, "error": f"{busy} (Windows error {code})." if code in (5, 32, 170)
                    else f"WinUSB could not use the adapter (Windows error {code}). Reinstall WinUSB for \"WUP-028\" with Zadig."}
        timeout = wintypes.ULONG(100)
        winusb.WinUsb_SetPipePolicy(usb, 0x81, 0x03, 4, ctypes.byref(timeout))            # PIPE_TRANSFER_TIMEOUT
        written = wintypes.ULONG(0)
        start = (ctypes.c_ubyte * 1)(0x13)
        if not winusb.WinUsb_WritePipe(usb, 0x02, start, 1, ctypes.byref(written), None):
            return {"ok": False, "error": f"The adapter does not accept the start command (Windows error {ctypes.get_last_error()})."}
        _gca_stop.clear()
        buf = (ctypes.c_ubyte * 37)()
        got = wintypes.ULONG(0)
        reports, last, ports, seen = 0, 0.0, None, set()
        end = time.monotonic() + seconds
        while time.monotonic() < end and not _gca_stop.is_set():
            if not winusb.WinUsb_ReadPipe(usb, 0x81, buf, 37, ctypes.byref(got), None):
                continue
            parsed = parse_gca_report(bytes(buf[:got.value]))
            if not parsed:
                continue
            reports += 1
            ports = parsed
            seen.update(p["port"] for p in parsed if p["connected"])
            if time.monotonic() - last > 0.05:
                last = time.monotonic()
                emit(parsed)
        if ports:
            emit(ports)
        if not reports:
            return {"ok": False, "error": "The adapter opened but sent nothing. Plug in its second (black) USB cable too, or try another USB port."}
        return {"ok": True, "reports": reports, "connected": sorted(seen),
                "summary": f"Adapter works: {reports} reports read; controller(s) in port(s) {', '.join(map(str, sorted(seen)))}." if seen
                else f"Adapter works ({reports} reports read), but no controller answered: check the plugs (ports 1–4)."}
    finally:
        if usb:
            winusb.WinUsb_Free(usb)
        kernel.CloseHandle(handle)


def stop_gamecube_adapter_test():
    _gca_stop.set()


class _WaveOutCaps(ctypes.Structure):
    _fields_ = [("wMid", ctypes.c_ushort), ("wPid", ctypes.c_ushort), ("vDriverVersion", ctypes.c_uint),
                ("szPname", ctypes.c_wchar * 32), ("dwFormats", ctypes.c_uint), ("wChannels", ctypes.c_ushort),
                ("wReserved1", ctypes.c_ushort), ("dwSupport", ctypes.c_uint)]


def audio_devices() -> list[dict]:
    """The sound outputs as the game's waveOut sees them (names stop at 31 characters there, so these are the names
    graphics.ini audio_device matches)."""
    try:
        winmm = ctypes.WinDLL("winmm")
    except (AttributeError, OSError):
        return []
    winmm.waveOutGetNumDevs.restype = ctypes.c_uint
    winmm.waveOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(_WaveOutCaps), ctypes.c_uint]
    winmm.waveOutGetDevCapsW.restype = ctypes.c_uint
    rows = []
    for index in range(winmm.waveOutGetNumDevs()):
        caps = _WaveOutCaps()
        if winmm.waveOutGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps)) == 0 and caps.szPname:
            rows.append({"id": index, "name": caps.szPname})
    return rows
