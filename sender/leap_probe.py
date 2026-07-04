#!/usr/bin/env python3
"""
leap_probe.py — Ultraleap Gemini(v5) 生フレーム取得の疎通確認。

旧OrionのWebSocket(6437)は死んでるので使わない。LeapC(公式python bindings)で
トラッキングサービスに直接繋ぐ。手がデバイス上に無くても、接続確立・デバイス認識・
フレーム流入が観測できれば「データ経路OK」。手を出せば全指スケルトンをdumpする。

実行: <leap312>\\python.exe leap_probe.py
"""
import sys
import time
import traceback

# SSH越しのWindowsコンソールはcp1252。日本語/シリアルで死ぬのでUTF-8に矯正。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import leap

DUR = 40.0  # 観測秒数
MAX_DUMPS = 3       # 何ポーズ採取するか
DUMP_GAP = 3.0      # ポーズ間隔(秒)
OUTFILE = "leap_capture.txt"

state = {"frames": 0, "max_hands": 0, "device": None,
         "dumps": 0, "last_dump": 0.0, "fh": None}
DIGITS = ["thumb", "index", "middle", "ring", "pinky"]


def emit(line):
    print(line)
    if state["fh"]:
        state["fh"].write(line + "\n")
        state["fh"].flush()


class Probe(leap.Listener):
    def on_connection_event(self, event):
        print("[connected] tracking service へ接続")

    def on_device_event(self, event):
        try:
            info = event.device.get_info()
            state["device"] = getattr(info, "serial", None)
        except Exception as e:
            state["device"] = f"(get_info失敗: {e})"
        print("[device]", state["device"])

    def on_tracking_event(self, event):
        state["frames"] += 1
        n = len(event.hands)
        if n > state["max_hands"]:
            state["max_hands"] = n

        now = time.time()
        if (n > 0 and state["dumps"] < MAX_DUMPS
                and now - state["last_dump"] > DUMP_GAP):
            state["dumps"] += 1
            state["last_dump"] = now
            emit(f"\n=== POSE {state['dumps']}/{MAX_DUMPS} (frame id={event.tracking_frame_id}) ===")
            try:
                for hand in event.hands:
                    p = hand.palm.position
                    o = hand.palm.orientation  # quaternion (x,y,z,w)
                    emit(
                        f"[{str(hand.type)}] palm pos=({p.x:6.1f},{p.y:6.1f},{p.z:6.1f}) "
                        f"quat=({o.x:+.3f},{o.y:+.3f},{o.z:+.3f},{o.w:+.3f}) "
                        f"grab={hand.grab_strength:.2f} pinch={hand.pinch_strength:.2f}"
                    )
                    for di, digit in enumerate(hand.digits):
                        emit(f"   {DIGITS[di]}:")
                        for b in range(4):
                            bone = digit.bones[b]
                            pj, nj = bone.prev_joint, bone.next_joint
                            r = bone.rotation  # quaternion
                            bn = ["meta", "prox", "inter", "dist"][b]
                            emit(
                                f"     {bn:5s} prev=({pj.x:5.0f},{pj.y:5.0f},{pj.z:5.0f}) "
                                f"next=({nj.x:5.0f},{nj.y:5.0f},{nj.z:5.0f}) "
                                f"rot=({r.x:+.3f},{r.y:+.3f},{r.z:+.3f},{r.w:+.3f})"
                            )
            except Exception:
                emit("!! スケルトン走査で例外（属性名を要調整）:")
                traceback.print_exc()
        elif state["frames"] % 30 == 0:
            print(f"[frame {event.tracking_frame_id}] hands={n}")


def main():
    print("leap_probe: connection open ...")
    try:
        state["fh"] = open(OUTFILE, "w", encoding="utf-8")
    except Exception as e:
        print("(ファイル出力を開けず、stdoutのみ):", e)
    conn = leap.Connection()
    conn.add_listener(Probe())
    with conn.open():
        conn.set_tracking_mode(leap.TrackingMode.Desktop)
        t0 = time.time()
        while time.time() - t0 < DUR:
            time.sleep(0.2)
            if state["dumps"] >= MAX_DUMPS:
                print(">> 3ポーズ採取完了、終了")
                break

    print("\n=== SUMMARY ===")
    print("tracking frames    :", state["frames"])
    print("max hands / frame  :", state["max_hands"])
    print("poses captured     :", state["dumps"])
    ok = state["frames"] > 0
    print("RESULT:", "DATA PATH OK (フレーム流入を確認)" if ok
          else "NO FRAMES — service/device 要確認")
    if state["dumps"] > 0:
        print("capture saved      :", OUTFILE)
    if state["fh"]:
        state["fh"].close()


if __name__ == "__main__":
    main()
