"""Shared timing for the PLAY ZONE short. Imported by build_scene.py (Blender) and make_audio.py (plain Python).

All frames are 1-based at 24 fps; 1200 frames = 50 seconds.
"""

FPS = 24
FRAME_START = 1
FRAME_END = 1200
TITLE_START = 1093          # hard cut to the black title card

# Opening: ceiling lights switch on bank by bank, radiating out from the camera start.
# (frame, radius in metres) - lights whose centre is within the radius are on.
LIGHTS_ON_STEPS = [(1, -1.0), (38, 3.5), (52, 7.0), (63, 11.0), (72, 16.0),
                   (79, 22.0), (85, 30.0), (90, 40.0), (94, 1000.0)]
LIGHTS_ON_CENTER = (0.0, -1.0)

# Global blackout flicker while the figure vanishes down the cross aisle (frame, multiplier).
GLOBAL_FLICKER = [(1, 1.0), (518, 0.0), (521, 1.0), (523, 0.0), (525, 0.35), (527, 0.0),
                  (537, 1.0), (540, 0.0), (542, 1.0)]

# Darkness rolls toward the camera: lights with centre y > front go out (frame, front y).
DARK_FRONT_STEPS = [(1, 1e5), (800, 57.0), (812, 54.0), (823, 51.0), (833, 48.0), (842, 45.0),
                    (851, 42.0), (859, 39.0), (867, 36.0), (875, 33.0), (884, 30.0),
                    (893, 27.0), (901, 24.0), (908, 21.0), (914, 18.0), (920, 15.0),
                    (933, 12.0), (938, 9.0), (942, -1e5)]

# Random per-panel flicker amount (fraction of panels dropping out at any moment).
FLICKER_AMOUNT = [(1, 0.0), (100, 0.0), (104, 0.25), (110, 0.0), (505, 0.0), (510, 0.18),
                  (517, 0.35), (545, 0.0), (790, 0.0), (796, 0.12), (941, 0.12)]

# Camera flashlight (frame, energy multiplier 0..1), constant interpolation.
TORCH = [(1, 0.0), (972, 1.0), (976, 0.15), (979, 1.0), (1001, 0.6), (1003, 1.0),
         (1076, 0.2), (1078, 1.0), (1080, 0.0), (1082, 1.0), (1084, 0.1), (1086, 1.0),
         (1088, 0.0), (1089, 1.0), (TITLE_START, 0.0)]

# Red emergency light under the EXIT sign comes on once the mains die.
EMERGENCY_ON = 946

# Ball pit eruption.
BALL_STIR_START = 618
BALL_LAUNCHES = 640          # first launch frame; later balls follow

# Mascot appearances (frame -> (x, y, yaw_deg)); None = hidden below the floor.
MASCOT_POSES = [(1, None), (432, (27.0, 12.0, -90.0)), (529, None),
                (775, (0.0, 30.6, 0.0)), (895, None), (950, (0.0, 12.35, 180.0))]
MASCOT_HEAD_TILT = [(1, 0.0), (1036, 0.0), (1068, 24.0)]
MASCOT_LUNGE = (1074, 1090)  # lean in toward the lens

# Audio cue points (seconds are derived from these frames).
STINGER_FRAME = 1031         # face reveal
CUT_FRAME = TITLE_START


def sec(frame):
    return (frame - 1) / FPS
