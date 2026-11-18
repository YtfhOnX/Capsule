"""Simple settings window shown when you double-click Capsule."""
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox

from .engine import list_capture_devices
from . import audio as audio_mod
from . import icon

CONFIG = os.path.join(os.path.expanduser("~"), ".capsule.json")
MODES = {"Off (30 fps)": 1, "60 fps (2x)": 2, "90 fps (3x)": 3, "120 fps (4x)": 4}
QUALITY = {"Fast": 0.2, "Balanced": 0.25, "Clean": 0.4}
ENGINES = {"Auto (graphics card if faster)": "auto", "Graphics card (GPU)": "gpu", "Processor (CPU)": "cpu"}


def _load():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    cfg = _load()
    icon.set_app_id()
    root = tk.Tk()
    root.title("Capsule")
    icon.apply_tk(root)
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=16)
    frm.grid()

    cams = [f"{i}: {n}" for i, n in list_capture_devices()] or ["0: Video device 0"]
    devs = audio_mod.list_devices()
    ins = ["None (use console/controller audio)"] + [f"{i}: {n}" for i, n, ci, _ in devs if ci > 0]
    outs = ["System default"] + [f"{i}: {n}" for i, n, _, co in devs if co > 0]

    saved = str(cfg.get("device", ""))
    v_cam = tk.StringVar(value=saved if saved in cams else cams[0])
    v_mode = tk.StringVar(value=cfg.get("mode", "60 fps (2x)"))
    v_res = tk.StringVar(value=cfg.get("resolution", "1920x1080"))
    v_q = tk.StringVar(value=cfg.get("quality", "Balanced"))
    v_eng = tk.StringVar(value=cfg.get("engine", next(iter(ENGINES))))
    if v_eng.get() not in ENGINES:
        v_eng.set(next(iter(ENGINES)))
    v_ain = tk.StringVar(value=cfg.get("audio_in", ins[0]))
    v_aout = tk.StringVar(value=cfg.get("audio_out", outs[0]))
    v_delay = tk.IntVar(value=cfg.get("audio_delay", 80))
    v_stats = tk.BooleanVar(value=cfg.get("stats", True))

    rows = [("Capture card", ttk.Combobox(frm, textvariable=v_cam, values=cams, state="readonly", width=34)),
            ("Smoothness", ttk.Combobox(frm, textvariable=v_mode, values=list(MODES), state="readonly", width=34)),
            ("Resolution", ttk.Combobox(frm, textvariable=v_res, values=["1920x1080", "2560x1440", "3840x2160", "1280x720"], width=34)),
            ("Quality", ttk.Combobox(frm, textvariable=v_q, values=list(QUALITY), state="readonly", width=34)),
            ("Run on", ttk.Combobox(frm, textvariable=v_eng, values=list(ENGINES), state="readonly", width=34)),
            ("Audio from", ttk.Combobox(frm, textvariable=v_ain, values=ins, state="readonly", width=34)),
            ("Audio to", ttk.Combobox(frm, textvariable=v_aout, values=outs, state="readonly", width=34)),
            ("Audio delay (ms)", ttk.Spinbox(frm, from_=0, to=400, increment=10, textvariable=v_delay, width=8))]
    for r, (label, widget) in enumerate(rows):
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=r, column=1, sticky="w")
    ttk.Checkbutton(frm, text="Show stats overlay", variable=v_stats).grid(row=len(rows), column=1, sticky="w")
    ttk.Label(frm, foreground="#666", wraplength=330, justify="left",
              text="Tip: on PS5 turn off HDCP (Settings > System > HDMI). For sound in sync with the "
                   "smoothed picture, plug your headset into the PC and pick the capture card under 'Audio from'.") \
        .grid(row=len(rows) + 1, column=0, columnspan=2, pady=(10, 6), sticky="w")

    def idx(s):
        try:
            return int(s.split(":")[0])
        except ValueError:
            return None

    def start():
        c = {"device": v_cam.get(), "mode": v_mode.get(), "resolution": v_res.get(), "quality": v_q.get(), "engine": v_eng.get(),
             "audio_in": v_ain.get(), "audio_out": v_aout.get(), "audio_delay": int(v_delay.get()),
             "stats": bool(v_stats.get())}
        try:
            with open(CONFIG, "w") as f:
                json.dump(c, f)
        except OSError:
            pass
        root.withdraw()
        try:
            from .app import run_player
            w, h = (int(x) for x in c["resolution"].split("x"))
            run_player(idx(c["device"]) or 0, MODES[c["mode"]], w, h, QUALITY[c["quality"]], True,
                       idx(c["audio_in"]), idx(c["audio_out"]), c["audio_delay"], show_stats=c["stats"],
                       engine=ENGINES[c["engine"]])
        except Exception as e:
            messagebox.showerror("Capsule", str(e))
        root.deiconify()

    ttk.Button(frm, text="Start", command=start).grid(row=len(rows) + 2, column=1, sticky="e", pady=(8, 0))
    root.mainloop()


if __name__ == "__main__":
    main()
