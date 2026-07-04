#!/usr/bin/env python3
"""
vmc_ws_bridge.py — VMC(OSC/UDP) を受けて WebSocket でブラウザ(three-vrm)へ中継。

ブラウザは UDP を直接受けられないので レンダーホスト 上でこれを挟む。
顔(iFM)・指(Leap)・頭、全部この1ポートに VMC を送れば renderer に届く。

  VMC(UDP :39540) ──> [この橋] ──> WebSocket(:8200) ──> ブラウザ

実行: renderer/.venv/bin/python vmc_ws_bridge.py
"""
import asyncio
import json

import websockets
from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage

VMC_UDP_PORT = 39540
WS_PORT = 8200

CLIENTS = set()
stats = {"frames": 0, "last_bones": 0}
seen_bones = {}    # name -> last quat (診断)
seen_blends = {}   # name -> last val (診断)


def _handle_msg(msg: OscMessage, out: list):
    a = msg.address
    p = msg.params
    if a == "/VMC/Ext/Bone/Pos" and len(p) >= 8:
        seen_bones[p[0]] = (round(p[4], 3), round(p[5], 3), round(p[6], 3), round(p[7], 3))
        out.append({"k": "bone", "n": p[0],
                    "p": [p[1], p[2], p[3]],
                    "r": [p[4], p[5], p[6], p[7]]})
    elif a == "/VMC/Ext/Blend/Val" and len(p) >= 2:
        seen_blends[p[0]] = round(p[1], 3)
        out.append({"k": "blend", "n": p[0], "v": p[1]})
    elif a == "/VMC/Ext/Blend/Apply":
        out.append({"k": "blendApply"})
    elif a == "/VMC/Ext/Root/Pos" and len(p) >= 8:
        out.append({"k": "root", "p": [p[1], p[2], p[3]],
                    "r": [p[4], p[5], p[6], p[7]]})


def _walk_bundle(b: OscBundle, out: list):
    for i in range(b.num_contents):
        c = b.content(i)
        if isinstance(c, OscBundle):
            _walk_bundle(c, out)
        else:
            _handle_msg(c, out)


def parse_packet(data: bytes) -> list:
    out = []
    if OscBundle.dgram_is_bundle(data):
        _walk_bundle(OscBundle(data), out)
    else:
        _handle_msg(OscMessage(data), out)
    return out


class VMCProto(asyncio.DatagramProtocol):
    def __init__(self, loop):
        self.loop = loop

    def datagram_received(self, data, addr):
        try:
            updates = parse_packet(data)
        except Exception:
            return
        if not updates:
            return
        stats["frames"] += 1
        stats["last_bones"] = sum(1 for u in updates if u["k"] == "bone")
        if CLIENTS:
            payload = json.dumps(updates, separators=(",", ":"))
            for ws in list(CLIENTS):
                self.loop.create_task(_safe_send(ws, payload))


async def _safe_send(ws, payload):
    try:
        await ws.send(payload)
    except Exception:
        CLIENTS.discard(ws)


async def ws_handler(ws):
    CLIENTS.add(ws)
    print(f"[ws] client connected ({len(CLIENTS)} total)")
    try:
        async for _ in ws:
            pass
    finally:
        CLIENTS.discard(ws)
        print(f"[ws] client gone ({len(CLIENTS)} total)")


async def _report():
    while True:
        await asyncio.sleep(5)
        print(f"[stat] vmc frames={stats['frames']} last_bones={stats['last_bones']} "
              f"ws_clients={len(CLIENTS)}")
        print(f"[diag] bones({len(seen_bones)}): " +
              ", ".join(f"{k}={v}" for k, v in sorted(seen_bones.items())))
        print(f"[diag] blends({len(seen_blends)}): " +
              ", ".join(f"{k}={v}" for k, v in sorted(seen_blends.items())))


async def main():
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(
        lambda: VMCProto(loop), local_addr=("0.0.0.0", VMC_UDP_PORT))
    print(f"VMC(UDP) listening :{VMC_UDP_PORT}  ->  WebSocket :{WS_PORT}")
    loop.create_task(_report())
    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
