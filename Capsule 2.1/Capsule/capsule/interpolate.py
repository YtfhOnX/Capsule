"""Frame generation: creates in-between frames from two real frames.

Motion is measured with OpenCV's DIS optical flow on a downscaled copy of the
image, then both real frames are warped toward the in-between moment and
blended.

Two engines do the same maths:
  * GPU  - OpenCL through OpenCV's UMat. Works with NVIDIA, AMD and Intel
           graphics using the normal graphics driver; nothing extra to install.
  * CPU  - plain OpenCV, used if the graphics card can't be used.
"""
import time

import cv2
import numpy as np


def gpu_info():
    """(available, device name) for OpenCL on this PC."""
    try:
        if not cv2.ocl.haveOpenCL():
            return False, "no OpenCL driver found"
        cv2.ocl.setUseOpenCL(True)
        if not cv2.ocl.useOpenCL():
            return False, "OpenCL is turned off"
        dev = cv2.ocl.Device.getDefault()
        name = (dev.name() or "graphics card").strip()
        vendor = (dev.vendorName() or "").strip()
        return True, f"{name}" if vendor.lower() in name.lower() else f"{vendor} {name}".strip()
    except Exception as e:
        return False, str(e)


class FlowInterpolator:
    def __init__(self, flow_scale: float = 0.25, preset: int = cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST,
                 use_gpu: bool = False):
        self.flow_scale = flow_scale
        self.preset = preset
        self.dis = cv2.DISOpticalFlow_create(preset)
        self.gpu = bool(use_gpu)
        self._grid_cache = {}

    # ---- shared helpers ----
    def _small_grid(self, sh, sw, h, w):
        """Full-resolution pixel coordinates sampled at the low-res pixel centres
        (matches cv2.resize's centre alignment, so upsizing the map is exact)."""
        key = (sh, sw, h, w, self.gpu)
        if key not in self._grid_cache:
            sx, sy = w / sw, h / sh
            xs = (np.arange(sw, dtype=np.float32) + 0.5) * sx - 0.5
            ys = (np.arange(sh, dtype=np.float32) + 0.5) * sy - 0.5
            gx, gy = np.meshgrid(xs, ys)
            grid = np.dstack([gx, gy]).astype(np.float32)
            self._grid_cache[key] = (cv2.UMat(grid) if self.gpu else grid, (float(sx), float(sy)))
        return self._grid_cache[key]

    def _small_gray(self, img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.resize(g, None, fx=self.flow_scale, fy=self.flow_scale, interpolation=cv2.INTER_AREA)

    # ---- the two steps ----
    def prepare(self, a, b):
        """Measure motion between real frames a and b once; returns a context for make()."""
        h, w = a.shape[:2]
        if self.gpu:
            a, b = cv2.UMat(a), cv2.UMat(b)  # upload each real frame once
        ga, gb = self._small_gray(a), self._small_gray(b)
        f_ab = self.dis.calc(ga, gb, None)
        f_ba = self.dis.calc(gb, ga, None)
        sh, sw = (ga.get() if self.gpu else ga).shape[:2]
        grid, (sx, sy) = self._small_grid(sh, sw, h, w)
        # flow is measured in low-res pixels; convert to full-res pixels
        f_ab = cv2.multiply(f_ab, (sx, sy, 0, 0))
        f_ba = cv2.multiply(f_ba, (sx, sy, 0, 0))
        return (a, b, f_ab, f_ba, grid, w, h)

    def make(self, ctx, t: float):
        """Return the frame at time t (0 < t < 1) between a and b, as a normal image."""
        a, b, f_ab, f_ba, grid, w, h = ctx
        # Backward warp: a pixel x of the in-between frame came from x - t*F_ab in a
        # and from x - (1-t)*F_ba in b. The sampling maps are built at low
        # resolution and upsized, which is much cheaper.
        map_a = cv2.resize(cv2.scaleAdd(f_ab, -t, grid), (w, h), interpolation=cv2.INTER_LINEAR)
        map_b = cv2.resize(cv2.scaleAdd(f_ba, -(1 - t), grid), (w, h), interpolation=cv2.INTER_LINEAR)
        wa = cv2.remap(a, map_a, None, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        wb = cv2.remap(b, map_b, None, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        out = cv2.addWeighted(wa, 1 - t, wb, t, 0)
        return out.get() if self.gpu else out


def make_interpolator(flow_scale=0.25, engine="auto", log=print):
    """Pick the GPU if it works and is faster, otherwise the CPU.

    engine: "auto", "gpu" or "cpu". Returns (interpolator, description).
    """
    if engine != "cpu":
        ok, name = gpu_info()
        if ok:
            try:
                gpu = FlowInterpolator(flow_scale, use_gpu=True)
                ms_gpu = _benchmark(gpu)          # also compiles the GPU code (first run is slow)
                if engine == "gpu":
                    return gpu, f"GPU: {name} ({ms_gpu:.1f} ms/frame)"
                cpu = FlowInterpolator(flow_scale, use_gpu=False)
                ms_cpu = _benchmark(cpu)
                if ms_gpu <= ms_cpu * 1.1:
                    return gpu, f"GPU: {name} ({ms_gpu:.1f} ms/frame)"
                log(f"[engine] GPU {ms_gpu:.1f} ms vs CPU {ms_cpu:.1f} ms; using CPU")
                return cpu, f"CPU ({ms_cpu:.1f} ms/frame; GPU {name} was slower)"
            except Exception as e:
                log(f"[engine] graphics card failed, using CPU: {e}")
                name = f"failed: {e}"
        cv2.ocl.setUseOpenCL(False)
        if engine == "gpu":
            log(f"[engine] graphics card not available ({name}); using CPU")
    cpu = FlowInterpolator(flow_scale, use_gpu=False)
    return cpu, f"CPU ({_benchmark(cpu):.1f} ms/frame)"


def _benchmark(interp, w=1920, h=1080, rounds=4):
    rng = np.random.default_rng(0)
    a = cv2.GaussianBlur((rng.random((h, w, 3)) * 255).astype(np.uint8), (0, 0), 3)
    b = np.roll(a, 9, axis=1)
    interp.make(interp.prepare(a, b), 0.5)  # warm-up / compile
    t = time.perf_counter()
    for _ in range(rounds):
        ctx = interp.prepare(a, b)
        interp.make(ctx, 0.5)
    return (time.perf_counter() - t) / rounds * 1000


def is_duplicate(prev_small, cur_small, threshold: float = 0.6) -> bool:
    """Consoles send 60Hz video even for 30fps games, so every other frame is a copy.
    Compare tiny grayscale thumbnails; a near-zero difference means a repeated frame."""
    if prev_small is None:
        return False
    return float(cv2.absdiff(prev_small, cur_small).mean()) < threshold


def thumb(img):
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (96, 54), interpolation=cv2.INTER_AREA)
