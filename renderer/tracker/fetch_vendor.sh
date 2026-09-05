#!/usr/bin/env bash
# MediaPipe 一式(約26MB)を vendor/ に落とす。**CDN参照にしない理由**:
#   ・配信中にスマホが外へ出られない/CDNが落ちた瞬間にトラッカーが死ぬのを避ける(LAN内で完結させる)
#   ・バージョンが勝手に上がって挙動が変わるのを避ける(下の VER で固定)
# vendor/ は .gitignore 済み＝リポには入れず、このスクリプトで再現する。
set -euo pipefail
cd "$(dirname "$0")"

VER=1.0.1                                   # @mediapipe/tasks-vision のピン止め(上げる時はここだけ)
BASE="https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VER}"
MODEL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"

mkdir -p vendor/wasm
echo "== tasks-vision ${VER} =="
curl -sfL -o vendor/vision_bundle.mjs "$BASE/vision_bundle.mjs"
for f in vision_wasm_internal.js vision_wasm_internal.wasm \
         vision_wasm_nosimd_internal.js vision_wasm_nosimd_internal.wasm; do
  # nosimd 版も置く: WASM SIMD 非対応の端末では MediaPipe がこちらを取りに来る
  echo "  wasm/$f"
  curl -sfL -o "vendor/wasm/$f" "$BASE/wasm/$f"
done
echo "== face_landmarker.task (float16) =="
curl -sfL -o vendor/face_landmarker.task "$MODEL"

du -sh vendor
echo "OK: vendor/ 用意完了"
