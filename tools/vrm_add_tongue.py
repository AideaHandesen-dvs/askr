#!/usr/bin/env python3
"""VRM(GLB) に「舌」メッシュ＋`Tongue` モーフを Blender 無しで焼き込む。

VRoid 等の VRM は舌ジオメトリを持たないため、iFacialMocap の tongueOut を
出しても動かす対象が無い。このツールは：

  - 顔メッシュ(Fcl_* モーフ持ち)の `FaceMouth` マテリアルから口の位置を実測し、
  - そこへ先細りの舌メッシュを新規生成し head 骨にスキン(顔と同じ作り)して、
  - 安静=口内に収まり / モーフ=前(-Z)下(-Y)へ伸びて出る `Tongue` モーフを追加、
  - VRM0 blendShapeMaster にも `Tongue` グループを登録(他アプリ互換)。

元モデルは書き換えず別ファイルへ出力する。renderer 側は morph 名に "tongue" を
含むモーフを自動で拾って expression 'tongueout' にバインドする(index.html)。

使い方:
  python tools/vrm_add_tongue.py renderer/assets/model.vrm renderer/assets/model_tongue.vrm
  # 形/位置の微調整は下の TUNE 定数、または実行時の renderer 側 "舌 強さ" スライダーで。
  # ※ numpy が要る。renderer/.venv には入っていないので、numpy のある python で実行すること。

前提(満たさないと SystemExit で止まる): Fcl_* モーフを持つ顔メッシュ(=VRoid系VRM)、
口の位置を測る FaceMouth 系マテリアル、humanoid の head 骨が顔スキンの joints に居ること。
"""
import json
import struct
import sys
import numpy as np

# ---- 形状パラメータ(メートル・raw glTF空間)。既定はVRoid標準顔向け ----
TUNE = dict(
    root_back=0.028,    # 口の開口からどれだけ奥(内側)に舌の付け根を置くか
    rest_in=0.006,      # 安静時の舌先を開口からどれだけ内側に隠すか(+=内)
    ext_out=0.045,      # モーフ全開時に舌先が開口から前へ出る量(-Z)
    ext_down=0.020,     # モーフ全開時に舌先が下がる量(-Y)
    rest_up=0.002,      # 付け根を口中心から少し上へ
    half_w=0.016,       # 舌の半幅(全幅=2倍)
    half_t=0.005,       # 舌の半厚
    n_ring=7,           # 長手方向リング数
    n_seg=10,           # 断面分割数
    color=[0.86, 0.34, 0.42, 1.0],  # フォールバックのunlit色(素体テクスチャが使えない時のみ)
    use_face_texture=False,         # True=素体FaceMouthテクスチャ流用(口内UV)。ただし奥の暗色を拾い"梅干し"化しがち。
                                    # 既定Falseでソリッド色にし、色は renderer の「舌 色」ピッカーでライブ調整する運用を推奨
    morph_name="Tongue",
)

GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
CT_F32, CT_U16, CT_U32 = 5126, 5123, 5125


def read_glb(path):
    data = open(path, "rb").read()
    magic, ver, length = struct.unpack("<III", data[:12])
    assert magic == GLB_MAGIC, "not a GLB"
    off, J, BIN = 12, None, None
    while off < length:
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == JSON_CHUNK:
            J = json.loads(chunk.decode("utf-8"))
        elif ctype == BIN_CHUNK:
            BIN = bytearray(chunk)
    return J, BIN


def write_glb(path, J, BIN):
    jb = json.dumps(J, separators=(",", ":")).encode("utf-8")
    jb += b"\x20" * ((4 - len(jb) % 4) % 4)          # JSONはスペース埋め
    bb = bytes(BIN)
    bb += b"\x00" * ((4 - len(bb) % 4) % 4)           # BINはゼロ埋め
    total = 12 + 8 + len(jb) + 8 + len(bb)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", GLB_MAGIC, 2, total))
        f.write(struct.pack("<II", len(jb), JSON_CHUNK)); f.write(jb)
        f.write(struct.pack("<II", len(bb), BIN_CHUNK)); f.write(bb)


def accessor_np(J, BIN, ai):
    a = J["accessors"][ai]; bv = J["bufferViews"][a["bufferView"]]
    fmt = {CT_F32: ("<f4", 4), CT_U16: ("<u2", 2), CT_U32: ("<u4", 4), 5121: ("<u1", 1)}[a["componentType"]]
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
    s = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    seg = np.frombuffer(bytes(BIN[s:s + a["count"] * fmt[1] * ncomp]), dtype=np.dtype(fmt[0]))
    return seg.reshape(a["count"], ncomp).astype("f8")


def add_accessor(J, BIN, arr, comp_type, gltf_type, target, with_minmax):
    """np配列を新規bufferView+accessorとして追記し accessor index を返す。"""
    np_dtype = {CT_F32: "<f4", CT_U16: "<u2", CT_U32: "<u4"}[comp_type]
    blob = np.ascontiguousarray(arr, dtype=np.dtype(np_dtype)).tobytes()
    while len(BIN) % 4:               # bufferView は4byte境界に
        BIN += b"\x00"
    byte_off = len(BIN)
    BIN += blob
    bv = {"buffer": 0, "byteOffset": byte_off, "byteLength": len(blob)}
    if target:
        bv["target"] = target
    J["bufferViews"].append(bv)
    bv_idx = len(J["bufferViews"]) - 1
    count = arr.shape[0] if arr.ndim > 1 else arr.shape[0]
    acc = {"bufferView": bv_idx, "byteOffset": 0, "componentType": comp_type,
           "count": count, "type": gltf_type}
    if with_minmax:
        acc["min"] = [float(x) for x in np.asarray(arr).min(axis=0).ravel()]
        acc["max"] = [float(x) for x in np.asarray(arr).max(axis=0).ravel()]
    J["accessors"].append(acc)
    return len(J["accessors"]) - 1


def find_face_mesh(J):
    for mi, m in enumerate(J["meshes"]):
        names = (m.get("extras") or {}).get("targetNames") or []
        if any(n.startswith("Fcl_") for n in names):
            return mi
    raise SystemExit("Fcl_* モーフを持つ顔メッシュが見つからない(VRoid系VRM前提)")


def find_mouth_material_prim(J, mesh_idx):
    m = J["meshes"][mesh_idx]
    for pr in m["primitives"]:
        mat = J["materials"][pr["material"]]
        if "facemouth" in (mat.get("name", "").lower()):
            return pr
    # フォールバック: 最初のプリミティブ
    return m["primitives"][0]


def find_head_skin(J, face_mesh_idx):
    """head 骨の node index / 顔スキン index / スキンjoints内でのhead位置 を返す。

    舌は骨階層に足さず、顔メッシュと同じスキンに weight=1 で head へ紐付ける
    (＝独立スキンメッシュ)。骨階層を書き換えないので three-vrm の humanoid
    正規化を壊さない(旧: head骨の子に付けたら頭/体の駆動が丸ごと死んだ)。
    """
    vrm = J.get("extensions", {}).get("VRM", {})
    head_node = None
    for b in vrm.get("humanoid", {}).get("humanBones", []):
        if b.get("bone") == "head":
            head_node = b.get("node")
    if head_node is None:
        raise SystemExit("VRM humanoid に head 骨が無い")
    face_skin = None
    for n in J["nodes"]:
        if n.get("mesh") == face_mesh_idx and "skin" in n:
            face_skin = n["skin"]
    if face_skin is None:
        raise SystemExit("顔メッシュがスキンを持たない(想定外のVRM)")
    joints = J["skins"][face_skin]["joints"]
    if head_node not in joints:
        raise SystemExit("head 骨が顔スキンのjointsに無い")
    return head_node, face_skin, joints.index(head_node)


def build_tongue(mouth_min, mouth_max, T):
    """口bbox(world) から、bind空間の舌ジオメトリ＋モーフdeltaを生成。"""
    cx = (mouth_min[0] + mouth_max[0]) / 2.0
    cy = (mouth_min[1] + mouth_max[1]) / 2.0
    open_z = mouth_min[2]                    # VRM0は-Z正面=最小Zが開口(前)
    # world 空間のセンターライン3点(付け根R / 安静舌先T0 / 全開舌先T1)
    R = np.array([cx, cy + T["rest_up"], open_z + T["root_back"]])
    T0 = np.array([cx, cy - 0.004, open_z + T["rest_in"]])
    T1 = np.array([cx, cy - T["ext_down"], open_z - T["ext_out"]])
    dtip = T1 - T0                            # 舌先の最大変位(モーフ全開)
    Nu, Nv = T["n_ring"], T["n_seg"]
    W, Th = T["half_w"], T["half_t"]
    verts, deltas, tris = [], [], []

    def ring_uv(u):
        s = np.sqrt(max(0.02, 1.0 - u * u))   # 楕円テーパ(丸い先端)
        return W * s, Th * s

    us = [i / (Nu - 1) * 0.92 for i in range(Nu)]   # 先端は別頂点で閉じる
    ring_start = []
    for u in us:
        hw, ht = ring_uv(u)
        c = R + (T0 - R) * u
        base = len(verts)
        ring_start.append(base)
        for j in range(Nv):
            th = 2 * np.pi * j / Nv
            verts.append(c + np.array([hw * np.cos(th), ht * np.sin(th), 0.0]))
            deltas.append(dtip * u)
    tip_i = len(verts); verts.append(T0.copy()); deltas.append(dtip.copy())
    root_i = len(verts); verts.append(R.copy()); deltas.append(np.zeros(3))
    # 側面(リング間キルト)
    for r in range(Nu - 1):
        a, b = ring_start[r], ring_start[r + 1]
        for j in range(Nv):
            jn = (j + 1) % Nv
            tris += [[a + j, a + jn, b + jn], [a + j, b + jn, b + j]]
    # 先端ファン
    a = ring_start[Nu - 1]
    for j in range(Nv):
        jn = (j + 1) % Nv
        tris += [[a + j, a + jn, tip_i]]
    # 付け根キャップ(裏返し向き)
    a = ring_start[0]
    for j in range(Nv):
        jn = (j + 1) % Nv
        tris += [[root_i, a + jn, a + j]]

    P = np.array(verts, dtype="f8")                # world/bind空間(顔と同一・スキンで頭追従)
    D = np.array(deltas, dtype="f8")               # モーフdelta(bind空間の変位)
    T = np.array(tris, dtype="u4")
    # 頂点法線(面法線を集約)。素体口の MToon マテリアルを流用する場合、陰影に要る
    N = np.zeros_like(P)
    fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    for k in range(3):
        np.add.at(N, T[:, k], fn)
    ln = np.linalg.norm(N, axis=1, keepdims=True); ln[ln == 0] = 1.0
    N = N / ln
    return P, N, D, T.ravel()


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "renderer/assets/model.vrm"
    dst = sys.argv[2] if len(sys.argv) > 2 else "renderer/assets/model_tongue.vrm"
    J, BIN = read_glb(src)

    face_mi = find_face_mesh(J)
    prim = find_mouth_material_prim(J, face_mi)
    POS = accessor_np(J, BIN, prim["attributes"]["POSITION"])
    idx = accessor_np(J, BIN, prim["indices"]).astype(int).ravel()
    mouth = POS[np.unique(idx)]
    mmin, mmax = mouth.min(0), mouth.max(0)
    head_node, face_skin, head_joint = find_head_skin(J, face_mi)
    print(f"[bake] face mesh={face_mi}  mouthMat={J['materials'][prim['material']]['name']}")
    print(f"[bake] mouth bbox world  min={np.round(mmin,4).tolist()} max={np.round(mmax,4).tolist()}")
    print(f"[bake] head node={head_node} skin={face_skin} headJointInSkin={head_joint}")

    # 素体口の色を舌へ: FaceMouthのテクスチャを流用し、口内(=舌色)のUVを舌全体に貼る。
    #   前=-Z ゆえ「最大Z=口内奥」の頂点UV重心＝口腔/舌の塗り。texture transformごと複製して同一テクセルを引く。
    face_mat = J["materials"][prim["material"]]
    face_tex = (face_mat.get("pbrMetallicRoughness", {}).get("baseColorTexture") or {})
    tongue_uv = None
    if TUNE["use_face_texture"] and "index" in face_tex and "TEXCOORD_0" in prim["attributes"]:
        uvs = accessor_np(J, BIN, prim["attributes"]["TEXCOORD_0"])
        uu = np.unique(idx); mz = POS[uu][:, 2]
        cav = uvs[uu][mz > np.percentile(mz, 80)].mean(0)
        tongue_uv = [float(cav[0]), float(cav[1])]
        print(f"[bake] 素体テクスチャ流用: mat='{face_mat['name']}' 口内UV={np.round(cav,4).tolist()}")

    P, N, D, I = build_tongue(mmin, mmax, TUNE)
    n = P.shape[0]
    JJ = np.tile(np.array([head_joint, 0, 0, 0]), (n, 1))   # 全頂点をheadへ100%
    WW = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (n, 1))
    idx_ct = CT_U16 if n <= 65535 else CT_U32
    if idx_ct == CT_U16:
        I = I.astype("u2")
    pos_acc = add_accessor(J, BIN, P, CT_F32, "VEC3", 34962, True)
    norm_acc = add_accessor(J, BIN, N, CT_F32, "VEC3", 34962, False)
    delta_acc = add_accessor(J, BIN, D, CT_F32, "VEC3", 34962, True)
    joints_acc = add_accessor(J, BIN, JJ, CT_U16, "VEC4", 34962, False)
    weights_acc = add_accessor(J, BIN, WW, CT_F32, "VEC4", 34962, False)
    idx_acc = add_accessor(J, BIN, I.reshape(-1, 1), idx_ct, "SCALAR", 34963, False)
    attrs = {"POSITION": pos_acc, "NORMAL": norm_acc, "JOINTS_0": joints_acc, "WEIGHTS_0": weights_acc}

    # マテリアル(両面unlit)。素体テクスチャがあれば流用、無ければフォールバック単色
    J.setdefault("extensionsUsed", [])
    if "KHR_materials_unlit" not in J["extensionsUsed"]:
        J["extensionsUsed"].append("KHR_materials_unlit")
    pbr = {"metallicFactor": 0.0, "roughnessFactor": 0.9}
    if tongue_uv is not None:
        uv_acc = add_accessor(J, BIN, np.tile(np.array(tongue_uv), (n, 1)), CT_F32, "VEC2", 34962, False)
        attrs["TEXCOORD_0"] = uv_acc
        pbr["baseColorTexture"] = json.loads(json.dumps(face_tex))   # transform等ごと複製=同一テクセル
        pbr["baseColorFactor"] = face_mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
    else:
        pbr["baseColorFactor"] = TUNE["color"]
    J["materials"].append({"name": "Tongue", "pbrMetallicRoughness": pbr,
                           "extensions": {"KHR_materials_unlit": {}}, "doubleSided": True})
    mat_idx = len(J["materials"]) - 1

    J["meshes"].append({
        "name": "Tongue",
        "primitives": [{
            "attributes": attrs,
            "indices": idx_acc,
            "material": mat_idx,
            "targets": [{"POSITION": delta_acc}],
            "extras": {"targetNames": [TUNE["morph_name"]]},
        }],
        "weights": [0.0],
        "extras": {"targetNames": [TUNE["morph_name"]]},   # three.jsはmesh.extrasを読む
    })
    mesh_idx = len(J["meshes"]) - 1

    # 舌は独立スキンメッシュ(顔と同じ作り)。骨階層は触らず head へスキンして追従。
    #   ⚠ head 骨の子ノードに足すと three-vrm の humanoid 正規化が壊れ頭/体駆動が死ぬ。
    J["nodes"].append({"name": "Tongue", "mesh": mesh_idx, "skin": face_skin})
    tongue_node = len(J["nodes"]) - 1
    scene = J.get("scene", 0)
    J["scenes"][scene].setdefault("nodes", []).append(tongue_node)

    # VRM0 blendShapeMaster に Tongue グループ(他アプリ互換。three-vrmはbind.mesh=mesh index)
    vrm = J.setdefault("extensions", {}).setdefault("VRM", {})
    bsm = vrm.setdefault("blendShapeMaster", {}).setdefault("blendShapeGroups", [])
    if not any((gr.get("name", "").lower() == "tongue") for gr in bsm):
        bsm.append({"name": "Tongue", "presetName": "unknown", "isBinary": False,
                    "binds": [{"mesh": mesh_idx, "index": 0, "weight": 100}],
                    "materialValues": []})

    J["buffers"][0]["byteLength"] = len(BIN)
    write_glb(dst, J, BIN)
    print(f"[bake] tongue verts={P.shape[0]} tris={I.reshape(-1,1).shape[0]//3} "
          f"mesh={mesh_idx} node={tongue_node} material={mat_idx}")
    print(f"[bake] wrote {dst}")


if __name__ == "__main__":
    main()
