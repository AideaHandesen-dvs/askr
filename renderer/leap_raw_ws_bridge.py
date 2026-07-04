#!/usr/bin/env python3
"""生Leap(UDP:49986 JSON) を WebSocket(:8202) でブラウザ(renderer)へ中継。

raw_ifm_ws_bridge.py と同型。撮影PC の leap_send.py が投げる手/指JSONを、そのまま
renderer へ流すだけ。座標変換・リターゲットは renderer(JS)側。

  生Leap(UDP :49986) ──> [この橋: レンダーホスト] ──> WebSocket(:8202) ──> renderer

起動: renderer/.venv/bin/python leap_raw_ws_bridge.py
"""
import asyncio

import websockets

RAW_PORT = 49986
WS_PORT = 8202
CLIENTS = set()
stats = {"frames": 0}


class Proto(asyncio.DatagramProtocol):
    def __init__(self, loop):
        self.loop = loop

    def datagram_received(self, data, addr):
        stats["frames"] += 1
        if not CLIENTS:
            return
        text = data.decode("utf-8", errors="ignore")
        for ws in list(CLIENTS):
            self.loop.create_task(_send(ws, text))


async def _send(ws, text):
    try:
        await ws.send(text)
    except Exception:
        CLIENTS.discard(ws)


async def ws_handler(ws):
    CLIENTS.add(ws)
    print(f"[leap-ws] client connected ({len(CLIENTS)})", flush=True)
    try:
        async for _ in ws:
            pass
    finally:
        CLIENTS.discard(ws)
        print(f"[leap-ws] client gone ({len(CLIENTS)})", flush=True)


async def _report():
    while True:
        await asyncio.sleep(10)
        print(f"[stat] leap frames={stats['frames']} ws_clients={len(CLIENTS)}", flush=True)


async def main():
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: Proto(loop), local_addr=("0.0.0.0", RAW_PORT))
    print(f"raw Leap UDP:{RAW_PORT}  ->  WS:{WS_PORT}", flush=True)
    loop.create_task(_report())
    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
