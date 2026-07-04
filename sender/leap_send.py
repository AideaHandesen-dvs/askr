#!/usr/bin/env python3
r"""leap_send.py — Ultraleap Gemini の手/指フレームを UDP-JSON で レンダーホスト へ送る。

顔(iFM)が生テキストを レンダーホスト へ UDP で投げるのと同じ流儀。ここ(撮影PC)は「読んで詰めて
投げるだけ」の薄い送信器で、座標変換・rest合わせ・リターゲットは全部 renderer(JS)側でやる。
理由: 指ボーンのローカル回転計算には実機VRMのrest poseが要る＝VRMを持つ renderer で回すのが正解。

  Leap(LeapC) ──> [これ: 撮影PC] ──UDP:49986 JSON──> レンダーホスト(leap_raw_ws_bridge.py) ──WS:8202──> renderer

実行: <leap312>\python.exe leap_send.py [--host <レンダーホスト>] [--port 49986]

ワイヤ形式(1フレーム1パケット, mm・右手系・X右/Y上/Z手前=ユーザ向き。renderer側で three へ変換):
  {"t":<frame_id>,
   "h":[ {"s":"l"|"r",                        # hand type
          "p":[x,y,z], "q":[x,y,z,w],         # palm 位置 / 向き(quat)
          "g":grab, "pn":pinch,               # 握り/つまみ 0..1
          "a":{"e":[x,y,z],"w":[x,y,z],"q":[x,y,z,w]},  # arm: elbow / wrist / 前腕quat
          "d":[ [j0,j1,j2,j3,j4], ... x5 ] }  # digit毎に 5関節位置(親→指先)。j*=[x,y,z]
       ] }
手が無いフレームは "h":[] 。renderer 側は手ロストで rest へ戻す。
"""
import argparse
import json
import socket
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import leap

DIGITS = 5   # thumb, index, middle, ring, pinky


def r1(v):   # mm は 0.1mm 精度で十分。帯域を絞る
    return round(v, 1)


def r4(v):
    return round(v, 4)


def vec(v):
    return [r1(v.x), r1(v.y), r1(v.z)]


def quat(q):
    return [r4(q.x), r4(q.y), r4(q.z), r4(q.w)]


def digit_joints(digit):
    # bones[0..3] = metacarpal, proximal, intermediate, distal。
    # 5関節 = bone0.prev, bone0.next(=bone1.prev), ..., bone3.next(=指先)。親→先の順。
    b = digit.bones
    joints = [vec(b[0].prev_joint)]
    for i in range(4):
        joints.append(vec(b[i].next_joint))
    return joints


def hand_obj(hand):
    arm = hand.arm
    return {
        "s": "l" if str(hand.type).lower().endswith("left") else "r",
        "p": vec(hand.palm.position),
        "q": quat(hand.palm.orientation),
        "g": r4(hand.grab_strength),
        "pn": r4(hand.pinch_strength),
        "a": {"e": vec(arm.prev_joint), "w": vec(arm.next_joint), "q": quat(arm.rotation)},
        "d": [digit_joints(hand.digits[i]) for i in range(DIGITS)],
    }


class Sender(leap.Listener):
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.frames = 0
        self.sent = 0
        self.max_hands = 0
        self.last_report = time.time()

    def on_connection_event(self, event):
        print("[connected] tracking service", flush=True)

    def on_tracking_event(self, event):
        self.frames += 1
        n = len(event.hands)
        if n > self.max_hands:
            self.max_hands = n
        try:
            msg = {"t": event.tracking_frame_id,
                   "h": [hand_obj(h) for h in event.hands]}
            self.sock.sendto(json.dumps(msg, separators=(",", ":")).encode("utf-8"), self.addr)
            self.sent += 1
        except Exception as e:
            if self.frames % 120 == 0:
                print("[send err]", e, flush=True)
        now = time.time()
        if now - self.last_report > 5.0:
            print(f"[stat] frames={self.frames} sent={self.sent} "
                  f"hands(now/max)={n}/{self.max_hands} -> {self.addr[0]}:{self.addr[1]}",
                  flush=True)
            self.last_report = now


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="送信先(レンダーホスト)")
    ap.add_argument("--port", type=int, default=49986)
    args = ap.parse_args()

    try:
        ip = socket.gethostbyname(args.host)
    except Exception:
        ip = args.host
    addr = (ip, args.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"leap_send: -> {args.host}({ip}):{args.port}", flush=True)

    conn = leap.Connection()
    conn.add_listener(Sender(sock, addr))
    with conn.open():
        conn.set_tracking_mode(leap.TrackingMode.Desktop)
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nbye", flush=True)


if __name__ == "__main__":
    main()
