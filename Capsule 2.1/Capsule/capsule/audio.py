"""Audio passthrough: takes the capture card's audio and plays it on the PC's
headset, delayed so it lines up with the frame-generated video.

(A headset plugged into the controller gets sound straight from the console,
before the video, so for in-sync sound plug the headset into the PC.)
"""
import collections
import threading

try:
    import numpy as np
    import sounddevice as sd
except Exception:  # sounddevice / PortAudio missing
    sd = None


def list_devices():
    if sd is None:
        return []
    return [(i, d["name"], d["max_input_channels"], d["max_output_channels"])
            for i, d in enumerate(sd.query_devices())]


class DelayedPassthrough:
    def __init__(self, input_device=None, output_device=None, delay_ms=80, samplerate=48000, channels=2):
        if sd is None:
            raise RuntimeError("Audio needs the 'sounddevice' package (pip install sounddevice).")
        self.samplerate = samplerate
        self.channels = channels
        self.input_device = input_device
        self.output_device = output_device
        self._lock = threading.Lock()
        self._buf = collections.deque()
        self._buffered = 0
        self.set_delay(delay_ms)
        self.stream = None

    def set_delay(self, delay_ms):
        self.delay_frames = int(self.samplerate * max(0, delay_ms) / 1000)

    def _callback(self, indata, outdata, frames, time, status):
        with self._lock:
            self._buf.append(indata.copy())
            self._buffered += frames
            out = np.zeros((frames, self.channels), dtype=np.float32)
            # Only play once enough audio is queued to cover the delay.
            if self._buffered - frames >= self.delay_frames:
                filled = 0
                while filled < frames and self._buf:
                    chunk = self._buf[0]
                    take = min(frames - filled, len(chunk))
                    out[filled:filled + take] = chunk[:take]
                    if take == len(chunk):
                        self._buf.popleft()
                    else:
                        self._buf[0] = chunk[take:]
                    filled += take
                self._buffered -= filled
            # Drop excess if the delay was lowered while running.
            while self._buffered > self.delay_frames + 4 * frames and self._buf:
                self._buffered -= len(self._buf.popleft())
            outdata[:] = out

    def start(self):
        self.stream = sd.Stream(device=(self.input_device, self.output_device),
                                samplerate=self.samplerate, channels=self.channels,
                                dtype="float32", latency="low", callback=self._callback)
        self.stream.start()

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
