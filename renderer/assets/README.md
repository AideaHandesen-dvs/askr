# VRM を置く場所

renderer は起動時に `model.vrm` を読み込みます（VRM 0.x / 1.0）。
別名を使いたい場合は URL パラメータで指定できます: `http://<host>:8199/?vrm=yourfile.vrm`

**サンプル `model.vrm` を同梱済み**（© handesen・舌焼き込み済み。ライセンスは
[`MODEL_LICENSE.txt`](MODEL_LICENSE.txt) 参照）。自分のアバターに差し替えるなら
[VRoid Studio](https://vroid.com/studio) 等で用意して `model.vrm` を置き換えてください。
舌を出したいモデルには `python tools/vrm_add_tongue.py in.vrm out.vrm` で舌を焼き込めます。
