# Askr

**ブラウザで動く、いじれる VTuber レンダラ。** 顔（iFacialMocap）と手/腕（Ultraleap Gemini）の
トラッキングを取り込み、[three-vrm](https://github.com/pixiv/three-vrm) で VRM アバターをブラウザ上に
描画する。VMC 互換。出力は OBS（ブラウザソース・背景透過）経由で NDI へ。

> **Askr（アスク）** — 北欧神話で、神々が浜辺の**命の無い流木**に息・動き・姿を与えて作った最初の人間。
> 静的な VRM（＝木）に、トラッキングで**動き**を、レンダリングで**姿**を与えて生かす——このソフトの比喩そのもの。

---

## なぜ作るか

- **フルオープンで全部いじれる軽量レンダラが欲しかった**。ブラウザ完結・生データ直結・スタックを丸ごと自分で握れる——そういう構成が手元に無かった
- **現行 Leap（Gemini / LeapC）を自作パイプラインに取り込む手順自体が希少**。世の情報は廃止済みの旧
  WebSocket API ばかりで皆詰む → [docs/leap-gemini-bringup.md](docs/leap-gemini-bringup.md) に手順をまとめた
- 全ての調整がブラウザ上のパネルで完結し、`config.json` に永続化される。改造前提の素直な構成

## 構成

```
  ┌─────────── 撮影PC ───────────┐        ┌──────────────── レンダーホスト ────────────────┐
  │  iFacialMocap ─┐             │        │  raw_ifm_ws_bridge.py  :49985 → WS :8201        │
  │                ├ ifm_forward.py ──UDP─┼─▶                                              │
  │                │  :49984      │        │  leap_raw_ws_bridge.py :49986 → WS :8202        │
  │  Leap(LeapC) ─ leap_send.py ──UDP──────┼─▶                                              │
  │                              │        │  config_server.py :8199  (index.html + /config) │
  └──────────────────────────────┘        │           │                                    │
                                           │           ▼   ブラウザ (three-vrm renderer)     │
                                           │   http://<host>:8199   WS:8201(顔)/8202(手)受信 │
                                           └───────────────────────┬────────────────────────┘
                                                                    ▼
                                        OBS ブラウザソース (?clean=1, 背景透過α) ──NDI──▶ 配信/合成
```

顔と手は独立した経路。撮影PC で VRM の rest pose を持たないため、Leap のリターゲット（関節 → VRM 指/腕
ボーンのローカル回転）は VRM を持つ **renderer(JS) 側**で行う。撮影PC 側は「読んで投げるだけ」。

### ポート

| ポート | 役割 |
|---|---|
| 8199 | renderer 配信 + 設定 API（`config_server.py`。`GET/POST /config`） |
| 8201 | 顔（生 iFM）WebSocket（`raw_ifm_ws_bridge.py`） |
| 8202 | 手/腕（Leap JSON）WebSocket（`leap_raw_ws_bridge.py`） |
| 49984 | 撮影PC の iFacialMocap 受信（`ifm_forward.py`） |
| 49985 | レンダーホストの生 iFM 受信 |
| 49986 | レンダーホストの生 Leap 受信 |
| 8200 / 39540 | （任意）VMC 入力の WebSocket 中継（`vmc_ws_bridge.py`） |

## セットアップ

### レンダーホスト

```bash
cd renderer
python3 -m venv .venv && . .venv/bin/activate
pip install websockets python-osc          # python-osc は VMC 中継を使う場合のみ
# VRM を置く（自分の VRoid 等）。同梱はしていない
cp /path/to/your.vrm assets/model.vrm       # または URL の ?vrm=... で指定
python config_server.py                      # :8199
python raw_ifm_ws_bridge.py                  # :8201  (顔を使うなら)
python leap_raw_ws_bridge.py                 # :8202  (手を使うなら)
```

ブラウザで `http://<レンダーホスト>:8199` を開く。調整用は素の URL（診断表示あり）。

### 撮影PC

Leap は現行 Gemini（LeapC）を隔離 Python 3.12 から叩く。手順は
[docs/leap-gemini-bringup.md](docs/leap-gemini-bringup.md) を参照（ここが要）。

```bash
# 疎通確認
<leap312>\python.exe sender\leap_probe.py
# 送出（--host にレンダーホストを指定）
<leap312>\python.exe sender\leap_send.py --host <レンダーホスト>
# 顔（iFacialMocap を撮影PC:49984 へ送る設定にした上で）
python sender\ifm_forward.py --host <レンダーホスト>
```

## OBS / NDI

- OBS の**ブラウザソース**に `http://<レンダーホスト>:8199/?clean=1` を指定
  - `?clean=1` で HUD・診断ドット・Leap デバッグ球を**全消し**（＝アバターだけのクリーン映像）
  - 背景透過は renderer が α 対応。OBS ブラウザソースのアルファでそのまま抜ける（クロマキー不要）
- あとは OBS の NDI 出力（DistroAV / obs-ndi 等）で配信・合成先へ

## 操作

- 全調整は**右上のパネル**（目線・表情・体駆動・Leap の腕/手/指・カメラ・背景）。変更は `config.json` に保存
- **キー 1–4**：カメラ視点スロットの呼び出し（パネルで保存、起動時はスロット 1 を復元）
- **Space**：診断表示（HUD/ドット）のトグル

## 既知の限界

- **前腕のねじれ（ソーセージ）**：VRoid 由来の VRM は**ツイスト骨を持たない**ため、前腕の回内/回外が
  単一の骨に集中してメッシュが巻きつく。Askr ではひねりを前腕/手へ配分＋肘下げバイアスで**軽減**して
  いるが、**完全な解消には Blender 等でツイスト骨を追加する**必要がある
- **Leap の肘推定**はデバイス FOV 外だと甘い。単眼 Leap なので可動範囲にも限界がある
- 顔は iFacialMocap（iPhone 等）前提

## ライセンス

MIT. See [LICENSE](LICENSE).
