# PLAY ZONE — an endless indoor play place horror short

A 50-second (1,200 frames @ 24 fps) horror short made in **Blender 5.2.2 LTS** with Cycles. The scene is built
entirely from Python: procedural geometry and procedural materials, with no downloaded assets. The soundtrack is
synthesized with numpy/scipy, with no samples and no AI audio.

`PLAY_ZONE_horror_50s.mp4` is the finished film: 1280×720, H.264 + AAC.

## The film

| Time | What happens |
|---|---|
| 0–6 s | Darkness. A red EXIT sign far away. Fluorescent banks clunk on one by one, revealing a soft-play maze that never ends. |
| 6–18 s | A child's-eye walk (1.2 m camera, handheld bob) down the aisle: ball pits, tube slides, netting, "ZONE 7" on every pillar, a music box somewhere. |
| 18–25 s | At the crossing, the camera turns and zooms: a tall mascot stands at the end of the cross aisle. The lights black out, and it's gone. |
| 25–32 s | The ball pit begins to rattle. Balls burst over the wall and one rolls to the camera's feet. |
| 32–40 s | The mascot is back, at the end of the aisle. Row by row the lights die, rolling toward the camera. |
| 40–45 s | Total dark and a heartbeat. A flashlight clicks on. The camera turns around… and it's right there. |
| 45–50 s | Hard cut to silence: **PLAY ZONE — WE NEVER CLOSE**. |

## How it's built

- **Infinite space:** one 12 m "block" (island + aisles) is a collection instanced 10×10. One troffer mesh is arrayed
  into about 1,600 ceiling panels. The compositor's mist pass fades everything into dark haze.
- **Lights that fail on cue:** every panel's emission is computed in its shader from its own snapped world
  position. A few keyed Value nodes drive the switch-on wave, the rolling darkness front, the random flicker and a
  handful of permanently dying tubes (`M_Troffer`).
- **Ball pit:** 5,225 balls per pit, built as one numpy mesh with a per-ball colour attribute. The nine escaping
  balls are simulated in Python (gravity, bounces, rolling friction, roll rotation) and baked to keys.
- **Mascot:** a cracked fiberglass head, black glass eyes with pin-point glints, a crescent grin with jagged teeth,
  a party hat, and long arms with long fingers. It's a hierarchy of hip and neck pivots for the head tilt and the
  lunge.
- **Camera:** keyposes interpolated with monotone cubic splines, plus walk bob and sway tied to distance travelled,
  handheld drift and shock shakes. All of it is baked per frame. Footstep times go to `cues.json` for the audio.
- **Look:** AgX Medium High Contrast, then a compositor with mist haze, fog glow, lens distortion/dispersion,
  desaturation, a green-cyan colour balance and a vignette. Grain is added at encode.

## Rebuild / re-render

```bash
blender -b -y --python-exit-code 1 -P build_scene.py   # -> playplace.blend + cues.json
python3 make_audio.py                                    # -> soundtrack.wav (needs numpy + scipy)
blender -b playplace.blend -t 4 -a                       # -> frames/f_0001.png … f_1200.png
./encode.sh                                              # -> PLAY_ZONE_horror_50s.mp4
```

Look-dev stills: `blender -b playplace.blend -P render_test.py -- 50 4 120 512 1040` renders frames 120, 512 and
1040 at 50% size with 4 samples into `tests/`.

Render settings were chosen for a 4-core CPU with no GPU: Cycles at 960×540, 4 samples, Fast GI, 1 diffuse and
1 glossy bounce, OpenImageDenoise. The CPU compositor was used, which took about 6 s per frame. On a machine with a
GPU, raise `cycles.samples`, set `resolution_percentage` to 100 (or larger) and enable GPU compute for a cleaner,
sharper render. The scene doesn't otherwise change.

Timing for everything (light steps, flicker, mascot appearances, torch, stinger) lives in `timeline.py`, which
both the Blender build and the audio script read.
