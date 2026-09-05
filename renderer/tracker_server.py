#!/usr/bin/env python3
"""自作ブラウザ版フェイストラッカーの受け皿：HTTPS配信 と WSS受信 を「同一ポート」で兼ねるサーバ。

  スマホのブラウザ ──HTTPS──> [この鯖 :8443] ── tracker/ の静的配信(MediaPipe同梱)
        └─────────WSS /ws─────> [この鯖] ──UDP 127.0.0.1:49985──> raw_ifm_ws_bridge.py ──WS:8201──> askr

■ なぜ HTTPS か
  `getUserMedia`(カメラ)は **セキュアコンテキスト必須**。localhost 以外は https でないと呼べないので、
  LAN の 192.168.x.x で開くスマホ向けには自己署名でも TLS が要る。

■ 素のHTTP(:8080)も開けてある理由
  自己署名の警告画面(「詳細設定→アクセスする」)は端末やブラウザによっては出ない/押せないことがある。
  そこで **証明書を一切通らない口** :8080 も開ける。ただし `getUserMedia` はセキュアコンテキスト必須なので、
  http で開いた時はページ側が「カメラが使えない理由と2つの逃げ道」を出す（chrome://flags で
  そのオリジンを安全扱いにする / HTTPS の口を使う）。**"開くことすらできない"のか"開けるがカメラだけ駄目"なのかを
  スマホ側で切り分けられる**のが要点。

■ なぜ「同一ポート」に拘るか（これが構成の肝）
  自己署名証明書は、ブラウザが「危険性を承知で続行」の画面を出して**ユーザが手で例外を入れる**必要がある。
  ところが **WebSocket にはその画面が出せない**（wss:// のハンドシェイクが黙って失敗するだけ）。
  例外は host:port 単位なので、HTTPS ページと WSS を別ポートに分けると **WSS 側だけ永久に繋がらない**。
  そこで websockets の `process_request` を使い、**同じ :8443 で** 通常のGET=静的配信 / `/ws`=WebSocket
  に振り分ける。ページを開いて例外を通した時点で WSS も一緒に通る。

起動: renderer/.venv/bin/python tracker_server.py
      (証明書が無ければ tracker/make_cert.sh を先に実行するよう案内して終了する)
"""
import asyncio
import os
import socket
import ssl
import sys

import websockets
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "tracker")                  # 静的配信のルート(この外は出さない)
CERT = os.path.join(ROOT, "certs", "tracker.crt")
KEY = os.path.join(ROOT, "certs", "tracker.key")
PORT = 8443                                           # HTTPS + WSS(本命)
PLAIN_PORT = 8080                                     # 素のHTTP + WS(証明書を通らない入り口・下記)
RAW_ADDR = ("127.0.0.1", 49985)                       # 生iFMの内部転送口。ここに流せば既存の橋がrendererへ配る

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".wasm": "application/wasm",                      # ← 誤ると WASM のストリーミングコンパイルが失敗する
    ".task": "application/octet-stream",              # MediaPipe のモデル
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}
# 26MB ある wasm/モデルは毎回落とすとスマホでは待たされる＝不変物としてキャッシュさせる。
# HTML/JS は編集するので no-store(常に最新を取りに行かせる)。
IMMUTABLE = (".wasm", ".task")

udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
stats = {"frames": 0, "bytes": 0, "clients": 0}


def _resp(status, reason, body=b"", ctype="text/plain; charset=utf-8", cache="no-store"):
    h = Headers()
    h["Content-Type"] = ctype
    h["Content-Length"] = str(len(body))
    h["Cache-Control"] = cache
    return Response(status, reason, h, body)


def process_request(connection, request):
    """WebSocket 以外のリクエストを静的ファイルとして返す。None を返すと WS ハンドシェイクに進む。"""
    path = request.path.split("?")[0]
    # 誰が触りに来たかを必ず1行出す。「スマホから届いていないのか、届いた上で失敗しているのか」は
    # これが出るか出ないかで一発で決まる(切り分けの土台)。
    if path in ("/", "/index.html", "/ws"):
        try:
            peer = connection.remote_address[0]
        except Exception:
            peer = "?"
        print(f"[req] {peer} {path}  UA={request.headers.get('User-Agent', '?')[:70]}", flush=True)
    if path == "/ws":
        return None                                   # ← ここだけ WebSocket にする
    if path == "/":
        path = "/index.html"
    # パストラバーサル対策: 正規化した絶対パスが ROOT 配下に無ければ 403
    fp = os.path.normpath(os.path.join(ROOT, path.lstrip("/")))
    if not fp.startswith(ROOT + os.sep) or not os.path.isfile(fp):
        return _resp(404, "Not Found", b"not found\n")
    ext = os.path.splitext(fp)[1].lower()
    try:
        with open(fp, "rb") as f:
            body = f.read()
    except OSError as e:
        return _resp(500, "Internal Server Error", str(e).encode())
    cache = "public, max-age=31536000, immutable" if ext in IMMUTABLE else "no-store"
    return _resp(200, "OK", body, MIME.get(ext, "application/octet-stream"), cache)


async def ws_handler(ws):
    stats["clients"] += 1
    print(f"[tracker] client connected ({stats['clients']}) from {ws.remote_address}", flush=True)
    try:
        async for msg in ws:
            if isinstance(msg, str):
                msg = msg.encode("utf-8")
            stats["frames"] += 1
            stats["bytes"] += len(msg)
            udp.sendto(msg, RAW_ADDR)                 # 既存の iFM パイプへ合流(rendererは無改造で受け取る)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        stats["clients"] -= 1
        print(f"[tracker] client gone ({stats['clients']})", flush=True)


async def _report():
    last = 0
    while True:
        await asyncio.sleep(10)
        d = stats["frames"] - last
        last = stats["frames"]
        print(f"[stat] frames={stats['frames']} (+{d} / {d/10:.1f}fps) "
              f"bytes={stats['bytes']} clients={stats['clients']}", flush=True)


async def main():
    if not (os.path.isfile(CERT) and os.path.isfile(KEY)):
        sys.exit(f"証明書が無い: {CERT}\n  先に  bash {os.path.join(ROOT, 'make_cert.sh')}  を実行して作ること。")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    ip = (os.popen("hostname -I").read().split() or ["<このPCのIP>"])[0]
    print(f"tracker  HTTPS+WSS :{PORT} / HTTP+WS :{PLAIN_PORT}   -> UDP {RAW_ADDR[0]}:{RAW_ADDR[1]}", flush=True)
    print(f"  ① https://{ip}:{PORT}/   (自己署名なので初回だけ「詳細設定→アクセスする」)", flush=True)
    print(f"  ② http://{ip}:{PLAIN_PORT}/  (証明書を通らない口。開けるかどうかの切り分け用)", flush=True)
    asyncio.get_running_loop().create_task(_report())
    common = dict(process_request=process_request,
                  compression=None,                   # 30fpsの短いテキスト＝圧縮はCPUの無駄
                  ping_interval=20, ping_timeout=20)
    async with serve(ws_handler, "0.0.0.0", PORT, ssl=ctx, **common), \
               serve(ws_handler, "0.0.0.0", PLAIN_PORT, **common):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
