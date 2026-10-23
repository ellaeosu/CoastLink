"""Test connection (the Online screen): can this PC reach the lobby, how long a round trip to it takes, and who is waiting
with this lobby code: players of this CoastLink and game version, and players of another version (who cannot be matched).

It speaks the lobby protocol of the runtime (net_relay.c, "SU" version 1): JOIN, WELCOME, PING, PONG, LEAVE. It never
sends MATCH, so it is never paired with anyone, and it leaves the lobby at once. GPL-3.0-or-later.
"""
from __future__ import annotations

import os
import socket
import struct
import time

PROTO, JOIN, WELCOME, REJECT, PING, PONG, LEAVE = 1, 1, 2, 3, 4, 5, 7
NAME_LEN, BUILD_LEN = 32, 40


def _hdr(kind: int) -> bytes:
    return b"SU" + bytes((PROTO, kind))


def _field(text: str, size: int) -> bytes:
    return text.encode("utf-8")[:size].ljust(size, b"\0")


def join_packet(nonce: int, code: str, name: str, build: str) -> bytes:
    return (_hdr(JOIN) + struct.pack(">Q", nonce) + _field(code, NAME_LEN) + _field(name, NAME_LEN) + _field(build, BUILD_LEN)
            + struct.pack(">IHB", 0, 0, 0))


def parse_pong(packet: bytes) -> dict | None:
    """PONG: time u64, players u16 (this build and code), rooms u16 [, searching u16, players u16 (every build of this code)]."""
    if len(packet) < 16 or packet[:4] != _hdr(PONG):
        return None
    sent, same, rooms = struct.unpack_from(">QHH", packet, 4)
    searching, code = struct.unpack_from(">HH", packet, 16) if len(packet) >= 20 else (None, None)
    return {"time": sent, "same": same, "rooms": rooms, "searching": searching, "code": code}


def lobby_probe(server: str, code: str, build: str, timeout: float = 4.0) -> dict:
    host, _, port = server.rpartition(":")
    try:
        address = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_DGRAM)[0][4]
    except (socket.gaierror, ValueError, IndexError):
        return {"reachable": False, "error": f"The lobby {server} could not be found (no internet, or a wrong address)."}
    nonce = int.from_bytes(os.urandom(8), "big")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    cookie = None
    try:
        deadline = time.monotonic() + timeout
        while cookie is None and time.monotonic() < deadline:
            sock.sendto(join_packet(nonce, code, "CoastLink test", build), address)
            try:
                packet, _ = sock.recvfrom(2048)
            except (socket.timeout, ConnectionResetError):
                continue
            if packet[:4] == _hdr(WELCOME) and len(packet) >= 24 and struct.unpack_from(">Q", packet, 4)[0] == nonce:
                cookie = struct.unpack_from(">Q", packet, 16)[0]
            elif packet[:4] == _hdr(REJECT) and len(packet) >= 12:
                return {"reachable": True, "error": "The lobby refused: " + packet[12:76].split(b"\0")[0].decode("utf-8", "replace")}
        if cookie is None:
            return {"reachable": False, "error": f"No answer from the lobby {server}. A firewall may block UDP port {port}."}
        rtts, pong = [], None
        for _ in range(4):
            sent = time.monotonic()
            sock.sendto(_hdr(PING) + struct.pack(">QQB", cookie, int(sent * 1000), 0), address)
            try:
                packet, _ = sock.recvfrom(2048)
            except (socket.timeout, ConnectionResetError):
                continue
            reply = parse_pong(packet)
            if reply:
                rtts.append((time.monotonic() - sent) * 1000)
                pong = reply
            time.sleep(0.15)
        if not pong:
            return {"reachable": False, "error": "The lobby answered once, then stopped. Try again."}
        waiting = max(0, pong["same"] - 1)                                       # (this test counts itself)
        other = max(0, (pong["code"] or pong["same"]) - pong["same"])
        return {"reachable": True, "lobby_ms": round(min(rtts)), "waiting_same_version": waiting, "waiting_other_version": other,
                "rooms": pong["rooms"], "server": server, "build": build}
    finally:
        if cookie is not None:
            try:
                sock.sendto(_hdr(LEAVE) + struct.pack(">Q", cookie), address)
            except OSError:
                pass
        sock.close()


def candidate_builds(game_version: str, mine: str) -> dict[str, str]:
    """Build ids another CoastLink may use with this game version -> the version to name: CoastLink up to 0.5.x (no +cl
    part) and the releases around this one. The lobby only says how many players of this code run another build."""
    base = f"ssbu-recomp-ldn1-{game_version}"
    major, minor = (int(part) for part in (mine.split(".") + ["0", "0"])[:2])
    out = {base: "0.5.x or older"}
    for m in range(max(0, minor - 1), minor + 3):
        for patch in range(0, 10):
            version = f"{major}.{m}.{patch}"
            if version != mine:
                out[f"{base}+cl{version}"[:BUILD_LEN]] = version
    return out


def identify_other_versions(server: str, code: str, game_version: str, mine: str) -> list[str]:
    """The versions (from candidate_builds) that have a player with this lobby code right now."""
    from concurrent.futures import ThreadPoolExecutor
    candidates = candidate_builds(game_version, mine)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda build: (build, lobby_probe(server, code, build, timeout=2.5)), candidates))
    return [candidates[build] for build, result in results if result.get("waiting_same_version")]
