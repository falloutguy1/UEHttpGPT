"""PLAY ZONE - an endless indoor play place horror short (50 s @ 24 fps).

Builds the whole scene procedurally for Blender 5.2 LTS (Cycles), saves playplace.blend
and cues.json (footstep / ball-bounce timings for the sound design).

    blender -b -y --python-exit-code 1 -P build_scene.py

Units are metres. The world is an infinite-looking grid of 12 m "blocks" (one play island
plus the aisles around it) instanced in every direction and swallowed by distance fog.
"""
import bpy, bmesh, math, random, json, os, sys
from mathutils import Vector, Matrix, Euler, Quaternion

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timeline as TL
import time as _time
_T0 = _time.time()


def log(msg):
    print(f"[{_time.time() - _T0:7.1f}s] {msg}", flush=True)


OUT_BLEND = os.path.join(HERE, "playplace.blend")
OUT_CUES = os.path.join(HERE, "cues.json")

# ----------------------------------------------------------------------------- constants
BLOCK = 12.0                 # block period (island 8 m + 4 m aisles)
CEIL_H = 3.8
LIGHT_GRID = 3.0             # troffer spacing
TROFFER_BASE = 14.0          # emission strength of a lit troffer
BLOCKS_X = range(-5, 5)      # instanced blocks (x from -60 to 60)
BLOCKS_Y = range(-4, 6)      # y from -48 to 72
EYE_H = 1.2                  # child eye height
BALL_R = 0.04
HIDE = (0.0, 0.0, -30.0)     # where the mascot waits when "not there"
FONT_PATHS = ["/usr/share/fonts/opentype/inter/Inter-Black.otf",
              "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]

# faded primary vinyl colours (linear)
RED = (0.42, 0.035, 0.03)
BLUE = (0.035, 0.09, 0.36)
YELLOW = (0.62, 0.40, 0.035)
GREEN = (0.05, 0.24, 0.07)
PURPLE = (0.16, 0.06, 0.22)

random.seed(13)

# ----------------------------------------------------------------------------- reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "PlayZone"
prefs = bpy.context.preferences.edit
if hasattr(prefs, "use_keyframe_insert_available"):
    prefs.use_keyframe_insert_available = False


def set_interp(kind):
    prefs.keyframe_new_interpolation_type = kind


def coll_new(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(c)
    return c


C_WORLD = coll_new("World_Static")
C_BLOCK = coll_new("Block_Source")
C_INST = coll_new("Block_Instances")
C_PROPS = coll_new("Props")
C_MASCOT = coll_new("Mascot")
C_CAM = coll_new("Camera_Lights")
C_TITLE = coll_new("Title_Card")


# ----------------------------------------------------------------------------- node helpers
def sock(sockets, *keys):
    """Find an enabled socket by identifier or name (5.x Mix node has several 'A' sockets)."""
    for k in keys:
        for s in sockets:
            if (s.identifier == k or s.name == k) and getattr(s, "enabled", True):
                return s
    raise KeyError(f"{keys} not in {[(s.name, s.identifier) for s in sockets]}")


class G:
    """Tiny shader-graph builder bound to one node tree."""

    def __init__(self, nt):
        self.nt = nt

    def node(self, t, **kw):
        n = self.nt.nodes.new(t)
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    def link(self, a, b):
        self.nt.links.new(a, b)

    def set(self, node, key, val):
        s = node.inputs[key] if isinstance(key, int) else sock(node.inputs, key)
        if isinstance(val, bpy.types.NodeSocket):
            self.nt.links.new(val, s)
        else:
            if s.type == 'RGBA' and len(val) == 3:
                val = (*val, 1.0)
            s.default_value = val
        return s

    def math(self, op, a, b=0.0, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(n, 0, a)
        self.set(n, 1, b)
        return n.outputs[0]

    def vmath(self, op, a, b=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.set(n, 0, a)
        if b is not None:
            self.set(n, 1, b)
        return n.outputs['Value'] if op in ('DOT_PRODUCT', 'DISTANCE', 'LENGTH') else n.outputs['Vector']

    def mix(self, fac, a, b, blend='MIX'):
        n = self.node("ShaderNodeMix", data_type='RGBA', blend_type=blend)
        self.set(n, 'Factor_Float', fac)
        self.set(n, 'A_Color', a)
        self.set(n, 'B_Color', b)
        return sock(n.outputs, 'Result_Color')

    def mixf(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type='FLOAT')
        self.set(n, 'Factor_Float', fac)
        self.set(n, 'A_Float', a)
        self.set(n, 'B_Float', b)
        return sock(n.outputs, 'Result_Float')

    def maprange(self, v, fmin, fmax, tmin=0.0, tmax=1.0, smooth=True):
        n = self.node("ShaderNodeMapRange", clamp=True)
        if smooth:
            n.interpolation_type = 'SMOOTHSTEP'
        self.set(n, 'Value', v)
        self.set(n, 'From Min', fmin)
        self.set(n, 'From Max', fmax)
        self.set(n, 'To Min', tmin)
        self.set(n, 'To Max', tmax)
        return n.outputs['Result']

    def ramp(self, fac, stops, interp='LINEAR'):
        n = self.node("ShaderNodeValToRGB")
        cr = n.color_ramp
        cr.interpolation = interp
        els = cr.elements
        els[0].position, els[0].color = stops[0][0], (*stops[0][1], 1.0)
        els[1].position, els[1].color = stops[-1][0], (*stops[-1][1], 1.0)
        for pos, col in stops[1:-1]:
            e = els.new(pos)
            e.color = (*col, 1.0)
        self.set(n, 'Fac', fac)
        return n.outputs['Color']

    def noise(self, vec=None, scale=5.0, detail=2.0, rough=0.5, dims='3D', w=None):
        n = self.node("ShaderNodeTexNoise")
        n.noise_dimensions = dims
        if vec is not None:
            self.set(n, 'Vector', vec)
        self.set(n, 'Scale', scale)
        self.set(n, 'Detail', detail)
        self.set(n, 'Roughness', rough)
        if w is not None:
            self.set(n, 'W', w)
        return n

    def white(self, vec, dims='3D', w=None):
        n = self.node("ShaderNodeTexWhiteNoise")
        n.noise_dimensions = dims
        self.set(n, 'Vector', vec)
        if w is not None:
            self.set(n, 'W', w)
        return n

    def pos(self):
        return self.node("ShaderNodeNewGeometry").outputs['Position']

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self.link(v, n.inputs[0])
        return n.outputs['X'], n.outputs['Y'], n.outputs['Z']

    def comb(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        self.set(n, 'X', x)
        self.set(n, 'Y', y)
        self.set(n, 'Z', z)
        return n.outputs[0]

    def bump(self, height, strength=0.2, distance=0.01, normal=None):
        n = self.node("ShaderNodeBump")
        self.set(n, 'Height', height)
        self.set(n, 'Strength', strength)
        self.set(n, 'Distance', distance)
        if normal is not None:
            self.set(n, 'Normal', normal)
        return n.outputs['Normal']

    def principled(self, base, rough=0.5, **inputs):
        n = self.node("ShaderNodeBsdfPrincipled")
        self.set(n, 'Base Color', base)
        self.set(n, 'Roughness', rough)
        for k, v in inputs.items():
            self.set(n, k, v)
        return n

    def output(self, shader):
        o = self.node("ShaderNodeOutputMaterial")
        self.link(shader.outputs[0] if hasattr(shader, "outputs") else shader, o.inputs['Surface'])
        return o


def new_mat(name):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    m.node_tree.nodes.clear()
    return m, G(m.node_tree)


# ----------------------------------------------------------------------------- materials
def mat_floor():
    m, g = new_mat("M_FloorMats")
    p = g.pos()
    tile = g.vmath('FLOOR', p)
    wn = g.white(tile)
    col = g.ramp(wn.outputs['Value'], [(0.0, RED), (0.25, BLUE), (0.5, YELLOW), (0.75, GREEN)], 'CONSTANT')
    # per-tile fading
    fade = g.maprange(sock(wn.outputs, 'Color'), 0.0, 1.0, 0.75, 1.05, smooth=False)
    col = g.mix(1.0, col, g.comb(fade, fade, fade), 'MULTIPLY')
    # seams between the 1 m interlocking foam tiles
    fx, fy, _ = g.sep(g.vmath('FRACTION', p))
    e = g.math('MINIMUM', g.math('MINIMUM', fx, g.math('SUBTRACT', 1.0, fx)),
               g.math('MINIMUM', fy, g.math('SUBTRACT', 1.0, fy)))
    seam = g.maprange(e, 0.0, 0.012)
    col = g.mix(seam, (0.015, 0.015, 0.015), col)
    # grime: big blotches + scuffs
    grime_n = g.noise(p, scale=0.35, detail=5.0, rough=0.6)
    grime = g.maprange(grime_n.outputs['Fac'], 0.45, 0.72)
    scuff = g.maprange(g.noise(p, scale=7.0, detail=3.0).outputs['Fac'], 0.55, 0.75)
    dirt = g.math('MAXIMUM', g.math('MULTIPLY', grime, 0.6), g.math('MULTIPLY', scuff, 0.35))
    col = g.mix(dirt, col, (0.05, 0.045, 0.035))
    rough = g.math('ADD', 0.5, g.math('MULTIPLY', dirt, 0.3))
    fine = g.noise(p, scale=220.0, detail=1.0).outputs['Fac']
    height = g.math('ADD', seam, g.math('MULTIPLY', fine, 0.15))
    nrm = g.bump(height, strength=0.3, distance=0.004)
    bsdf = g.principled(col, rough, **{'Normal': nrm, 'Specular IOR Level': 0.4})
    g.output(bsdf)
    return m


def mat_ceiling():
    m, g = new_mat("M_CeilingTiles")
    p = g.vmath('ADD', g.pos(), (0.0, 0.3, 0.0))
    fx, fy, _ = g.sep(g.vmath('FRACTION', g.vmath('DIVIDE', p, (0.6, 0.6, 0.6))))
    e = g.math('MINIMUM', g.math('MINIMUM', fx, g.math('SUBTRACT', 1.0, fx)),
               g.math('MINIMUM', fy, g.math('SUBTRACT', 1.0, fy)))
    grid = g.maprange(e, 0.012, 0.03)
    stain_n = g.noise(p, scale=0.22, detail=6.0, rough=0.65)
    stain = g.maprange(stain_n.outputs['Fac'], 0.58, 0.74)
    base = g.mix(stain, (0.40, 0.385, 0.34), (0.20, 0.13, 0.055))
    col = g.mix(grid, (0.16, 0.16, 0.15), base)
    fine = g.noise(p, scale=160.0, detail=0.0).outputs['Fac']
    nrm = g.bump(g.math('ADD', grid, g.math('MULTIPLY', fine, 0.3)), strength=0.25, distance=0.004)
    g.output(g.principled(col, 0.85, **{'Normal': nrm}))
    return m


def mat_troffer():
    """Fluorescent panel. Emission is driven per panel by world position so the lights can
    switch on in a wave, fail row by row, and flicker - all from a few keyed Value nodes."""
    m, g = new_mat("M_Troffer")
    m.cycles.emission_sampling = 'FRONT'
    p = g.pos()
    snap = g.vmath('MULTIPLY', g.vmath('ADD', g.vmath('FLOOR', g.vmath('DIVIDE', p, (LIGHT_GRID,) * 3)),
                                       (0.5, 0.5, 0.5)), (LIGHT_GRID,) * 3)
    sx, sy, _ = g.sep(snap)
    flat = g.comb(sx, sy, 0.0)
    ctl = {}
    for name, val in (("CTL_Ron", 1000.0), ("CTL_Front", 1e5), ("CTL_Flicker", 0.0),
                      ("CTL_Global", 1.0), ("CTL_Time", 1.0)):
        n = g.node("ShaderNodeValue", name=name, label=name)
        n.outputs[0].default_value = val
        ctl[name] = n
    cx, cy = TL.LIGHTS_ON_CENTER
    d = g.vmath('DISTANCE', flat, (cx, cy, 0.0))
    on1 = g.math('LESS_THAN', d, ctl["CTL_Ron"].outputs[0])
    on2 = g.math('LESS_THAN', sy, ctl["CTL_Front"].outputs[0])
    t12 = g.math('FLOOR', g.math('MULTIPLY', ctl["CTL_Time"].outputs[0], 0.5))
    rnd = g.white(snap, '4D', t12).outputs['Value']
    on3 = g.math('GREATER_THAN', rnd, ctl["CTL_Flicker"].outputs[0])
    h = g.white(g.vmath('ADD', snap, (13.1, 7.7, 0.0))).outputs['Value']
    dying = g.math('LESS_THAN', h, 0.045)
    t8 = g.math('FLOOR', g.math('DIVIDE', ctl["CTL_Time"].outputs[0], 3.0))
    drop = g.math('LESS_THAN', g.white(snap, '4D', g.math('ADD', t8, 100.0)).outputs['Value'], 0.5)
    on4 = g.math('SUBTRACT', 1.0, g.math('MULTIPLY', g.math('MULTIPLY', dying, drop), 0.92))
    s = g.math('MULTIPLY', g.math('MULTIPLY', on1, on2), g.math('MULTIPLY', on3, on4))
    s = g.math('MULTIPLY', g.math('MULTIPLY', s, ctl["CTL_Global"].outputs[0]), TROFFER_BASE)
    # old tubes drift in colour; dimmer near the panel edges
    h2 = g.white(g.vmath('ADD', snap, (3.3, 1.9, 0.0))).outputs['Value']
    col = g.mix(h2, (0.80, 1.0, 0.86), (1.0, 0.93, 0.76))
    lx, ly, _ = g.sep(g.vmath('FRACTION', g.vmath('DIVIDE', p, (LIGHT_GRID,) * 3)))
    edge = g.math('MULTIPLY', g.maprange(g.math('ABSOLUTE', g.math('SUBTRACT', lx, 0.5)), 0.1, 0.03, 0.55, 1.0),
                  g.maprange(g.math('ABSOLUTE', g.math('SUBTRACT', ly, 0.5)), 0.2, 0.1, 0.6, 1.0))
    s = g.math('MULTIPLY', s, edge)
    bsdf = g.principled((0.7, 0.72, 0.68), 0.4, **{'Emission Color': col, 'Emission Strength': s})
    g.output(bsdf)
    return m, ctl


def mat_vinyl(name, rgb, rough=0.34):
    m, g = new_mat(name)
    p = g.pos()
    wr = g.noise(p, scale=3.5, detail=6.0, rough=0.55).outputs['Fac']
    gr = g.maprange(g.noise(p, scale=1.6, detail=4.0).outputs['Fac'], 0.5, 0.72)
    _, _, z = g.sep(p)
    low = g.maprange(z, 0.35, 0.0)      # scuffed near the floor
    dirt = g.math('MAXIMUM', g.math('MULTIPLY', gr, 0.45), g.math('MULTIPLY', low, 0.4))
    col = g.mix(dirt, rgb, (0.05, 0.04, 0.03))
    nrm = g.bump(wr, strength=0.12, distance=0.02)
    bsdf = g.principled(col, g.math('ADD', rough, g.math('MULTIPLY', dirt, 0.3)),
                        **{'Normal': nrm, 'Coat Weight': 0.25, 'Coat Roughness': 0.3})
    g.output(bsdf)
    return m


def mat_plastic(name, rgb, rough=0.22):
    m, g = new_mat(name)
    p = g.pos()
    sc = g.maprange(g.noise(p, scale=9.0, detail=4.0).outputs['Fac'], 0.55, 0.75)
    col = g.mix(g.math('MULTIPLY', sc, 0.4), rgb, (0.08, 0.07, 0.05))
    scratch = g.noise(p, scale=60.0, detail=2.0).outputs['Fac']
    nrm = g.bump(scratch, strength=0.05, distance=0.003)
    g.output(g.principled(col, g.math('ADD', rough, g.math('MULTIPLY', sc, 0.25)),
                          **{'Normal': nrm, 'Coat Weight': 0.3}))
    return m


def mat_simple(name, rgb, rough=0.5, metallic=0.0, **extra):
    m, g = new_mat(name)
    g.output(g.principled(rgb, rough, **{'Metallic': metallic, **extra}))
    return m


def mat_emit(name, rgb, strength):
    m, g = new_mat(name)
    em = g.node("ShaderNodeEmission")
    g.set(em, 'Color', rgb)
    g.set(em, 'Strength', strength)
    g.output(em)
    return m, em


def mat_balls():
    m, g = new_mat("M_PitBalls")
    a = g.node("ShaderNodeAttribute", attribute_name="ball_rand", attribute_type='GEOMETRY')
    col = g.ramp(a.outputs['Fac'], [(0.0, (0.55, 0.03, 0.03)), (0.27, (0.75, 0.52, 0.03)),
                                     (0.52, (0.03, 0.12, 0.55)), (0.76, (0.05, 0.35, 0.08)),
                                     (0.94, (0.55, 0.35, 0.40))], 'CONSTANT')
    gr = g.maprange(g.noise(g.pos(), scale=1.2, detail=3.0).outputs['Fac'], 0.5, 0.7)
    col = g.mix(g.math('MULTIPLY', gr, 0.4), col, (0.06, 0.05, 0.04))
    g.output(g.principled(col, 0.28, **{'Coat Weight': 0.4, 'Coat Roughness': 0.15}))
    return m


def mat_pitfill():
    m, g = new_mat("M_PitDepths")
    n = g.noise(g.pos(), scale=28.0, detail=1.0)
    col = g.ramp(n.outputs['Fac'], [(0.3, (0.05, 0.004, 0.004)), (0.45, (0.06, 0.04, 0.004)),
                                     (0.6, (0.004, 0.015, 0.06)), (0.72, (0.006, 0.04, 0.01))], 'CONSTANT')
    g.output(g.principled(col, 0.4))
    return m


def mat_fur():
    m, g = new_mat("M_MascotFur")
    p = g.pos()
    clump = g.noise(p, scale=45.0, detail=4.0, rough=0.7).outputs['Fac']
    stain = g.maprange(g.noise(p, scale=2.2, detail=5.0).outputs['Fac'], 0.5, 0.68)
    base = g.mix(g.math('MULTIPLY', clump, 0.35), (0.13, 0.055, 0.17), (0.07, 0.03, 0.08))
    col = g.mix(g.math('MULTIPLY', stain, 0.7), base, (0.06, 0.045, 0.02))
    nrm = g.bump(clump, strength=0.45, distance=0.01)
    g.output(g.principled(col, 0.9, **{'Normal': nrm, 'Sheen Weight': 0.8, 'Sheen Roughness': 0.4,
                                       'Specular IOR Level': 0.25}))
    return m


def mat_head():
    m, g = new_mat("M_MascotHead")
    p = g.pos()
    vor = g.node("ShaderNodeTexVoronoi", feature='DISTANCE_TO_EDGE')
    g.set(vor, 'Vector', p)
    g.set(vor, 'Scale', 7.0)
    crack = g.maprange(vor.outputs['Distance'], 0.0, 0.02, 1.0, 0.0)
    crack = g.math('MULTIPLY', crack, g.maprange(g.noise(p, scale=3.0).outputs['Fac'], 0.5, 0.62))
    grime = g.maprange(g.noise(p, scale=4.0, detail=6.0).outputs['Fac'], 0.45, 0.75)
    col = g.mix(g.math('MULTIPLY', grime, 0.55), (0.62, 0.52, 0.38), (0.16, 0.11, 0.06))
    col = g.mix(crack, col, (0.04, 0.03, 0.02))
    nrm = g.bump(g.math('SUBTRACT', 1.0, crack), strength=0.3, distance=0.005)
    g.output(g.principled(col, g.math('ADD', 0.35, g.math('MULTIPLY', grime, 0.35)),
                          **{'Normal': nrm, 'Coat Weight': 0.2}))
    return m


def mat_hat():
    m, g = new_mat("M_PartyHat")
    w = g.node("ShaderNodeTexWave", wave_type='BANDS', bands_direction='Z')
    g.set(w, 'Vector', g.node("ShaderNodeTexCoord").outputs['Object'])
    g.set(w, 'Scale', 3.0)
    col = g.ramp(w.outputs['Fac'], [(0.0, (0.45, 0.04, 0.05)), (0.5, (0.6, 0.55, 0.45))], 'CONSTANT')
    g.output(g.principled(col, 0.5))
    return m


def mat_title(name, rgb):
    m, em = mat_emit(name, rgb, 0.0)
    return m, em


log('start materials')
MAT = {}
MAT['floor'] = mat_floor()
MAT['ceiling'] = mat_ceiling()
MAT['troffer'], CTL = mat_troffer()
MAT['troffer_frame'] = mat_simple("M_TrofferFrame", (0.45, 0.45, 0.42), 0.4)
for k, c in (('red', RED), ('blue', BLUE), ('yellow', YELLOW), ('green', GREEN), ('purple', PURPLE)):
    MAT['v_' + k] = mat_vinyl("M_Vinyl_" + k.title(), c)
MAT['steel'] = mat_vinyl("M_PaintedSteel", (0.42, 0.42, 0.40), rough=0.5)
MAT['net'] = mat_simple("M_Netting", (0.012, 0.012, 0.014), 0.6)
MAT['tube'] = mat_plastic("M_Plastic_TubeYellow", (0.7, 0.42, 0.03))
MAT['slide'] = mat_plastic("M_Plastic_SlideRed", (0.5, 0.03, 0.03))
MAT['balls'] = mat_balls()
MAT['pitfill'] = mat_pitfill()
MAT['board'] = mat_simple("M_SignBoard", (0.55, 0.54, 0.5), 0.55)
MAT['cable'] = mat_simple("M_Cable", (0.05, 0.05, 0.05), 0.4, 0.8)
MAT['exitbox'] = mat_simple("M_ExitBox", (0.6, 0.6, 0.58), 0.4)
MAT['exit'], _ = mat_emit("M_ExitGlow", (1.0, 0.03, 0.02), 9.0)
MAT['fur'] = mat_fur()
MAT['head'] = mat_head()
MAT['eye'] = mat_simple("M_EyeBlack", (0.004, 0.004, 0.004), 0.05, **{'Coat Weight': 1.0})
MAT['glint'], _ = mat_emit("M_EyeGlint", (1.0, 0.95, 0.85), 4.0)
MAT['mouth'] = mat_simple("M_MouthHole", (0.02, 0.0, 0.0), 0.15)
MAT['teeth'] = mat_simple("M_Teeth", (0.5, 0.44, 0.3), 0.3)
MAT['nose'] = mat_plastic("M_Nose", (0.45, 0.02, 0.02), 0.18)
MAT['cheek'] = mat_simple("M_Cheek", (0.5, 0.15, 0.17), 0.6)
MAT['belly'] = mat_simple("M_Belly", (0.42, 0.36, 0.26), 0.85, **{'Sheen Weight': 0.6})
MAT['glove'] = mat_simple("M_Glove", (0.45, 0.42, 0.36), 0.8, **{'Sheen Weight': 0.5})
MAT['shoe'] = mat_vinyl("M_Shoe", (0.3, 0.02, 0.02))
MAT['hat'] = mat_hat()
MAT['pompom'] = mat_simple("M_PomPom", (0.6, 0.45, 0.04), 0.9, **{'Sheen Weight': 1.0})
MAT['balloon'] = mat_plastic("M_Balloon", (0.45, 0.01, 0.015), 0.18)
MAT['string'] = mat_simple("M_String", (0.5, 0.5, 0.48), 0.7)
BALL_COLS = [(0.55, 0.03, 0.03), (0.75, 0.52, 0.03), (0.03, 0.12, 0.55), (0.05, 0.35, 0.08)]
MAT['ball_solid'] = [mat_plastic(f"M_Ball_{i}", c, 0.25) for i, c in enumerate(BALL_COLS)]

FONT = None
for fp in FONT_PATHS:
    if os.path.exists(fp):
        FONT = bpy.data.fonts.load(fp)
        break


# ----------------------------------------------------------------------------- geometry helpers
def mesh_obj(name, bm, mats, coll, loc=(0, 0, 0), smooth=False):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
    for mt in (mats if isinstance(mats, (list, tuple)) else [mats]):
        me.materials.append(mt)
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    coll.objects.link(ob)
    return ob


def add_bevel(ob, width, segs=3):
    md = ob.modifiers.new("Bevel", 'BEVEL')
    md.width = width
    md.segments = segs
    md.limit_method = 'ANGLE'
    md.harden_normals = True
    ob.data.polygons.foreach_set('use_smooth', [True] * len(ob.data.polygons))
    return md


def box(name, size, loc, mat, coll, bevel=0.0, rot=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    ob = mesh_obj(name, bm, mat, coll, loc)
    ob.rotation_euler = rot
    if bevel > 0:
        add_bevel(ob, bevel)
    return ob


def cyl(name, r, h, loc, mat, coll, segs=24, rot=(0, 0, 0), r2=None, caps=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=caps, cap_tris=False, segments=segs, radius1=r,
                          radius2=r if r2 is None else r2, depth=h)
    ob = mesh_obj(name, bm, mat, coll, loc, smooth=True)
    ob.rotation_euler = rot
    # keep caps flat-looking
    md = ob.modifiers.new("Bevel", 'BEVEL')
    md.width = min(0.03, r * 0.3)
    md.segments = 2
    md.limit_method = 'ANGLE'
    md.harden_normals = True
    return ob


def sphere(name, r, loc, mat, coll, scale=(1, 1, 1), segs=32):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=max(8, segs // 2), radius=r)
    ob = mesh_obj(name, bm, mat, coll, loc, smooth=True)
    ob.scale = scale
    return ob


def net(name, w, h, loc, rot_z, coll, cell=0.1):
    """Vertical netting panel (local X = width, Z = height) via a Wireframe modifier."""
    bm = bmesh.new()
    nx, nz = max(1, round(w / cell)), max(1, round(h / cell))
    rows = [[bm.verts.new((-w / 2 + w * i / nx, 0.0, h * j / nz)) for i in range(nx + 1)] for j in range(nz + 1)]
    for j in range(nz):
        for i in range(nx):
            bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
    ob = mesh_obj(name, bm, MAT['net'], coll, loc)
    ob.rotation_euler = (0, 0, rot_z)
    md = ob.modifiers.new("Wire", 'WIREFRAME')
    md.thickness = 0.011
    md.use_replace = True
    md.use_even_offset = True
    return ob


def curve_tube(name, pts, radius, mat, coll, radii=None, caps=False, thick=0.0, res=12):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(len(pts) - 1)
    for i, (bp, p) in enumerate(zip(sp.bezier_points, pts)):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = 'AUTO'
        if radii:
            bp.radius = radii[i]
    sp.use_smooth = True
    cu.bevel_depth = radius
    cu.bevel_resolution = 4
    cu.resolution_u = res
    cu.use_fill_caps = caps
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    coll.objects.link(ob)
    if thick > 0:
        md = ob.modifiers.new("Solid", 'SOLIDIFY')
        md.thickness = thick
    return ob


def text_obj(name, body, size, loc, rot, mats, coll, extrude=0.01, per_char=None):
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body = body
    if FONT:
        cu.font = FONT
    cu.size = size
    cu.extrude = extrude
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    for mt in (mats if isinstance(mats, (list, tuple)) else [mats]):
        cu.materials.append(mt)
    if per_char:
        for i, idx in enumerate(per_char):
            cu.body_format[i].material_index = idx
    ob = bpy.data.objects.new(name, cu)
    ob.location = loc
    ob.rotation_euler = rot
    coll.objects.link(ob)
    return ob


R90 = math.radians(90)

# ----------------------------------------------------------------------------- world shell
def build_shell():
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=130.0)
    mesh_obj("Floor", bm, MAT['floor'], C_WORLD, (0, 12, 0))
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=130.0)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    mesh_obj("Ceiling", bm, MAT['ceiling'], C_WORLD, (0, 12, CEIL_H))
    # one troffer, arrayed over the whole ceiling
    bm = bmesh.new()
    frame = bmesh.ops.create_cube(bm, size=1.0)['verts']
    bmesh.ops.scale(bm, vec=(0.64, 1.24, 0.05), verts=frame)
    bmesh.ops.translate(bm, vec=(0, 0, CEIL_H - 0.02), verts=frame)
    for f in bm.faces:
        f.material_index = 0
    v = [bm.verts.new(c) for c in ((-0.29, -0.59, CEIL_H - 0.047), (0.29, -0.59, CEIL_H - 0.047),
                                   (0.29, 0.59, CEIL_H - 0.047), (-0.29, 0.59, CEIL_H - 0.047))]
    face = bm.faces.new((v[3], v[2], v[1], v[0]))      # normal pointing down
    face.material_index = 1
    x0 = BLOCKS_X[0] * BLOCK + LIGHT_GRID / 2
    y0 = BLOCKS_Y[0] * BLOCK + LIGHT_GRID / 2
    ob = mesh_obj("Troffers", bm, [MAT['troffer_frame'], MAT['troffer']], C_WORLD, (x0, y0, 0))
    nx = int(len(BLOCKS_X) * BLOCK / LIGHT_GRID)
    ny = int(len(BLOCKS_Y) * BLOCK / LIGHT_GRID)
    for axis, n in (((LIGHT_GRID, 0, 0), nx), ((0, LIGHT_GRID, 0), ny)):
        md = ob.modifiers.new("Array", 'ARRAY')
        md.use_relative_offset = False
        md.use_constant_offset = True
        md.constant_offset_displace = axis
        md.count = n
    return ob


log('materials done')
TROFFERS = build_shell()
log('shell built')


# ----------------------------------------------------------------------------- one block (instanced)
def build_block():
    c = C_BLOCK
    V = MAT
    # padded pillars at island corners / edges
    for i, (x, y) in enumerate([(2, 2), (6, 2), (10, 2), (2, 6), (10, 6.5), (2, 10), (6, 10), (10, 10)]):
        box(f"Pillar_{i}", (0.36, 0.36, CEIL_H), (x, y, CEIL_H / 2), V['steel'], c)
        pad = V['v_blue'] if i % 2 == 0 else V['v_green']
        box(f"PillarPad_{i}", (0.5, 0.5, 1.75), (x, y, 0.875), pad, c, bevel=0.05)
        box(f"PillarBand_{i}", (0.53, 0.53, 0.22), (x, y, 1.86), V['v_red'] if i % 2 == 0 else V['v_yellow'], c,
            bevel=0.04)
    # "ZONE 7" placards facing both aisles
    for x, rz, side in ((10.0, R90, 1), (2.0, -R90, -1)):
        bx = x + side * 0.19
        box(f"ZonePlate_{side}", (0.02, 0.62, 0.32), (bx, 2.0, 2.35), V['board'], c, bevel=0.005)
        text_obj(f"ZoneText_{side}", "ZONE 7", 0.13, (bx + side * 0.012, 2.0, 2.35), (R90, 0, rz),
                 V['v_red'], c, extrude=0.003)

    # ---- ball pit (local x 5.5..10, y 2..6.5); aisle-facing wall at x=10 left open above
    walls = [((7.75, 2.125), (4.5, 0.25)), ((7.75, 6.375), (4.5, 0.25)),
             ((5.625, 4.25), (0.25, 4.5)), ((9.875, 4.25), (0.25, 4.5))]
    for i, ((x, y), (sx, sy)) in enumerate(walls):
        box(f"PitWall_{i}", (sx, sy, 0.6), (x, y, 0.3), V['v_blue'], c, bevel=0.06)
        horiz = sx > sy
        length = (sx if horiz else sy) - 0.1
        cyl(f"PitCushion_{i}", 0.1, length, (x, y, 0.7), V['v_red'] if i % 2 else V['v_yellow'], c,
            rot=(0, R90, 0) if horiz else (R90, 0, 0))
    log('pit walls')
    box("PitDepths", (4.0, 4.0, 0.4), (7.75, 4.25, 0.2), V['pitfill'], c)
    build_ball_mesh("PitBalls", 5.75, 9.75, 2.25, 6.25, 0.5, c)
    log('pit balls')
    for i, (x, y) in enumerate([(5.62, 2.12), (9.88, 2.12), (5.62, 6.38), (9.88, 6.38)]):
        cyl(f"PitPost_{i}", 0.08, 3.4, (x, y, 1.7), V['v_yellow'], c)
    net("PitNet_Front", 4.2, 2.5, (7.75, 2.12, 0.85), 0.0, c)
    net("PitNet_Back", 4.2, 2.5, (5.62, 4.25, 0.85), R90, c)

    # ---- raised platform behind the pit (x 5.5..10, y 6.5..10)
    box("Deck", (4.5, 3.5, 0.15), (7.75, 8.25, 1.55), V['v_blue'], c, bevel=0.04)
    box("DeckEdge", (4.5, 0.18, 0.22), (7.75, 6.55, 1.55), V['v_red'], c, bevel=0.06)
    for i, (x, y) in enumerate([(9.9, 9.9), (5.6, 9.9), (9.9, 6.6), (5.6, 6.6)]):
        cyl(f"DeckPost_{i}", 0.08, 3.4, (x, y, 1.7), V['v_yellow'], c)
    net("DeckNet_Aisle", 3.3, 1.65, (9.95, 8.25, 1.7), R90, c)
    net("DeckNet_Back", 4.3, 1.65, (7.75, 9.95, 1.7), 0.0, c)
    for i, (x, y) in enumerate([(6.6, 7.4), (8.9, 7.4), (6.6, 9.1), (8.9, 9.1)]):
        cyl(f"Roller_{i}", 0.17, 1.47, (x, y, 0.74), V['v_red'] if i % 2 else V['v_blue'], c)
    curve_tube("TubeSlide", [(8.9, 7.5, 2.05), (9.3, 6.3, 1.75), (9.0, 5.0, 1.35), (7.9, 4.35, 0.95),
                             (6.7, 4.7, 0.82)], 0.34, V['tube'], c, thick=0.03)

    # ---- tower + wavy slide on the other side of the island (x 2..5.5)
    box("TowerDeck", (2.6, 2.6, 0.15), (3.5, 3.5, 1.55), V['v_green'], c, bevel=0.04)
    for i, (x, y) in enumerate([(2.25, 2.25), (4.75, 2.25), (2.25, 4.75), (4.75, 4.75)]):
        cyl(f"TowerPost_{i}", 0.08, 3.4, (x, y, 1.7), V['v_red'], c)
    net("TowerNet_Front", 2.4, 1.65, (3.5, 2.25, 1.7), 0.0, c)
    net("TowerNet_Side", 2.4, 1.65, (4.75, 3.5, 1.7), R90, c)
    net("TowerNet_Aisle", 1.4, 1.65, (2.22, 3.0, 1.7), R90, c)
    build_wavy_slide("WavySlide", (2.95, 4.75, 1.62), (2.95, 8.5, 0.2), c)
    # foam shapes
    box("Foam_Cube", (0.6, 0.6, 0.6), (4.2, 6.2, 0.3), V['v_yellow'], c, bevel=0.06, rot=(0, 0, 0.3))
    cyl("Foam_Cyl", 0.3, 0.6, (4.6, 7.4, 0.3), V['v_blue'], c)
    cyl("Foam_Roll", 0.25, 1.0, (3.9, 5.2, 0.25), V['v_red'], c, rot=(0, R90, 0.4))
    bm = bmesh.new()
    vs = [bm.verts.new(p) for p in ((-0.4, -0.35, 0), (0.4, -0.35, 0), (0.4, 0.35, 0), (-0.4, 0.35, 0),
                                     (0.4, -0.35, 0.5), (0.4, 0.35, 0.5))]
    for f in ((0, 3, 2, 1), (1, 2, 5, 4), (0, 1, 4), (3, 5, 2), (0, 4, 5, 3)):
        bm.faces.new([vs[i] for i in f])
    w = mesh_obj("Foam_Wedge", bm, V['v_green'], c, (3.3, 7.0, 0.0))
    w.rotation_euler = (0, 0, 2.2)
    add_bevel(w, 0.05)
    # foam stairs up to the platform
    for k in range(4):
        x0 = 3.0 + 0.62 * k
        box(f"Stair_{k}", (5.5 - x0, 1.2, 0.4), ((x0 + 5.5) / 2, 9.0, 0.2 + 0.4 * k),
            V['v_red'] if k % 2 else V['v_yellow'], c, bevel=0.05)

    # ---- hanging "PLAY ZONE" sign over the intersection at the block corner
    box("SignBoard", (2.5, 0.06, 0.62), (0.0, 0.0, 2.95), V['board'], c, bevel=0.01)
    letters = "PLAY ZONE"
    idx = [0, 1, 2, 3, 0, 0, 1, 2, 3]
    mats = [V['v_red'], V['v_blue'], V['v_yellow'], V['v_green']]
    text_obj("SignText_S", letters, 0.38, (0.0, -0.035, 2.95), (R90, 0, 0), mats, c, 0.005, idx)
    text_obj("SignText_N", letters, 0.38, (0.0, 0.035, 2.95), (R90, 0, math.pi), mats, c, 0.005, idx)
    for x in (-1.1, 1.1):
        cyl(f"SignCable_{x}", 0.006, CEIL_H - 3.26, (x, 0, (CEIL_H + 3.26) / 2), V['cable'], c, segs=6)


def build_ball_mesh(name, x0, x1, y0, y1, ztop, coll):
    """Two loose layers of 8 cm balls, built in one go from a template icosphere."""
    import numpy as np
    tb = bmesh.new()
    bmesh.ops.create_icosphere(tb, subdivisions=2, radius=1.0)
    tv = np.array([v.co[:] for v in tb.verts])
    tf = np.array([[v.index for v in f.verts] for f in tb.faces])
    tb.free()
    centers, radii, vals = [], [], []
    sp = 2 * BALL_R * 1.04
    for layer in range(2):
        z = ztop - BALL_R - layer * BALL_R * 1.5
        j = 0
        y = y0 + BALL_R
        while y < y1 - BALL_R:
            x = x0 + BALL_R + ((j + layer) % 2) * sp / 2
            while x < x1 - BALL_R:
                px = x + random.uniform(-0.18, 0.18) * BALL_R
                py = y + random.uniform(-0.18, 0.18) * BALL_R
                pz = z + random.uniform(-0.4, 0.4) * BALL_R
                pz += 0.025 * math.sin(px * 2.1) * math.sin(py * 1.7)   # gently heaped surface
                centers.append((px, py, pz))
                radii.append(BALL_R * random.uniform(0.96, 1.0))
                vals.append(random.random())
                x += sp
            y += sp * 0.866
            j += 1
    n, nv = len(centers), len(tv)
    verts = (tv[None] * np.array(radii)[:, None, None] + np.array(centers)[:, None, :]).reshape(-1, 3)
    faces = (tf[None] + (np.arange(n) * nv)[:, None, None]).reshape(-1, 3)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts.tolist(), [], faces.tolist())
    me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
    attr = me.attributes.new('ball_rand', 'FLOAT', 'POINT')
    attr.data.foreach_set('value', np.repeat(np.array(vals, dtype=np.float32), nv))
    me.materials.append(MAT['balls'])
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    log(f"pit balls: {n}")
    return ob


def build_wavy_slide(name, p0, p1, coll, n=48, width=0.82):
    bm = bmesh.new()
    prof = [(-width / 2 - 0.04, 0.28), (-width / 2, 0.02), (-width / 2 + 0.08, 0.0), (width / 2 - 0.08, 0.0),
            (width / 2, 0.02), (width / 2 + 0.04, 0.28)]
    def zf(t):
        ease = t * t * (3 - 2 * t)
        return p0[2] + (p1[2] - p0[2]) * (0.25 * t + 0.75 * ease) + 0.12 * math.sin(t * math.pi * 3) * 4 * t * (1 - t)

    rows = []
    for i in range(n + 1):
        t = i / n
        y = p0[1] + (p1[1] - p0[1]) * t
        z = zf(t)
        rows.append([bm.verts.new((p0[0] + lx, y, z + lz)) for lx, lz in prof])
    for i in range(n):
        for k in range(len(prof) - 1):
            bm.faces.new((rows[i][k], rows[i][k + 1], rows[i + 1][k + 1], rows[i + 1][k]))
    ob = mesh_obj(name, bm, MAT['slide'], coll, smooth=True)
    md = ob.modifiers.new("Solid", 'SOLIDIFY')
    md.thickness = 0.04
    # supports
    for t in (0.4, 0.75):
        y = p0[1] + (p1[1] - p0[1]) * t
        h = zf(t) - 0.03
        cyl(f"{name}_Leg_{t}", 0.05, h, (p0[0], y, h / 2), MAT['v_yellow'], coll, segs=12)
    return ob


build_block()
log("block built")

# exclude the source collection, instance it on a grid
scene.view_layers[0].layer_collection.children[C_BLOCK.name].exclude = True
for i in BLOCKS_X:
    for j in BLOCKS_Y:
        e = bpy.data.objects.new(f"Block_{i}_{j}", None)
        e.instance_type = 'COLLECTION'
        e.instance_collection = C_BLOCK
        e.location = (i * BLOCK, j * BLOCK, 0)
        C_INST.objects.link(e)


# ----------------------------------------------------------------------------- props
def build_props():
    c = C_PROPS
    # EXIT sign hanging over the aisle - it never leads anywhere
    box("ExitBox", (0.78, 0.1, 0.28), (0, 10.0, 3.08), MAT['exitbox'], c, bevel=0.01)
    for rz, dy in ((0.0, -0.052), (math.pi, 0.052)):
        text_obj(f"ExitText_{dy}", "EXIT", 0.18, (0, 10.0 + dy, 3.08), (R90, 0, rz), MAT['exit'], c, 0.002)
    for x in (-0.3, 0.3):
        cyl(f"ExitRod_{x}", 0.006, CEIL_H - 3.22, (x, 10.0, (CEIL_H + 3.22) / 2), MAT['cable'], c, segs=6)
    # a balloon stuck on the ceiling, string hanging
    b = sphere("Balloon", 0.17, (1.05, 6.2, CEIL_H - 0.22), MAT['balloon'], c, scale=(1, 1, 1.18))
    cyl("BalloonKnot", 0.025, 0.05, (1.05, 6.2, CEIL_H - 0.43), MAT['balloon'], c, segs=10, r2=0.006)
    pts = [(1.05, 6.2, CEIL_H - 0.45), (1.08, 6.22, 3.0), (1.02, 6.18, 2.5), (1.06, 6.21, 2.0)]
    s = curve_tube("BalloonString", pts, 0.003, MAT['string'], c)
    # a child's party hat dropped in the aisle
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=False, cap_tris=False, segments=24, radius1=0.08, radius2=0.004,
                          depth=0.2)
    hat = mesh_obj("DroppedHat", bm, MAT['hat'], c, (0.75, 7.6, 0.075), smooth=True)
    hat.rotation_euler = (0.0, math.radians(68), 0.6)
    sphere("DroppedHat_Pom", 0.025, (0.75 + 0.06, 7.6 + 0.045, 0.035), MAT['pompom'], c, segs=12)


build_props()
log('props built')


# ----------------------------------------------------------------------------- mascot
HEAD_R = 0.42
HEAD_C = Vector((0, 0, 2.18))


def head_pt(az, el, roff=0.0):
    R = HEAD_R + roff
    return HEAD_C + Vector((R * math.sin(az) * math.cos(el), -R * math.cos(az) * math.cos(el), R * math.sin(el)))


def surface_patch(name, fn, nu, nv, mat, coll):
    bm = bmesh.new()
    grid = [[bm.verts.new(fn(i / nu, j / nv)) for j in range(nv + 1)] for i in range(nu + 1)]
    for i in range(nu):
        for j in range(nv):
            bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return mesh_obj(name, bm, mat, coll, smooth=True)


def build_mascot():
    c = C_MASCOT
    root = bpy.data.objects.new("Mascot_Root", None)
    root.empty_display_type = 'ARROWS'
    c.objects.link(root)
    hip = bpy.data.objects.new("Mascot_Hip", None)
    hip.location = (0, 0, 0.95)
    c.objects.link(hip)
    neck = bpy.data.objects.new("Mascot_Neck", None)
    neck.location = (0, 0, 1.82)
    c.objects.link(neck)
    parts = {"root": [], "hip": [], "neck": []}

    # legs + shoes
    for sx in (-1, 1):
        parts["root"].append(cyl(f"Leg_{sx}", 0.12, 0.95, (0.15 * sx, 0, 0.55), MAT['fur'], c))
        parts["root"].append(sphere(f"Shoe_{sx}", 1.0, (0.16 * sx, -0.07, 0.08), MAT['shoe'], c,
                                    scale=(0.13, 0.22, 0.09)))
    # torso, belly, neck
    parts["hip"].append(sphere("Torso", 1.0, (0, 0, 1.36), MAT['fur'], c, scale=(0.34, 0.28, 0.52)))
    parts["hip"].append(sphere("Belly", 1.0, (0, -0.21, 1.3), MAT['belly'], c, scale=(0.24, 0.08, 0.32)))
    parts["hip"].append(cyl("Neck", 0.11, 0.22, (0, 0, 1.82), MAT['fur'], c))
    # long arms with gloves and too-long fingers
    for sx in (-1, 1):
        pts = [(0.33 * sx, 0, 1.70), (0.43 * sx, -0.02, 1.2), (0.47 * sx, -0.06, 0.72)]
        parts["hip"].append(curve_tube(f"Arm_{sx}", pts, 0.085, MAT['fur'], c, radii=[1.0, 0.85, 0.7],
                                       caps=True))
        parts["hip"].append(sphere(f"Glove_{sx}", 1.0, (0.48 * sx, -0.06, 0.64), MAT['glove'], c,
                                   scale=(0.08, 0.06, 0.1)))
        for k, dx in enumerate((-0.035, 0.0, 0.035)):
            fx = 0.48 * sx + dx
            parts["hip"].append(curve_tube(f"Finger_{sx}_{k}", [(fx, -0.07, 0.6), (fx * 1.01, -0.08, 0.5),
                                                                (fx * 1.02, -0.06, 0.4 - 0.02 * (k == 1))],
                                           0.018, MAT['glove'], c, caps=True))
    # head
    parts["neck"].append(sphere("Head", HEAD_R, HEAD_C, MAT['head'], c, segs=48))
    for sx in (-1, 1):
        eye_c = head_pt(0.36 * sx, 0.2, -0.05)
        parts["neck"].append(sphere(f"Eye_{sx}", 0.11, eye_c, MAT['eye'], c))
        look = (Vector((0, -1.0, -0.15)) - Vector((0.18 * sx, 0, 0))).normalized()
        parts["neck"].append(sphere(f"Glint_{sx}", 0.013, eye_c + look * 0.108, MAT['glint'], c, segs=12))
        cheek = lambda u, v, sx=sx: head_pt(0.5 * sx + 0.09 * u * math.cos(v * 2 * math.pi),
                                            -0.12 + 0.07 * u * math.sin(v * 2 * math.pi), 0.002)
        parts["neck"].append(surface_patch(f"Cheek_{sx}", cheek, 4, 16, MAT['cheek'], c))
        ear = sphere(f"Ear_{sx}", 0.14, head_pt(0.62 * sx, 0.8, -0.02), MAT['fur'], c, scale=(1, 0.55, 1))
        parts["neck"].append(ear)
    parts["neck"].append(sphere("Nose", 0.065, head_pt(0, -0.02, 0.025), MAT['nose'], c))

    # the grin: a dark crescent conforming to the head, with jagged teeth on both lips
    def mouth_el(u):
        return -0.33 + 0.24 * u * u

    def mouth_h(u):
        return 0.1 * max(0.0, 1 - u * u) ** 0.6 + 0.012

    mouth = lambda a, b: head_pt((a * 2 - 1) * 0.85, mouth_el(a * 2 - 1) + (b * 2 - 1) * mouth_h(a * 2 - 1), 0.003)
    parts["neck"].append(surface_patch("Mouth", mouth, 40, 6, MAT['mouth'], c))
    bm = bmesh.new()
    for lip, sign in (("top", 1), ("bot", -1)):
        n = 15 if lip == "top" else 13
        for k in range(n):
            u = -0.85 + 1.7 * (k + 0.5) / n
            ue = u / 0.85
            edge = mouth_el(ue) + sign * mouth_h(ue)
            half = 0.6 / n
            length = (0.045 + random.uniform(-0.012, 0.018)) * (1 - 0.5 * ue * ue)
            a = head_pt(u - half, edge + sign * 0.004, 0.006)
            b = head_pt(u + half, edge + sign * 0.004, 0.006)
            tip = head_pt(u + random.uniform(-0.01, 0.01), edge - sign * length, 0.004)
            back = head_pt(u, edge, -0.004)
            vs = [bm.verts.new(p) for p in (a, b, tip, back)]
            for f in ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)):
                bm.faces.new([vs[i] for i in f])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    parts["neck"].append(mesh_obj("Teeth", bm, MAT['teeth'], c))
    # party hat
    tilt = Matrix.Translation(head_pt(0.12, 1.2, -0.02)) @ Euler((0.0, 0.28, -0.1)).to_matrix().to_4x4()
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=False, cap_tris=False, segments=32, radius1=0.15, radius2=0.004,
                          depth=0.42, matrix=tilt @ Matrix.Translation((0, 0, 0.21)))
    parts["neck"].append(mesh_obj("Hat", bm, MAT['hat'], c, smooth=True))
    parts["neck"].append(sphere("PomPom", 0.05, tilt @ Vector((0, 0, 0.43)), MAT['pompom'], c, segs=16))

    bpy.context.view_layer.update()
    hip.parent = root
    neck.parent = hip
    neck.matrix_parent_inverse = hip.matrix_world.inverted()
    for key, par in (("root", root), ("hip", hip), ("neck", neck)):
        inv = par.matrix_world.inverted()
        for ob in parts[key]:
            ob.parent = par
            ob.matrix_parent_inverse = inv
    for ob in c.objects:
        try:
            ob.cycles.use_motion_blur = False     # it teleports between appearances
        except Exception:
            pass
    return root, hip, neck


M_ROOT, M_HIP, M_NECK = build_mascot()
log('mascot built')


# ----------------------------------------------------------------------------- step-function helpers
def step_val(steps, f):
    v = steps[0][1]
    for fr, val in steps:
        if f >= fr:
            v = val
    return v


INTERP = {'CONSTANT': 0, 'LINEAR': 1, 'BEZIER': 2}


def bake(id_, path, keys, index=0, interp='LINEAR'):
    """Write one F-curve in bulk. keys = [(frame, value), ...]. (Per-key keyframe_insert calls
    are far too slow on a scene this heavy.)"""
    ad = id_.animation_data or id_.animation_data_create()
    if ad.action is None:
        ad.action = bpy.data.actions.new(f"{id_.name}_Action")
    fc = ad.action.fcurve_ensure_for_datablock(id_, path, index=index)
    kp = fc.keyframe_points
    kp.add(len(keys))
    kp.foreach_set("co", [c for k in keys for c in (float(k[0]), float(k[1]))])
    kp.foreach_set("interpolation", [INTERP[interp]] * len(keys))
    fc.update()
    return fc


def bake_vec(id_, path, frames, vecs, interp='LINEAR'):
    for i in range(len(vecs[0])):
        bake(id_, path, [(f, v[i]) for f, v in zip(frames, vecs)], index=i, interp=interp)


def node_path(node, sock_idx=0, out=True):
    return f'nodes["{node.name}"].{"outputs" if out else "inputs"}[{sock_idx}].default_value'


# ----------------------------------------------------------------------------- lights animation
TROFFER_TREE = MAT['troffer'].node_tree
for name, steps in (("CTL_Ron", TL.LIGHTS_ON_STEPS), ("CTL_Front", TL.DARK_FRONT_STEPS),
                    ("CTL_Global", TL.GLOBAL_FLICKER), ("CTL_Flicker", TL.FLICKER_AMOUNT)):
    bake(TROFFER_TREE, node_path(CTL[name]), steps, interp='CONSTANT')
bake(TROFFER_TREE, node_path(CTL["CTL_Time"]), [(TL.FRAME_START, TL.FRAME_START), (TL.FRAME_END, TL.FRAME_END)])
# hide the panel array entirely while every panel is dark (saves light-tree samples)
bake(TROFFERS, "hide_render", [(1, 1), (TL.LIGHTS_ON_STEPS[1][0], 0), (TL.DARK_FRONT_STEPS[-1][0] + 1, 1)],
     interp='CONSTANT')
log("lights animated")


# ----------------------------------------------------------------------------- mascot animation
frames, locs, rots = [], [], []
for fr, pose in TL.MASCOT_POSES:
    frames.append(fr)
    if pose is None:
        locs.append(HIDE)
        rots.append((0, 0, 0))
    else:
        x, y, yaw = pose
        locs.append((x, y, 0.0))
        rots.append((0, 0, math.radians(yaw)))
bake_vec(M_ROOT, "location", frames, locs, 'CONSTANT')
bake_vec(M_ROOT, "rotation_euler", frames, rots, 'CONSTANT')
f0, f1 = TL.MASCOT_LUNGE
bake(M_NECK, "rotation_euler", [(1, 0.0), (f0, 0.0), (f1, math.radians(14))], index=0, interp='BEZIER')
bake(M_NECK, "rotation_euler", [(f, math.radians(d)) for f, d in TL.MASCOT_HEAD_TILT] + [(f1, math.radians(24))],
     index=1, interp='BEZIER')
bake(M_HIP, "rotation_euler", [(1, 0.0), (f0, 0.0), (f1, math.radians(38))], index=0, interp='BEZIER')
log("mascot animated")


# ----------------------------------------------------------------------------- popping balls
def sim_ball(p0, v0, f_launch, f_end, spin):
    p, v, q = Vector(p0), Vector(v0), Quaternion()
    axis, w = spin
    out, bounces, rolling = {}, [], False
    sub = 10
    dt = 1.0 / (TL.FPS * sub)
    for f in range(f_launch, f_end + 1):
        out[f] = (p.copy(), q.copy())
        if rolling and v.length < 1e-4:
            continue
        for _ in range(sub):
            if not rolling:
                v.z -= 9.81 * dt
            p += v * dt
            if p.z < BALL_R:
                p.z = BALL_R
                if not rolling and v.z < -0.4:
                    bounces.append((f, -v.z))
                    v.z = -v.z * 0.55
                    v.x *= 0.85
                    v.y *= 0.85
                else:
                    rolling = True
                    v.z = 0.0
            if rolling:
                sp = v.length
                if sp > 1e-5:
                    v *= max(0.0, sp - 0.5 * dt) / sp
                    ax = Vector((-v.y, v.x, 0.0))
                    if ax.length > 1e-7:
                        q = Quaternion(ax.normalized(), v.length / BALL_R * dt) @ q
            else:
                q = Quaternion(axis, w * dt) @ q
    return out, bounces


def clears_wall(out):
    for p, _ in out.values():
        if -2.4 <= p.x <= -1.85 and p.z < 0.92:
            return False
    return True


def build_balls():
    launches = [TL.BALL_LAUNCHES + d for d in (0, 3, 5, 9, 12, 16, 23, 31)]
    special = TL.BALL_LAUNCHES + 50
    f_end = 800
    balls, all_bounces = [], []
    rng = random.Random(4)
    mesh = None
    for idx, fl in enumerate(launches + [special]):
        is_special = fl == special
        best = None
        for attempt in range(1500):
            p0 = (rng.uniform(-3.3, -2.55), rng.uniform(14.8, 17.6), 0.5)
            if is_special:
                p0 = (rng.uniform(-3.4, -2.8), rng.uniform(15.4, 16.8), 0.5)
                v0 = (rng.uniform(0.9, 2.2), rng.uniform(-0.7, 0.3), rng.uniform(3.0, 4.2))
            else:
                v0 = (rng.uniform(1.8, 3.0), rng.uniform(-0.9, 0.6), rng.uniform(3.0, 4.2))
            spin = (Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))).normalized(),
                    rng.uniform(6, 16))
            out, bnc = sim_ball(p0, v0, fl, f_end, spin)
            if not clears_wall(out):
                continue
            end = out[f_end][0]
            if is_special:
                err = (end - Vector((-0.6, 15.55, BALL_R))).length
                if best is None or err < best[0]:
                    best = (err, p0, v0, spin, out, bnc)
                if err < 0.08:
                    break
            elif -1.6 < end.x < 1.6 and (end - Vector((0, 14.6, 0))).length > 0.6:
                best = (0, p0, v0, spin, out, bnc)
                break
        assert best is not None, f"no trajectory for ball {idx}"
        _, p0, v0, spin, out, bnc = best
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=3, radius=BALL_R)
        ob = mesh_obj(f"LooseBall_{idx}", bm, MAT['ball_solid'][idx % 4], C_PROPS, smooth=True)
        ob.rotation_mode = 'QUATERNION'
        # rest in the pit, stir, then fly
        rest = Vector(p0)
        frames, locs, quats = [TL.FRAME_START], [rest.copy()], [Quaternion()]
        for f in range(TL.BALL_STIR_START, fl):
            k = (f - TL.BALL_STIR_START) / max(1, fl - TL.BALL_STIR_START)
            jit = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0, 1.5))) * 0.012 * (0.3 + k)
            frames.append(f)
            locs.append(rest + jit)
            quats.append(Quaternion())
        for f in range(fl, f_end + 1):
            p, q = out[f]
            frames.append(f)
            locs.append(p)
            quats.append(q)
        bake_vec(ob, "location", frames, locs)
        bake_vec(ob, "rotation_quaternion", frames, quats)
        all_bounces += [(f, round(s, 3)) for f, s in bnc]
        balls.append((ob.name, fl, tuple(round(x, 3) for x in out[f_end][0])))
    return balls, sorted(all_bounces), launches + [special]


BALLS, BOUNCES, LAUNCHES = build_balls()
log("balls simulated")


# ----------------------------------------------------------------------------- camera
# keyposes: frame, x, y, yaw, pitch, lens, focus distance
CAM_KEYS = [
    (1, 0.0, -1.00, 0, 4, 24, 6.0),
    (150, 0.0, -0.85, 0, 3, 24, 6.0),
    (200, 0.05, 0.75, 3, 1, 24, 6.0),
    (250, 0.10, 2.90, 10, -2, 24, 5.0),
    (290, 0.05, 4.55, 40, -8, 24, 3.5),
    (335, -0.05, 6.40, 32, -4, 24, 4.0),
    (375, 0.0, 8.40, 2, 0, 24, 6.0),
    (402, 0.05, 9.85, -16, -1, 24, 5.0),
    (432, 0.0, 11.70, -6, 1, 24, 8.0),
    (446, 0.0, 12.00, -8, 1, 24, 10.0),
    (470, 0.0, 12.00, -86, 1, 24, 20.0),
    (482, 0.0, 12.00, -90, 1, 24, 26.0),
    (512, 0.0, 12.00, -90, 2, 52, 27.0),
    (518, 0.0, 12.00, -90, 2, 52, 27.0),
    (548, 0.0, 12.00, -93, 1, 52, 27.0),
    (562, 0.0, 12.00, -86, 1, 42, 20.0),
    (578, 0.0, 12.00, -90, 1, 28, 12.0),
    (592, 0.0, 12.00, -60, 0, 24, 8.0),
    (612, 0.0, 12.05, -2, 0, 24, 6.0),
    (650, 0.0, 14.30, 10, -2, 24, 4.0),
    (668, 0.0, 14.60, 48, -8, 24, 3.0),
    (690, 0.0, 14.60, 40, -14, 24, 2.5),
    (705, 0.0, 14.60, 30, -20, 24, 2.0),
    (722, 0.0, 14.60, 25, -30, 24, 1.8),
    (748, 0.0, 14.60, 20, -38, 24, 1.5),
    (772, 0.0, 14.60, 18, -36, 24, 1.5),
    (798, 0.0, 14.60, 2, 0, 24, 15.0),
    (832, 0.0, 14.60, 0, 1, 31, 16.0),
    (862, 0.0, 14.50, 0, 1, 31, 16.0),
    (905, 0.0, 13.95, 1, 0, 28, 10.0),
    (942, 0.0, 13.60, 0, -1, 24, 6.0),
    (968, 0.0, 13.60, 2, -4, 24, 5.0),
    (990, 0.0, 13.60, 5, -9, 24, 4.0),
    (1001, 0.0, 13.60, 10, -6, 24, 4.0),
    (1013, 0.0, 13.60, 70, 4, 24, 2.0),
    (1024, 0.0, 13.62, 150, 12, 24, 1.5),
    (1032, 0.0, 13.65, 178, 33, 24, 1.4),
    (1050, 0.0, 13.66, 180, 37, 24, 1.4),
    (1074, 0.0, 13.68, 181, 38, 24, 1.3),
    (1090, 0.0, 13.75, 180, 34, 24, 0.6),
]
WALK_SEGMENTS = [(150, 446), (612, 668), (862, 942)]
SHAKES = [(518, 0.7, 18), (TL.BALL_LAUNCHES, 0.5, 14), (TL.STINGER_FRAME, 2.6, 26), (1076, 1.8, 16),
          (1084, 2.5, 10)]


def pchip(xs, ys):
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    for i in range(1, n - 1):
        if d[i - 1] * d[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])

    def f(x):
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        i = max(k for k in range(n - 1) if xs[k] <= x)
        t = (x - xs[i]) / h[i]
        h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
        h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
        return h00 * ys[i] + h10 * h[i] * m[i] + h01 * ys[i + 1] + h11 * h[i] * m[i + 1]
    return f


def track_ball(ball_name):
    """Re-aim the camera keys between the launch and settle of the last ball so it follows it."""
    ob = bpy.data.objects[ball_name]
    cam_xy = Vector((0.0, 14.6, EYE_H))
    for i, k in enumerate(CAM_KEYS):
        f = k[0]
        if 690 <= f <= 772:
            scene.frame_set(f + 3)          # look slightly ahead of the ball
            d = ob.matrix_world.translation - cam_xy
            yaw = math.degrees(math.atan2(-d.x, d.y))
            pitch = math.degrees(math.atan2(d.z, d.xy.length)) + 6.0
            CAM_KEYS[i] = (f, k[1], k[2], round(yaw, 2), round(pitch, 2), k[5], round(d.length, 2))
    scene.frame_set(1)


def build_camera():
    cam_data = bpy.data.cameras.new("Cam_Main")
    cam_data.sensor_width = 36
    cam_data.clip_start = 0.02
    cam_data.clip_end = 300
    cam_data.dof.use_dof = True
    cam_data.dof.aperture_fstop = 2.8
    cam = bpy.data.objects.new("Cam_Main", cam_data)
    C_CAM.objects.link(cam)
    frames = [k[0] for k in CAM_KEYS]
    ch = [pchip(frames, [k[i] for k in CAM_KEYS]) for i in range(1, 7)]
    rng = random.Random(21)
    waves = [[(rng.uniform(0.12, 0.9), rng.uniform(0, 6.28), rng.uniform(0.5, 1.0)) for _ in range(3)]
             for _ in range(6)]

    def hand(k, t):
        return sum(a * math.sin(2 * math.pi * fr * t + ph) for fr, ph, a in waves[k]) / 2.0

    dist = 0.0
    prev = None
    steps = []
    step_len = 0.55
    K = {"f": [], "loc": [], "rot": [], "lens": [], "focus": []}
    for f in range(TL.FRAME_START, TL.TITLE_START):
        x, y, yaw, pitch, lens, focus = (c(f) for c in ch)
        walking = any(a <= f <= b for a, b in WALK_SEGMENTS)
        if prev is not None:
            dist += math.hypot(x - prev[0], y - prev[1])
        prev = (x, y)
        phase = math.pi * dist / step_len
        speed = 0.0
        if f > 1:
            speed = math.hypot(ch[0](f) - ch[0](f - 1), ch[1](f) - ch[1](f - 1)) * TL.FPS
        amp = min(1.0, speed / 1.0) if walking else 0.0
        bob = -0.028 * amp * abs(math.sin(phase))
        sway = 0.012 * amp * math.sin(phase / 2.0 * 2)
        roll = 0.6 * amp * math.sin(phase)
        if walking and amp > 0.15:
            k = math.floor(phase / math.pi + 0.5)
            if not steps or steps[-1][1] != k:
                steps.append((f, k, round(amp, 2)))
        t = f / TL.FPS
        sh = 0.0
        for sf, sa, sd in SHAKES:
            if sf <= f < sf + sd:
                sh += sa * (1 - (f - sf) / sd) ** 2
        jx = sh * math.sin(f * 2.7 + 1.3) * 0.6
        jz = sh * math.sin(f * 3.3 + 0.2) * 0.6
        yaw_r = math.radians(yaw + 0.35 * hand(0, t) + jz)
        K["f"].append(f)
        K["loc"].append((x + sway * math.cos(yaw_r) + 0.004 * hand(3, t),
                         y + sway * math.sin(yaw_r), EYE_H + bob + 0.005 * hand(4, t)))
        K["rot"].append((math.radians(90 + pitch + 0.35 * hand(1, t) + jx),
                         math.radians(roll + 0.25 * hand(2, t)), yaw_r))
        K["lens"].append((f, lens))
        K["focus"].append((f, focus))
    bake_vec(cam, "location", K["f"], K["loc"])
    bake_vec(cam, "rotation_euler", K["f"], K["rot"])
    bake(cam_data, "lens", K["lens"])
    bake(cam_data, "dof.focus_distance", K["focus"])
    # flashlight on the camera
    tl = bpy.data.lights.new("Torch", 'SPOT')
    tl.energy = 0.0
    tl.color = (1.0, 0.9, 0.75)
    tl.spot_size = math.radians(50)
    tl.spot_blend = 0.55
    tl.shadow_soft_size = 0.015
    torch = bpy.data.objects.new("Torch", tl)
    torch.parent = cam
    torch.location = (0.07, -0.08, 0.0)
    C_CAM.objects.link(torch)
    bake(tl, "energy", [(fr, 70.0 * val) for fr, val in TL.TORCH], interp='CONSTANT')
    return cam, [s[0] for s in steps], [s[2] for s in steps]


track_ball(BALLS[-1][0])
CAM, FOOTSTEPS, FOOT_AMP = build_camera()
scene.camera = CAM
log("camera animated")

# red emergency light under the EXIT sign
el = bpy.data.lights.new("EmergencyRed", 'AREA')
el.size = 0.6
el.color = (1.0, 0.05, 0.03)
emerg = bpy.data.objects.new("EmergencyRed", el)
emerg.location = (0, 10.0, 2.9)
C_CAM.objects.link(emerg)
bake(el, "energy", [(1, 0.0), (TL.EMERGENCY_ON, 32.0), (TL.TITLE_START, 0.0)], interp='CONSTANT')


# ----------------------------------------------------------------------------- title card
def build_title():
    tz = -100.0
    cols = [(0.9, 0.06, 0.04), (0.05, 0.2, 1.0), (1.0, 0.7, 0.05), (0.08, 0.7, 0.12)]
    mats, ems = [], []
    for i, col in enumerate(cols):
        m, em = mat_title(f"M_Title_{i}", col)
        mats.append(m)
        ems.append(em)
    text_obj("Title_PlayZone", "PLAY ZONE", 0.62, (0, 0, tz + 0.18), (R90, 0, 0), mats, C_TITLE, 0.02,
             [0, 1, 2, 3, 0, 0, 1, 2, 3])
    sub, sub_em = mat_title("M_Title_Sub", (0.85, 0.82, 0.75))
    text_obj("Title_Sub", "WE NEVER CLOSE", 0.16, (0, 0, tz - 0.42), (R90, 0, 0), sub, C_TITLE, 0.005)
    t0 = TL.TITLE_START
    fade = [(t0 + 12, 0.0), (t0 + 22, 0.9), (t0 + 34, 2.2), (1150, 2.2), (1151, 0.2), (1152, 2.2), (1154, 0.0),
            (1157, 2.2)]
    strength_idx = list(ems[0].inputs).index(sock(ems[0].inputs, 'Strength'))
    for m, em in zip(mats, ems):
        bake(m.node_tree, node_path(em, strength_idx, out=False), fade, interp='LINEAR')
    bake(sub.node_tree, node_path(sub_em, strength_idx, out=False), [(1158, 0.0), (1170, 0.5), (1178, 1.0)])
    cd = bpy.data.cameras.new("Cam_Title")
    cd.lens = 50
    tc = bpy.data.objects.new("Cam_Title", cd)
    tc.location = (0, -7.5, tz)
    tc.rotation_euler = (R90, 0, 0)
    C_TITLE.objects.link(tc)
    return tc


TITLE_CAM = build_title()
mk = scene.timeline_markers.new("Cam_Main", frame=1)
mk.camera = CAM
mk = scene.timeline_markers.new("Cam_Title", frame=TL.TITLE_START)
mk.camera = TITLE_CAM


# ----------------------------------------------------------------------------- world, render, compositor
world = bpy.data.worlds.new("Void")
scene.world = world
try:
    world.use_nodes = True
except Exception:
    pass
bg = world.node_tree.nodes.get("Background") or world.node_tree.nodes.new("ShaderNodeBackground")
bg.inputs['Color'].default_value = (0, 0, 0, 1)
bg.inputs['Strength'].default_value = 0.0
world.mist_settings.start = 3.0
world.mist_settings.depth = 48.0
world.mist_settings.falloff = 'LINEAR'

r = scene.render
r.engine = 'CYCLES'
cy = scene.cycles
cy.device = 'CPU'
cy.samples = 4                 # CPU-only render farm of one: denoiser does the rest
cy.use_adaptive_sampling = False
cy.use_denoising = True
cy.denoising_quality = 'FAST'
cy.use_fast_gi = True
try:
    cy.denoiser = 'OPENIMAGEDENOISE'
except Exception:
    pass
cy.max_bounces = 3
cy.diffuse_bounces = 1
cy.glossy_bounces = 1
cy.transmission_bounces = 2
cy.transparent_max_bounces = 8
cy.volume_bounces = 0
cy.caustics_reflective = False
cy.caustics_refractive = False
cy.blur_glossy = 1.0
cy.sample_clamp_indirect = 4.0
cy.use_light_tree = True
r.use_persistent_data = True
r.use_motion_blur = True
r.motion_blur_shutter = 0.5
r.fps = TL.FPS
r.resolution_x = 1280
r.resolution_y = 720
r.resolution_percentage = 75     # 960x540, upscaled at encode
scene.frame_start = TL.FRAME_START
scene.frame_end = TL.FRAME_END
r.image_settings.file_format = 'PNG'
r.image_settings.color_mode = 'RGB'
r.image_settings.color_depth = '8'
r.filepath = "//frames/f_"
r.use_overwrite = False
r.use_placeholder = True
r.use_compositing = True
r.compositor_device = 'CPU'      # no GPU here; GPU compositing would fall back to software GL
scene.view_settings.view_transform = 'AgX'
for look in ("AgX - Medium High Contrast", "Medium High Contrast", "AgX - High Contrast"):
    try:
        scene.view_settings.look = look
        print("LOOK", look)
        break
    except TypeError:
        continue
scene.view_settings.exposure = -0.25
vl = scene.view_layers[0]
vl.use_pass_mist = True


def build_compositor():
    tree = bpy.data.node_groups.new("PlayZone_Comp", "CompositorNodeTree")
    tree.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')
    scene.compositing_node_group = tree
    g = G(tree)
    rl = g.node("CompositorNodeRLayers")
    # distance haze: mist pass mixes toward a dim haze colour whose brightness follows the lights
    lvl = g.node("ShaderNodeValue", name="FogLevel", label="FogLevel")
    lvl.outputs[0].default_value = 1.0
    fog_col = g.mix(1.0, (0.010, 0.012, 0.009), g.comb(lvl.outputs[0], lvl.outputs[0], lvl.outputs[0]), 'MULTIPLY')
    mist = g.math('MULTIPLY', rl.outputs['Mist'], 0.96)
    img = g.mix(mist, rl.outputs['Image'], fog_col)
    glare = g.node("CompositorNodeGlare")
    g.set(glare, 'Image', img)
    g.set(glare, 'Type', 'Fog Glow')
    g.set(glare, 'Highlights Threshold', 1.2)
    g.set(glare, 'Strength', 0.35)
    g.set(glare, 'Size', 0.6)
    lens = g.node("CompositorNodeLensdist")
    g.link(glare.outputs['Image'], lens.inputs['Image'])
    g.set(lens, 'Distortion', -0.015)
    g.set(lens, 'Dispersion', 0.012)
    hs = g.node("CompositorNodeHueSat")
    g.link(lens.outputs['Image'], hs.inputs['Image'])
    g.set(hs, 'Saturation', 0.8)
    cb = g.node("CompositorNodeColorBalance")     # sickly fluorescent grade: green-cyan shadows
    g.link(hs.outputs['Image'], cb.inputs['Image'])
    g.set(cb, 'Color Lift', (0.985, 1.01, 1.0))
    g.set(cb, 'Color Gain', (0.98, 1.02, 0.95))
    hs = cb
    em = g.node("CompositorNodeEllipseMask")
    g.set(em, 'Size', (0.98, 0.9, 0.0) if len(em.inputs['Size'].default_value) == 3 else (0.98, 0.9))
    blur = g.node("CompositorNodeBlur")
    g.link(em.outputs['Mask'], blur.inputs['Image'])
    sz = blur.inputs['Size'].default_value
    blur.inputs['Size'].default_value = (180, 180) if len(sz) == 2 else (180, 180, 0)
    vig = g.maprange(blur.outputs['Image'], 0.0, 1.0, 0.42, 1.0, smooth=False)
    out_img = g.mix(1.0, hs.outputs['Image'], g.comb(vig, vig, vig), 'MULTIPLY')
    go = g.node("NodeGroupOutput")
    g.link(out_img, go.inputs[0])
    return tree, lvl


COMP, FOG_LVL = build_compositor()
log('compositor built')


def light_level(f):
    """Rough overall brightness of the room for the haze colour."""
    if f >= TL.TITLE_START:
        return 0.0
    ron = step_val(TL.LIGHTS_ON_STEPS, f)
    front = step_val(TL.DARK_FRONT_STEPS, f)
    lvl = min(1.0, max(0.0, ron / 30.0)) * step_val(TL.GLOBAL_FLICKER, f)
    lvl *= min(1.0, max(0.0, (front - 14.0) / 40.0))
    lvl *= 1.0 - 0.6 * step_val(TL.FLICKER_AMOUNT, f)
    return round(lvl, 3)


prev, fog_keys = None, []
for f in range(TL.FRAME_START, TL.FRAME_END + 1):
    v = light_level(f)
    if v != prev:
        fog_keys.append((f, v))
        prev = v
bake(COMP, node_path(FOG_LVL), fog_keys, interp='CONSTANT')

scene.frame_set(1)
log('frame set')

# ----------------------------------------------------------------------------- save + cues
with open(OUT_CUES, "w") as fh:
    json.dump({"fps": TL.FPS, "footsteps": FOOTSTEPS, "foot_amp": FOOT_AMP, "ball_bounces": BOUNCES,
               "ball_launches": LAUNCHES, "balls": BALLS}, fh, indent=1)
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)

# report what was built
tris = 0
for ob in C_BLOCK.objects:
    if ob.type == 'MESH':
        tris += sum(len(p.vertices) - 2 for p in ob.data.polygons)
print(f"BUILD OK: blocks={len(BLOCKS_X) * len(BLOCKS_Y)} block_objects={len(C_BLOCK.objects)} "
      f"block_base_tris~{tris} mascot_parts={len(C_MASCOT.objects)} footsteps={len(FOOTSTEPS)} "
      f"bounces={len(BOUNCES)} balls={BALLS}")
