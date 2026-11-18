"""Capsule player: shows the capture card full screen with generated frames."""
import argparse
import queue
import sys
import time

import cv2
import numpy as np

from .engine import CaptureThread, FrameGenerator, GenerateThread, probe_cameras
from . import audio as audio_mod
from . import icon

WINDOW = "Capsule"
HELP = "1-4: multiplier  F: fullscreen  S: stats  [ ]: audio delay  Q/Esc: quit"


def _message_screen(lines):
    """Dark screen with text, shown instead of a blank grey window while waiting."""
    img = np.full((720, 1280, 3), 18, np.uint8)
    y = 300 - 25 * len(lines)
    for i, line in enumerate(lines):
        scale, thick = (1.3, 3) if i == 0 else (0.8, 2)
        (tw, _), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        cv2.putText(img, line, ((1280 - tw) // 2, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (255, 255, 255) if i == 0 else (180, 180, 180), thick, cv2.LINE_AA)
        y += 70 if i == 0 else 45
    return img


def _waiting_lines(cap, waited):
    if cap.blank:
        return ["Capture card is sending a blank picture",
                "PS5: Settings > System > HDMI > turn OFF Enable HDCP",
                "Also turn HDR off for now (Settings > Screen and Video > Video Output)",
                "Then make sure the console is on and showing a picture.   Q = quit"]
    if waited < 4:
        return ["Connecting to capture card...", "This can take a few seconds."]
    return ["Still waiting for video from the capture card",
            "Close OBS, Elgato Studio / Camera Hub and anything else using the card",
            "Check you picked the right card in the list, and the console is on",
            "Q = quit"]


def run_player(source, multiplier=2, width=1920, height=1080, flow_scale=0.25,
               fullscreen=True, audio_in=None, audio_out=None, audio_delay_ms=80,
               present_delay_ms=6, show_stats=False, engine="auto"):
    icon.set_app_id()
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    icon.apply_opencv(WINDOW)
    if fullscreen:
        cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.imshow(WINDOW, _message_screen(["Starting Capsule...",
                                        "Testing your graphics card (first time takes a few seconds)"]))
    cv2.waitKey(1)

    gen = FrameGenerator(multiplier, flow_scale, engine)
    print(f"[engine] {gen.engine_desc}", flush=True)
    cap = CaptureThread(source, width, height)
    cap.start()
    worker = GenerateThread(cap, gen)
    worker.start()

    passthrough = None
    if audio_in is not None:
        try:
            passthrough = audio_mod.DelayedPassthrough(audio_in, audio_out, audio_delay_ms)
            passthrough.start()
        except Exception as e:
            print(f"[audio] disabled: {e}")
            passthrough = None

    pending = []  # (display_time, frame)
    shown, last_fps_t, out_fps, src_fps, last_real = 0, time.perf_counter(), 0.0, 0.0, 0
    present_delay = present_delay_ms / 1000
    started = time.perf_counter()
    last_msg = 0.0
    shown_any = False

    try:
        while True:
            while worker.out:
                due_t, f = worker.out.popleft()
                pending.append((due_t + present_delay, f))
            if not cap.running and cap.error:
                raise RuntimeError(cap.error)
            if worker.error:
                raise RuntimeError(worker.error)

            now = time.perf_counter()
            if cap.blank or (not shown_any and not pending):
                if now - last_msg > 0.25:
                    cv2.imshow(WINDOW, _message_screen(_waiting_lines(cap, now - started)))
                    last_msg = now
                if cap.blank:
                    pending = []
            due = [p for p in pending if p[0] <= now]
            if due:
                _, frame = due[-1]  # newest due frame; skip any we're late for
                pending = [p for p in pending if p[0] > now]
                if show_stats:
                    frame = frame.copy()
                    lines = [f"real {src_fps:.0f} fps -> shown {out_fps:.0f} fps (x{gen.multiplier})",
                             f"engine: {gen.engine_desc}",
                             f"generate: {worker.gen_ms:.1f} ms/frame   catch-up skips: {worker.catchup_skips}",
                             f"capture: {cap.mode}   duplicates removed: {cap.dropped_dupes}"]
                    if passthrough:
                        lines.append(f"audio delay: {passthrough.delay_frames * 1000 // passthrough.samplerate} ms")
                    lines.append(HELP)
                    for i, line in enumerate(lines):
                        cv2.putText(frame, line, (20, 40 + 34 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                                    (0, 0, 0), 4, cv2.LINE_AA)
                        cv2.putText(frame, line, (20, 40 + 34 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                                    (255, 255, 255), 2, cv2.LINE_AA)
                cv2.imshow(WINDOW, frame)
                shown_any = True
                shown += 1

            if now - last_fps_t >= 1.0:
                out_fps = shown / (now - last_fps_t)
                src_fps = (worker.real_count - last_real) / (now - last_fps_t)
                last_real = worker.real_count
                print(f"[stats] real {src_fps:.1f} fps -> shown {out_fps:.1f} fps (x{gen.multiplier}) "
                      f"gen {worker.gen_ms:.1f} ms skips {worker.catchup_skips}", flush=True)
                shown, last_fps_t = 0, now

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("1"), ord("2"), ord("3"), ord("4")):
                gen.multiplier = key - ord("0")
            elif key == ord("s"):
                show_stats = not show_stats
            elif key == ord("f"):
                fs = cv2.getWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN)
                cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN,
                                      cv2.WINDOW_NORMAL if fs == cv2.WINDOW_FULLSCREEN else cv2.WINDOW_FULLSCREEN)
            elif passthrough and key in (ord("["), ord("]")):
                cur = passthrough.delay_frames * 1000 / passthrough.samplerate
                passthrough.set_delay(cur + (10 if key == ord("]") else -10))
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.running = False
        worker.running = False
        if passthrough:
            passthrough.stop()
        cv2.destroyAllWindows()


def convert_file(inp, outp, multiplier=2, flow_scale=0.25, dedupe=True, engine="auto"):
    """Offline mode: make a smoother copy of a recorded clip. Returns stats."""
    from .interpolate import is_duplicate, thumb
    src = cv2.VideoCapture(inp)
    fps = src.get(cv2.CAP_PROP_FPS) or 60
    gen = FrameGenerator(multiplier, flow_scale, engine)
    print(f"[engine] {gen.engine_desc}", flush=True)
    writer, prev_small, real, dupes, written = None, None, 0, 0, 0
    t0 = time.perf_counter()
    idx = 0
    unique_times = []
    while True:
        ok, frame = src.read()
        if not ok:
            break
        t = idx / fps
        idx += 1
        small = thumb(frame)
        if dedupe and is_duplicate(prev_small, small):
            dupes += 1
            continue
        prev_small = small
        real += 1
        unique_times.append(t)
        for f, _ in gen.push(frame, t):
            if writer is None:
                h, w = f.shape[:2]
                writer = cv2.VideoWriter(outp, cv2.VideoWriter_fourcc(*"mp4v"),
                                         _estimate_fps(fps, dedupe) * multiplier, (w, h))
            writer.write(f)
            written += 1
    if gen.prev is not None and writer is not None:
        writer.write(gen.prev)
        written += 1
    if writer:
        writer.release()
    elapsed = time.perf_counter() - t0
    return {"real_frames": real, "duplicates_removed": dupes, "frames_written": written,
            "seconds": round(elapsed, 2), "generated_fps": round(max(written - real, 0) / elapsed, 1)}


def _estimate_fps(container_fps, dedupe):
    # A 60fps recording of a 30fps game: unique frames arrive at 30fps.
    return container_fps / 2 if dedupe and container_fps >= 50 else container_fps


def main(argv=None):
    p = argparse.ArgumentParser(prog="capsule", description="Smoother console gameplay from a capture card.")
    p.add_argument("--device", type=int, help="capture card index (see --list)")
    p.add_argument("--file", help="play a video file instead of a capture card")
    p.add_argument("--multiplier", type=int, default=2, choices=[1, 2, 3, 4], help="2 = 30->60, 4 = 30->120")
    p.add_argument("--resolution", default="1920x1080")
    p.add_argument("--flow-scale", type=float, default=0.25, help="lower = faster, higher = cleaner motion")
    p.add_argument("--windowed", action="store_true")
    p.add_argument("--stats", action="store_true")
    p.add_argument("--audio-in", type=int, help="capture card audio device index (see --list)")
    p.add_argument("--audio-out", type=int, help="headset/speaker device index (default: system default)")
    p.add_argument("--audio-delay", type=int, default=80, help="ms to delay audio so it matches the video")
    p.add_argument("--list", action="store_true", help="list video and audio devices")
    p.add_argument("--engine", default="auto", choices=["auto", "gpu", "cpu"], help="where frames are generated")
    p.add_argument("--convert", nargs=2, metavar=("IN", "OUT"), help="make a smoother copy of a recording")
    a = p.parse_args(argv)

    if a.list:
        from .engine import list_capture_devices
        from .interpolate import gpu_info
        print("Video devices:")
        for i, name in list_capture_devices():
            print(f"  {i}: {name}")
        ok, gname = gpu_info()
        print(f"Graphics card (OpenCL): {gname if ok else 'not available - ' + gname}")
        devs = audio_mod.list_devices()
        print("Audio devices:" if devs else "Audio devices: (install 'sounddevice' to list)")
        for i, name, ins, outs in devs:
            print(f"  {i}: {name}  (in {ins}, out {outs})")
        return 0
    if a.convert:
        print(convert_file(a.convert[0], a.convert[1], a.multiplier, a.flow_scale, engine=a.engine))
        return 0

    w, h = (int(x) for x in a.resolution.lower().split("x"))
    source = a.file if a.file else (a.device if a.device is not None else 0)
    run_player(source, a.multiplier, w, h, a.flow_scale, not a.windowed,
               a.audio_in, a.audio_out, a.audio_delay, show_stats=a.stats, engine=a.engine)
    return 0


if __name__ == "__main__":
    sys.exit(main())
