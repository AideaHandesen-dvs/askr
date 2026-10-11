#!/usr/bin/env python3
"""VRM(GLB) の顔に「頬ふくらまし」モーフ `CheekPuff` を Blender 無しで焼き込む。

VRoid 等の VRM は頬をふくらませる表情を持たないため、iFacialMocap(ARKit)の
cheekPuff を出しても動かす対象が無い。このツールは：

  - 顔メッシュ(Fcl_* モーフ持ち)の `FaceMouth` マテリアルから口の位置を実測し、
  - 口の左右・少し上にある顔の肌の頂点を中心に、なめらかな山型の重みで
    頂点法線の向き(＝外側)へ押し出す `CheekPuff` モーフを追加、
  - VRM0 blendShapeMaster にも `CheekPuff` グループを登録(他アプリ互換)。

新しい頂点は作らない(既存の顔の頂点を動かすだけ)。顔メッシュの全プリミティブに
同じモーフを足す(glTF はプリミティブ間でモーフ数が揃っている必要がある)。
動かすのは肌(SKIN)マテリアルが使う頂点だけ＝目・眉・まつげは動かない。

元モデルは書き換えず別ファイルへ出力する。renderer 側は morph 名に "cheekpuff" を
含むモーフを自動で拾って expression 'cheekpuff' にバインドする(index.html)。

使い方:
  python tools/vrm_add_cheekpuff.py your_avatar.vrm your_avatar_cheek.vrm
  # 膨らみの位置/大きさは下の TUNE 定数、量は renderer 側の "頬 強さ" スライダーでも調整できる。
  # ※ numpy が要る。読み書きの下回りは vrm_add_tongue.py と共用(同じディレクトリに置くこと)。

前提(満たさないと SystemExit で止まる): Fcl_* モーフを持つ顔メッシュ(=VRoid系VRM)、
口の位置を測る FaceMouth 系マテリアル、肌の SKIN 系マテリアル。
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vrm_add_tongue import (read_glb, write_glb, accessor_np, add_accessor,  # noqa: E402
                            find_face_mesh, find_mouth_material_prim, CT_F32)

# ---- 形状パラメータ(メートル・raw glTF空間)。既定はVRoid標準顔向け ----
TUNE = dict(
    side=2.2,          # 頬の中心の横位置＝口の半幅の何倍外か
    up=0.004,          # 頬の中心を口の中心からどれだけ上へ
    radius=0.045,      # 膨らむ範囲の半径(この距離で重み0)
    push=0.016,        # 中心での押し出し量(法線方向)
    forward=0.2,       # 法線に足す「前(-Z)」成分の割合。横へ逃げすぎず前にも丸く出す
    morph_name="CheekPuff",
)


def find_skin_prim(J, mesh_idx):
    for pr in J["meshes"][mesh_idx]["primitives"]:
        if "skin" in J["materials"][pr["material"]].get("name", "").lower():
            return pr
    raise SystemExit("顔メッシュに SKIN 系マテリアルのプリミティブが無い(VRoid系VRM前提)")


def has_cheekpuff(J):
    """既に CheekPuff モーフを持つVRMか。二重焼き込み防止用。"""
    for m in J.get("meshes", []):
        names = (m.get("extras") or {}).get("targetNames") or []
        if any("cheekpuff" in str(x).lower().replace("_", "") for x in names):
            return True
    return False


def build_deltas(P, N, skin_ids, mmin, mmax, T):
    """顔の全頂点ぶんのモーフdelta(肌の頬まわり以外は0)を返す。"""
    cx = (mmin[0] + mmax[0]) / 2.0
    cy = (mmin[1] + mmax[1]) / 2.0 + T["up"]
    half_w = (mmax[0] - mmin[0]) / 2.0
    D = np.zeros_like(P)
    S = P[skin_ids]
    centers = []
    for sgn in (-1.0, 1.0):
        tx = cx + sgn * half_w * T["side"]
        # 頬の中心＝(tx, cy) に xy で近い肌の頂点のうち、いちばん前(-Z)にある物＝顔の表面
        dxy = np.hypot(S[:, 0] - tx, S[:, 1] - cy)
        near = dxy < 0.006
        if not near.any():
            raise SystemExit(f"頬の中心 x={tx:.3f} y={cy:.3f} の近くに肌の頂点が無い(TUNE side/up を見直す)")
        c = S[near][np.argmin(S[near][:, 2])]
        centers.append(c)
        d = np.linalg.norm(S - c, axis=1)
        w = np.clip(1.0 - d / T["radius"], 0.0, 1.0)
        w = w * w * (3.0 - 2.0 * w)                       # smoothstep＝縁がなめらか
        n = N[skin_ids] + np.array([0.0, 0.0, -T["forward"]])
        n /= np.linalg.norm(n, axis=1, keepdims=True)
        D[skin_ids] += n * (w * T["push"])[:, None]
    return D, centers


def main():
    if len(sys.argv) < 3:
        raise SystemExit("使い方: vrm_add_cheekpuff.py in.vrm out.vrm")
    src, dst = sys.argv[1], sys.argv[2]
    J, BIN = read_glb(src)
    if has_cheekpuff(J):
        raise SystemExit(f"中止: '{src}' は既に CheekPuff モーフを持っている＝二重に焼くことになる。")

    face_mi = find_face_mesh(J)
    mesh = J["meshes"][face_mi]
    mouth_pr = find_mouth_material_prim(J, face_mi)
    skin_pr = find_skin_prim(J, face_mi)
    pos_acc = skin_pr["attributes"]["POSITION"]
    if "NORMAL" not in skin_pr["attributes"]:
        raise SystemExit("顔メッシュが法線(NORMAL)を持たない(想定外のVRM)")
    P = accessor_np(J, BIN, pos_acc)
    N = accessor_np(J, BIN, skin_pr["attributes"]["NORMAL"])

    mouth_P = accessor_np(J, BIN, mouth_pr["attributes"]["POSITION"])
    mouth_ids = np.unique(accessor_np(J, BIN, mouth_pr["indices"]).astype(int).ravel())
    mmin, mmax = mouth_P[mouth_ids].min(0), mouth_P[mouth_ids].max(0)
    skin_ids = np.unique(accessor_np(J, BIN, skin_pr["indices"]).astype(int).ravel())

    D, centers = build_deltas(P, N, skin_ids, mmin, mmax, TUNE)
    moved = int((np.linalg.norm(D, axis=1) > 1e-6).sum())
    print(f"[bake] face mesh={face_mi} verts={len(P)} skinVerts={len(skin_ids)} moved={moved}")
    print(f"[bake] mouth bbox min={np.round(mmin, 4).tolist()} max={np.round(mmax, 4).tolist()}")
    print(f"[bake] cheek centers={[np.round(c, 4).tolist() for c in centers]} maxPush={np.linalg.norm(D, axis=1).max():.4f}m")

    delta_acc = add_accessor(J, BIN, D, CT_F32, "VEC3", 34962, True)
    zero_acc = None
    name = TUNE["morph_name"]
    for pr in mesh["primitives"]:
        tg = pr.setdefault("targets", [])
        if pr["attributes"]["POSITION"] == pos_acc:
            tg.append({"POSITION": delta_acc})
        else:                                   # 頂点を共有しないプリミティブ＝動かさない(0のdelta)
            if zero_acc is None or J["accessors"][zero_acc]["count"] != J["accessors"][pr["attributes"]["POSITION"]]["count"]:
                cnt = J["accessors"][pr["attributes"]["POSITION"]]["count"]
                zero_acc = add_accessor(J, BIN, np.zeros((cnt, 3)), CT_F32, "VEC3", 34962, True)
            tg.append({"POSITION": zero_acc})
        pn = (pr.get("extras") or {}).get("targetNames")
        if pn is not None:
            pn.append(name)
    mesh.setdefault("extras", {}).setdefault("targetNames", []).append(name)   # three.jsはmesh.extrasを読む
    if "weights" in mesh:
        mesh["weights"].append(0.0)
    morph_idx = len(mesh["extras"]["targetNames"]) - 1

    vrm = J.setdefault("extensions", {}).setdefault("VRM", {})
    bsm = vrm.setdefault("blendShapeMaster", {}).setdefault("blendShapeGroups", [])
    if not any(gr.get("name", "").lower() == "cheekpuff" for gr in bsm):
        bsm.append({"name": name, "presetName": "unknown", "isBinary": False,
                    "binds": [{"mesh": face_mi, "index": morph_idx, "weight": 100}],
                    "materialValues": []})

    J["buffers"][0]["byteLength"] = len(BIN)
    write_glb(dst, J, BIN)
    print(f"[bake] morph '{name}' index={morph_idx} を顔メッシュの全 {len(mesh['primitives'])} プリミティブに追加")
    print(f"[bake] wrote {dst}")


if __name__ == "__main__":
    main()
