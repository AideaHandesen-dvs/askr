#!/usr/bin/env python3
"""ifm_forward.py — iFacialMocap の生UDPを、そのままレンダーホストへ転送する薄い中継。

iFacialMocap(iPhone等)は撮影PCの入力ポートにテキストUDPを投げてくる。これを一切加工せず
レンダーホストの raw-iFM ポートへ横流しする。renderer 側(raw_ifm_ws_bridge.py → WS)で全部処理する。
leap_send.py と同じ「読んで投げるだけ」の流儀。標準ライブラリのみ・依存なし。

  iFacialMocap ──UDP:49984──> [これ:撮影PC] ──UDP:49985──> レンダーホスト(raw_ifm_ws_bridge.py)

実行: python ifm_forward.py --host <レンダーホスト>
"""
import argparse
import socket
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="転送先(レンダーホスト)")
    ap.add_argument("--in-port", type=int, default=49984, help="iFacialMocap 受信ポート")
    ap.add_argument("--out-port", type=int, default=49985, help="レンダーホストの生iFM受信ポート")
    args = ap.parse_args()

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("0.0.0.0", args.in_port))
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dst = (args.host, args.out_port)
    print(f"ifm_forward: :{args.in_port} -> {args.host}:{args.out_port}", flush=True)

    frames, last = 0, time.time()
    while True:
        data, _ = rx.recvfrom(65535)
        tx.sendto(data, dst)
        frames += 1
        now = time.time()
        if now - last > 5.0:
            print(f"[stat] forwarded={frames} -> {dst[0]}:{dst[1]}", flush=True)
            last = now


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
