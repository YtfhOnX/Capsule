"""Capture -> remove duplicate frames -> generate in-between frames -> schedule for display."""
import collections
import threading
import time
import queue

import cv2

from .interpolate import FlowInterpolator, make_interpolator, is_duplicate, thumb


class FrameGenerator:
    """Feed real (unique) frames with their arrival time; get back frames to show and when.

    For each new real frame B (previous A), it yields A plus (multiplier-1) generated
    frames spread evenly across the next source interval. Showing them one interval
    late is what makes the in-between frames possible. Frames are yielded one at a
    time so the first can be shown while the rest are still being made.
    """

    def __init__(self, multiplier=2, flow_scale=0.25, engine="auto", log=print):
        self.multiplier = multiplier
        self.interp, self.engine_desc = make_interpolator(flow_scale, engine, log)
        self.flow_scale = flow_scale
        self.log = log
        self.prev = None
        self.prev_t = None
        self.interval = None  # smoothed seconds between real frames

    def push(self, frame, t, generate=True):
        """generate=False skips the in-between frames (used to catch up when the PC falls behind)."""
        if self.prev is not None:
            dt = t - self.prev_t
            if 0 < dt < 0.25:
                self.interval = dt if self.interval is None else 0.9 * self.interval + 0.1 * dt
            d = self.interval or dt
            m = self.multiplier
            yield self.prev, t
            if generate and m > 1 and 0 < dt < 0.25:  # don't morph across stalls / scene loads
                try:
                    ctx = self.interp.prepare(self.prev, frame)
                    for k in range(1, m):
                        yield self.interp.make(ctx, k / m), t + k * d / m
                except cv2.error as e:
                    if not self.interp.gpu:
                        raise
                    # graphics driver hiccup: carry on with the CPU instead of crashing
                    self.log(f"[engine] graphics card error, switching to CPU: {e}")
                    cv2.ocl.setUseOpenCL(False)
                    self.interp = FlowInterpolator(self.flow_scale, use_gpu=False)
                    self.engine_desc = "CPU (graphics card error)"
        self.prev, self.prev_t = frame, t


class GenerateThread(threading.Thread):
    """Takes real frames from the capture thread, makes the in-between frames in the
    background and hands finished frames to the display loop. OpenCV releases
    Python's lock while it works, so capture, generation and display overlap."""

    def __init__(self, capture, generator):
        super().__init__(daemon=True)
        self.capture, self.gen = capture, generator
        self.out = collections.deque()
        self.running = True
        self.real_count = 0
        self.catchup_skips = 0
        self.gen_ms = 0.0
        self.error = None

    def run(self):
        try:
            while self.running:
                try:
                    frame, t = self.capture.frames.get(timeout=0.2)
                except queue.Empty:
                    if not self.capture.running:
                        break
                    continue
                self.real_count += 1
                behind = not self.capture.frames.empty()  # newer frame already waiting
                if behind:
                    self.catchup_skips += 1
                t0 = time.perf_counter()
                n = 0
                for f, due in self.gen.push(frame, t, generate=not behind):
                    self.out.append((due, f))
                    n += 1
                if n > 1:
                    ms = (time.perf_counter() - t0) * 1000 / (n - 1)
                    self.gen_ms = ms if not self.gen_ms else 0.9 * self.gen_ms + 0.1 * ms
        except Exception as e:
            self.error = f"Frame generation stopped: {e}"
        self.running = False


class CaptureThread(threading.Thread):
    """Reads the capture card (or a video file) and passes on only unique frames."""

    MAX_DUP_RUN = 3  # drop at most 3 copies in a row, so a still picture (menus, pause) keeps updating

    def __init__(self, source, width=1920, height=1080, fps=60, dedupe=True, dup_threshold=0.6):
        super().__init__(daemon=True)
        self.source = source
        self.is_file = isinstance(source, str)
        self.width, self.height, self.fps = width, height, fps
        self.dedupe = dedupe
        self.dup_threshold = dup_threshold
        self.frames = queue.Queue(maxsize=4)
        self.running = True
        self.dropped_dupes = 0
        self.raw_frames = 0      # every frame the card delivered, duplicates included
        self.blank = False       # card is sending a flat single-colour picture (HDCP / no signal)
        self.error = None
        self.mode = ""           # how the card was opened, shown in stats

    def open(self):
        if self.is_file:
            cap = cv2.VideoCapture(self.source)
            return cap if cap.isOpened() else None
        return open_device(self, self.source, self.width, self.height, self.fps)

    def run(self):
        try:
            cap = self.open()
        except Exception as e:
            cap, self.error = None, f"Could not open capture card {self.source}: {e}"
        if cap is None:
            self.error = self.error or (
                f"Capture card {self.source} isn't sending video.\n\n"
                "Check: the card is picked correctly, OBS / Elgato Studio / Camera Hub are closed, "
                "the console is on, and HDR is off on the console for now.")
            self.running = False
            return
        file_dt = 1.0 / (cap.get(cv2.CAP_PROP_FPS) or 60) if self.is_file else 0
        prev_small = None
        dup_run = 0
        blank_since = None
        next_t = time.perf_counter()
        fails = 0
        while self.running:
            ok, frame = cap.read()
            if not ok or frame is None:
                if self.is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop demo files
                    continue
                fails += 1
                if fails > 120:  # about 2 seconds of nothing
                    self.error = "Capture card stopped sending video"
                    break
                time.sleep(0.016)
                continue
            fails = 0
            frame = _to_bgr(frame)
            if frame is None:
                self.error = ("The capture card is sending a video format Capsule can't read "
                              "(usually HDR). Turn HDR off on the console and try again.")
                break
            if self.is_file:  # play files at their real speed
                next_t += file_dt
                time.sleep(max(0, next_t - time.perf_counter()))
            t = time.perf_counter()
            self.raw_frames += 1
            small = thumb(frame)
            if float(small.std()) < 2.0:  # flat picture: black (HDCP) or a "no signal" screen
                blank_since = blank_since or t
                self.blank = t - blank_since > 1.5
            else:
                blank_since, self.blank = None, False
            if (self.dedupe and dup_run < self.MAX_DUP_RUN
                    and is_duplicate(prev_small, small, self.dup_threshold)):
                self.dropped_dupes += 1
                dup_run += 1
                continue
            dup_run = 0
            prev_small = small
            try:
                self.frames.put((frame, t), timeout=0.5)
            except queue.Full:
                pass
        cap.release()
        self.running = False


def _to_bgr(frame):
    if frame.ndim == 3 and frame.shape[2] == 3:
        return frame
    if frame.ndim == 3 and frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    if frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 1):
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return None


def _is_windows():
    import sys
    return sys.platform.startswith("win")


def _backends():
    if _is_windows():
        return [("DirectShow", cv2.CAP_DSHOW), ("Media Foundation", cv2.CAP_MSMF)]
    return [("default", cv2.CAP_ANY)]


def open_device(owner, index, width, height, fps):
    """Open a capture card and make sure real frames come out.

    Tries each Windows backend, first with the card's own pixel format (Elgato HD60 X
    and most HDMI cards send NV12/YUY2), then with MJPG. Returns an open VideoCapture
    or None.
    """
    for be_name, be in _backends():
        for fourcc in (None, "MJPG"):
            cap = cv2.VideoCapture(index, be)
            if not cap.isOpened():
                cap.release()
                break  # this backend can't open the device at all
            if fourcc:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            deadline = time.perf_counter() + 3.0  # cards can take a moment to start
            while time.perf_counter() < deadline:
                ok, f = cap.read()
                if ok and f is not None and f.size:
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    owner.mode = f"{be_name}{' MJPG' if fourcc else ''} {w}x{h}"
                    return cap
                time.sleep(0.03)
            cap.release()
    return None


def camera_names():
    """Names of video devices in DirectShow order (same numbering OpenCV uses)."""
    if not _is_windows():
        return []
    try:
        from pygrabber.dshow_graph import FilterGraph
        return list(FilterGraph().get_input_devices())
    except Exception:
        return []


CARD_WORDS = ("elgato", "hd60", "4k60", "4k x", "capture", "cam link", "avermedia", "live gamer",
              "razer ripsaw", "game capture", "usb video", "hdmi")


def list_capture_devices(max_index=8):
    """[(index, name)] for video devices; capture cards listed first."""
    names = camera_names()
    if names:
        devs = list(enumerate(names))
    else:
        devs = [(i, f"Video device {i}") for i in probe_cameras(max_index)]
    looks_like_card = lambda n: any(w in n.lower() for w in CARD_WORDS)
    return sorted(devs, key=lambda d: (not looks_like_card(d[1]), d[0]))


def probe_cameras(max_index=6):
    """Return indexes of video devices that open (capture cards show up as cameras)."""
    found = []
    for i in range(max_index):
        backend = cv2.CAP_DSHOW if _is_windows() else cv2.CAP_ANY
        cap = cv2.VideoCapture(i, backend)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found
