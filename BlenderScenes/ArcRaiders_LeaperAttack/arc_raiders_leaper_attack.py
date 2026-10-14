"""
ARC Raiders fan scene: "Leaper at the Wall"
===========================================

A fully procedural Blender action scene. A Leaper (the big four-legged,
pouncing ARC machine) leaps off a ruined tower, lands in the sand of a
Buried-City-style ruin and tears open the facade of an apartment block to
get at a terrified Raider who is cornered in a second-floor room.

The script generates everything: terrain, buildings, a pre-fractured wall,
the rigged Leaper (IK legs), a posable Raider, interior props, dust/sparks
FX, lighting, six cameras with handheld shake and timeline-marker cuts.
It needs no external assets or add-ons.

Shot list (24 fps, frames 1-288, about 12 s)
  1   1- 60  Exterior wide: the Leaper pounces, lands, rears up, first strike
  2  61-120  Interior: the wall caves in around the Raider, two more strikes
  3 121-168  Exterior 3/4: the Leaper hooks the breach and rips the wall away
  4 169-228  Over the Leaper's head: the red searchlight finds the Raider
  5 229-268  Floor level: a leg spears into the room and misses
  6 269-288  Close-up on the Raider as the second strike lands closer

Usage
  In Blender: Scripting workspace > Open this file > Run Script.
  Command line (everything after "--" goes to this script):
    blender --python arc_raiders_leaper_attack.py
    blender -b --python arc_raiders_leaper_attack.py -- --save leaper_attack.blend
    blender -b --python arc_raiders_leaper_attack.py -- --preview --render-frames 40 100 200
    blender -b --python arc_raiders_leaper_attack.py -- --render-anim --out /tmp/leaper/

Tested with Blender 4.5 LTS and 5.2. Fan work; ARC Raiders is a trademark of
Embark Studios. Every model is an original approximation built from primitives.
"""

import argparse
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector, noise

# =============================================================================
# Configuration
# =============================================================================
SEED = 1983
FPS = 24
FRAME_START, FRAME_END = 1, 288
RESOLUTION = (1920, 1080)
SAMPLES = 128
PREVIEW_RESOLUTION = (960, 540)
PREVIEW_SAMPLES = 24
MOTION_BLUR = True
EXTERIOR_HAZE = True      # thin world-scale volume for aerial perspective
ROOM_DUST = True          # dusty air inside the room (makes light beams visible)

# Building layout (metres). The facade faces -Y; the Leaper attacks from there.
WALL_T = 0.3
BX = 6.0                  # wall centre lines at x = +-BX
BACK_Y = 7.0              # back wall centre line (facade centre line is y = 0)
FLOOR2 = 3.4              # top of the Raider's floor
CEIL2 = 6.5               # underside of the slab above
FLOOR3 = 6.8
ROOF = 10.2
SLAB_T = 0.3
BREACH = (-3.0, 3.0)      # x-range of the fracturable part of the 2nd-floor facade
SAND_BASE = 1.25

# Low golden-hour sun from the south-east (+x, -y); vector points at the sun.
SUN_ELEV = 13.0
SUN_TO = Vector((0.72, -0.62, 0.0)).normalized()
SUN_TO = Vector((SUN_TO.x * math.cos(math.radians(SUN_ELEV)),
                 SUN_TO.y * math.cos(math.radians(SUN_ELEV)),
                 math.sin(math.radians(SUN_ELEV))))

# Action beats shared by animation, FX and camera shake.
LAND_F = 28
WALL_HITS = [  # frame, contact point on the facade, breach radius, strength
    dict(f=56, p=Vector((-1.0, -0.15, 4.6)), r=0.75, s=1.0),
    dict(f=72, p=Vector((0.7, -0.15, 4.2)), r=0.9, s=1.1),
    dict(f=98, p=Vector((-0.3, -0.15, 5.3)), r=1.0, s=1.2),
]
HOOK_F = 132
HOOKS = [Vector((-1.3, 0.15, 4.5)), Vector((1.25, 0.15, 4.3))]
RIP_F = 141
STABS = [dict(f=246, p=Vector((1.75, 4.9, FLOOR2))),
         dict(f=280, p=Vector((2.2, 5.5, FLOOR2)))]
SHAKES = [(LAND_F, 1.0), (56, 0.6), (72, 0.7), (98, 0.8), (HOOK_F, 0.3),
          (RIP_F, 1.0), (246, 0.8), (280, 0.9)]

RNG = random.Random(SEED)


# =============================================================================
# Small math helpers
# =============================================================================
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def smoothstep(t):
    t = clamp(t)
    return t * t * (3.0 - 2.0 * t)


EASE = {
    "s": smoothstep,                                   # ease in/out
    "l": lambda t: t,                                  # linear
    "i": lambda t: t * t,                              # accelerate (strikes)
    "o": lambda t: 1.0 - (1.0 - t) * (1.0 - t),        # decelerate (recoil)
    "h": lambda t: 0.0 if t < 1.0 else 1.0,            # hold, then snap
}


def _lerp(a, b, t):
    if isinstance(a, Vector):
        return a.lerp(b, t)
    if isinstance(a, tuple):
        return tuple(_lerp(x, y, t) for x, y in zip(a, b))
    if isinstance(a, dict):
        out = {}
        for k in set(a) | set(b):
            va = a[k] if k in a else _zero_like(b[k])
            vb = b[k] if k in b else _zero_like(a[k])
            out[k] = _lerp(va, vb, t)
        return out
    return a + (b - a) * t


def _zero_like(v):
    if isinstance(v, Vector):
        return Vector((0.0,) * len(v))
    return 0.0


def _copy(v):
    if isinstance(v, tuple):
        return tuple(_copy(x) for x in v)
    if isinstance(v, dict):
        return {k: _copy(x) for k, x in v.items()}
    return v.copy() if hasattr(v, "copy") else v


class Track:
    """Piecewise keyed value: keys are (frame, value[, ease]) where the ease
    letter describes how the segment *arriving* at that key is shaped."""

    def __init__(self, keys):
        self.keys = sorted(((k[0], k[1], k[2] if len(k) > 2 else "s") for k in keys),
                           key=lambda k: k[0])

    def __call__(self, f):
        ks = self.keys
        if f <= ks[0][0]:
            return _copy(ks[0][1])
        for (f0, v0, _), (f1, v1, e) in zip(ks, ks[1:]):
            if f0 <= f <= f1:
                t = (f - f0) / float(f1 - f0) if f1 > f0 else 1.0
                return _lerp(v0, v1, EASE[e](t))
        return _copy(ks[-1][1])


def nz(x, seed=0.0, y=0.0):
    """1D-ish Perlin noise in [-1, 1]."""
    return noise.noise(Vector((x, seed * 13.17 + 0.5, y + 0.37)))


def sand_height(x, y):
    """Height of the sand surface; also used to plant feet and settle debris."""
    h = SAND_BASE
    dx = max(-BX - WALL_T / 2 - x, 0.0, x - BX - WALL_T / 2)
    dy = max(-WALL_T / 2 - y, 0.0, y - BACK_Y - WALL_T / 2)
    h += 0.55 * math.exp(-math.hypot(dx, dy) / 1.4)          # drift against the walls
    h += 0.05 * noise.noise(Vector((x * 0.35, y * 0.35, 0.0)))
    far = smoothstep((math.hypot(x * 0.8, (y + 3.0) * 0.6) - 11.0) / 14.0)
    dunes = 2.4 * (noise.noise(Vector((x * 0.045, y * 0.045, 3.1))) + 0.35)
    dunes += 1.0 * noise.noise(Vector((x * 0.11, y * 0.09, 7.3)))
    return h + far * dunes


def floor_height(x, y):
    """Surface debris rests on: the room floor, the slab ledge or the sand."""
    if abs(x) < BX - WALL_T / 2 and WALL_T / 2 < y < BACK_Y - WALL_T / 2:
        return FLOOR2
    if -0.35 <= y <= WALL_T / 2 and abs(x) < BX + WALL_T / 2:
        return FLOOR2
    return sand_height(x, y)


def look_quat(pos, target, roll=0.0):
    q = (Vector(target) - Vector(pos)).to_track_quat("-Z", "Y")
    if roll:
        q = q @ Quaternion((0.0, 0.0, 1.0), roll)
    return q


def rad3(v):
    return Euler([math.radians(a) for a in v], "XYZ")


# =============================================================================
# Scene reset / collections
# =============================================================================
def clear_scene():
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    scene = bpy.context.scene
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    scene.world = None
    for blocks in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                   bpy.data.cameras, bpy.data.armatures, bpy.data.curves,
                   bpy.data.particles, bpy.data.actions, bpy.data.worlds):
        for block in list(blocks):
            blocks.remove(block)
    scene.timeline_markers.clear()


def make_collections():
    root = bpy.data.collections.new("ARC_LeaperAttack")
    bpy.context.scene.collection.children.link(root)
    cols = {}
    for name in ("Environment", "Building", "Debris", "Interior", "Leaper",
                 "Raider", "FX", "Lights", "Cameras", "Templates"):
        c = bpy.data.collections.new(name)
        root.children.link(c)
        cols[name] = c
    return cols


# =============================================================================
# Mesh building helpers (bmesh)
# =============================================================================
def _rot4(rot):
    if rot is None:
        return Matrix.Identity(4)
    if isinstance(rot, (Euler, Quaternion)):
        return rot.to_matrix().to_4x4()
    return rot.to_4x4() if len(rot) == 3 else rot.copy()


def _faces_of(verts):
    faces = set()
    for v in verts:
        faces.update(v.link_faces)
    return faces


def _set_mat(verts, mat):
    for f in _faces_of(verts):
        f.material_index = mat
    return verts


def bm_box(bm, center, size, rot=None, mat=0):
    m = (Matrix.Translation(Vector(center)) @ _rot4(rot)
         @ Matrix.Diagonal((size[0], size[1], size[2], 1.0)))
    return _set_mat(bmesh.ops.create_cube(bm, size=1.0, matrix=m)["verts"], mat)


def bm_aabb(bm, x0, x1, y0, y1, z0, z1, mat=0):
    return bm_box(bm, ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2),
                  (x1 - x0, y1 - y0, z1 - z0), mat=mat)


def bm_cyl(bm, p0, p1, r0, r1=None, segs=16, mat=0, squash=(1.0, 1.0), caps=True):
    """Cylinder / cone from p0 (radius r0) to p1 (radius r1)."""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    m = (Matrix.Translation((p0 + p1) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
         @ Matrix.Diagonal((squash[0], squash[1], 1.0, 1.0)))
    verts = bmesh.ops.create_cone(
        bm, cap_ends=caps, cap_tris=False, segments=segs, radius1=r0,
        radius2=r0 if r1 is None else r1, depth=d.length, matrix=m)["verts"]
    return _set_mat(verts, mat)


def bm_sphere(bm, center, radius, segs=16, rings=8, scale=(1, 1, 1), rot=None, mat=0):
    m = (Matrix.Translation(Vector(center)) @ _rot4(rot)
         @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0)))
    verts = bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings,
                                      radius=radius, matrix=m)["verts"]
    return _set_mat(verts, mat)


def bm_dome(bm, center, radius, scale=(1, 1, 1), cut=0.0, segs=20, rings=10, mat=0):
    """Sphere with everything below `cut` (relative to centre) removed."""
    verts = bm_sphere(bm, center, radius, segs, rings, scale, mat=mat)
    c = Vector(center)
    low = [v for v in verts if v.co.z < c.z + cut - 1e-6]
    bmesh.ops.delete(bm, geom=low, context="VERTS")
    return [v for v in verts if v.is_valid]


def beam_frame(p0, p1, up):
    ax = (Vector(p1) - Vector(p0)).normalized()
    side = ax.cross(Vector(up))
    if side.length < 1e-4:
        side = ax.orthogonal()
    side.normalize()
    return ax, side, side.cross(ax).normalized()


def bm_beam(bm, p0, p1, w0, h0, w1, h1, up=(0, 0, 1), mat=0):
    """Tapered box from p0 to p1; w is across `side`, h along the up vector."""
    p0, p1 = Vector(p0), Vector(p1)
    _, side, upn = beam_frame(p0, p1, up)

    def ring(p, w, h):
        return [bm.verts.new(p + side * sx * w / 2 + upn * sy * h / 2)
                for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]

    a, b = ring(p0, w0, h0), ring(p1, w1, h1)
    faces = [bm.faces.new(list(reversed(a))), bm.faces.new(b)]
    for i in range(4):
        j = (i + 1) % 4
        faces.append(bm.faces.new((a[i], a[j], b[j], b[i])))
    for f in faces:
        f.material_index = mat
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    return a + b


def mesh_obj(name, bm, coll, mats=(), smooth=True, sharp_deg=32.0, rest=None):
    """Turn a bmesh into an object. `rest` adds a 'rest_pos' attribute holding
    world-space rest coordinates (offset by `rest`) so procedural textures stay
    glued to pieces that later move, deform or fly apart."""
    bm.normal_update()
    if smooth:
        lim = math.radians(sharp_deg)
        for f in bm.faces:
            f.smooth = True
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > lim:
                e.smooth = False
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    if rest is not None:
        add_rest_attr(me, Vector(rest))
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def add_rest_attr(me, offset=Vector()):
    n = len(me.vertices)
    co = [0.0] * (3 * n)
    me.vertices.foreach_get("co", co)
    for i in range(n):
        co[3 * i] += offset.x
        co[3 * i + 1] += offset.y
        co[3 * i + 2] += offset.z
    attr = me.attributes.new("rest_pos", "FLOAT_VECTOR", "POINT")
    attr.data.foreach_set("vector", co)


def add_bevel(ob, width=0.02, segments=2, angle=35.0):
    mod = ob.modifiers.new("Bevel", "BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(angle)
    try:
        mod.harden_normals = True
    except AttributeError:
        pass
    return mod


def new_empty(name, coll, loc=(0, 0, 0), size=0.1, kind="PLAIN_AXES"):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = kind
    ob.empty_display_size = size
    ob.location = loc
    coll.objects.link(ob)
    return ob


def key_visibility(ob, f_on, f_off=None):
    """Hidden in renders outside [f_on, f_off)."""
    for f, hidden in ((FRAME_START, True), (f_on, False)) + (((f_off, True),) if f_off else ()):
        ob.hide_render = hidden
        ob.hide_viewport = hidden
        ob.keyframe_insert("hide_render", frame=f)
        ob.keyframe_insert("hide_viewport", frame=f)


# =============================================================================
# Materials
# =============================================================================
def _node(nt, kind, loc=(0, 0), **props):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in props.items():
        setattr(n, k, v)
    return n


def _in(node, *names):
    for name in names:
        s = node.inputs.get(name)
        if s is not None:
            return s
    raise KeyError("%s has none of %s" % (node.bl_idname, names))


def _feed(nt, sock, val):
    if val is None:
        return
    if isinstance(val, (int, float)):
        sock.default_value = val
    elif isinstance(val, (tuple, list)):
        sock.default_value = tuple(val) + ((1.0,) if len(val) == 3 and len(sock.default_value) == 4 else ())
    else:
        nt.links.new(val, sock)


def _math(nt, op, a, b=None, clamp_=False, loc=(0, 0)):
    m = _node(nt, "ShaderNodeMath", loc, operation=op, use_clamp=clamp_)
    _feed(nt, m.inputs[0], a)
    if b is not None:
        _feed(nt, m.inputs[1], b)
    return m.outputs[0]


def _mix(nt, blend, fac, a, b, loc=(0, 0)):
    m = _node(nt, "ShaderNodeMix", loc)
    m.data_type = "RGBA"
    m.blend_type = blend
    fac_in = [s for s in m.inputs if s.name == "Factor" and s.type == "VALUE"][0]
    cols = [s for s in m.inputs if s.type == "RGBA"]
    _feed(nt, fac_in, fac)
    _feed(nt, cols[0], a)
    _feed(nt, cols[1], b)
    return [s for s in m.outputs if s.type == "RGBA"][0]


def _ramp(nt, fac, stops, loc=(0, 0), interp="LINEAR"):
    r = _node(nt, "ShaderNodeValToRGB", loc)
    cr = r.color_ramp
    cr.interpolation = interp
    els = cr.elements
    els[0].position, els[-1].position = stops[0][0], stops[-1][0]
    for pos, _ in stops[1:-1]:
        els.new(pos)
    for pos, col in stops:
        el = min(els, key=lambda e: abs(e.position - pos))
        el.color = tuple(col) + ((1.0,) if len(col) == 3 else ())
    _feed(nt, r.inputs["Fac"], fac)
    return r.outputs["Color"]


def _noise(nt, vec, scale, detail=4.0, rough=0.55, loc=(0, 0)):
    n = _node(nt, "ShaderNodeTexNoise", loc)
    _in(n, "Scale").default_value = scale
    _in(n, "Detail").default_value = detail
    _in(n, "Roughness").default_value = rough
    nt.links.new(vec, n.inputs["Vector"])
    return n.outputs["Fac"]


def _coords(nt, mode, loc=(-1400, 0)):
    if mode == "rest":
        a = _node(nt, "ShaderNodeAttribute", loc)
        a.attribute_name = "rest_pos"
        return a.outputs["Vector"]
    return _node(nt, "ShaderNodeTexCoord", loc).outputs["Object"]


def _scale_vec(nt, vec, scale, loc=(0, 0)):
    m = _node(nt, "ShaderNodeMapping", loc)
    nt.links.new(vec, m.inputs["Vector"])
    m.inputs["Scale"].default_value = scale
    return m.outputs["Vector"]


def _new_material(name):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = _node(nt, "ShaderNodeOutputMaterial", (500, 0))
    return mat, nt, out


def mat_surface(name, base, var=None, var_scale=1.5, rough=0.6, rough_var=0.15,
                metal=0.0, coord="object", grime=0.0, streaks=0.0, bump=0.15,
                bump_scale=9.0, band=None, checker=None, patches=None, scratches=0.0, emission=None,
                emission_strength=0.0, coat=0.0):
    """General weathered PBR surface built from procedural noise.

    var       second colour blended in by low-frequency noise
    grime     darkening by mid-frequency dirt noise (0..1)
    streaks   vertical rain/rust streaks (0..1)
    band      (z, colour) - wainscot: below z use this colour (needs coord='rest')
    checker   (scale, colour) floor tiles
    scratches bright worn-metal flecks (0..1)
    """
    mat, nt, out = _new_material(name)
    bsdf = _node(nt, "ShaderNodeBsdfPrincipled", (200, 0))
    vec = _coords(nt, coord)
    col = tuple(base)
    if var is not None:
        f = _noise(nt, vec, var_scale, 5.0, 0.6, (-1100, 300))
        col = _ramp(nt, f, [(0.35, base), (0.65, var)], (-850, 300))
    if checker is not None:
        chk = _node(nt, "ShaderNodeTexChecker", (-1100, 600))
        nt.links.new(vec, chk.inputs["Vector"])
        chk.inputs["Scale"].default_value = checker[0]
        chk.inputs["Color1"].default_value = (1, 1, 1, 1)
        chk.inputs["Color2"].default_value = (0, 0, 0, 1)
        col = _mix(nt, "MIX", chk.outputs["Fac"], col, checker[1], (-600, 500))
    if patches is not None:    # flaked-off paint/plaster revealing what is underneath
        pn = _noise(nt, vec, patches[0], 6.0, 0.7, (-1100, 1000))
        pm = _math(nt, "GREATER_THAN", pn, patches[1], loc=(-900, 1000))
        col = _mix(nt, "MIX", pm, col, patches[2], (-600, 900))
    if band is not None:
        sep = _node(nt, "ShaderNodeSeparateXYZ", (-1100, 800))
        nt.links.new(vec, sep.inputs[0])
        below = _math(nt, "LESS_THAN", sep.outputs["Z"], band[0], loc=(-900, 800))
        col = _mix(nt, "MIX", below, col, band[1], (-600, 700))
    if grime > 0:
        g = _noise(nt, vec, 4.0, 8.0, 0.65, (-1100, 0))
        gm = _ramp(nt, g, [(0.45, (1, 1, 1)), (0.75, (1 - grime * 0.7,) * 3)], (-850, 0))
        col = _mix(nt, "MULTIPLY", 1.0, col, gm, (-400, 200))
    if streaks > 0:
        sv = _scale_vec(nt, vec, (0.9, 0.9, 0.07), (-1250, -300))
        s = _noise(nt, sv, 2.2, 4.0, 0.5, (-1100, -300))
        sm = _ramp(nt, s, [(0.52, (1, 1, 1)), (0.7, (1 - streaks * 0.4, 1 - streaks * 0.45, 1 - streaks * 0.5))], (-850, -300))
        col = _mix(nt, "MULTIPLY", 1.0, col, sm, (-250, 100))
    metal_in = metal
    rough_in = rough
    if scratches > 0:
        sc = _noise(nt, vec, 38.0, 2.0, 0.5, (-1100, -600))
        mask = _math(nt, "GREATER_THAN", sc, 1.0 - 0.18 * scratches, loc=(-850, -600))
        col = _mix(nt, "MIX", mask, col, (0.42, 0.42, 0.43), (-100, 0))
        metal_in = _math(nt, "MAXIMUM", mask, metal, loc=(-600, -650))
        rough_in = _math(nt, "SUBTRACT", rough, _math(nt, "MULTIPLY", mask, 0.3, loc=(-600, -750)), loc=(-400, -700))
    elif rough_var > 0:
        rn = _noise(nt, vec, 6.0, 3.0, 0.5, (-1100, -900))
        rough_in = _math(nt, "ADD", rough - rough_var / 2,
                         _math(nt, "MULTIPLY", rn, rough_var, loc=(-850, -900)), loc=(-600, -900))
    _feed(nt, _in(bsdf, "Base Color"), col)
    _feed(nt, _in(bsdf, "Metallic"), metal_in)
    _feed(nt, _in(bsdf, "Roughness"), rough_in)
    if coat:
        _feed(nt, _in(bsdf, "Coat Weight", "Clearcoat"), coat)
    if emission is not None:
        _feed(nt, _in(bsdf, "Emission Color", "Emission"), emission)
        _feed(nt, _in(bsdf, "Emission Strength"), emission_strength)
    if bump > 0:
        b = _noise(nt, vec, bump_scale, 10.0, 0.6, (-400, -400))
        bn = _node(nt, "ShaderNodeBump", (0, -400))
        bn.inputs["Strength"].default_value = bump
        _feed(nt, _in(bn, "Distance"), 0.02)
        nt.links.new(b, bn.inputs["Height"])
        nt.links.new(bn.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def mat_emit(name, color, strength):
    mat, nt, out = _new_material(name)
    em = _node(nt, "ShaderNodeEmission", (200, 0))
    em.inputs["Color"].default_value = tuple(color) + (1.0,)
    em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return mat


def mat_eye(name):
    """Glowing ARC optic: hot core fading to deep red at the rim."""
    mat, nt, out = _new_material(name)
    sep = _node(nt, "ShaderNodeSeparateXYZ", (-700, 0))
    nt.links.new(_coords(nt, "rest", (-900, 0)), sep.inputs[0])
    # The optic faces +Y in the rest pose; radial distance in the XZ plane.
    comb = _node(nt, "ShaderNodeCombineXYZ", (-500, 0))
    nt.links.new(sep.outputs["X"], comb.inputs["X"])
    nt.links.new(_math(nt, "SUBTRACT", sep.outputs["Z"], 0.06 * 1.2, loc=(-600, -150)), comb.inputs["Y"])
    ln = _node(nt, "ShaderNodeVectorMath", (-300, 0), operation="LENGTH")
    nt.links.new(comb.outputs[0], ln.inputs[0])
    col = _ramp(nt, _math(nt, "DIVIDE", ln.outputs["Value"], 0.25 * 1.2, loc=(-150, 0)),
                [(0.0, (1.0, 0.75, 0.45)), (0.25, (1.0, 0.18, 0.03)), (1.0, (0.55, 0.01, 0.0))], (0, 0))
    em = _node(nt, "ShaderNodeEmission", (250, 0))
    nt.links.new(col, em.inputs["Color"])
    em.inputs["Strength"].default_value = 45.0
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return mat


def mat_volume(name, color, density, puff=False, anisotropy=0.25):
    """Volume shader. `puff`: soft noisy sphere whose density is scaled by the
    object's colour alpha (animated per dust puff)."""
    mat, nt, out = _new_material(name)
    vol = _node(nt, "ShaderNodeVolumePrincipled", (200, 0))
    vol.inputs["Color"].default_value = tuple(color) + (1.0,)
    _feed(nt, _in(vol, "Anisotropy"), anisotropy)
    if puff:
        tc = _node(nt, "ShaderNodeTexCoord", (-1100, 0))
        ln = _node(nt, "ShaderNodeVectorMath", (-900, 100), operation="LENGTH")
        nt.links.new(tc.outputs["Object"], ln.inputs[0])
        fall = _math(nt, "SUBTRACT", 1.0, ln.outputs["Value"], clamp_=True, loc=(-700, 100))
        fall = _math(nt, "POWER", fall, 1.3, loc=(-500, 100))
        nz_ = _noise(nt, tc.outputs["Object"], 1.8, 6.0, 0.6, (-900, -150))
        nz_ = _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", nz_, 0.3, loc=(-700, -150)), 2.2,
                    clamp_=True, loc=(-500, -150))
        info = _node(nt, "ShaderNodeObjectInfo", (-700, -350))
        d = _math(nt, "MULTIPLY", fall, nz_, loc=(-300, 0))
        d = _math(nt, "MULTIPLY", d, info.outputs["Alpha"], loc=(-150, 0))
        d = _math(nt, "MULTIPLY", d, density, loc=(0, 0))
        nt.links.new(d, vol.inputs["Density"])
    else:
        vol.inputs["Density"].default_value = density
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    return mat


def build_materials():
    M = {}
    # Building (rest_pos coordinates keep the texture continuous across chunks)
    M["plaster"] = mat_surface("ARC_Plaster", (0.8, 0.62, 0.43), var=(0.7, 0.45, 0.32),
                               var_scale=0.3, rough=0.9, coord="rest", grime=0.35,
                               streaks=0.6, patches=(0.9, 0.66, (0.5, 0.47, 0.43)),
                               bump=0.2, bump_scale=5.0)
    M["paint"] = mat_surface("ARC_InteriorPaint", (0.66, 0.62, 0.52), var=(0.55, 0.52, 0.44),
                             var_scale=1.2, rough=0.8, coord="rest", grime=0.5, streaks=0.5,
                             band=(FLOOR2 + 1.15, (0.17, 0.34, 0.33)), bump=0.1)
    M["concrete"] = mat_surface("ARC_Concrete", (0.44, 0.42, 0.39), var=(0.3, 0.29, 0.27),
                                var_scale=2.0, rough=0.92, coord="rest", grime=0.3, bump=0.45,
                                bump_scale=14.0)
    M["tiles"] = mat_surface("ARC_FloorTiles", (0.56, 0.5, 0.43), var=(0.62, 0.53, 0.4),
                             var_scale=0.8, rough=0.55, coord="rest", grime=0.55,
                             checker=(1.6, (0.33, 0.3, 0.27)), bump=0.08)
    M["sand"] = mat_surface("ARC_Sand", (0.78, 0.6, 0.41), var=(0.66, 0.49, 0.33),
                            var_scale=0.08, rough=0.95, rough_var=0.0, bump=0.35, bump_scale=2.5)
    M["shutter"] = mat_surface("ARC_ShutterPaint", (0.12, 0.36, 0.36), var=(0.36, 0.3, 0.22),
                               var_scale=3.0, rough=0.7, grime=0.4, streaks=0.4, bump=0.1)
    M["window"] = mat_surface("ARC_DarkWindow", (0.012, 0.012, 0.014), rough=0.25, rough_var=0.1, bump=0.0)
    M["rust"] = mat_surface("ARC_Rust", (0.32, 0.13, 0.05), var=(0.18, 0.09, 0.05), var_scale=4.0,
                            rough=0.85, metal=0.3, grime=0.3, bump=0.3, bump_scale=20.0)
    M["wood"] = mat_surface("ARC_Wood", (0.36, 0.23, 0.13), var=(0.24, 0.15, 0.08), var_scale=6.0,
                            rough=0.75, grime=0.3, bump=0.1)
    M["fabric"] = mat_surface("ARC_OldFabric", (0.48, 0.42, 0.33), var=(0.36, 0.3, 0.22),
                              var_scale=3.0, rough=0.95, grime=0.4, bump=0.1)
    M["rug"] = mat_surface("ARC_Rug", (0.42, 0.1, 0.07), var=(0.3, 0.2, 0.12), var_scale=5.0,
                           rough=0.95, grime=0.5, bump=0.05)
    M["sign"] = mat_surface("ARC_SignPaint", (0.75, 0.68, 0.52), var=(0.5, 0.42, 0.3), var_scale=2.0,
                            rough=0.7, grime=0.5, streaks=0.6)
    M["sign_text"] = mat_surface("ARC_SignLetters", (0.45, 0.07, 0.05), var=(0.28, 0.12, 0.07),
                                 var_scale=3.0, rough=0.6, grime=0.3)
    # Leaper
    M["arc_dark"] = mat_surface("ARC_Armor_Dark", (0.07, 0.075, 0.08), var=(0.11, 0.095, 0.08),
                                var_scale=2.5, rough=0.42, metal=0.65, coord="rest", grime=0.4,
                                scratches=1.0, bump=0.06, bump_scale=30.0)
    M["arc_plate"] = mat_surface("ARC_Armor_Plate", (0.4, 0.4, 0.37), var=(0.3, 0.21, 0.14),
                                 var_scale=1.8, rough=0.55, metal=0.2, coord="rest", grime=0.55,
                                 streaks=0.6, scratches=0.8, bump=0.05, bump_scale=25.0)
    M["arc_accent"] = mat_surface("ARC_Armor_Accent", (0.62, 0.16, 0.04), var=(0.3, 0.12, 0.06),
                                  var_scale=2.5, rough=0.5, metal=0.2, coord="rest", grime=0.4,
                                  scratches=1.0, bump=0.05, bump_scale=25.0)
    M["arc_joint"] = mat_surface("ARC_Joint", (0.025, 0.025, 0.027), rough=0.55, metal=0.4,
                                 coord="rest", grime=0.2, bump=0.05, bump_scale=40.0)
    M["chrome"] = mat_surface("ARC_Piston", (0.75, 0.74, 0.72), rough=0.2, metal=1.0, coord="rest",
                              grime=0.35, bump=0.0)
    M["eye"] = mat_eye("ARC_Eye")
    M["arc_light"] = mat_emit("ARC_Lights", (1.0, 0.16, 0.03), 30.0)
    M["arc_core"] = mat_emit("ARC_Core", (1.0, 0.32, 0.05), 7.0)
    # Raider
    M["jacket"] = mat_surface("Raider_Jacket", (0.66, 0.44, 0.1), var=(0.5, 0.36, 0.12),
                              var_scale=6.0, rough=0.85, grime=0.5, bump=0.12, bump_scale=60.0)
    M["pants"] = mat_surface("Raider_Pants", (0.2, 0.22, 0.14), var=(0.26, 0.24, 0.17),
                             var_scale=6.0, rough=0.9, grime=0.5, bump=0.1, bump_scale=60.0)
    M["gear"] = mat_surface("Raider_Webbing", (0.07, 0.065, 0.055), var=(0.12, 0.1, 0.08),
                            var_scale=8.0, rough=0.8, grime=0.3, bump=0.1, bump_scale=80.0)
    M["canvas"] = mat_surface("Raider_Backpack", (0.5, 0.2, 0.08), var=(0.36, 0.2, 0.1),
                              var_scale=5.0, rough=0.9, grime=0.55, bump=0.12, bump_scale=60.0)
    M["bedroll"] = mat_surface("Raider_Bedroll", (0.16, 0.32, 0.3), var=(0.2, 0.24, 0.2),
                               var_scale=5.0, rough=0.9, grime=0.4, bump=0.1)
    M["helmet"] = mat_surface("Raider_Helmet", (0.38, 0.35, 0.24), var=(0.26, 0.24, 0.17),
                              var_scale=4.0, rough=0.5, metal=0.1, grime=0.5, scratches=0.6, bump=0.05)
    M["skin"] = mat_surface("Raider_Skin", (0.56, 0.38, 0.28), var=(0.5, 0.32, 0.24), var_scale=8.0,
                            rough=0.55, grime=0.35, bump=0.05)
    M["boots"] = mat_surface("Raider_Boots", (0.13, 0.085, 0.05), rough=0.65, grime=0.4, bump=0.05)
    M["glass"] = mat_surface("Raider_Goggles", (0.02, 0.03, 0.03), rough=0.06, rough_var=0.0,
                             coat=1.0, bump=0.0)
    M["metal"] = mat_surface("Raider_Metal", (0.22, 0.22, 0.22), rough=0.4, metal=0.9, grime=0.3,
                             scratches=0.6, bump=0.0)
    M["lens"] = mat_emit("Flashlight_Lens", (1.0, 0.92, 0.75), 25.0)
    # FX
    M["spark"] = mat_emit("FX_Spark", (1.0, 0.5, 0.14), 40.0)
    M["dust"] = mat_volume("FX_Dust", (0.75, 0.62, 0.48), 2.6, puff=True, anisotropy=0.35)
    M["haze"] = mat_volume("FX_Haze", (0.9, 0.78, 0.64), 0.002, anisotropy=0.45)
    M["room_dust"] = mat_volume("FX_RoomDust", (0.85, 0.78, 0.68), 0.014, anisotropy=0.55)
    M["bulb"] = mat_emit("Lamp_Bulb", (1.0, 0.72, 0.4), 12.0)
    return M


def classify_face(c, n):
    """Material index for building geometry from face centre and normal:
    0 exterior plaster, 1 interior paint, 2 concrete, 3 floor tiles."""
    inside = (abs(c.x) < BX - WALL_T / 2 + 1e-3 and WALL_T / 2 - 1e-3 < c.y < BACK_Y - WALL_T / 2 + 1e-3)
    if n.z > 0.7:
        return 3 if inside and abs(c.z - FLOOR2) < 0.05 else 2
    if n.z < -0.7:
        return 2
    exterior = (abs(c.x) > BX - WALL_T / 2 + 1e-3 or c.y < WALL_T / 2 - 1e-3
                or c.y > BACK_Y - WALL_T / 2 + 1e-3)
    return 0 if exterior else 1


# =============================================================================
# Environment: sky, sun, sand, distant ruins, props outside
# =============================================================================
def build_world(scene):
    world = bpy.data.worlds.new("ARC_Sky")
    scene.world = world
    if world.node_tree is None:
        world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = _node(nt, "ShaderNodeOutputWorld", (400, 0))
    bg = _node(nt, "ShaderNodeBackground", (200, 0))
    sky = _node(nt, "ShaderNodeTexSky", (0, 0))
    for kind in ("NISHITA", "SINGLE_SCATTERING", "MULTIPLE_SCATTERING", "HOSEK_WILKIE"):
        try:
            sky.sky_type = kind
            break
        except TypeError:
            continue
    settings = (("sun_disc", False), ("sun_elevation", math.radians(SUN_ELEV)),
                ("sun_rotation", math.atan2(SUN_TO.x, SUN_TO.y) % (2 * math.pi)),
                ("altitude", 300.0), ("air_density", 1.2), ("dust_density", 4.5),
                ("aerosol_density", 4.5), ("ozone_density", 1.0), ("turbidity", 4.0))
    for attr, val in settings:
        if hasattr(sky, attr):
            try:
                setattr(sky, attr, val)
            except (TypeError, ValueError, AttributeError):
                pass
    if hasattr(sky, "sun_direction") and sky.sky_type == "HOSEK_WILKIE":
        sky.sun_direction = SUN_TO
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.22
    nt.links.new(bg.outputs[0], out.inputs["Surface"])


def build_sun(cols):
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = 4.2
    data.color = (1.0, 0.76, 0.52)
    data.angle = math.radians(1.5)
    sun = bpy.data.objects.new("Sun", data)
    sun.rotation_euler = (-SUN_TO).to_track_quat("-Z", "Y").to_euler()
    cols["Lights"].objects.link(sun)
    return sun


def axis_coords(a0, a1, f0, f1, fine, coarse):
    out, x = [], a0
    while x < a1:
        out.append(x)
        x += fine if f0 <= x <= f1 else coarse
    out.append(a1)
    return out


def build_ground(cols, M):
    xs = axis_coords(-110.0, 110.0, -22.0, 22.0, 0.5, 3.0)
    ys = axis_coords(-80.0, 130.0, -28.0, 16.0, 0.5, 3.0)
    bm = bmesh.new()
    rows = [[bm.verts.new((x, y, sand_height(x, y))) for x in xs] for y in ys]
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
    ob = mesh_obj("Sand_Dunes", bm, cols["Environment"], [M["sand"]], sharp_deg=180)
    ob.modifiers.new("Collision", "COLLISION")
    return ob


def ruin_block(name, cols, M, cx, cy, w, d, h, seed):
    """Background ruin: half-buried block with window voids and a broken top."""
    rng = random.Random(seed)
    base = sand_height(cx, cy) - 2.5
    bm = bmesh.new()
    bm_aabb(bm, cx - w / 2, cx + w / 2, cy - d / 2, cy + d / 2, base, base + h, mat=0)
    # broken crown: a few stubs of the next floor
    for _ in range(rng.randint(3, 6)):
        sx, sy = rng.uniform(1.0, w * 0.45), rng.uniform(1.0, d * 0.45)
        px = cx + rng.uniform(-w / 2 + sx / 2, w / 2 - sx / 2)
        py = cy + rng.uniform(-d / 2 + sy / 2, d / 2 - sy / 2)
        bm_aabb(bm, px - sx / 2, px + sx / 2, py - sy / 2, py + sy / 2,
                base + h, base + h + rng.uniform(0.6, 2.8), mat=0)
    # windows on all four faces
    floors = int((h - 2.5) / 3.2)
    for k in range(floors):
        z = base + 2.5 + 3.2 * k + 1.0
        if z + 1.4 > base + h:
            break
        for axis, sign in (("y", -1), ("y", 1), ("x", -1), ("x", 1)):
            span = w if axis == "y" else d
            n = max(1, int(span / 2.6))
            for i in range(n):
                if rng.random() < 0.12:
                    continue
                t = (i + 0.5) / n - 0.5
                if axis == "y":
                    x0 = cx + t * span - 0.55
                    y0 = cy + sign * d / 2
                    bm_aabb(bm, x0, x0 + 1.1, y0 - 0.06, y0 + 0.06, z, z + 1.4, mat=1)
                else:
                    y0 = cy + t * span - 0.55
                    x0 = cx + sign * w / 2
                    bm_aabb(bm, x0 - 0.06, x0 + 0.06, y0, y0 + 1.1, z, z + 1.4, mat=1)
    ob = mesh_obj(name, bm, cols["Environment"], [M["plaster"], M["window"]], rest=(0, 0, 0))
    return ob


def build_environment(cols, M):
    build_ground(cols, M)
    ruins = [
        ("Ruin_LaunchTower", -28.0, -12.5, 7.5, 7.0, 13.5),   # the Leaper pounces off this
        ("Ruin_B", -17.0, 15.0, 9.0, 8.0, 9.0),
        ("Ruin_C", 15.0, 13.0, 8.0, 10.0, 14.0),
        ("Ruin_D", 23.0, -5.0, 7.0, 7.0, 7.0),
        ("Ruin_E", -6.0, 27.0, 12.0, 8.0, 11.0),
        ("Ruin_F", 31.0, 27.0, 10.0, 10.0, 17.0),
        ("Ruin_G", -36.0, 21.0, 10.0, 10.0, 10.0),
        ("Ruin_H", 6.0, 38.0, 14.0, 9.0, 13.0),
        ("Ruin_I", 45.0, 8.0, 9.0, 12.0, 12.0),
        ("Ruin_J", -48.0, -5.0, 9.0, 9.0, 8.0),
    ]
    for i, (name, x, y, w, d, h) in enumerate(ruins):
        ruin_block(name, cols, M, x, y, w, d, h, SEED + i)

    # Leaning utility poles with sagging cables
    poles = [Vector((15.5, -4.0)), Vector((16.5, -14.0)), Vector((17.0, -24.0))]
    tops = []
    bm = bmesh.new()
    for i, p in enumerate(poles):
        g = sand_height(p.x, p.y)
        lean = Vector((0.4 * (i % 2) - 0.2, 0.25, 0.0))
        top = Vector((p.x, p.y, g + 7.5)) + lean
        bm_cyl(bm, (p.x, p.y, g - 1.0), top, 0.14, 0.11, segs=10, mat=0)
        bm_box(bm, top - Vector((0, 0, 0.5)), (1.6, 0.12, 0.12), mat=0)
        tops.append(top - Vector((0, 0, 0.45)))
    mesh_obj("Utility_Poles", bm, cols["Environment"], [M["wood"]])
    for k, side in enumerate((-0.7, 0.0, 0.7)):
        for a, b in zip(tops, tops[1:]):
            curve = bpy.data.curves.new("Cable", "CURVE")
            curve.dimensions = "3D"
            curve.bevel_depth = 0.012
            sp = curve.splines.new("POLY")
            pts = 14
            sp.points.add(pts - 1)
            for j in range(pts):
                t = j / (pts - 1)
                p = a.lerp(b, t) + Vector((side, 0, 0))
                p.z -= 1.4 * 4 * t * (1 - t)
                sp.points[j].co = (p.x, p.y, p.z, 1.0)
            ob = bpy.data.objects.new("Cable", curve)
            ob.data.materials.append(M["arc_joint"])
            cols["Environment"].objects.link(ob)
    # cables running off into the distance from the last pole
    # Half-buried rusted car
    bm = bmesh.new()
    cx, cy = -16.0, -8.0
    g = sand_height(cx, cy)
    rot = Euler((math.radians(-8), math.radians(14), math.radians(35)))
    R = rot.to_matrix()
    bm_box(bm, Vector((cx, cy, g + 0.05)), (1.8, 4.2, 0.9), rot=rot)
    bm_box(bm, Vector((cx, cy, g + 0.05)) + R @ Vector((0, -0.2, 0.7)), (1.6, 2.0, 0.6), rot=rot)
    for sx in (-0.95, 0.95):
        for sy in (-1.3, 1.3):
            c = Vector((cx, cy, g + 0.05)) + R @ Vector((sx, sy, -0.35))
            bm_cyl(bm, c - R @ Vector((0.12, 0, 0)), c + R @ Vector((0.12, 0, 0)), 0.36, segs=14)
    mesh_obj("Rusted_Car", bm, cols["Environment"], [M["rust"]])

    # Two distant ARC Wasp drones patrolling the skyline
    for i, (c, r, z) in enumerate(((Vector((22.0, 30.0)), 6.0, 16.0),
                                   (Vector((-20.0, 34.0)), 4.0, 12.0))):
        bm = bmesh.new()
        bm_sphere(bm, (0, 0, 0), 0.35, scale=(1.0, 1.4, 0.6), mat=0)
        for sx in (-1, 1):
            for sy in (-1, 1):
                p = Vector((sx * 0.55, sy * 0.55, 0.12))
                bm_beam(bm, (0, 0, 0), p, 0.08, 0.06, 0.06, 0.05, mat=0)
                bm_cyl(bm, p, p + Vector((0, 0, 0.05)), 0.3, segs=12, mat=0)
        bm_sphere(bm, (0, 0.45, -0.02), 0.09, mat=1)
        wasp = mesh_obj("ARC_Wasp_%d" % i, bm, cols["Environment"], [M["arc_dark"], M["arc_light"]])
        add_rest_attr(wasp.data)
        for f in range(FRAME_START, FRAME_END + 1, 3):
            a = f * 0.012 * (1 if i == 0 else -1) + i
            wasp.location = (c.x + r * math.cos(a), c.y + r * math.sin(a),
                             z + 0.6 * math.sin(f * 0.11 + i))
            wasp.rotation_euler = (math.radians(8), 0.0, a + math.pi * (1.0 if i == 0 else 0.0))
            wasp.keyframe_insert("location", frame=f)
            wasp.keyframe_insert("rotation_euler", frame=f)

    if EXTERIOR_HAZE:
        bm = bmesh.new()
        bm_aabb(bm, -120, 120, -90, 140, -2, 45)
        mesh_obj("Atmosphere_Haze", bm, cols["Environment"], [M["haze"]], smooth=False)


# =============================================================================
# Building
# =============================================================================
def wall_boxes(bm, along, a0, a1, t0, t1, z0, z1, openings=()):
    """Wall slab along x (along='x') or y with rectangular openings
    (a0, a1, z0, z1) cut out. Built from boxes so it needs no booleans."""
    cuts = sorted({a0, a1} | {o[0] for o in openings} | {o[1] for o in openings})
    for s0, s1 in zip(cuts, cuts[1:]):
        mid = (s0 + s1) / 2
        cover = sorted((o for o in openings if o[0] <= mid <= o[1]), key=lambda o: o[2])
        zs = [z0]
        for o in cover:
            zs += [max(o[2], z0), min(o[3], z1)]
        zs.append(z1)
        for za, zb in zip(zs[0::2], zs[1::2]):
            if zb - za > 1e-4:
                if along == "x":
                    bm_aabb(bm, s0, s1, t0, t1, za, zb)
                else:
                    bm_aabb(bm, t0, t1, s0, s1, za, zb)


def build_building(cols, M):
    bm = bmesh.new()
    t = WALL_T / 2
    x0, x1 = -BX - t, BX + t
    y0, y1 = -t, BACK_Y + t
    # Slabs (+ thin ledges that read as floor lines on the facade)
    for top in (FLOOR2, FLOOR3, ROOF):
        bm_aabb(bm, x0, x1, y0, y1, top - SLAB_T, top)
        bm_aabb(bm, x0 - 0.2, x1 + 0.2, y0 - 0.2, y0, top - 0.22, top)
    floors = [(-0.6, FLOOR2 - SLAB_T), (FLOOR2, CEIL2), (FLOOR3, ROOF - SLAB_T)]
    win = lambda a, b, z: (a, b, z, z + 1.6)
    # Facade (y = 0)
    wall_boxes(bm, "x", x0, x1, -t, t, *floors[0],
               openings=[(-0.9, 0.9, 0.0, 2.5), win(-4.6, -3.2, 1.0), win(3.2, 4.6, 1.0)])
    wall_boxes(bm, "x", x0, BREACH[0], -t, t, *floors[1], openings=[win(-5.0, -3.8, FLOOR2 + 0.85)])
    wall_boxes(bm, "x", BREACH[1], x1, -t, t, *floors[1], openings=[win(3.8, 5.0, FLOOR2 + 0.85)])
    wall_boxes(bm, "x", x0, x1, -t, t, *floors[2],
               openings=[win(-4.8, -3.4, FLOOR3 + 0.85), win(-0.7, 0.7, FLOOR3 + 0.85),
                         win(3.4, 4.8, FLOOR3 + 0.85)])
    # Back wall
    wall_boxes(bm, "x", x0, x1, BACK_Y - t, BACK_Y + t, *floors[0])
    wall_boxes(bm, "x", x0, x1, BACK_Y - t, BACK_Y + t, *floors[1],
               openings=[(-1.7, -0.5, FLOOR2 + 1.2, FLOOR2 + 2.5)])
    wall_boxes(bm, "x", x0, x1, BACK_Y - t, BACK_Y + t, *floors[2],
               openings=[win(-3.0, -1.6, FLOOR3 + 0.85), win(1.6, 3.0, FLOOR3 + 0.85)])
    # Side walls
    for sx in (-1, 1):
        c = sx * BX
        wall_boxes(bm, "y", y0, y1, c - t, c + t, *floors[0])
        wall_boxes(bm, "y", y0, y1, c - t, c + t, *floors[1],
                   openings=[win(2.0, 3.4, FLOOR2 + 0.85)] if sx > 0 else [win(4.6, 5.8, FLOOR2 + 0.85)])
        wall_boxes(bm, "y", y0, y1, c - t, c + t, *floors[2], openings=[win(2.4, 3.8, FLOOR3 + 0.85)])
    # Roof parapet with a collapsed section
    for (a, b) in ((x0, -1.0), (2.2, x1)):
        bm_aabb(bm, a, b, -t, t, ROOF, ROOF + 0.7)
    bm_aabb(bm, x0, x1, BACK_Y - t, BACK_Y + t, ROOF, ROOF + 0.7)
    for sx in (-1, 1):
        bm_aabb(bm, sx * BX - t, sx * BX + t, y0, y1, ROOF, ROOF + 0.7)
    # Window sills
    for (a, b, z) in ((-5.0, -3.8, FLOOR2 + 0.85), (3.8, 5.0, FLOOR2 + 0.85),
                      (-4.8, -3.4, FLOOR3 + 0.85), (3.4, 4.8, FLOOR3 + 0.85)):
        bm_aabb(bm, a - 0.1, b + 0.1, -t - 0.12, -t + 0.02, z - 0.08, z)
    bm.normal_update()
    for f in bm.faces:
        f.material_index = classify_face(f.calc_center_median(), f.normal)
    bld = mesh_obj("Apartment_Block", bm, cols["Building"],
                   [M["plaster"], M["paint"], M["concrete"], M["tiles"]], rest=(0, 0, 0))
    add_bevel(bld, 0.012, 1, 50)
    floor_col = bld.modifiers.new("Collision", "COLLISION")

    # Wooden shutters, balcony railing, roof clutter, shop sign
    bm = bmesh.new()
    for (a, b, z, swing) in ((-5.0, -3.8, FLOOR2 + 0.85, (60, -75)), (3.8, 5.0, FLOOR2 + 0.85, (95, -20)),
                             (-4.8, -3.4, FLOOR3 + 0.85, (80, -85)), (3.4, 4.8, FLOOR3 + 0.85, (-5, -100))):
        w = (b - a) / 2
        for hinge, ang, side in ((a, swing[0], -1), (b, swing[1], 1)):
            rot = Euler((0, 0, math.radians(ang)))
            ctr = Vector((hinge, -t - 0.03, z + 0.8)) + rot.to_matrix() @ Vector((side * w / 2, 0, 0))
            bm_box(bm, ctr, (w, 0.04, 1.55), rot=rot)
            for k in range(5):
                bm_box(bm, ctr + rot.to_matrix() @ Vector((0, -0.025, -0.6 + 0.3 * k)), (w * 0.95, 0.02, 0.05), rot=rot)
    mesh_obj("Window_Shutters", bm, cols["Building"], [M["shutter"]])

    bm = bmesh.new()
    # roof water tank + antenna
    bm_cyl(bm, (3.5, 5.0, ROOF), (3.5, 5.0, ROOF + 0.5), 0.06, segs=8)
    bm_cyl(bm, (3.5, 5.0, ROOF + 0.5), (3.5, 5.0, ROOF + 1.9), 0.75, segs=20)
    bm_cyl(bm, (-4.0, 6.0, ROOF), (-4.3, 6.2, ROOF + 5.0), 0.04, 0.02, segs=6)
    for k in range(4):
        z = ROOF + 2.0 + k * 0.8
        bm_cyl(bm, (-4.1 - 0.06 * k - 0.6, 6.05, z), (-4.1 - 0.06 * k + 0.6, 6.05, z), 0.015, segs=5)
    mesh_obj("Roof_Clutter", bm, cols["Building"], [M["rust"]])

    # Faded shop sign above the ground floor door: "PENSIONE ROSA"
    bm = bmesh.new()
    bm_box(bm, (0.0, -t - 0.06, FLOOR2 - 0.75), (4.6, 0.08, 0.7))
    mesh_obj("Sign_Board", bm, cols["Building"], [M["sign"]])
    txt = bpy.data.curves.new("SignText", "FONT")
    txt.body = "PENSIONE ROSA"
    txt.align_x = "CENTER"
    txt.align_y = "CENTER"
    txt.size = 0.42
    txt.extrude = 0.015
    tob = bpy.data.objects.new("Sign_Text", txt)
    tob.location = (0.0, -t - 0.115, FLOOR2 - 0.75)
    tob.rotation_euler = (math.radians(90), 0, 0)
    tob.data.materials.append(M["sign_text"])
    cols["Building"].objects.link(tob)
    return bld


# =============================================================================
# Breach wall: BSP-fractured chunks of the 2nd-floor facade
# =============================================================================
def _cut(bm, co, no, keep_below):
    geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
    res = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-6, plane_co=co, plane_no=no,
                                 clear_outer=keep_below, clear_inner=not keep_below)
    edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    if edges:
        filled = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
        for f in filled["faces"]:
            f.material_index = 2


def _bbox(bm):
    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))


def fracture_slab(lo, hi, pieces, rng):
    base = bmesh.new()
    bm_aabb(base, lo.x, hi.x, lo.y, hi.y, lo.z, hi.z)
    out = [base]
    tries = 0
    while len(out) < pieces and tries < pieces * 20:
        tries += 1
        out.sort(key=lambda b: b.calc_volume())
        p = out.pop()
        a, b = _bbox(p)
        ext = b - a
        c = (a + b) / 2 + Vector((rng.uniform(-0.22, 0.22) * ext.x, 0.0, rng.uniform(-0.22, 0.22) * ext.z))
        ang = math.radians(rng.uniform(-38, 38))
        if ext.x >= ext.z:
            n = Vector((math.cos(ang), rng.uniform(-0.12, 0.12), math.sin(ang)))
        else:
            n = Vector((math.sin(ang), rng.uniform(-0.12, 0.12), math.cos(ang)))
        n.normalize()
        pa, pb = p.copy(), p.copy()
        _cut(pa, c, n, True)
        _cut(pb, c, n, False)
        if min(len(pa.verts), len(pb.verts)) < 4 or min(pa.calc_volume(), pb.calc_volume()) < 0.008:
            pa.free()
            pb.free()
            out.append(p)
            continue
        p.free()
        out += [pa, pb]
    return out


def build_breach_wall(cols, M):
    rng = random.Random(SEED + 7)
    lo = Vector((BREACH[0], -WALL_T / 2, FLOOR2))
    hi = Vector((BREACH[1], WALL_T / 2, CEIL2))
    chunks = []
    for i, piece in enumerate(fracture_slab(lo, hi, 64, rng)):
        piece.normal_update()
        for f in piece.faces:
            if f.material_index != 2:
                f.material_index = classify_face(f.calc_center_median(), f.normal)
        a, b = _bbox(piece)
        ctr = sum((v.co for v in piece.verts), Vector()) / len(piece.verts)
        for v in piece.verts:
            v.co -= ctr
        ob = mesh_obj("Breach_Chunk_%02d" % i, piece, cols["Debris"],
                      [M["plaster"], M["paint"], M["concrete"]], rest=ctr)
        ob.location = ctr
        half = (b - a) / 2
        chunks.append(dict(obj=ob, loc=ctr.copy(), rot=Vector((0, 0, 0)),
                           rad=(min(half) + sum(half) / 3) / 2, free=False))
    return chunks


def _key_chunk(ch, f):
    ob = ch["obj"]
    ob.location = ch["loc"]
    ob.rotation_euler = Euler(ch["rot"])
    ob.keyframe_insert("location", frame=f)
    ob.keyframe_insert("rotation_euler", frame=f)


def _nudge(ch, f, push, rng):
    _key_chunk(ch, f - 1)
    ch["loc"] += push
    ch["rot"] += Vector([rng.uniform(-0.05, 0.05) for _ in range(3)]) * (push.length * 8.0)
    _key_chunk(ch, f + 1)


def _ballistic(ch, f0, vel, spin):
    """Simple rigid-ish debris: gravity, bounce, friction, walls of the room."""
    ch["free"] = True
    _key_chunk(ch, f0 - 1)
    p, r, v, w = ch["loc"].copy(), ch["rot"].copy(), vel.copy(), spin.copy()
    rad, sub, g = ch["rad"], 3, 9.81
    dt = 1.0 / (FPS * sub)
    still = 0
    f = f0
    while f <= FRAME_END and still < 4:
        for _ in range(sub):
            v.z -= g * dt
            p += v * dt
            r += w * dt
            inside = abs(p.x) < BX - WALL_T / 2 and WALL_T / 2 < p.y and p.z > FLOOR2 - 0.2
            if inside:
                if p.y > BACK_Y - WALL_T / 2 - rad:
                    p.y, v.y = BACK_Y - WALL_T / 2 - rad, -abs(v.y) * 0.3
                if abs(p.x) > BX - WALL_T / 2 - rad:
                    p.x, v.x = math.copysign(BX - WALL_T / 2 - rad, p.x), -v.x * 0.3
                if p.z > CEIL2 - rad:
                    p.z, v.z = CEIL2 - rad, -abs(v.z) * 0.3
            floor = floor_height(p.x, p.y)
            if p.z - rad < floor:
                p.z = floor + rad
                if v.z < 0:
                    v.z = -v.z * 0.22
                v.x *= 0.6
                v.y *= 0.6
                w *= 0.55
        ch["loc"], ch["rot"] = p, r
        _key_chunk(ch, f)
        resting = v.length < 0.25 and p.z - rad - floor_height(p.x, p.y) < 0.02
        still = still + 1 if resting else 0
        f += 1


def animate_breach(chunks):
    rng = random.Random(SEED + 11)
    for hit in WALL_HITS:
        c = Vector((hit["p"].x, hit["p"].z))
        for ch in chunks:
            if ch["free"]:
                continue
            d = (Vector((ch["loc"].x, ch["loc"].z)) - c).length
            if d < hit["r"] * rng.uniform(0.85, 1.15):
                radial = (Vector((ch["loc"].x, 0, ch["loc"].z)) - Vector((c.x, 0, c.y)))
                radial = radial.normalized() if radial.length > 1e-4 else Vector((0, 0, 1))
                vel = (Vector((0, rng.uniform(2.2, 4.2) * hit["s"], rng.uniform(0.3, 1.8)))
                       + radial * rng.uniform(0.6, 2.2))
                spin = Vector([rng.uniform(-9, 9) for _ in range(3)])
                _ballistic(ch, hit["f"] + int(d * 2.5), vel, spin)
            elif d < hit["r"] + 0.9:
                k = 1.0 - (d - hit["r"]) / 0.9
                _nudge(ch, hit["f"], Vector((0, rng.uniform(0.01, 0.05) * k, rng.uniform(-0.01, 0.01))), rng)
    # Legs hook the breach edges: the surrounding wall bends outward
    for h in HOOKS:
        for ch in chunks:
            if not ch["free"] and (Vector((ch["loc"].x, ch["loc"].z)) - Vector((h.x, h.z))).length < 0.9:
                _nudge(ch, HOOK_F + 2, Vector((0, -rng.uniform(0.04, 0.12), rng.uniform(-0.02, 0.03))), rng)
    # The rip: everything inside a rough rounded rectangle tears loose outward
    for ch in chunks:
        if ch["free"]:
            continue
        x, z = ch["loc"].x, ch["loc"].z
        q = (abs(x) / 2.45) ** 4 + (abs(z - 4.95) / 1.7) ** 4
        if q < 1.0 + 0.35 * nz(x * 1.7, 3.0, z * 1.7):
            vel = Vector((x * rng.uniform(0.4, 1.0), -rng.uniform(4.5, 8.5), rng.uniform(0.5, 3.5)))
            spin = Vector([rng.uniform(-7, 7) for _ in range(3)])
            _ballistic(ch, RIP_F + rng.randint(0, 4), vel, spin)


# =============================================================================
# Interior of the Raider's room
# =============================================================================
def build_interior(cols, M):
    coll = cols["Interior"]
    rng = random.Random(SEED + 3)
    z = FLOOR2
    # Overturned table and chairs (wood)
    bm = bmesh.new()
    c = Vector((-3.4, 1.3, z + 0.42))
    bm_box(bm, c, (1.4, 0.05, 0.8), rot=Euler((0, 0, math.radians(20))))
    for sx in (-0.6, 0.6):
        for sz in (-0.33, 0.33):
            leg0 = c + Euler((0, 0, math.radians(20))).to_matrix() @ Vector((sx, 0.03, sz))
            bm_cyl(bm, leg0, leg0 + Euler((0, 0, math.radians(20))).to_matrix() @ Vector((0, 0.7, 0)), 0.03, segs=6)
    for (cx, cy, ang, tip) in ((-3.6, 2.0, 30, 80), (3.2, 2.6, -60, 0)):
        r = Euler((math.radians(tip), 0, math.radians(ang)))
        base = Vector((cx, cy, z + (0.25 if tip else 0.45)))
        bm_box(bm, base, (0.45, 0.45, 0.04), rot=r)
        bm_box(bm, base + r.to_matrix() @ Vector((0, 0.21, 0.25)), (0.45, 0.04, 0.5), rot=r)
        for sx in (-0.2, 0.2):
            for sy in (-0.2, 0.2):
                p = base + r.to_matrix() @ Vector((sx, sy, 0))
                bm_cyl(bm, p, p + r.to_matrix() @ Vector((0, 0, -0.45)), 0.02, segs=6)
    # Shelf against the left wall + crates
    sx0 = -BX + WALL_T / 2
    bm_aabb(bm, sx0, sx0 + 0.4, 3.0, 3.06, z, z + 2.0)
    bm_aabb(bm, sx0, sx0 + 0.4, 4.4, 4.46, z, z + 2.0)
    for k in range(5):
        bm_aabb(bm, sx0, sx0 + 0.4, 3.0, 4.46, z + 0.1 + k * 0.45, z + 0.13 + k * 0.45)
    for (cx, cy, s, a) in ((4.6, 6.2, 0.7, 10), (4.5, 5.3, 0.6, -25), (4.6, 6.15, 0.55, 40)):
        zz = z + s / 2 + (0.7 if (cx, cy) == (4.6, 6.15) else 0.0)
        bm_box(bm, (cx, cy, zz), (s, s, s), rot=Euler((0, 0, math.radians(a))))
    mesh_obj("Furniture", bm, coll, [M["wood"]])

    # Cans / jars on the shelf
    bm = bmesh.new()
    for k in range(4):
        for j in range(rng.randint(2, 5)):
            p = Vector((sx0 + 0.2, 3.15 + j * 0.25 + rng.uniform(-0.05, 0.05), z + 0.13 + k * 0.45))
            bm_cyl(bm, p, p + Vector((0, 0, rng.uniform(0.12, 0.2))), rng.uniform(0.04, 0.06), segs=10)
    mesh_obj("Shelf_Cans", bm, coll, [M["metal"]])

    # Mattress + rug + blanket
    bm = bmesh.new()
    bm_box(bm, (-4.3, 5.7, z + 0.1), (1.9, 0.95, 0.2), rot=Euler((0, 0, math.radians(8))))
    mesh_obj("Mattress", bm, coll, [M["fabric"]])
    bm = bmesh.new()
    bm_box(bm, (0.2, 3.6, z + 0.006), (3.2, 2.2, 0.012), rot=Euler((0, 0, math.radians(-6))))
    mesh_obj("Rug", bm, coll, [M["rug"]])

    # Dropped rifle (Ferro-style single-shot)
    bm = bmesh.new()
    rr = Euler((0, math.radians(90), math.radians(-25)))
    Rm = rr.to_matrix()
    base = Vector((1.15, 5.45, z + 0.05))
    bm_box(bm, base, (0.08, 0.06, 0.75), rot=rr, mat=1)
    bm_cyl(bm, base + Rm @ Vector((0, 0, 0.35)), base + Rm @ Vector((0, 0, 1.05)), 0.02, segs=8, mat=0)
    bm_cyl(bm, base + Rm @ Vector((0, 0.06, 0.1)), base + Rm @ Vector((0, 0.06, 0.4)), 0.03, segs=10, mat=0)
    mesh_obj("Raider_Rifle", bm, coll, [M["metal"], M["wood"]])

    # Rubble already littering the floor
    bm = bmesh.new()
    for _ in range(70):
        p = Vector((rng.uniform(-5.6, 5.6), rng.uniform(0.6, 6.6), z))
        s = rng.uniform(0.04, 0.18)
        bm_box(bm, p + Vector((0, 0, s * 0.3)), (s, s * rng.uniform(0.6, 1.2), s * 0.6),
               rot=Euler([rng.uniform(0, 6.3) for _ in range(3)]))
    mesh_obj("Floor_Rubble", bm, coll, [M["concrete"]], rest=(0, 0, 0))

    # Faded poster on the back wall
    bm = bmesh.new()
    bm_box(bm, (3.9, BACK_Y - WALL_T / 2 - 0.006, z + 1.7), (0.7, 0.01, 1.0),
           rot=Euler((0, math.radians(4), 0)))
    mesh_obj("Poster", bm, coll, [M["sign_text"]])

    # Hanging lamp that swings and flickers after every impact
    pivot = new_empty("Lamp_Pivot", coll, (0.4, 3.4, CEIL2), 0.2)
    bm = bmesh.new()
    bm_cyl(bm, (0, 0, 0), (0, 0, -0.9), 0.006, segs=6, mat=0)
    bm_cyl(bm, (0, 0, -0.9), (0, 0, -1.12), 0.05, 0.28, segs=20, mat=0, caps=False)
    bm_sphere(bm, (0, 0, -1.1), 0.05, mat=1)
    lamp = mesh_obj("Hanging_Lamp", bm, coll, [M["rust"], M["bulb"]])
    lamp.parent = pivot
    ldata = bpy.data.lights.new("Lamp_Light", "POINT")
    ldata.energy = 25.0
    ldata.color = (1.0, 0.7, 0.4)
    ldata.shadow_soft_size = 0.05
    lamp_light = bpy.data.objects.new("Lamp_Light", ldata)
    lamp_light.parent = pivot
    lamp_light.location = (0, 0, -1.16)
    coll.objects.link(lamp_light)
    events = [(h["f"], 0.35 * h["s"]) for h in WALL_HITS] + [(RIP_F, 0.5), (246, 0.3), (280, 0.35)]
    flick = random.Random(SEED + 5)
    for f in range(FRAME_START, FRAME_END + 1):
        ax = ay = 0.0
        jolt = 0.0
        for f0, amp in events:
            if f >= f0:
                tt = (f - f0) / FPS
                ax += amp * math.exp(-tt * 0.9) * math.sin(tt * 2 * math.pi * 0.55)
                ay += amp * 0.5 * math.exp(-tt * 0.9) * math.sin(tt * 2 * math.pi * 0.62 + 1.0)
                jolt = max(jolt, math.exp(-(f - f0) / 14.0))
        pivot.rotation_euler = (ax, ay, 0.0)
        pivot.keyframe_insert("rotation_euler", frame=f)
        e = 25.0
        if jolt > 0.05 and flick.random() < 0.55 * jolt:
            e = flick.uniform(0.0, 8.0)
        ldata.energy = e
        ldata.keyframe_insert("energy", frame=f)

    if ROOM_DUST:
        bm = bmesh.new()
        bm_aabb(bm, -BX + 0.16, BX - 0.16, 0.0, BACK_Y - 0.16, FLOOR2 + 0.005, CEIL2 - 0.005)
        mesh_obj("Room_Dust_Volume", bm, coll, [M["room_dust"]], smooth=False)


# =============================================================================
# The Leaper: armature with IK legs + rigid-skinned hard-surface mesh
# =============================================================================
LEAPER_SCALE = 1.2        # the model below is authored at 1/1.2 size
LEGS = {
    #        hip                  knee                 foot (rest)          tucked (flight)
    "FL": ((-0.95, 1.0, 0.0), (-2.55, 3.1, 2.1), (-3.3, 4.1, -2.2), (-2.3, 3.0, -1.3)),
    "FR": ((0.95, 1.0, 0.0), (2.55, 3.1, 2.1), (3.3, 4.1, -2.2), (2.3, 3.0, -1.3)),
    "RL": ((-0.95, -1.0, 0.0), (-2.55, -3.0, 2.0), (-3.2, -4.1, -2.3), (-2.2, -2.9, -1.0)),
    "RR": ((0.95, -1.0, 0.0), (2.55, -3.0, 2.0), (3.2, -4.1, -2.3), (2.2, -2.9, -1.0)),
}
HEAD_BONE = ((0.0, 1.25, 0.05), (0.0, 1.95, 0.05))


def lv(v):
    """Leaper-space point scaled to world size."""
    return Vector(v) * LEAPER_SCALE


def pole_point(name, reach=False):
    """IK pole target in rig space. Front knees splay outward, up and back so
    they stay clear of the facade; rear knees point up like the rest pose."""
    hip, knee, foot = (lv(v) for v in LEGS[name][:3])
    if reach:          # spearing into the room: knee straight up the middle
        return hip + Vector((0.6, -1.0, 5.0))
    if name.startswith("F"):
        return hip + Vector((math.copysign(3.5, hip.x), -3.0, 3.5))
    return knee + (knee - (hip + foot) / 2).normalized() * 4.0


def pole_angle(hip, knee, foot, pole, x_axis):
    """Pole angle that keeps the rest pose when the pole sits at `pole`."""
    chain = knee - hip
    pole_normal = (foot - hip).cross(pole - hip)
    projected = pole_normal.cross(chain)
    ang = x_axis.angle(projected)
    if x_axis.cross(projected).angle(chain) < 1.0:
        ang = -ang
    return ang
LEAPER_MATS = ("arc_dark", "arc_plate", "arc_joint", "chrome", "eye", "arc_light", "arc_core", "arc_accent")


class Skin:
    """Collects geometry into one bmesh with each vertex weighted 100% to a bone."""

    def __init__(self, groups):
        self.bm = bmesh.new()
        self.dl = self.bm.verts.layers.deform.verify()
        self.groups = list(groups)
        self.index = {g: i for i, g in enumerate(self.groups)}

    def __call__(self, verts, group):
        gi = self.index[group]
        for v in verts:
            v[self.dl][gi] = 1.0


def leaper_geometry(sk):
    bm = sk.bm
    D, L, J, C, EYE, LITE, CORE, ACC = range(8)
    R = lambda x=0.0, y=0.0, z=0.0: Euler((math.radians(x), math.radians(y), math.radians(z)))
    # ---- chassis (bone: body) ----
    sk(bm_box(bm, (0, 0.1, 0.0), (1.55, 2.3, 0.8), mat=D), "body")
    sk(bm_beam(bm, (0, 1.2, -0.05), (0, 1.0, -0.05), 1.0, 0.55, 1.55, 0.8, mat=D), "body")
    for i, (y, w) in enumerate(((0.8, 1.7), (0.05, 1.82), (-0.7, 1.72))):
        sk(bm_box(bm, (0, y, 0.46 + 0.03 * i), (w, 0.88, 0.1), rot=R(-7), mat=L), "body")
        sk(bm_box(bm, (0, y - 0.1, 0.53 + 0.03 * i), (0.22, 0.5, 0.06), rot=R(-7), mat=ACC), "body")
    for s in (-1, 1):
        sk(bm_box(bm, (s * 0.86, 0.05, -0.08), (0.1, 2.0, 0.55), rot=R(0, s * -14), mat=L), "body")
        for k in range(3):
            sk(bm_box(bm, (s * 0.93, -0.55 + k * 0.55, 0.0), (0.04, 0.3, 0.08), rot=R(0, s * -14), mat=LITE if k == 1 else J), "body")
    sk(bm_box(bm, (0, 0.0, -0.52), (1.1, 1.8, 0.28), mat=J), "body")
    for y in (-0.55, 0.0, 0.55):
        sk(bm_cyl(bm, (-0.48, y, -0.66), (0.48, y, -0.66), 0.08, segs=12, mat=C), "body")
    # rear segment with the glowing core vent
    sk(bm_box(bm, (0, -1.55, 0.12), (1.25, 1.2, 0.85), rot=R(12), mat=D), "body")
    sk(bm_box(bm, (0, -1.6, 0.6), (1.32, 1.1, 0.1), rot=R(16), mat=L), "body")
    sk(bm_cyl(bm, (0, -2.08, 0.05), (0, -2.2, 0.05), 0.33, segs=24, mat=J), "body")
    sk(bm_cyl(bm, (0, -2.18, 0.05), (0, -2.23, 0.05), 0.25, segs=24, mat=CORE), "body")
    for z in (-0.1, 0.05, 0.2):
        sk(bm_box(bm, (0, -2.25, z), (0.52, 0.03, 0.035), mat=J), "body")
    for s in (-1, 1):
        sk(bm_cyl(bm, (s * 0.42, -1.85, 0.45), (s * 0.5, -2.3, 1.05), 0.1, 0.075, segs=12, mat=J), "body")
        sk(bm_cyl(bm, (s * 0.3, -1.2, 0.55), (s * 0.48, -1.95, 2.0), 0.02, 0.008, segs=6, mat=C), "body")
        sk(bm_sphere(bm, (s * 0.48, -1.95, 2.0), 0.03, mat=LITE), "body")
    # hip turrets
    for hip, _, _, _ in LEGS.values():
        h = Vector(hip)
        sk(bm_cyl(bm, h - Vector((0, 0, 0.27)), h + Vector((0, 0, 0.27)), 0.31, segs=20, mat=J), "body")
        sk(bm_cyl(bm, h + Vector((0, 0, 0.27)), h + Vector((0, 0, 0.36)), 0.27, 0.2, segs=20, mat=L), "body")

    # ---- head (bone: head) ----
    sk(bm_cyl(bm, (0, 0.95, 0.0), (0, 1.45, 0.05), 0.34, segs=16, mat=J), "head")
    sk(bm_beam(bm, (0, 1.3, 0.05), (0, 2.12, 0.02), 1.18, 0.9, 0.92, 0.72, mat=D), "head")
    sk(bm_box(bm, (0, 1.72, 0.5), (1.06, 0.86, 0.1), rot=R(-10), mat=L), "head")
    sk(bm_box(bm, (0, 1.62, 0.57), (0.18, 0.6, 0.06), rot=R(-10), mat=ACC), "head")
    for s in (-1, 1):
        sk(bm_box(bm, (s * 0.56, 1.72, -0.02), (0.08, 0.72, 0.58), rot=R(0, 0, s * 8), mat=L), "head")
        sk(bm_sphere(bm, (s * 0.44, 2.1, 0.33), 0.05, mat=LITE), "head")
        sk(bm_sphere(bm, (s * 0.52, 2.0, 0.18), 0.035, mat=LITE), "head")
        sk(bm_cyl(bm, (s * 0.3, 2.0, -0.3), (s * 0.17, 2.6, -0.66), 0.08, 0.008, segs=8, mat=C), "head")
    eye = Vector((0, 2.14, 0.06))
    sk(bm_cyl(bm, eye, eye + Vector((0, 0.1, 0)), 0.37, segs=32, mat=J), "head")
    sk(bm_cyl(bm, eye + Vector((0, 0.05, 0)), eye + Vector((0, 0.13, 0)), 0.26, segs=32, mat=EYE), "head")
    sk(bm_sphere(bm, eye + Vector((0, 0.12, 0)), 0.15, segs=24, rings=12, scale=(1, 0.45, 1), mat=EYE), "head")
    for k in range(3):   # the three armoured eye plates around the optic
        a = math.radians(90 + 120 * k)
        c = eye + Vector((math.cos(a) * 0.42, 0.13, math.sin(a) * 0.42))
        sk(bm_box(bm, c, (0.4, 0.07, 0.17), rot=Euler((0.0, -(a + math.pi / 2), 0.0)), mat=ACC), "head")

    # ---- legs (bones: femur.X, tibia.X) ----
    for name, (hip, knee, foot, _) in LEGS.items():
        hip, knee, foot = Vector(hip), Vector(knee), Vector(foot)
        fem, tib = "femur." + name, "tibia." + name
        n = (knee - hip).cross(foot - knee).normalized()
        outward = Vector((math.copysign(1.0, hip.x), 0.35 * math.copysign(1.0, hip.y), 0.0)).normalized()
        if n.dot(outward) < 0:
            n = -n
        # femur
        sk(bm_beam(bm, hip, knee, 0.5, 0.56, 0.36, 0.42, mat=D), fem)
        _, side, upn = beam_frame(hip, knee, (0, 0, 1))
        sk(bm_beam(bm, hip.lerp(knee, 0.1) + upn * 0.32, hip.lerp(knee, 0.88) + upn * 0.25,
                   0.62, 0.09, 0.48, 0.09, mat=L), fem)
        sk(bm_beam(bm, hip.lerp(knee, 0.3) + upn * 0.38, hip.lerp(knee, 0.62) + upn * 0.35,
                   0.16, 0.05, 0.14, 0.05, mat=ACC), fem)
        p0, p1 = hip.lerp(knee, 0.18) - upn * 0.36, hip.lerp(knee, 0.82) - upn * 0.29
        sk(bm_cyl(bm, p0, p0.lerp(p1, 0.55), 0.09, segs=12, mat=J), fem)
        sk(bm_cyl(bm, p0.lerp(p1, 0.5), p1, 0.05, segs=12, mat=C), fem)
        sk(bm_cyl(bm, knee - n * 0.36, knee + n * 0.36, 0.31, segs=24, mat=J), fem)
        sk(bm_cyl(bm, knee + n * 0.36, knee + n * 0.4, 0.13, segs=16, mat=LITE), fem)
        sk(bm_cyl(bm, knee - n * 0.4, knee - n * 0.36, 0.2, segs=16, mat=C), fem)
        # tibia + three armour plates + spike
        t_end = knee.lerp(foot, 0.86)
        sk(bm_beam(bm, knee, t_end, 0.42, 0.5, 0.19, 0.22, up=outward, mat=D), tib)
        _, side, upt = beam_frame(knee, t_end, outward)
        for u0, u1 in ((0.06, 0.3), (0.35, 0.58), (0.63, 0.82)):
            h0, h1 = 0.5 + (0.22 - 0.5) * u0 / 0.86, 0.5 + (0.22 - 0.5) * u1 / 0.86
            w0, w1 = 0.42 + (0.19 - 0.42) * u0 / 0.86, 0.42 + (0.19 - 0.42) * u1 / 0.86
            sk(bm_beam(bm, knee.lerp(foot, u0) + upt * (h0 / 2 + 0.04), knee.lerp(foot, u1) + upt * (h1 / 2 + 0.04),
                       w0 + 0.14, 0.07, w1 + 0.1, 0.07, up=outward, mat=L), tib)
        sk(bm_cyl(bm, knee.lerp(foot, 0.4) - upt * 0.15, knee.lerp(foot, 0.7) - upt * 0.1, 0.03, segs=8, mat=C), tib)
        sk(bm_cyl(bm, t_end, foot, 0.12, 0.004, segs=12, mat=C), tib)


def build_leaper(cols, M):
    coll = cols["Leaper"]
    arm_data = bpy.data.armatures.new("Leaper_Rig")
    arm_data.display_type = "STICK"
    arm = bpy.data.objects.new("Leaper_Rig", arm_data)
    coll.objects.link(arm)
    view_layer = bpy.context.view_layer
    view_layer.update()              # make sure the new objects have view-layer bases
    for ob in view_layer.objects:
        if ob is not None:
            ob.select_set(False)
    view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones
    body = eb.new("body")
    body.head, body.tail = lv((0, -1.0, 0)), lv((0, 1.0, 0))
    head = eb.new("head")
    head.head, head.tail = lv(HEAD_BONE[0]), lv(HEAD_BONE[1])
    head.parent = body
    poles = {}
    for name, (hip, knee, foot, _) in LEGS.items():
        hip, knee, foot = lv(hip), lv(knee), lv(foot)
        n = (knee - hip).cross(foot - knee).normalized()
        f = eb.new("femur." + name)
        f.head, f.tail, f.parent = hip, knee, body
        t = eb.new("tibia." + name)
        t.head, t.tail, t.parent = knee, foot, f
        t.use_connect = True
        f.align_roll(n)
        t.align_roll(n)
        # angle for a pole lying in the rest bend plane -> the knee then
        # points straight at whichever pole location we choose
        in_plane = knee + (knee - (hip + foot) / 2).normalized() * 4.0
        poles[name] = pole_angle(hip, knee, foot, in_plane, f.x_axis.copy())
    bpy.ops.object.mode_set(mode="OBJECT")

    feet = {}
    for name, (_, _, foot, _) in LEGS.items():
        tgt = new_empty("Leaper_IK_" + name, coll, lv(foot), 0.4, "SPHERE")
        pole = new_empty("Leaper_Pole_" + name, coll, pole_point(name), 0.3, "CONE")
        pole.parent = arm          # knees keep pointing up/out as the body moves
        if name == "FR":
            for f, reach in ((REACH_POLE_F[0], False), (REACH_POLE_F[1], True)):
                pole.location = pole_point(name, reach)
                pole.keyframe_insert("location", frame=f)
        feet[name] = tgt
        ik = arm.pose.bones["tibia." + name].constraints.new("IK")
        ik.target = tgt
        ik.pole_target = pole
        ik.pole_angle = poles[name]
        ik.chain_count = 2
        ik.use_stretch = False
    arm.pose.bones["head"].rotation_mode = "XYZ"

    groups = ["body", "head"] + ["%s.%s" % (b, n) for n in LEGS for b in ("femur", "tibia")]
    sk = Skin(groups)
    leaper_geometry(sk)
    bmesh.ops.scale(sk.bm, vec=(LEAPER_SCALE,) * 3, verts=sk.bm.verts)
    mesh = mesh_obj("Leaper_Body", sk.bm, coll, [M[m] for m in LEAPER_MATS], rest=(0, 0, 0))
    for g in groups:
        mesh.vertex_groups.new(name=g)
    add_bevel(mesh, 0.018, 2, 40)
    mod = mesh.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    mesh.parent = arm

    # Lights riding on the head bone: searchlight + glow, plus the core vent
    hb = arm_data.bones["head"]
    tail_m = hb.matrix_local @ Matrix.Translation((0, hb.length, 0))

    def on_head(ob, local_matrix):
        ob.parent = arm
        ob.parent_type = "BONE"
        ob.parent_bone = "head"
        ob.matrix_parent_inverse = tail_m.inverted()
        ob.matrix_basis = local_matrix

    eye_pos = lv((0, 2.48, 0.06))        # just in front of the lens surface
    spot = bpy.data.lights.new("Leaper_Searchlight", "SPOT")
    spot.energy = 2600.0
    spot.color = (1.0, 0.1, 0.03)
    spot.spot_size = math.radians(38)
    spot.spot_blend = 0.55
    spot.shadow_soft_size = 0.12
    spot_ob = bpy.data.objects.new("Leaper_Searchlight", spot)
    coll.objects.link(spot_ob)
    aim = Vector((0, 1, -0.03)).to_track_quat("-Z", "Y").to_matrix().to_4x4()
    on_head(spot_ob, Matrix.Translation(eye_pos) @ aim)
    glow = bpy.data.lights.new("Leaper_EyeGlow", "POINT")
    glow.energy = 120.0
    glow.color = (1.0, 0.12, 0.03)
    glow.shadow_soft_size = 0.25
    glow_ob = bpy.data.objects.new("Leaper_EyeGlow", glow)
    coll.objects.link(glow_ob)
    on_head(glow_ob, Matrix.Translation(eye_pos + Vector((0, 0.1, 0))))
    core = bpy.data.lights.new("Leaper_CoreGlow", "POINT")
    core.energy = 35.0
    core.color = (1.0, 0.4, 0.08)
    core.shadow_soft_size = 0.2
    core_ob = bpy.data.objects.new("Leaper_CoreGlow", core)
    coll.objects.link(core_ob)
    core_ob.parent = arm
    core_ob.location = lv((0, -2.45, 0.05))
    return dict(arm=arm, feet=feet, mesh=mesh, spot=spot_ob)


# ---- Leaper choreography ----------------------------------------------------
def S(x, y, lift=0.0):
    return Vector((x, y, sand_height(x, y) - 0.05 + lift))


REACH_POLE_F = (232, 240)
LEAP_FROM = Vector((-24.5, -12.0, 16.2))
LEAP_TO = Vector((0.4, -6.2, 3.0))
LEAP_ARC = 2.5

BODY = Track([
    (LAND_F, (LEAP_TO, Vector((-12, 0, 0)))),
    (31, (Vector((0.4, -6.0, 2.35)), Vector((-6, 0, 0))), "o"),
    (38, (Vector((0.4, -5.7, 3.6)), Vector((0, 0, 0)))),
    (46, (Vector((0.3, -4.5, 4.3)), Vector((10, 2, 0)))),
    (52, (Vector((0.3, -4.1, 4.65)), Vector((18, 3, 0)))),
    (56, (Vector((0.2, -3.6, 4.4)), Vector((8, -2, 0))), "i"),
    (62, (Vector((0.25, -3.9, 4.6)), Vector((12, 0, 0)))),
    (67, (Vector((0.3, -4.0, 4.7)), Vector((18, 4, 0)))),
    (72, (Vector((0.35, -3.45, 4.4)), Vector((6, -6, 0))), "i"),
    (80, (Vector((0.3, -3.7, 4.6)), Vector((12, -2, 0)))),
    (92, (Vector((0.2, -4.0, 4.8)), Vector((20, 3, 0)))),
    (98, (Vector((0.15, -3.35, 4.5)), Vector((5, 6, 0))), "i"),
    (108, (Vector((0.2, -3.5, 4.5)), Vector((8, 0, 0)))),
    (120, (Vector((0.2, -3.4, 4.4)), Vector((6, 0, 0)))),
    (132, (Vector((0.2, -3.0, 4.3)), Vector((2, 0, 0)))),
    (138, (Vector((0.15, -3.2, 4.4)), Vector((6, 0, 0)))),
    (146, (Vector((0.1, -4.4, 5.0)), Vector((22, 0, 0))), "o"),
    (156, (Vector((0.1, -4.0, 4.6)), Vector((10, 0, 0)))),
    (168, (Vector((0.15, -3.3, 4.4)), Vector((0, 0, 0)))),
    (180, (Vector((0.2, -2.6, 4.25)), Vector((-6, 0, 0)))),
    (200, (Vector((0.25, -2.35, 4.2)), Vector((-8, 0, 0)))),
    (228, (Vector((0.3, -2.2, 4.2)), Vector((-8, 0, 0)))),
    (240, (Vector((-0.1, -5.0, 4.6)), Vector((2, 3, 0)))),
    (246, (Vector((-0.1, -4.75, 4.3)), Vector((-6, 5, 0))), "i"),
    (262, (Vector((-0.1, -4.45, 4.35)), Vector((-6, 4, 0)))),
    (272, (Vector((-0.1, -5.6, 4.3)), Vector((-4, 3, 0)))),
    (280, (Vector((0.0, -4.1, 4.3)), Vector((-9, 6, 0))), "i"),
    (288, (Vector((0.0, -4.15, 4.33)), Vector((-8, 5, 0)))),
])

HEAD = Track([  # (pitch, yaw) of the head bone in degrees; +yaw looks to the Leaper's left
    (1, Vector((0, 0))), (LAND_F, Vector((-10, 0))), (40, Vector((-4, 6))),
    (50, Vector((-8, -4))), (60, Vector((-6, 4))), (90, Vector((-6, -3))),
    (150, Vector((4, 0))), (168, Vector((0, 0))), (176, Vector((-6, 24))),
    (186, Vector((-8, -16)), "o"), (194, Vector((-10, -20))), (228, Vector((-12, -22))),
    (246, Vector((-14, -24))), (288, Vector((-16, -24))),
])

FOOT_KEYS = {
    "FL": [(LAND_F, S(-3.0, -2.9)), (44, S(-3.0, -2.9)), (48, Vector((-2.2, -2.2, 5.5))),
           (52, Vector((-1.7, -1.6, 6.9))), (56, Vector((-1.0, 0.25, 4.6)), "i"),
           (58, Vector((-1.0, 0.35, 4.55))), (64, Vector((-2.0, -1.2, 5.6)), "o"),
           (70, Vector((-2.6, -0.28, FLOOR2 + 0.02))), (90, Vector((-2.6, -0.28, FLOOR2 + 0.02))),
           (94, Vector((-1.4, -2.0, 6.8))), (98, Vector((-0.3, 0.3, 5.3)), "i"),
           (100, Vector((-0.3, 0.4, 5.25))), (106, Vector((-2.0, -1.0, 5.6)), "o"),
           (116, Vector((-2.3, -0.9, 5.2))), (126, Vector((-2.0, -0.5, 5.2))),
           (132, Vector((-1.3, 0.55, 4.5))), (138, Vector((-1.3, 0.6, 4.45))),
           (146, Vector((-3.2, -1.6, 5.6)), "o"), (154, Vector((-2.6, -1.4, 4.4))),
           (164, Vector((-4.6, -0.27, FLOOR2 + 0.02))), (288, Vector((-4.6, -0.27, FLOOR2 + 0.02)))],
    "FR": [(LAND_F, S(3.6, -2.7)), (40, S(3.6, -2.7)), (44, Vector((3.2, -1.6, 4.0))),
           (48, Vector((2.6, -0.28, FLOOR2 + 0.02))), (62, Vector((2.6, -0.28, FLOOR2 + 0.02))),
           (66, Vector((1.8, -1.9, 6.7))), (72, Vector((0.7, 0.3, 4.2)), "i"),
           (74, Vector((0.7, 0.4, 4.15))), (80, Vector((2.2, -1.0, 5.6)), "o"),
           (88, Vector((2.7, -0.28, FLOOR2 + 0.02))), (116, Vector((2.7, -0.28, FLOOR2 + 0.02))),
           (122, Vector((2.4, -0.9, 5.6))), (132, Vector((1.25, 0.55, 4.3))),
           (138, Vector((1.25, 0.6, 4.25))), (146, Vector((3.1, -1.6, 5.3)), "o"),
           (156, Vector((2.5, -1.5, 4.4))), (166, Vector((4.6, -0.27, FLOOR2 + 0.02))),
           (232, Vector((4.6, -0.27, FLOOR2 + 0.02))), (240, Vector((1.6, -1.8, 5.1))),
           (246, STABS[0]["p"] + Vector((0, 0, 0.02)), "i"), (250, STABS[0]["p"] + Vector((0, 0, 0.02))),
           (262, Vector((2.0, 5.2, FLOOR2 + 0.02))), (272, Vector((1.9, 3.5, 3.8)), "o"),
           (280, STABS[1]["p"] + Vector((0, 0, 0.02)), "i"), (288, STABS[1]["p"] + Vector((0, 0, 0.02)))],
    "RL": [(LAND_F, S(-3.3, -9.8)), (32, S(-3.3, -9.8)), (35, S(-3.1, -8.6, 1.3)),
           (39, S(-2.9, -7.2)), (168, S(-2.9, -7.2)), (172, S(-2.9, -6.1, 1.2)),
           (177, S(-2.8, -5.0)), (230, S(-2.8, -5.0)), (234, S(-2.9, -6.4, 1.2)),
           (238, S(-3.0, -7.8)), (288, S(-3.0, -7.8))],
    "RR": [(LAND_F, S(3.8, -9.6)), (34, S(3.8, -9.6)), (37, S(3.6, -8.4, 1.3)),
           (41, S(3.3, -7.0)), (176, S(3.3, -7.0)), (180, S(3.2, -6.0, 1.2)),
           (185, S(3.1, -4.9)), (232, S(3.1, -4.9)), (236, S(3.2, -6.2, 1.2)),
           (240, S(3.3, -7.6)), (288, S(3.3, -7.6))],
}
FOOT_TRACKS = {k: Track(v) for k, v in FOOT_KEYS.items()}


def leaper_body(f):
    """Body location and rotation (degrees) at frame f, flight arc included."""
    if f <= LAND_F:
        t = (f - FRAME_START) / float(LAND_F - FRAME_START)
        p = LEAP_FROM.lerp(LEAP_TO, t)
        p.z += 4.0 * LEAP_ARC * t * (1.0 - t)
        rot = Vector((_lerp(20.0, -12.0, t), 0.0, _lerp(-65.0, 0.0, smoothstep(t * 1.15))))
        return p, rot
    loc, rot = BODY(f)
    loc = loc + Vector((0.03 * nz(f * 0.07, 1), 0.03 * nz(f * 0.07, 2), 0.04 * nz(f * 0.09, 3)))
    return loc, rot


def body_matrix(f):
    loc, rot = leaper_body(f)
    return Matrix.Translation(loc) @ rad3(rot).to_matrix().to_4x4()


def foot_position(leg, f):
    planted = FOOT_TRACKS[leg](f)
    tuck = body_matrix(f) @ lv(LEGS[leg][3])
    if f <= LAND_F - 6:
        return tuck
    if f < LAND_F:
        return tuck.lerp(planted, smoothstep((f - (LAND_F - 6)) / 6.0))
    return planted


LOCK_ON = Track([(1, 0.0), (182, 0.0), (190, 1.0, "o"), (288, 1.0)])   # head tracks the Raider


def head_angles(f):
    """Head pitch/yaw (degrees): keyed scan, blended into a lock-on that aims
    the eye (and its searchlight) at the Raider's chest."""
    pitch, yaw = HEAD(f)
    w = LOCK_ON(f)
    if w > 0:
        x, y, _ = RAIDER_ROOT(f)
        target = Vector((x, y, FLOOR2 + 0.75))
        m = body_matrix(f)
        local = m.inverted() @ target - lv(HEAD_BONE[0])
        lyaw = math.degrees(math.atan2(-local.x, local.y))
        lpitch = math.degrees(math.atan2(local.z, math.hypot(local.x, local.y)))
        pitch, yaw = _lerp(pitch, lpitch, w), _lerp(yaw, lyaw, w)
    return pitch, yaw


def animate_leaper(rig):
    arm, feet = rig["arm"], rig["feet"]
    head = arm.pose.bones["head"]
    for f in range(FRAME_START, FRAME_END + 1):
        loc, rot = leaper_body(f)
        arm.location = loc
        arm.rotation_euler = rad3(rot)
        arm.keyframe_insert("location", frame=f)
        arm.keyframe_insert("rotation_euler", frame=f)
        for leg, tgt in feet.items():
            tgt.location = foot_position(leg, f)
            tgt.keyframe_insert("location", frame=f)
        pitch, yaw = head_angles(f)
        twitch = 1.5 * nz(f * 0.35, 9)
        head.rotation_euler = Euler((math.radians(pitch + twitch), 0.0, math.radians(yaw + twitch)))
        head.keyframe_insert("rotation_euler", frame=f)


# =============================================================================
# The Raider: a jointed puppet built from primitives
# =============================================================================
RAIDER_JOINTS = [
    ("hips", None, (0.0, 0.0, 0.95)),
    ("spine", "hips", (0.0, 0.0, 1.05)),
    ("chest", "spine", (0.0, 0.0, 1.27)),
    ("neck", "chest", (0.0, -0.01, 1.5)),
    ("head", "neck", (0.0, -0.01, 1.58)),
    ("upperarm.L", "chest", (0.21, 0.0, 1.45)),
    ("forearm.L", "upperarm.L", (0.21, 0.0, 1.16)),
    ("hand.L", "forearm.L", (0.21, 0.0, 0.91)),
    ("upperarm.R", "chest", (-0.21, 0.0, 1.45)),
    ("forearm.R", "upperarm.R", (-0.21, 0.0, 1.16)),
    ("hand.R", "forearm.R", (-0.21, 0.0, 0.91)),
    ("thigh.L", "hips", (0.1, 0.0, 0.92)),
    ("shin.L", "thigh.L", (0.1, 0.0, 0.49)),
    ("foot.L", "shin.L", (0.1, 0.0, 0.08)),
    ("thigh.R", "hips", (-0.1, 0.0, 0.92)),
    ("shin.R", "thigh.R", (-0.1, 0.0, 0.49)),
    ("foot.R", "shin.R", (-0.1, 0.0, 0.08)),
]
RAIDER_MATS = ("jacket", "pants", "gear", "canvas", "bedroll", "helmet", "skin", "boots",
               "glass", "metal", "lens", "arc_light")
JK, PA, GE, CA, BR, HE, SK, BO, GL, ME, LE, RL_ = range(12)


def raider_part(joint, bm):
    """Geometry in the joint's local space (character faces -Y, Z up)."""
    side = 1.0 if joint.endswith(".L") else -1.0
    base = joint.split(".")[0]
    if base == "hips":
        bm_sphere(bm, (0, 0.0, -0.03), 0.17, scale=(1.0, 0.78, 0.72), mat=PA)
        bm_cyl(bm, (0, 0, 0.01), (0, 0, 0.07), 0.168, squash=(1, 0.8), segs=20, mat=GE)
        for sx in (-1, 1):
            bm_box(bm, (sx * 0.16, -0.05, 0.0), (0.06, 0.09, 0.1), mat=GE)
        bm_box(bm, (0.0, 0.15, 0.0), (0.16, 0.06, 0.1), mat=GE)
    elif base == "spine":
        bm_cyl(bm, (0, 0, 0.0), (0, 0, 0.24), 0.15, 0.165, squash=(1, 0.74), segs=20, mat=JK)
    elif base == "chest":
        bm_cyl(bm, (0, 0, -0.02), (0, 0, 0.2), 0.17, 0.2, squash=(1, 0.68), segs=20, mat=JK)
        for sx in (-1, 1):
            bm_sphere(bm, (sx * 0.2, 0, 0.17), 0.075, mat=JK)
        bm_cyl(bm, (0, 0, 0.18), (0, 0, 0.28), 0.125, 0.105, segs=16, mat=BR)
        bm_box(bm, (0, -0.135, 0.06), (0.3, 0.05, 0.22), mat=GE)
        for sx in (-0.085, 0.0, 0.085):
            bm_box(bm, (sx, -0.17, 0.05), (0.065, 0.035, 0.12), mat=GE)
        bm_box(bm, (0, 0.25, 0.05), (0.42, 0.25, 0.56), mat=CA)
        bm_box(bm, (0, 0.25, 0.32), (0.44, 0.27, 0.07), mat=CA)
        bm_box(bm, (0, 0.385, -0.02), (0.3, 0.04, 0.26), mat=GE)
        bm_cyl(bm, (-0.25, 0.27, 0.45), (0.25, 0.27, 0.45), 0.095, segs=14, mat=BR)
        for sx in (-1, 1):
            bm_box(bm, (sx * 0.25, 0.24, -0.06), (0.07, 0.18, 0.26), mat=GE)
        bm_cyl(bm, (0.15, 0.33, 0.3), (0.2, 0.39, 1.05), 0.007, segs=6, mat=GE)
        bm_sphere(bm, (0.2, 0.39, 1.05), 0.014, mat=RL_)
    elif base == "neck":
        bm_cyl(bm, (0, 0, 0), (0, 0, 0.1), 0.055, segs=12, mat=SK)
    elif base == "head":
        bm_sphere(bm, (0, -0.01, 0.11), 0.105, scale=(0.92, 1.0, 1.12), mat=SK)
        bm_dome(bm, (0, 0.005, 0.13), 0.13, scale=(1.0, 1.06, 0.95), cut=0.005, mat=HE)
        bm_cyl(bm, (0, 0.005, 0.125), (0, 0.005, 0.145), 0.138, squash=(1, 1.06), segs=24, mat=HE)
        for sx in (-1, 1):
            bm_cyl(bm, (sx * 0.045, -0.1, 0.205), (sx * 0.045, -0.135, 0.205), 0.03, segs=14, mat=GL)
            bm_cyl(bm, (sx * 0.05, -0.115, 0.04), (sx * 0.085, -0.155, 0.02), 0.028, segs=12, mat=ME)
            bm_sphere(bm, (sx * 0.035, -0.096, 0.125), 0.012, segs=8, rings=6, mat=GL)
        bm_box(bm, (0, -0.08, 0.205), (0.16, 0.03, 0.03), mat=GE)
        bm_cyl(bm, (0, -0.07, 0.06), (0, -0.14, 0.05), 0.052, 0.04, segs=14, mat=GE)
    elif base == "upperarm":
        bm_cyl(bm, (0, 0, 0.0), (0, 0, -0.29), 0.06, 0.05, segs=14, mat=JK)
        bm_box(bm, (side * 0.045, 0, -0.06), (0.03, 0.1, 0.1), mat=GE)
    elif base == "forearm":
        bm_sphere(bm, (0, 0, 0), 0.052, mat=JK)
        bm_cyl(bm, (0, 0, 0.0), (0, 0, -0.23), 0.05, 0.042, segs=14, mat=JK)
        bm_cyl(bm, (0, 0, -0.19), (0, 0, -0.25), 0.047, segs=14, mat=GE)
    elif base == "hand":
        bm_box(bm, (0, 0, -0.055), (0.08, 0.042, 0.1), mat=GE)
        bm_box(bm, (-side * 0.03, -0.03, -0.035), (0.025, 0.025, 0.06), mat=GE)
        if side < 0:  # flashlight in the right fist, pointing along the forearm
            bm_cyl(bm, (0, 0, -0.02), (0, 0, -0.17), 0.021, 0.026, segs=12, mat=ME)
            bm_cyl(bm, (0, 0, -0.17), (0, 0, -0.176), 0.024, segs=12, mat=LE)
    elif base == "thigh":
        bm_sphere(bm, (0, 0, 0), 0.085, mat=PA)
        bm_cyl(bm, (0, 0, 0.0), (0, 0, -0.43), 0.086, 0.066, segs=16, mat=PA)
        bm_box(bm, (side * 0.08, 0, -0.2), (0.03, 0.12, 0.14), mat=PA)
    elif base == "shin":
        bm_sphere(bm, (0, 0, 0), 0.066, mat=PA)
        bm_cyl(bm, (0, 0, 0.0), (0, 0, -0.41), 0.062, 0.05, segs=16, mat=PA)
        bm_box(bm, (0, -0.06, -0.03), (0.11, 0.04, 0.14), mat=GE)
        bm_cyl(bm, (0, 0, -0.26), (0, 0, -0.41), 0.058, segs=14, mat=BO)
    elif base == "foot":
        bm_box(bm, (0, -0.06, -0.035), (0.105, 0.27, 0.09), mat=BO)
        bm_box(bm, (0, -0.06, -0.075), (0.115, 0.28, 0.02), mat=GE)


def build_raider(cols, M):
    coll = cols["Raider"]
    root = new_empty("Raider", coll, (0, 0, FLOOR2), 0.3, "ARROWS")
    joints, rest = {}, {}
    for name, parent, pos in RAIDER_JOINTS:
        j = new_empty("RJ_" + name, coll, (0, 0, 0), 0.06)
        j.parent = joints[parent] if parent else root
        p = Vector(pos)
        j.location = p - (rest[parent] if parent else Vector())
        j.rotation_mode = "XYZ"
        joints[name], rest[name] = j, p
        bm = bmesh.new()
        raider_part(name, bm)
        if len(bm.verts):
            part = mesh_obj("Raider_" + name, bm, coll, [M[m] for m in RAIDER_MATS], sharp_deg=50)
            part.parent = j
    spot = bpy.data.lights.new("Raider_Flashlight", "SPOT")
    spot.energy = 70.0
    spot.color = (1.0, 0.9, 0.72)
    spot.spot_size = math.radians(32)
    spot.spot_blend = 0.6
    spot.shadow_soft_size = 0.02
    fl = bpy.data.objects.new("Raider_Flashlight", spot)
    coll.objects.link(fl)
    fl.parent = joints["hand.R"]
    fl.location = (0, 0, -0.18)
    return dict(root=root, joints=joints, rest=rest)


def _pose(hips_z, **joints):
    d = {"hips_z": hips_z}
    for k, v in joints.items():
        d[k.replace("_L", ".L").replace("_R", ".R")] = Vector(v)
    return d


SIT_LEGS = dict(thigh_L=(-113, 0, 10), shin_L=(91, 0, 0), foot_L=(34, 0, 0),
                thigh_R=(-113, 0, -10), shin_R=(91, 0, 0), foot_R=(34, 0, 0))
RAIDER_POSES = {
    "crouch": _pose(0.46, hips=(10, 0, 0), spine=(12, 0, 0), chest=(8, 0, 0), neck=(-8, 0, 0),
                    head=(-14, 0, 0), thigh_L=(-80, 0, 12), shin_L=(127, 0, 0), foot_L=(-57, 0, 0),
                    thigh_R=(-80, 0, -12), shin_R=(127, 0, 0), foot_R=(-57, 0, 0),
                    upperarm_R=(-78, 0, 12), forearm_R=(-15, 0, 0),
                    upperarm_L=(-55, 0, -22), forearm_L=(-70, 0, 0)),
    "sit_flinch": _pose(0.2, hips=(-12, 0, 0), spine=(8, 0, -10), chest=(10, 0, -15),
                        neck=(10, 0, -15), head=(15, 0, -35),
                        upperarm_R=(-125, 0, 30), forearm_R=(-100, 0, 0),
                        upperarm_L=(-105, 0, -25), forearm_L=(-105, 0, 0), **SIT_LEGS),
    "push_a": _pose(0.22, hips=(-22, 0, 0), spine=(10, 0, 0), chest=(6, 0, 0), head=(12, 0, -10),
                    thigh_L=(-75, 0, 10), shin_L=(55, 0, 0), foot_L=(40, 0, 0),
                    thigh_R=(-120, 0, -10), shin_R=(115, 0, 0), foot_R=(30, 0, 0),
                    upperarm_L=(40, -15, 0), forearm_L=(-15, 0, 0),
                    upperarm_R=(35, 15, 0), forearm_R=(-15, 0, 0)),
    "push_b": _pose(0.22, hips=(-22, 0, 0), spine=(10, 0, 0), chest=(6, 0, 0), head=(12, 0, 10),
                    thigh_L=(-120, 0, 10), shin_L=(115, 0, 0), foot_L=(30, 0, 0),
                    thigh_R=(-75, 0, -10), shin_R=(55, 0, 0), foot_R=(40, 0, 0),
                    upperarm_L=(35, -15, 0), forearm_L=(-15, 0, 0),
                    upperarm_R=(40, 15, 0), forearm_R=(-15, 0, 0)),
    "sit_cower": _pose(0.2, hips=(-12, 0, 0), spine=(16, 0, 0), chest=(12, 0, 0), neck=(-4, 0, 0),
                       head=(-6, 0, 0), upperarm_R=(-80, 0, 10), forearm_R=(-12, 0, 0),
                       upperarm_L=(-48, 0, -18), forearm_L=(-78, 0, 0), **SIT_LEGS),
    "sit_aim": _pose(0.2, hips=(-14, 0, 0), spine=(0, 0, 0), chest=(-4, 0, 0), neck=(-8, 0, 0),
                     head=(-14, 0, 0), upperarm_R=(-100, 0, 6), forearm_R=(-6, 0, 0),
                     upperarm_L=(28, -18, 0), forearm_L=(-10, 0, 0), **SIT_LEGS),
    "sit_terror": _pose(0.19, hips=(-16, 0, 0), spine=(20, 0, -8), chest=(16, 0, -12),
                        neck=(4, 0, -12), head=(-6, 0, -34),
                        thigh_L=(-122, 0, 8), shin_L=(108, 0, 0), foot_L=(30, 0, 0),
                        thigh_R=(-122, 0, -8), shin_R=(108, 0, 0), foot_R=(30, 0, 0),
                        upperarm_R=(-118, 0, 28), forearm_R=(-92, 0, 0),
                        upperarm_L=(22, -28, 0), forearm_L=(-12, 0, 0)),
}

RAIDER_POSE_KEYS = [
    (1, "crouch"), (62, "crouch"), (72, "crouch"), (76, "sit_flinch", "o"), (81, "push_a"),
    (86, "push_b"), (91, "push_a"), (96, "sit_flinch"), (100, "sit_flinch"),
    (108, "sit_cower"), (186, "sit_cower"), (194, "sit_aim", "o"), (244, "sit_aim"),
    (249, "sit_terror", "o"), (255, "push_b"), (261, "sit_terror"), (280, "sit_terror"),
    (283, "sit_flinch", "o"), (288, "sit_terror"),
]
RAIDER_ROOT = Track([  # (x, y, facing angle about Z in degrees)
    (1, Vector((1.3, 4.9, -16))), (72, Vector((1.3, 4.9, -16))),
    (78, Vector((1.35, 5.1, -17)), "o"), (96, Vector((2.2, 6.3, -22))),
    (246, Vector((2.2, 6.3, -22))), (258, Vector((2.45, 6.35, -24))), (288, Vector((2.45, 6.35, -24))),
])
FEAR = Track([(1, 0.5), (60, 0.6), (72, 1.0), (110, 0.8), (186, 0.8), (194, 1.0), (246, 1.6), (288, 1.4)])


def animate_raider(r):
    root, joints, rest = r["root"], r["joints"], r["rest"]
    pose_track = Track([(k[0], RAIDER_POSES[k[1]]) + tuple(k[2:]) for k in RAIDER_POSE_KEYS])
    for f in range(FRAME_START, FRAME_END + 1):
        x, y, ang = RAIDER_ROOT(f)
        root.location = (x, y, FLOOR2)
        root.rotation_euler = (0, 0, math.radians(ang))
        root.keyframe_insert("location", frame=f)
        root.keyframe_insert("rotation_euler", frame=f)
        pose = pose_track(f)
        fear = FEAR(f)
        breath = math.sin(f * 2 * math.pi / (FPS * (0.9 if fear > 0.9 else 1.4)))
        for name, j in joints.items():
            v = pose.get(name, Vector((0, 0, 0))).copy()
            if name in ("hand.R", "forearm.R", "head", "neck"):   # trembling
                sd = sum(map(ord, name))
                v += Vector((nz(f * 0.9, sd % 97) * 2.2, nz(f * 0.8, sd % 89) * 1.5,
                             nz(f * 0.85, sd % 83) * 2.2)) * fear
            if name == "chest":
                v.x += 2.0 * breath * fear
            j.rotation_euler = rad3(v)
            j.keyframe_insert("rotation_euler", frame=f)
        hips = joints["hips"]
        hips.location = (0.0, 0.0, pose["hips_z"])
        hips.keyframe_insert("location", frame=f)


# =============================================================================
# FX: dust puffs (volumes), sparks / gravel / ceiling dust (particles)
# =============================================================================
class FX:
    def __init__(self, cols, M):
        self.coll, self.M = cols["FX"], M
        self.rng = random.Random(SEED + 21)
        self.n = 0
        tcoll = cols["Templates"]
        bm = bmesh.new()
        bm_box(bm, (0, 0, 0), (0.01, 0.16, 0.01))    # instances align their Y axis to velocity
        self.spark = mesh_obj("TPL_Spark", bm, tcoll, [M["spark"]], smooth=False)
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.05)
        self.gravel = mesh_obj("TPL_Gravel", bm, tcoll, [M["concrete"]], smooth=False, rest=(0, 0, 0))
        bm = bmesh.new()
        bm_box(bm, (0, 0, 0), (0.12, 0.09, 0.02))
        self.shard = mesh_obj("TPL_TileShard", bm, tcoll, [M["concrete"]], smooth=False, rest=(0, 0, 3.4))
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.006)
        self.speck = mesh_obj("TPL_DustSpeck", bm, tcoll, [M["sand"]], smooth=False)
        for i, t in enumerate((self.spark, self.gravel, self.shard, self.speck)):
            t.location = (i * 2.0, 0, -60.0)      # parked under the dunes

    def puff(self, loc, f, size, drift=Vector(), life=60, dens=1.0):
        self.n += 1
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        ob = mesh_obj("FX_Dust_%03d" % self.n, bm, self.coll, [self.M["dust"]], smooth=False)
        ob.rotation_euler = [self.rng.uniform(0, 6.28) for _ in range(3)]
        keys = ((f, 0.15, 0.0, 0.0), (f + 3, 0.45, 1.0, 0.12), (f + life * 0.45, 0.85, 0.65, 0.55),
                (f + life, 1.0, 0.0, 1.0))
        for fr, s, a, m in keys:
            ob.scale = (size * s,) * 3
            ob.color = (1, 1, 1, a * dens)
            ob.location = Vector(loc) + drift * m
            ob.keyframe_insert("scale", frame=fr)
            ob.keyframe_insert("color", frame=fr)
            ob.keyframe_insert("location", frame=fr)
        key_visibility(ob, f, int(f + life + 1))
        return ob

    def burst(self, kind, loc, f, direction, count, speed=5.0, spread=3.0, life=16, size=1.0,
              gravity=1.0, radius=0.08, frames=2):
        self.n += 1
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=radius)
        em = mesh_obj("FX_%s_%03d" % (kind, self.n), bm, self.coll, [], smooth=False)
        em.location = loc
        try:
            em.show_instancer_for_render = False
            em.show_instancer_for_viewport = False
        except AttributeError:
            pass
        em.modifiers.new("Particles", "PARTICLE_SYSTEM")
        ps = em.particle_systems[-1]
        ps.seed = self.rng.randint(0, 9999)
        st = ps.settings
        st.count = count
        st.frame_end = 10000
        st.frame_start = f
        st.frame_end = f + frames
        st.lifetime = life
        st.lifetime_random = 0.5
        st.emit_from = "FACE"
        st.normal_factor = 0.6
        st.object_align_factor = tuple(Vector(direction).normalized() * speed)
        st.factor_random = spread
        st.physics_type = "NEWTON"
        st.effector_weights.gravity = gravity
        st.render_type = "OBJECT"
        st.instance_object = {"spark": self.spark, "gravel": self.gravel,
                              "shard": self.shard, "speck": self.speck}[kind]
        st.particle_size = size
        st.size_random = 0.6
        st.use_rotations = True
        st.rotation_mode = "VEL" if kind == "spark" else "GLOB_X"
        if kind != "spark":
            st.phase_factor_random = 2.0
            st.use_dynamic_rotation = True
            st.angular_velocity_mode = "RAND"
            st.angular_velocity_factor = 8.0
        for attr, val in (("drag_factor", 0.05 if kind != "speck" else 0.9),):
            if hasattr(st, attr):
                setattr(st, attr, val)
        ps.point_cache.frame_start = FRAME_START
        ps.point_cache.frame_end = FRAME_END
        return em

    def ceiling_dust(self, f, x0, x1, y0, y1, count=250):
        self.n += 1
        bm = bmesh.new()
        bm_aabb(bm, x0, x1, y0, y1, CEIL2 - 0.03, CEIL2 - 0.02)
        em = mesh_obj("FX_CeilingDust_%03d" % self.n, bm, self.coll, [], smooth=False)
        try:
            em.show_instancer_for_render = False
        except AttributeError:
            pass
        em.modifiers.new("Particles", "PARTICLE_SYSTEM")
        ps = em.particle_systems[-1]
        st = ps.settings
        st.count = count
        st.frame_end = 10000
        st.frame_start = f
        st.frame_end = f + 14
        st.lifetime = 40
        st.emit_from = "FACE"
        st.normal_factor = 0.0
        st.factor_random = 0.3
        st.effector_weights.gravity = 0.35
        st.render_type = "OBJECT"
        st.instance_object = self.speck
        st.particle_size = 1.0
        st.size_random = 0.7
        ps.point_cache.frame_start = FRAME_START
        ps.point_cache.frame_end = FRAME_END


def build_fx(cols, M):
    fx = FX(cols, M)
    rng = fx.rng
    # Landing: a ring of sand blasting outward + a shock of grit
    g = LEAP_TO.copy()
    g.z = sand_height(g.x, g.y)
    for k in range(14):
        a = 2 * math.pi * k / 14 + rng.uniform(-0.2, 0.2)
        d = Vector((math.cos(a), math.sin(a), 0))
        fx.puff(g + d * rng.uniform(1.5, 3.0) + Vector((0, 0, 0.5)), LAND_F, rng.uniform(1.2, 1.8),
                drift=d * rng.uniform(4.0, 7.0) + Vector((0, 0, 0.6)), life=55, dens=0.55)
    for _ in range(3):
        fx.puff(g + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0.6)), LAND_F + 1, 2.0,
                drift=Vector((0, 0, 1.2)), life=50, dens=0.45)
    fx.burst("gravel", g + Vector((0, 0, 0.3)), LAND_F, (0, 0, 1), 220, speed=6.0, spread=5.0,
             life=40, size=0.9, radius=1.5)
    # Feet stepping in the sand
    for leg, keys in (("RL", (39, 177)), ("RR", (41, 185)), ("FL", (LAND_F,)), ("FR", (LAND_F,))):
        for f in keys:
            p = FOOT_TRACKS[leg](f)
            fx.puff(p + Vector((0, 0, 0.3)), f, 1.0, drift=Vector((0, 0, 0.6)), life=45, dens=0.7)
    # Wall strikes: sparks outside, gravel + dust blowing into the room, dust off the ceiling
    for h in WALL_HITS:
        p, f = h["p"], h["f"]
        fx.burst("spark", p + Vector((0, -0.05, 0)), f, (0, -1, 0.6), 90, speed=7.0, spread=5.0, life=12)
        fx.burst("gravel", p + Vector((0, 0.3, 0)), f, (0, 1, 0.35), 160, speed=5.5, spread=3.0,
                 life=40, size=0.8, radius=0.4)
        for k in range(3):
            fx.puff(p + Vector((rng.uniform(-0.6, 0.6), -0.7, rng.uniform(-0.5, 0.5))), f, 1.4,
                    drift=Vector((rng.uniform(-1, 1), -1.5, 0.8)), life=55)
            fx.puff(p + Vector((rng.uniform(-0.6, 0.6), 0.9, rng.uniform(-0.6, 0.3))), f + 1, 1.5,
                    drift=Vector((rng.uniform(-1, 1), 2.5, 0.2)), life=70, dens=1.1)
        fx.ceiling_dust(f, -3.0, 3.0, 0.4, 4.5)
    # Hooks grinding on the breach edges
    for hp in HOOKS:
        fx.burst("spark", hp, HOOK_F, (0, -1, 0.5), 60, speed=5.0, spread=4.0, life=10)
    # The rip: a curtain of dust and grit
    for k in range(10):
        x = -2.4 + 4.8 * k / 9.0
        fx.puff(Vector((x, -1.0, rng.uniform(3.8, 6.0))), RIP_F + rng.randint(0, 3), rng.uniform(1.6, 2.4),
                drift=Vector((x * 0.6, -2.5, rng.uniform(-0.8, 0.4))), life=48, dens=0.8)
    fx.burst("gravel", Vector((0, -0.3, 4.9)), RIP_F, (0, -1, 0.4), 300, speed=6.0, spread=3.5,
             life=48, size=1.0, radius=1.3, frames=5)
    fx.ceiling_dust(RIP_F, -3.5, 3.5, 0.3, 5.5, count=400)
    # Stabs into the floor: sparks, tile shards, a little dust, and a crack decal
    for st in STABS:
        p, f = st["p"], st["f"]
        fx.burst("spark", p + Vector((0, 0, 0.05)), f, (0, 0, 1), 45, speed=3.5, spread=2.5, life=10)
        fx.burst("shard", p + Vector((0, 0, 0.08)), f, (0, 0, 1), 16, speed=2.2, spread=1.4,
                 life=26, size=0.45, radius=0.12)
        for k in range(3):
            fx.puff(p + Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), 0.2)), f, 0.9,
                    drift=Vector((rng.uniform(-0.8, 0.8), rng.uniform(-0.8, 0.8), 0.6)), life=50, dens=0.8)
        bm = bmesh.new()
        for k in range(7):
            a = rng.uniform(0, 2 * math.pi)
            ln = rng.uniform(0.25, 0.6)
            bm_box(bm, p + Vector((math.cos(a) * ln / 2, math.sin(a) * ln / 2, 0.003)),
                   (ln, 0.025, 0.006), rot=Euler((0, 0, a)))
        bm_cyl(bm, p + Vector((0, 0, 0.0)), p + Vector((0, 0, 0.007)), 0.16, segs=10)
        crack = mesh_obj("FX_FloorCrack_%d" % f, bm, fx.coll, [M["window"]], smooth=False)
        key_visibility(crack, f)
    return fx


# =============================================================================
# Cameras: per-shot moves, handheld noise, impact shake, marker cuts
# =============================================================================
def _gz(x, y, h):
    return Vector((x, y, sand_height(x, y) + h))


def _leaper_target(lag=2, offset=Vector((0, 0, 0.6))):
    return lambda f: leaper_body(max(FRAME_START, f - lag))[0] + offset


SHOTS = [
    dict(name="CAM_01_Exterior_Wide", start=1, end=60, fstop=8.0, shake=0.5,
         pos=Track([(1, _gz(-11.5, -18.5, 1.5)), (60, _gz(-10.0, -16.6, 1.8))]),
         target=lambda f: (_leaper_target()(f).lerp(Vector((-0.5, -1.8, 4.4)), smoothstep((f - 24) / 26.0))),
         lens=Track([(1, 22.0), (60, 27.0)])),
    dict(name="CAM_02_Interior_Corner", start=61, end=120, fstop=2.8, shake=1.0, exposure=1.3,
         pos=Track([(61, Vector((-5.0, 6.3, 4.65))), (120, Vector((-4.6, 6.2, 4.5)))]),
         target=Track([(61, Vector((1.1, 3.3, 4.2))), (120, Vector((1.2, 3.5, 4.3)))]),
         lens=Track([(61, 22.0), (120, 24.0)]), focus=Track([(61, 5.6), (95, 6.4), (120, 6.6)])),
    dict(name="CAM_03_Exterior_Rip", start=121, end=168, fstop=5.6, shake=0.8,
         pos=Track([(121, _gz(12.0, -12.5, 1.3)), (168, _gz(11.2, -11.6, 1.5))]),
         target=Track([(121, Vector((-0.4, -2.2, 4.9))), (168, Vector((-0.4, -1.8, 4.7)))]),
         lens=Track([(121, 24.0), (168, 27.0)])),
    dict(name="CAM_04_Leaper_POV", start=169, end=228, fstop=5.6, shake=0.7, exposure=0.6,
         pos=Track([(169, Vector((0.9, -2.0, 5.6))), (228, Vector((1.0, -1.6, 5.5)))]),
         target=Track([(169, Vector((1.6, 4.5, 3.4))), (190, Vector((2.0, 5.6, 3.45))),
                       (228, Vector((2.1, 6.0, 3.5)))]),
         lens=Track([(169, 26.0), (228, 32.0)]), focus=Track([(169, 10.5), (228, 10.2)])),
    dict(name="CAM_05_Floor_Level", start=229, end=268, fstop=2.8, shake=1.0, exposure=0.8,
         pos=Track([(229, Vector((0.9, 3.5, 3.85))), (268, Vector((1.0, 3.75, 3.82)))]),
         target=Track([(229, Vector((2.2, 6.2, 4.0))), (268, Vector((2.35, 6.3, 3.95)))]),
         lens=Track([(229, 24.0), (268, 24.0)]), focus=Track([(229, 2.9), (268, 2.8)])),
    dict(name="CAM_06_Raider_CloseUp", start=269, end=288, fstop=2.0, shake=1.2, exposure=0.8,
         pos=Track([(269, Vector((-0.15, 5.2, 4.05))), (288, Vector((0.05, 5.3, 4.02)))]),
         target=Track([(269, Vector((2.42, 6.3, 4.05))), (288, Vector((2.45, 6.33, 4.02)))]),
         lens=Track([(269, 40.0), (288, 46.0)]), focus=Track([(269, 2.75), (288, 2.6)])),
]


def shake_amount(f):
    a = 0.0
    for f0, s in SHAKES:
        if f >= f0:
            a += s * math.exp(-(f - f0) / 7.0)
    return a


def build_cameras(cols, scene):
    first = None
    for i, sh in enumerate(SHOTS):
        data = bpy.data.cameras.new(sh["name"])
        data.clip_start = 0.05
        data.clip_end = 600.0
        data.sensor_width = 36.0
        data.dof.use_dof = True
        data.dof.aperture_fstop = sh["fstop"]
        cam = bpy.data.objects.new(sh["name"], data)
        cols["Cameras"].objects.link(cam)
        cam.rotation_mode = "QUATERNION"
        prev = None
        for f in range(max(FRAME_START, sh["start"] - 1), min(FRAME_END, sh["end"] + 1) + 1):
            pos, tgt = sh["pos"](f), sh["target"](f)
            amp = shake_amount(f) * sh["shake"]
            hand = Vector((nz(f * 0.045, 11 + i), nz(f * 0.04, 21 + i), nz(f * 0.05, 31 + i)))
            jolt = Vector((nz(f * 0.55, 41 + i), nz(f * 0.6, 51 + i), nz(f * 0.5, 61 + i)))
            q = look_quat(pos, tgt, math.radians(1.2 * hand.z + 1.5 * amp * jolt.z))
            q = q @ Euler((math.radians(0.35 * hand.x + 1.3 * amp * jolt.x),
                           math.radians(0.35 * hand.y + 1.3 * amp * jolt.y), 0.0)).to_quaternion()
            if prev is not None and q.dot(prev) < 0:
                q.negate()
            prev = q
            cam.location = pos + jolt * (0.04 * amp)
            cam.rotation_quaternion = q
            cam.keyframe_insert("location", frame=f)
            cam.keyframe_insert("rotation_quaternion", frame=f)
            data.lens = sh["lens"](f)
            data.keyframe_insert("lens", frame=f)
            data.dof.focus_distance = sh["focus"](f) if "focus" in sh else (tgt - pos).length
            data.dof.keyframe_insert("focus_distance", frame=f)
        for f in (sh["start"], sh["end"]):
            scene.view_settings.exposure = sh.get("exposure", 0.0)
            scene.view_settings.keyframe_insert("exposure", frame=f)
        m = scene.timeline_markers.new("S%d_%s" % (i + 1, sh["name"][7:]), frame=sh["start"])
        m.camera = cam
        first = first or cam
    scene.camera = first


# =============================================================================
# Render settings
# =============================================================================
def setup_render(scene, preview, engine):
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = FRAME_START, FRAME_END
    res = PREVIEW_RESOLUTION if preview else RESOLUTION
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    if engine == "EEVEE":
        for ident in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = ident
                break
            except TypeError:
                continue
    else:
        scene.render.engine = "CYCLES"
        cy = scene.cycles
        cy.samples = PREVIEW_SAMPLES if preview else SAMPLES
        cy.use_adaptive_sampling = True
        cy.use_denoising = True
        cy.max_bounces = 6
        cy.diffuse_bounces = 3
        cy.glossy_bounces = 3
        cy.transmission_bounces = 4
        cy.volume_bounces = 1
        cy.transparent_max_bounces = 8
        cy.volume_step_rate = 4.0 if preview else 2.0
        cy.caustics_reflective = False
        cy.caustics_refractive = False
        cy.sample_clamp_indirect = 8.0
    scene.render.use_motion_blur = MOTION_BLUR
    scene.render.motion_blur_shutter = 0.5
    vs = scene.view_settings
    for vt in ("AgX", "Filmic"):
        try:
            vs.view_transform = vt
            break
        except TypeError:
            continue
    for look in ("AgX - Medium High Contrast", "AgX - Punchy", "Medium High Contrast"):
        try:
            vs.look = look
            break
        except TypeError:
            continue
    vs.exposure = 0.0
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"


# =============================================================================
# Entry point
# =============================================================================
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="arc_raiders_leaper_attack.py")
    p.add_argument("--save", help="save the generated scene to this .blend")
    p.add_argument("--preview", action="store_true", help="half resolution, low samples")
    p.add_argument("--engine", choices=("CYCLES", "EEVEE"), default="CYCLES")
    p.add_argument("--render-frames", nargs="*", type=int, default=[], help="render these frames as stills")
    p.add_argument("--render-anim", action="store_true", help="render the whole shot sequence")
    p.add_argument("--out", default=None, help="output directory for renders")
    return p.parse_args(argv)


def build(preview=False, engine="CYCLES"):
    clear_scene()
    scene = bpy.context.scene
    setup_render(scene, preview, engine)
    cols = make_collections()
    M = build_materials()
    build_world(scene)
    build_sun(cols)
    build_environment(cols, M)
    build_building(cols, M)
    chunks = build_breach_wall(cols, M)
    animate_breach(chunks)
    build_interior(cols, M)
    leaper = build_leaper(cols, M)
    animate_leaper(leaper)
    raider = build_raider(cols, M)
    animate_raider(raider)
    build_fx(cols, M)
    build_cameras(cols, scene)
    scene.frame_set(FRAME_START)
    return scene


def main():
    args = parse_args()
    scene = build(args.preview, args.engine)
    out = args.out or os.path.join(os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.getcwd(), "render")
    if args.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save), compress=True)
        print("Saved", os.path.abspath(args.save))
    if args.render_frames:
        os.makedirs(out, exist_ok=True)
        last = FRAME_START
        for f in sorted(args.render_frames):
            for step in range(last, f + 1):    # step through so particle caches stay valid
                scene.frame_set(step)
            last = f
            scene.render.filepath = os.path.join(out, "leaper_%04d" % f)
            bpy.ops.render.render(write_still=True)
            print("Rendered frame", f)
    if args.render_anim:
        os.makedirs(out, exist_ok=True)
        scene.render.filepath = os.path.join(out, "leaper_")
        bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
