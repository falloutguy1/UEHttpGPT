"""Procedural sound design for PLAY ZONE (no samples, no AI audio - just numpy/scipy synthesis).

    python3 make_audio.py            -> soundtrack.wav (48 kHz stereo, 50 s)

Timing comes from timeline.py (shared with the Blender scene) and cues.json (footsteps and
ball bounces exported by build_scene.py), so every clunk, flicker and bounce lands on its frame.
"""
import json, os
import numpy as np
from scipy import signal
import wave

import timeline as TL

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 48000
DUR = TL.FRAME_END / TL.FPS
N = int(SR * DUR)
rng = np.random.default_rng(7)
CUES = json.load(open(os.path.join(HERE, "cues.json")))

dry = np.zeros((2, N))
send = np.zeros((2, N))


def t_of(frame):
    return (frame - 1) / TL.FPS


def add(sig, t0, gain=1.0, pan=0.0, rev=0.3):
    """Mix a mono (or stereo) signal in at time t0 with constant-power pan and a reverb send."""
    i0 = int(round(t0 * SR))
    if i0 >= N:
        return
    sig = np.atleast_2d(sig)
    if sig.shape[0] == 1:
        a = (pan + 1) * np.pi / 4
        sig = np.vstack([sig[0] * np.cos(a), sig[0] * np.sin(a)]) * np.sqrt(2)
    n = min(sig.shape[1], N - i0)
    dry[:, i0:i0 + n] += sig[:, :n] * gain
    send[:, i0:i0 + n] += sig[:, :n] * gain * rev


def tt(dur):
    return np.arange(int(dur * SR)) / SR


def env(dur, attack=0.005, decay=0.2):
    t = tt(dur)
    return np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-t / decay)


def filt(x, kind, freq, order=2):
    sos = signal.butter(order, freq, btype=kind, fs=SR, output='sos')
    return signal.sosfilt(sos, x, axis=-1)


def noise(dur):
    return rng.standard_normal(int(dur * SR))


def steps_curve(steps, frames):
    out = np.empty(len(frames))
    for i, f in enumerate(frames):
        v = steps[0][1]
        for fr, val in steps:
            if f >= fr:
                v = val
        out[i] = v
    return out


def frame_env(values, smooth_hz=40.0):
    """Per-frame values -> audio-rate envelope (zero-order hold, then smoothed)."""
    idx = np.minimum((np.arange(N) / SR * TL.FPS).astype(int), len(values) - 1)
    e = values[idx]
    return filt(e, 'lowpass', smooth_hz, 1)


FR = np.arange(1, TL.FRAME_END + 1)
CAM_Y = np.interp(FR, [1, 150, 446, 612, 668, 862, 942, 1200], [-1, -0.85, 12, 12.05, 14.6, 14.5, 13.6, 13.6])

# ----------------------------------------------------------------------------- fluorescent hum
ron = steps_curve(TL.LIGHTS_ON_STEPS, FR)
front = steps_curve(TL.DARK_FRONT_STEPS, FR)
glob = steps_curve(TL.GLOBAL_FLICKER, FR)
flick = steps_curve(TL.FLICKER_AMOUNT, FR)
lvl = np.clip(ron / 16.0, 0, 1) * glob * np.clip((front - CAM_Y) / 30.0, 0, 1) ** 0.7
lvl *= 1 - 0.55 * flick * (rng.random(len(FR)) > 0.5)
lvl[FR >= TL.TITLE_START] = 0
hum_env = frame_env(lvl, 60.0)
t = np.arange(N) / SR
hum = np.zeros(N)
for k in range(1, 10):
    hum += np.sin(2 * np.pi * 120 * k * t + rng.uniform(0, 6.28)) / k ** 1.1
buzz = filt(noise(DUR), 'bandpass', [900, 4000]) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 120 * t)))
hum = hum * 0.05 + buzz * 0.012
whine = np.sin(2 * np.pi * 7820 * t) * 0.0025
add(np.vstack([hum + whine, np.roll(hum, 37) + whine]) * hum_env, 0.0, gain=0.9, rev=0.25)
# crackle when tubes are flickering
crackle_env = frame_env(np.clip(flick * 2.5, 0, 1) * (lvl > 0.05) + (np.abs(np.diff(glob, prepend=1)) > 0) * 1.5, 80)
crk = filt(noise(DUR) * (rng.random(N) < 0.004), 'highpass', 1500) * 0.6
add(crk * crackle_env, 0.0, gain=0.5, pan=0.1, rev=0.3)


# ----------------------------------------------------------------------------- relay clunks
def clunk(big=1.0):
    d = 0.9
    tl_ = tt(d)
    f = 70 * np.exp(-tl_ * 3) + 40
    thump = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tl_ / 0.18)
    click = filt(noise(d), 'bandpass', [300, 2500]) * env(d, 0.001, 0.025)
    ping = np.sin(2 * np.pi * 1180 * tl_) * env(d, 0.001, 0.06) * 0.15
    return (thump * 0.9 + click * 0.6 + ping) * big


for fr, r in TL.LIGHTS_ON_STEPS[1:]:
    add(clunk(0.9), t_of(fr), gain=0.55, pan=rng.uniform(-0.3, 0.3), rev=0.6)
for fr, fy in TL.DARK_FRONT_STEPS[1:]:
    d = max(1.0, fy - 14.0)
    g = 0.65 if fy < -1e4 else min(0.85, 0.22 + 6.0 / d)
    add(filt(clunk(1.0), 'lowpass', 900 + 6000 / d), t_of(fr), gain=g, pan=rng.uniform(-0.15, 0.15), rev=0.7)
# blackout pops during the figure scene
for fr in (518, 523, 527, 540):
    add(clunk(0.5), t_of(fr), gain=0.35, rev=0.5)


# ----------------------------------------------------------------------------- footsteps on foam
def footstep(amp):
    d = 0.35
    th = filt(noise(d), 'lowpass', 180, 2) * env(d, 0.004, 0.05) * 3.0
    fo = filt(noise(d), 'bandpass', [400, 1400]) * env(d, 0.002, 0.03) * 0.4
    return (th + fo) * amp


for i, (fr, a) in enumerate(zip(CUES["footsteps"], CUES["foot_amp"])):
    pan = -0.12 if i % 2 else 0.12
    add(footstep(0.7 + 0.3 * a), t_of(fr) + rng.uniform(-0.01, 0.01), gain=0.5, pan=pan, rev=0.2)
    if i % 5 == 3:        # sneaker squeak
        d = 0.09
        tl_ = tt(d)
        f = 1900 + 500 * tl_ / d + 60 * np.sin(2 * np.pi * 45 * tl_)
        sq = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * tl_ / d) ** 2
        add(sq, t_of(fr) + 0.03, gain=0.04, pan=pan, rev=0.35)


# ----------------------------------------------------------------------------- music box
NOTE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def hz(name, octave=6):
    return 261.63 * 2 ** ((NOTE[name] + 12 * (octave - 4)) / 12)


def tine(f, dur=2.4):
    tl_ = tt(dur)
    x = np.sin(2 * np.pi * f * tl_) * np.exp(-tl_ / 1.3)
    x += 0.25 * np.sin(2 * np.pi * f * 6.27 * tl_) * np.exp(-tl_ / 0.22)
    x += 0.07 * np.sin(2 * np.pi * f * 17.5 * tl_) * np.exp(-tl_ / 0.05)
    x += filt(noise(dur), 'highpass', 3000) * env(dur, 0.0005, 0.004) * 0.3
    return x * np.minimum(1, tl_ / 0.002)


TWINKLE = "C C G G A A G- F F E E D D C- G G F F E E D- G G F F E E D- C C G G A A G- F F E E D D C-".split()


def music_box(t0, t1, start_beat=0.42, slowdown=1.6, pitch_drop=-0.6, gain=0.08, notes=TWINKLE, stop_at=None):
    """Plays the tune from t0, beats stretching and pitch sagging like a spring running down."""
    t_cur, i = t0, 0
    while t_cur < t1 and i < len(notes) * 3:
        n = notes[i % len(notes)]
        prog = (t_cur - t0) / max(1e-3, t1 - t0)
        beat = start_beat * (1 + (slowdown - 1) * prog ** 2)
        semis = pitch_drop * prog ** 2 + 0.08 * np.sin(t_cur * 2.3)
        f = hz(n[0]) * 2 ** (semis / 12)
        add(filt(tine(f), 'lowpass', 3800), t_cur, gain=gain * rng.uniform(0.8, 1.0), pan=-0.35, rev=0.85)
        t_cur += beat * (2 if n.endswith('-') else 1)
        i += 1
        if stop_at is not None and i >= stop_at:
            break


music_box(t_of(160), t_of(516), slowdown=2.3, pitch_drop=-1.4)


# ----------------------------------------------------------------------------- ball pit
f_stir, f_last = TL.BALL_STIR_START, max(CUES["ball_launches"]) + 20
for fr in range(f_stir, f_last):
    k = (fr - f_stir) / (f_last - f_stir)
    dens = int(2 + 40 * np.sin(np.pi * min(1, k * 1.4)) ** 2)
    for _ in range(dens // 4 + rng.integers(0, 3)):
        d = rng.uniform(0.004, 0.014)
        c = filt(noise(0.03), 'bandpass', [1500, 6500]) * env(0.03, 0.0005, d)
        add(c, t_of(fr) + rng.uniform(0, 1 / TL.FPS), gain=rng.uniform(0.04, 0.12), pan=rng.uniform(-0.9, -0.3),
            rev=0.25)
for fr in CUES["ball_launches"]:
    pop = filt(noise(0.25), 'lowpass', 400) * env(0.25, 0.003, 0.05) * 1.5
    add(pop, t_of(fr), gain=0.4, pan=-0.6, rev=0.3)


def tok(speed):
    d = 0.12
    tl_ = tt(d)
    f = rng.uniform(850, 1500)
    x = np.sin(2 * np.pi * f * tl_) * env(d, 0.0005, 0.02) + filt(noise(d), 'highpass', 2000) * env(d, 0.0003, 0.003)
    return x * min(1.0, speed / 3.5)


for fr, sp in CUES["ball_bounces"]:
    add(tok(sp), t_of(fr) + rng.uniform(0, 0.04), gain=0.35, pan=rng.uniform(-0.4, 0.5), rev=0.3)


# ----------------------------------------------------------------------------- drones and tension
def shape(points):
    fr = np.array([p[0] for p in points], float)
    v = np.array([p[1] for p in points], float)
    return np.interp(t, (fr - 1) / TL.FPS, v)


sub_env = shape([(1, 0), (420, 0), (512, 0.55), (560, 0.35), (620, 0.2), (780, 0.25), (940, 0.8), (1031, 0.85),
                 (1040, 1.0), (1092, 1.0), (1093, 0)])
sub = (np.sin(2 * np.pi * 36.7 * t) + np.sin(2 * np.pi * 38.9 * t) * 0.8 + np.sin(2 * np.pi * 55 * t) * 0.4)
add(sub * sub_env * 0.11, 0.0, rev=0.1)
pad_env = shape([(1, 0), (780, 0), (900, 0.5), (1000, 0.7), (1031, 1.0), (1092, 1.0), (1093, 0)])
pad = np.zeros(N)
for f0 in (73.4, 77.8, 103.8, 110.0):
    ph = np.cumsum(f0 * (1 + 0.003 * np.sin(2 * np.pi * rng.uniform(0.05, 0.2) * t))) / SR
    pad += signal.sawtooth(2 * np.pi * ph)
lfo = 500 + 300 * np.sin(2 * np.pi * 0.07 * t)
pad = filt(pad, 'lowpass', 650, 4) * (0.8 + 0.2 * np.sin(2 * np.pi * 0.11 * t))
add(np.vstack([pad, np.roll(pad, 900)]) * pad_env * 0.045, 0.0, rev=0.5)
hi_env = shape([(1, 0), (880, 0), (1000, 0.6), (1031, 0.2), (1074, 0.5), (1092, 1.0), (1093, 0)])
hi = np.sin(2 * np.pi * 1760 * t) + np.sin(2 * np.pi * 1765.5 * t)
add(hi * hi_env * 0.006, 0.0, rev=0.4)

# distant heavy footfalls after the figure vanishes (it is moving somewhere out there)
for fr in (552, 571, 590, 609):
    add(filt(footstep(1.6), 'lowpass', 220), t_of(fr), gain=0.35, pan=0.6, rev=0.9)

# heartbeat in the dark
tb, beat = t_of(950), 0.95
while tb < t_of(TL.STINGER_FRAME):
    for off, f0, g in ((0.0, 55, 1.0), (0.27, 47, 0.7)):
        d = 0.25
        tl_ = tt(d)
        x = np.sin(2 * np.pi * f0 * tl_) * env(d, 0.006, 0.06)
        add(x, tb + off, gain=0.45 * g, rev=0.05)
    tb += beat
    beat = max(0.5, beat * 0.93)

# torch switch and its failing contacts
for fr in (972, 979, 1003):
    for off in (0.0, 0.009):
        add(filt(noise(0.02), 'highpass', 2500) * env(0.02, 0.0002, 0.002), t_of(fr) + off, gain=0.25, pan=0.25,
            rev=0.1)
for fr in range(1074, 1092):
    if fr % 2 == 0:
        add(filt(noise(0.05), 'bandpass', [1200, 6000]) * env(0.05, 0.001, 0.01), t_of(fr), gain=0.2, pan=0.2,
            rev=0.1)

# ----------------------------------------------------------------------------- reveal stinger
ts = t_of(TL.STINGER_FRAME)
d = 3.5
tl_ = tt(d)
boom = np.sin(2 * np.pi * np.cumsum(30 + 60 * np.exp(-tl_ * 4)) / SR) * np.exp(-tl_ / 0.9)
cluster = np.zeros_like(tl_)
for f0 in (110, 116.5, 155.6, 233.1, 246.9, 329.6):
    cluster += signal.sawtooth(2 * np.pi * f0 * (1 + 0.004 * rng.standard_normal()) * tl_)
cluster = np.tanh(filt(cluster, 'lowpass', 2600) * 0.6) * env(d, 0.01, 1.1)
scr_f = 1300 + 1100 * (1 - np.exp(-tl_ / 0.6)) + 90 * np.sin(2 * np.pi * 7 * tl_)
screech = np.tanh(np.sin(2 * np.pi * np.cumsum(scr_f) / SR) * 3) * env(d, 0.02, 0.8)
burst = filt(noise(d), 'lowpass', 5000) * env(d, 0.001, 0.15)
add(boom, ts, gain=0.9, rev=0.3)
add(cluster, ts, gain=0.32, rev=0.6)
add(screech, ts + 0.05, gain=0.07, pan=0.1, rev=0.6)
add(burst, ts, gain=0.25, rev=0.5)

# lunge: a rising roar that is cut dead by the edit
f0, f1 = TL.MASCOT_LUNGE
d = t_of(TL.CUT_FRAME) - t_of(f0)
tl_ = tt(d)
prog = tl_ / d
roar = np.zeros_like(tl_)
nz = noise(d)
for lo, hi_ in ((200, 900), (600, 2400), (1500, 5000)):
    roar += filt(nz, 'bandpass', [lo, hi_])
roar = np.tanh(roar * (0.5 + 3 * prog ** 2)) * prog ** 1.5
saw = np.tanh(signal.sawtooth(2 * np.pi * np.cumsum(140 + 600 * prog ** 2) / SR) * 2) * prog ** 2
add(roar * 0.3 + saw * 0.12, t_of(f0), gain=1.0, rev=0.2)

# ----------------------------------------------------------------------------- room tone
room = filt(np.cumsum(rng.standard_normal(N)) * 0.002, 'lowpass', 220)
room = filt(room, 'highpass', 25)
room_env = shape([(1, 0.6), (40, 1.0), (1092, 1.0), (1093, 0.0)])
add(np.vstack([room, np.roll(room, 2400)]) * room_env * 0.25, 0.0, rev=0.0)

# ----------------------------------------------------------------------------- reverb, hard cut, master
ir_len = int(2.6 * SR)
ti = np.arange(ir_len) / SR
ir = np.vstack([filt(rng.standard_normal(ir_len), 'lowpass', 5000) * np.exp(-ti / 0.55) for _ in range(2)])
ir[:, :int(0.018 * SR)] = 0
ir /= np.sqrt((ir ** 2).sum(axis=1, keepdims=True))
wet = np.vstack([signal.fftconvolve(send[c], ir[c])[:N] for c in range(2)]) * 0.55
mix = dry + wet
cut0 = int(t_of(TL.CUT_FRAME) * SR)
# the cut to the title is dead silence (no reverb tails) apart from the title's own music box:
# a single slow, detuned phrase that never resolves
dry[:, :], send[:, :] = 0, 0
music_box(t_of(1112), t_of(1200), start_beat=0.62, slowdown=1.5, pitch_drop=-0.9, gain=0.075, stop_at=7)
title = dry + np.vstack([signal.fftconvolve(send[c], ir[c])[:N] for c in range(2)]) * 0.55
mix[:, cut0:] = title[:, cut0:]
# soft master limiter
peak = np.max(np.abs(mix))
mix = np.tanh(mix / peak * 1.4) / np.tanh(1.4) * 0.89
out = (mix.T * 32767).astype(np.int16)
with wave.open(os.path.join(HERE, "soundtrack.wav"), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(out.tobytes())
rms = lambda a, b: float(np.sqrt(np.mean(mix[:, int(a * SR):int(b * SR)] ** 2)))
print(f"soundtrack.wav written: {DUR:.1f}s, peak in={peak:.2f}, rms opening={rms(0, 6):.3f} "
      f"walk={rms(8, 16):.3f} stinger={rms(42.9, 44):.3f} title={rms(45.6, 50):.4f}")
