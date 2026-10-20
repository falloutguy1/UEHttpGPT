"""Render a handful of frames for look-dev.
blender -b playplace.blend -P render_test.py -- <pct> <samples> <frame> [<frame> ...]"""
import bpy, sys, time, os
argv = sys.argv[sys.argv.index("--") + 1:]
pct, spp, frames = int(argv[0]), int(argv[1]), [int(a) for a in argv[2:]]
s = bpy.context.scene
s.render.resolution_percentage = pct
s.cycles.samples = spp
out = os.path.join(os.path.dirname(bpy.data.filepath), "tests")
for f in frames:
    s.frame_set(f)
    s.render.filepath = os.path.join(out, f"t_{f:04d}.png")
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"FRAME {f} {time.time() - t:.1f}s", flush=True)
