#!/usr/bin/env python3
"""renderer配信 + 設定の保存/読込API（旧 `python3 -m http.server 8199` の置き換え）。

  GET  /config   -> config.json を返す（無ければ {}）
  POST /config   -> body(JSON) を config.json に保存（アトミック置換）
  その他         -> renderer/ の静的ファイル配信

設定を レンダーホスト 側の config.json に置くので、どのPCのブラウザから開いても同じ設定を共有する。
起動: renderer/ で `python3 config_server.py`（標準ライブラリのみ・依存なし）
"""
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
PORT = 8199


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def _json(self, code, data: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] == "/config":
            data = b"{}"
            if os.path.exists(CFG_PATH):
                with open(CFG_PATH, "rb") as f:
                    data = f.read() or b"{}"
            return self._json(200, data)
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] == "/config":
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n) if n else b"{}"
            try:
                json.loads(body)                      # 壊れたJSONは弾く
                tmp = CFG_PATH + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(body)
                os.replace(tmp, CFG_PATH)             # アトミック置換
                return self._json(200, b'{"ok":true}')
            except Exception as e:
                return self._json(400, json.dumps({"error": str(e)}).encode())
        self.send_response(404)
        self.end_headers()

    def end_headers(self):
        if self.path.split("?")[0] != "/config":     # 静的配信もキャッシュ無効（常に最新renderer）
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"renderer + config API on :{PORT}  (config: {CFG_PATH})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
