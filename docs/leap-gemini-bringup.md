# Ultraleap Gemini (v5) を Python から叩く — LeapC 持ち込み手順

Leap の手/指トラッキングを自作パイプラインに取り込むための記録。ここが Askr で一番ハマりやすく、
かつ世に情報が少ない部分なので独立ドキュメントにしてある。

## なぜ Leap が難所なのか

世に出回る Leap のサンプルは **ほぼ全部が旧世代の WebSocket API**（`ws://127.0.0.1:6437/v6.json`）。
これは Leap Motion v2 〜 Orion 時代のもの。現行の **Ultraleap "Gemini" (v5)** では
**この WebSocket は廃止済み**。学習データや古い記事の化石 API をなぞると「繋がらない → 詰み」になる。

（"Gemini" は Ultraleap のトラッキングソフトの世代名。Google の Gemini とは無関係。）

正解は **LeapC（現行のネイティブ C API）を公式 python bindings 経由で直接叩く**こと。

## 前提（Windows 実機）

- トラッキングサービス（`UltraleapTracking` / `LeapSvc.exe`）が稼働していること
- SDK: `<Ultraleap>\LeapSDK\`（`LeapC.h` / `lib\x64\LeapC.dll` / `samples\*.c`）
- 低レベル Python binding: `LeapSDK\leapc_cffi\`
  - ここに **`_leapc_cffi.cp312-win_amd64.pyd` が同梱**＝**Python 3.12 用にビルド済み**

## 罠：ABI が Python 3.12 固定

同梱の binding は **cp312**（CPython 3.12 ABI）でビルドされている。箱の Python が 3.13 等だと
そのままでは **import できない**。コンパイラが無い環境では「3.13 用に再ビルド」も「C サンプルの
コンパイル」も不可。

→ **cp312 に ABI を合わせる＝隔離した Python 3.12 を持ち込む**のが唯一のコンパイラ不要ルート。

## 持ち込み手順（インストール不要・フォルダで持つ）

専用フォルダ（例 `<install-dir>\leap312\`）に隔離環境を作る。削除で原状復帰でき、git 対象外にできる。

1. **embeddable Python 3.12.x**（インストーラ不要 zip）を `<install-dir>\leap312\` へ展開
2. `python312._pth` を編集し site-packages を有効化
   （`python312.zip` / `.` / `Lib\site-packages` / `import site` を有効に）
3. `get-pip.py` で pip を bootstrap
4. `python.exe -m pip install cffi numpy`（**wheel のみ・コンパイル無し**）
5. SDK の `LeapSDK\leapc_cffi` を `Lib\site-packages\leapc_cffi` へ丸ごとコピー
   （cp312 の `.pyd` と `LeapC.dll` ごと）
6. GitHub `ultraleap/leapc-python-bindings` の **純 Python 高レベルパッケージ `leap`**
   （`leapc-python-api/src/leap`）を `Lib\site-packages\leap` へコピー（ビルド不要）
7. 疎通確認：`import leapc_cffi` → `ffi/libleapc` OK、`import leap` OK

## 疎通確認

```python
import leap

class P(leap.Listener):
    def on_tracking_event(self, e):
        print("hands:", len(e.hands))

conn = leap.Connection()
conn.add_listener(P())
with conn.open():
    conn.set_tracking_mode(leap.TrackingMode.Desktop)
    ...
```

- `leap.Connection().open()` でトラッキングサービスに接続、フレームが連続流入する
- 手をかざすと **全指スケルトン**（5 指 × 4 ボーンの 3D 関節座標・palm・grab/pinch）が取れる
- `hand.arm.prev_joint`（肘）/ `hand.arm.next_joint`（手首）/ `hand.arm.rotation`（前腕 quat）も取れる

## 座標系の注意

Leap は **右手系・mm・X 右 / Y 上 / Z 手前（ユーザ方向）**。VRM / Unity は左手系・Z 奥なので変換が要る。
Askr では位置ベースでリターゲットするため、この符号変換は renderer(JS) 側の一箇所に集約している。

## 小物

- `event.device.get_info()` が空例外でシリアルを取れないことがある（**トラッキングには不要・実害なし**）
- SSH 越しの Windows コンソールは cp1252 になり、日本語やシリアルで `UnicodeEncodeError` が出る。
  `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` で回避（`leap_probe.py` に実装済み）

## Askr での使い方

`sender/leap_probe.py` で疎通・生フレームの dump を確認 → `sender/leap_send.py` で
手/指/腕を JSON にして UDP でレンダーホストへ送出。リターゲットは renderer(JS) 側。
