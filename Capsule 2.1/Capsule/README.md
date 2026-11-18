# Capsule 0.2 (beta)

**Captured at 30. Released at 120.**

Play 30 FPS console games at 60, 90 or 120 FPS on your PC. Capsule reads your
capture card, removes the repeated frames consoles send, and generates the
in-between frames on your PC.

## What you need
- Windows 10/11 PC (6+ CPU cores recommended for 1080p 2x)
- A capture card (PCIe or low-latency USB) connected to your console
- A monitor running at 60 Hz or more (120 Hz+ for 4x mode)
- Python 3.10+ from python.org (only for the source version; not needed for the .exe)

## Setup
1. **PS5:** Settings > System > HDMI > turn off **Enable HDCP** (otherwise the capture card shows black).
2. Connect console -> capture card -> PC. Close OBS or any other app using the capture card.
3. Double-click **Capsule.bat**. The first run installs what it needs.
4. Pick your capture card, smoothness and audio, then press **Start**.

## Graphics card
Capsule generates frames on your graphics card (NVIDIA, AMD or Intel) through
OpenCL, which comes with the normal graphics driver. **Run on: Auto** tests the
card when you press Start and uses it if it's faster than the processor. The
stats overlay (S) shows which one is in use and how many ms each frame takes.
If nothing uses the GPU, update your graphics driver.

## Sound
A headset plugged into the controller hears the console directly, so it arrives
before the smoothed picture. For sound in sync, plug the headset into the PC,
set **Audio from** to your capture card and **Audio to** to the headset, then
fine-tune with `[` and `]` while playing.

## Controls while playing
| Key | Action |
|---|---|
| 1 / 2 / 3 / 4 | Off / 60 / 90 / 120 FPS |
| F | Fullscreen on/off |
| S | Stats overlay |
| [ / ] | Audio delay -10 / +10 ms |
| Q or Esc | Quit |

## Command line
```
python -m capsule --list                       # show video/audio devices and graphics card
python -m capsule --device 1 --multiplier 2 --stats --engine gpu
python -m capsule --convert clip.mp4 smooth.mp4  # smooth a recording
```

## Known limits
- Adds input lag (about one source frame plus capture delay).
- Fast motion and HUD elements can show warping/ghosting, especially at 4x.
- If your PC falls behind it skips generating frames to keep up (shown in stats).

## Building the .exe
Run `build_exe.bat` on Windows. The result is in `dist\Capsule\`.
