"""Assemble the configurator model from a sharp geometry-only scan plus modelled parts.

Run:  blender -b --python finish_roadster.py -- <body.glb> <out_dir> [--render] [--tris N]

- body.glb: the winning geometry-only generation (sharpest surfaces, no texture).
- source/tripo-h31-raw.glb: the textured Tripo scan, used only to decide which faces are glass,
  black trim and lights (its colours are never shown).
- parts.glb (from parts_roadster.py): wheels, tyres, brake discs, calipers.
- source/parts-handbuilt.glb: the active wing and the seat.
Writes roadster-body.glb (Draco-compressed) and base64 text parts for the page.
"""
import base64, json, math, os, sys
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

HERE = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
BODY_SRC, OUT_DIR = argv[0], argv[1]
RENDER = '--render' in argv
TARGET_TRIS = int(argv[argv.index('--tris') + 1]) if '--tris' in argv else 700_000
# --prealigned: the body is already in the normalised frame with wheels removed (retopo_roadster.py output),
# so skip the nose/tail test and wheel removal. --axles a,b gives the axle positions directly.
PREALIGNED = '--prealigned' in argv
AXLES_ARG = [float(v) for v in argv[argv.index('--axles') + 1].split(',')] if '--axles' in argv else None
LENGTH = 4.64
NOSE, TAIL = -LENGTH / 2, LENGTH / 2
WHEEL_R = 0.345

bpy.ops.wm.read_factory_settings(use_empty=True)


def select_only(objs, active=None):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or objs[0]


def import_joined(path, name):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in set(bpy.context.scene.objects) - before]
    meshes = [o for o in new if o.type == 'MESH']
    select_only(meshes)
    if len(meshes) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = name
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for x in new:
        if x is not o and x.name in bpy.data.objects:
            bpy.data.objects.remove(x, do_unlink=True)
    return o


def verts_np(o):
    co = np.empty(len(o.data.vertices) * 3)
    o.data.vertices.foreach_get('co', co)
    return co.reshape(-1, 3)


def normalise(o, turn):
    """Long axis on X, nose at -X, 4.64 m long, centred, wheels on the ground."""
    v = verts_np(o)
    if np.ptp(v[:, 1]) > np.ptp(v[:, 0]):
        o.data.transform(Matrix.Rotation(math.pi / 2, 4, 'Z'))
    if turn:
        o.data.transform(Matrix.Rotation(math.pi, 4, 'Z'))
    v = verts_np(o)
    mn, mx = v.min(0), v.max(0)
    s = LENGTH / (mx[0] - mn[0])
    c = (mn + mx) / 2
    o.data.transform(Matrix.Scale(s, 4) @ Matrix.Translation(Vector((-c[0], -c[1], -mn[2]))))
    o.data.update()


# ================================================================ colour reference: the textured Tripo scan
ref = import_joined(os.path.join(HERE, 'source/tripo-h31-raw.glb'), 'Ref')
normalise(ref, True)
mat = ref.data.materials[0]
bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
img = next(n.image for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image
           and any(l.to_socket == bsdf.inputs['Base Color'] for l in n.outputs['Color'].links))
TW, TH = img.size
tex = np.empty(TW * TH * 4, np.float32); img.pixels.foreach_get(tex)
tex = tex.reshape(TH, TW, 4)[..., :3]
tex = np.where(tex <= 0.04045, tex / 12.92, ((tex + 0.055) / 1.055) ** 2.4)
rme = ref.data
ruv = np.empty(len(rme.loops) * 2, np.float32); rme.uv_layers.active.data.foreach_get('uv', ruv); ruv = ruv.reshape(-1, 2)
rls = np.empty(len(rme.polygons), np.int64); rme.polygons.foreach_get('loop_start', rls)
rlv = np.empty(len(rme.loops), np.int64); rme.loops.foreach_get('vertex_index', rlv)
rco = verts_np(ref)
ref_bvh = BVHTree.FromObject(ref, bpy.context.evaluated_depsgraph_get())
low = rco[rco[:, 2] < 0.015]
AXLES = [float(np.median(low[low[:, 0] < 0][:, 0])), float(np.median(low[low[:, 0] > 0][:, 0]))]
REF_AXLES = list(AXLES)
WARP = {'yz': np.array([1.0, 0.0, 1.0, 0.0])}     # y scale, y offset, z scale, z offset (fitted below)


def to_ref(p):
    """Map a point on the body into the reference scan's space: axles matched along x, ICP fit across."""
    x = float(np.interp(p[0], [NOSE, AXLES[0], AXLES[1], TAIL], [NOSE, REF_AXLES[0], REF_AXLES[1], TAIL]))
    a = WARP['yz']
    return Vector((x, p[1] * a[0] + a[1], p[2] * a[2] + a[3]))


def ref_colour(p):
    loc, nrm, face, dist = ref_bvh.find_nearest(to_ref(p))
    if loc is None:
        return np.array([0.2, 0.2, 0.2]), 9.0
    ls = rls[face]
    tri = [Vector(rco[rlv[ls + k]]) for k in range(3)]
    uvs = [Vector((ruv[ls + k][0], ruv[ls + k][1], 0)) for k in range(3)]
    uv = barycentric_transform(loc, *tri, *uvs)
    return tex[min(TH - 1, max(0, int(uv.y % 1 * TH))), min(TW - 1, max(0, int(uv.x % 1 * TW)))], dist


# ================================================================ body: the sharp geometry, aligned to the reference
body = import_joined(BODY_SRC, 'Body')
if not PREALIGNED:      # a prealigned body has no wheels, so re-grounding it would drop it onto its underbody
    normalise(body, False)


def align_error():
    v = verts_np(body)[::max(1, len(body.data.vertices) // 4000)]
    return float(np.mean([ref_bvh.find_nearest(Vector(p))[3] for p in v]))


e0 = align_error()
e1 = e0
if not PREALIGNED:
    body.data.transform(Matrix.Rotation(math.pi, 4, 'Z'))      # centred, so this just swaps nose and tail
    e1 = align_error()
    if e0 < e1:
        body.data.transform(Matrix.Rotation(math.pi, 4, 'Z'))
print('ALIGNED, mean distance to reference cm', round(100 * min(e0, e1), 2), '(other way', round(100 * max(e0, e1), 2), ')')

tris = sum(len(p.vertices) - 2 for p in body.data.polygons)
if tris > TARGET_TRIS and not PREALIGNED:          # retopo input: its quad layout is the point, keep it
    dec = body.modifiers.new('Decimate', 'DECIMATE'); dec.ratio = TARGET_TRIS / tris
    select_only([body]); bpy.ops.object.modifier_apply(modifier=dec.name)
print('TRIS', tris, '->', sum(len(p.vertices) - 2 for p in body.data.polygons))

# Axles from this body's own tyre contact patches (its proportions differ slightly from the reference's).
bv = verts_np(body)
AXLES = list(AXLES_ARG) if AXLES_ARG else []
for half in ([] if AXLES_ARG else (bv[(bv[:, 0] < -0.6) & (bv[:, 0] > -2.0)], bv[(bv[:, 0] > 0.6) & (bv[:, 0] < 2.0)])):
    contact = half[half[:, 2] < half[:, 2].min() + 0.012]          # each tyre's own lowest band
    AXLES.append(float(np.median(contact[:, 0])))
print('AXLES', np.round(AXLES, 3), 'reference', np.round(REF_AXLES, 3))
# Fit width and height scale/offset by iterative closest points (x is already matched through the axles).
sample = bv[np.random.default_rng(0).choice(len(bv), 6000, replace=False)]
for _ in range(8):
    src = np.array([to_ref(p) for p in sample])
    dst = np.array([ref_bvh.find_nearest(Vector(q))[0] for q in src])
    for k, col in ((0, 1), (2, 2)):
        A = np.stack([sample[:, col], np.ones(len(sample))], 1)
        sol, *_ = np.linalg.lstsq(A, dst[:, col], rcond=None)
        WARP['yz'][k], WARP['yz'][k + 1] = sol
err = np.mean([ref_bvh.find_nearest(to_ref(p))[3] for p in sample[:2000]])
print('ICP warp', np.round(WARP['yz'], 4), 'mean distance cm', round(100 * err, 2))

# ---------------------------------------------------------------- remove the generated wheels (modelled ones replace them)
bm = bmesh.new(); bm.from_mesh(body.data)
gone = [] if PREALIGNED else [f for f in bm.faces if abs(f.calc_center_median().y) > 0.5 and any(
    math.hypot(f.calc_center_median().x - ax, f.calc_center_median().z - WHEEL_R) < WHEEL_R + 0.012 for ax in AXLES)]
bmesh.ops.delete(bm, geom=gone, context='FACES')
# Also drop loose islands left behind (spokes, rim bits).
bm.faces.ensure_lookup_table()
seen, islands = set(), []
for f in bm.faces:
    if f.index in seen:
        continue
    stack, isl = [f], []
    seen.add(f.index)
    while stack:
        g = stack.pop(); isl.append(g)
        for e in g.edges:
            for h in e.link_faces:
                if h.index not in seen:
                    seen.add(h.index); stack.append(h)
    islands.append(isl)
islands.sort(key=len, reverse=True)
small = [] if PREALIGNED else [f for isl in islands[1:] if len(isl) < 0.02 * len(bm.faces) for f in isl]
bmesh.ops.delete(bm, geom=small, context='FACES')
bm.to_mesh(body.data); bm.free()
print('WHEELS removed faces', len(gone), 'loose', len(small))

# ---------------------------------------------------------------- classify faces from the reference colours
CLASSES = ['Paint', 'Glass', 'Trim', 'LightWhite', 'LightRed', 'LightAmber']


def classify(c, p):
    r, g, b = c
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if r > 0.12 and r > 3 * g and r > 3 * b:
        return 4                                   # red tail light
    if r > 0.25 and g > 0.08 and r > 2 * b and g > 1.5 * b and lum < 0.5:
        return 5                                   # amber marker
    if lum > 0.55 and (p.x < NOSE + 0.4 or p.x > TAIL - 0.3):
        return 3                                   # white light bar, headlights
    if lum < 0.05:
        return 1 if (p.z > 0.62 and NOSE + 0.9 < p.x < TAIL - 0.6) else 2
    return 0


# Material slots must exist before indices are written, or Blender clamps them all to slot 0.
body.data.materials.clear()
for n in CLASSES:
    body.data.materials.append(bpy.data.materials.get(n) or bpy.data.materials.new(n))
bm = bmesh.new(); bm.from_mesh(body.data)
bm.faces.ensure_lookup_table()
cls = np.zeros(len(bm.faces), np.int8)
for f in bm.faces:
    p = f.calc_center_median()
    c, d = ref_colour(p)
    cls[f.index] = classify(c, p) if d < 0.06 else 0
# Smooth the class map spatially: diffuse one-hot class weights over face neighbours (about 4 cm),
# then take the strongest class. Boundaries come out as smooth curves instead of ragged speckle.
nb = np.full((len(bm.faces), 3), -1, np.int64)
for f in bm.faces:
    ns = [g.index for e in f.edges for g in e.link_faces if g is not f][:3]
    nb[f.index, :len(ns)] = ns
nb = np.where(nb < 0, np.arange(len(bm.faces))[:, None], nb)
W = np.eye(len(CLASSES))[cls]
W[:, 3:] *= 4.0                                    # lights are small: don't let paint swallow them
for _ in range(14):
    W = 0.4 * W + 0.2 * (W[nb[:, 0]] + W[nb[:, 1]] + W[nb[:, 2]])
cls = W.argmax(1).astype(np.int8)

# Design lines: fit smooth boundary curves to the classified areas, then redraw the classes from the
# curves, so every material edge is a clean line like a real panel edge.
cen = np.array([f.calc_center_median()[:] for f in bm.faces])
nrm = np.array([f.normal[:] for f in bm.faces])


def smooth_curve(xb, vals, sigma=4):
    ok = ~np.isnan(vals)
    v = np.interp(np.arange(len(vals)), np.where(ok)[0], vals[ok])
    r = 3 * sigma
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2); k /= k.sum()
    return np.convolve(np.pad(v, r, mode='edge'), k, mode='valid')


BINS = np.arange(NOSE, TAIL + 0.02, 0.02)
bi = np.clip(np.digitize(cen[:, 0], BINS) - 1, 0, len(BINS) - 2)
xb = (BINS[:-1] + BINS[1:]) / 2
old = cls.copy()
# Glass: lowest glass point in each 2 cm slice -> smooth glass-base line; front and rear limits.
g = old == 1
gl = np.full(len(xb), np.nan)
for k in range(len(xb)):
    zs = cen[g & (bi == k), 2]
    if len(zs) > 25:
        gl[k] = np.percentile(zs, 4)
have = np.where(~np.isnan(gl))[0]
x_g0, x_g1 = xb[have[0]] + 0.01, xb[have[-1]] - 0.01
glass_base = smooth_curve(xb, gl, sigma=8)
# --- slice the mesh exactly along the design lines, so redrawn materials end on clean cuts
side_rows = (np.abs(cen[:, 1]) > 0.5) & (cen[:, 2] < 0.55)
tl0 = np.full(len(xb), np.nan)
for k in range(len(xb)):
    zs = cen[(old == 2) & side_rows & (bi == k), 2]
    if len(zs) > 10:
        tl0[k] = np.percentile(zs, 90)
tl0 = np.where(np.isnan(tl0), np.nan, np.minimum(tl0, 0.30))   # the photos put the black band's top near 0.28 m
sill0 = smooth_curve(xb, tl0, sigma=12)
front0 = (nrm[:, 0] < -0.55) & (cen[:, 0] < NOSE + 0.45)
rear0 = (nrm[:, 0] > 0.55) & (cen[:, 0] > TAIL - 0.45)
zf0 = np.percentile(cen[front0 & (old == 2), 2], 92) if (front0 & (old == 2)).sum() > 50 else 0.38
zr0 = np.percentile(cen[rear0 & (old == 2), 2], 80) if (rear0 & (old == 2)).sum() > 50 else 0.5
reds0 = old == 4
zred0 = float(np.median(cen[reds0, 2])) if reds0.sum() > 30 else None
cuts = []                                          # (point, normal, x range, z range)
REAR_ZONE, REAR_HALF, FRONT_ZONE = 0.30, 0.80, 0.20
step = 5
for k in range(0, len(xb) - step, step):
    for curve, lo, hi, zband in ((glass_base, x_g0, x_g1, 0.05), (sill0, NOSE, TAIL, 0.05)):
        if xb[k + step] < lo or xb[k] > hi:
            continue
        p1, p2 = Vector((xb[k], 0, curve[k])), Vector((xb[k + step], 0, curve[k + step]))
        d = (p2 - p1).normalized()
        cuts.append((p1, Vector((-d.z, 0, d.x)), (xb[k] - 0.012, xb[k + step] + 0.012), (min(curve[k], curve[k + step]) - zband, max(curve[k], curve[k + step]) + zband)))
for z in [zf0, zf0 + 0.014]:
    cuts.append((Vector((NOSE, 0, z)), Vector((0, 0, 1)), (NOSE - 0.1, NOSE + 0.45), (z - 0.05, z + 0.05)))
for z in [zr0] + ([zred0 - 0.011, zred0 + 0.011] if zred0 else []):
    cuts.append((Vector((TAIL, 0, z)), Vector((0, 0, 1)), (TAIL - 0.45, TAIL + 0.1), (z - 0.05, z + 0.05)))
cuts.append((Vector((NOSE + 3.47, 0, 1.0)), Vector((1, 0, 0)), (NOSE + 3.40, NOSE + 3.54), (0.7, 1.4)))
for xg in (x_g0, x_g1):                                    # where the glass starts and ends along the car
    cuts.append((Vector((xg, 0, 1.0)), Vector((1, 0, 0)), (xg - 0.05, xg + 0.05), (0.55, 1.4)))
for sg in (-1, 1):                                          # front fascia corners
    cuts.append((Vector((NOSE, sg * 0.66, 0.3)), Vector((0, 1, 0)), (NOSE - 0.1, NOSE + 0.45), (0.1, 0.5)))
cuts.append((Vector((NOSE, 0, 0.24)), Vector((0, 0, 1)), (NOSE - 0.1, NOSE + 0.45), (0.15, 0.33)))
# Fascia zones by position (the diffuser and lip geometry faces every way, so normals can't decide):
# exact planes where the rear zone starts and ends and where the front lip zone ends.
cuts.append((Vector((TAIL - REAR_ZONE, 0, 0.4)), Vector((1, 0, 0)), (TAIL - REAR_ZONE - 0.05, TAIL - REAR_ZONE + 0.05), (0.0, zr0 + 0.05)))
for sg in (-1, 1):
    cuts.append((Vector((TAIL, sg * REAR_HALF, 0.4)), Vector((0, 1, 0)), (TAIL - REAR_ZONE - 0.05, TAIL + 0.1), (0.0, zr0 + 0.05)))
cuts.append((Vector((NOSE + FRONT_ZONE, 0, 0.3)), Vector((1, 0, 0)), (NOSE + FRONT_ZONE - 0.05, NOSE + FRONT_ZONE + 0.05), (0.0, zf0 + 0.05)))
for sg in (-1, 1):
    cuts.append((Vector((0, sg * 0.42, 1.0)), Vector((0, 1, 0)), (NOSE + 3.4, x_g1 + 0.05), (0.7, 1.4)))
# Low corner zones, full width: behind the rear arches and ahead of the front ones.
X_LOW_R, X_LOW_F, Z_LOW_R, Z_LOW_F = AXLES[1] + 0.40, AXLES[0] - 0.40, 0.30, 0.24
cuts.append((Vector((X_LOW_R, 0, 0.2)), Vector((1, 0, 0)), (X_LOW_R - 0.05, X_LOW_R + 0.05), (0.0, Z_LOW_R + 0.03)))
cuts.append((Vector((TAIL, 0, Z_LOW_R)), Vector((0, 0, 1)), (X_LOW_R - 0.03, TAIL + 0.1), (Z_LOW_R - 0.05, Z_LOW_R + 0.05)))
cuts.append((Vector((X_LOW_F, 0, 0.2)), Vector((1, 0, 0)), (X_LOW_F - 0.05, X_LOW_F + 0.05), (0.0, Z_LOW_F + 0.03)))
cuts.append((Vector((NOSE, 0, Z_LOW_F)), Vector((0, 0, 1)), (NOSE + 0.4, X_LOW_F + 0.03), (Z_LOW_F - 0.05, Z_LOW_F + 0.05)))
bm.faces.ensure_lookup_table()
fc = np.array([f.calc_center_median()[:] for f in bm.faces])
fc0 = fc.copy()                                   # the original faces, for carrying classes over
for co_, no_, (x0, x1), (z0, z1) in cuts:
    pick = np.where((fc[:, 0] > x0) & (fc[:, 0] < x1) & (fc[:, 2] > z0) & (fc[:, 2] < z1))[0]
    if not len(pick):
        continue
    bm.faces.ensure_lookup_table()
    faces = [bm.faces[i] for i in pick if i < len(bm.faces)]
    geom = list({v for f in faces for v in f.verts}) + list({e for f in faces for e in f.edges}) + faces
    bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co_, plane_no=no_)
    # Pieces from this cut must be visible to later cuts, or crossing lines stay ragged.
    bm.faces.ensure_lookup_table()
    for i in pick:
        if i < len(bm.faces):
            fc[i] = bm.faces[i].calc_center_median()[:]
    if len(bm.faces) > len(fc):
        fc = np.vstack([fc, [bm.faces[i].calc_center_median()[:] for i in range(len(fc), len(bm.faces))]])
bm.faces.ensure_lookup_table()
# Faces changed: recompute centres, normals and the old classes (nearest original face by centre).
from mathutils.kdtree import KDTree
kd = KDTree(len(fc0))
for i, c_ in enumerate(fc0):
    kd.insert(c_, i)
kd.balance()
cen = np.array([f.calc_center_median()[:] for f in bm.faces])
nrm = np.array([f.normal[:] for f in bm.faces])
old = np.array([old[kd.find(c_)[1]] for c_ in cen], np.int8)
bi = np.clip(np.digitize(cen[:, 0], BINS) - 1, 0, len(BINS) - 2)
print('CUTS', len(cuts), 'faces now', len(bm.faces))

# The rules read the same piecewise-linear lines the cuts were made along (knots every 10 cm).
KN = xb[0::step]
def glass_line(x): return np.interp(x, KN, glass_base[0::step])
def sill_line(x): return np.interp(x, KN, sill0[0::step])

new = old.copy()
new[old == 1] = 0
new[old == 4] = 0                                          # red comes back below as an exact band
in_x = (cen[:, 0] > x_g0) & (cen[:, 0] < x_g1)
behind_windows = cen[:, 0] > NOSE + 3.47          # past the side windows only the rear glass spine is glass
new[in_x & (cen[:, 2] >= glass_line(cen[:, 0]) - 0.0005) & (nrm[:, 2] > -0.3) & (~behind_windows | (np.abs(cen[:, 1]) < 0.42))] = 1
# Lower trim: highest trim point on the lower sides per slice -> smooth sill line.
near_arch = np.min([np.hypot(cen[:, 0] - ax, cen[:, 2] - WHEEL_R) for ax in AXLES], 0) < 0.47
side_low = (np.abs(cen[:, 1]) > 0.5) & (cen[:, 2] < 0.55)   # position only: normals flicker on the curved lower body
tl = np.full(len(xb), np.nan)
for k in range(len(xb)):
    zs = cen[(old == 2) & side_low & (bi == k), 2]
    if len(zs) > 10:
        tl[k] = np.percentile(zs, 90)
sill = sill0                                     # the exact line the mesh was cut along
new[(new == 2)] = 0
new[side_low & (cen[:, 2] <= sill_line(cen[:, 0]) + 0.0005) & (~near_arch | (cen[:, 2] < 0.16))] = 2
new[(cen[:, 2] < 0.13) & (nrm[:, 2] < 0)] = 2              # underbody, by height: normals flicker on the curved edge
# Nose and tail fascias: faces looking forward / back, below a fitted fascia top.
front = (nrm[:, 0] < -0.55) & (cen[:, 0] < NOSE + 0.45)
rear = (nrm[:, 0] > 0.55) & (cen[:, 0] > TAIL - 0.45)
z_front, z_rear = zf0, zr0                       # same planes as the cuts
new[front & (cen[:, 2] <= z_front) & ((np.abs(cen[:, 1]) < 0.66) | (cen[:, 2] < 0.24))] = 2   # between the fender blades
# By position too: everything below the fascia tops in the nose lip and tail diffuser zones is trim.
new[(cen[:, 0] < NOSE + FRONT_ZONE) & (cen[:, 2] <= z_front) & (np.abs(cen[:, 1]) < 0.66)] = 2
new[(cen[:, 0] > TAIL - REAR_ZONE) & (cen[:, 2] <= z_rear) & (np.abs(cen[:, 1]) < REAR_HALF)] = 2
new[(cen[:, 0] > X_LOW_R) & (cen[:, 2] <= Z_LOW_R)] = 2
new[(cen[:, 0] < X_LOW_F) & (cen[:, 2] <= Z_LOW_F)] = 2
# Light bar: a thin band right above the front fascia; tail light: band at the red light's height.
new[front & (cen[:, 2] > z_front) & (cen[:, 2] <= z_front + 0.014)] = 3
reds = old == 4
if reds.sum() > 30 and zred0:
    z_red = zred0; y_red = np.percentile(np.abs(cen[reds, 1]), 98)
    tail_face = (cen[:, 0] > TAIL - 0.45) & (nrm[:, 0] > 0.2)    # loose normal test: just not the deck
    new[tail_face & (np.abs(cen[:, 2] - z_red) < 0.011) & (np.abs(cen[:, 1]) < y_red)] = 4
new[old == 3] = 3                                          # keep the headlight slits found by colour
cls = new
# Speckle cleanup: where the scan surface folds back over a boundary, it leaves small islands of one material
# inside another. Merge paint/glass/trim islands under ISLAND_AREA into the class they share most edges with.
# Lights are thin by design and stay as they are.
ISLAND_AREA = 0.0025                                       # 25 cm^2
bm.faces.ensure_lookup_table()
area = np.array([f.calc_area() for f in bm.faces])
nbrs = [[l.link_loop_radial_next.face.index for l in f.loops if l.link_loop_radial_next.face is not f] for f in bm.faces]
for _ in range(3):
    seen = np.zeros(len(cls), bool); flips = 0
    for i0 in range(len(cls)):
        if seen[i0] or cls[i0] > 2:
            continue
        k = cls[i0]; comp = [i0]; seen[i0] = True; j = 0
        while j < len(comp):
            for n in nbrs[comp[j]]:
                if not seen[n] and cls[n] == k:
                    seen[n] = True; comp.append(n)
            j += 1
        if area[comp].sum() >= ISLAND_AREA:
            continue
        border = [cls[n] for c in comp for n in nbrs[c] if cls[n] != k]
        if border:
            cls[comp] = np.bincount(border).argmax(); flips += 1
    print('ISLANDS merged', flips)
    if not flips:
        break
print('LINES glass x', round(x_g0, 2), round(x_g1, 2), 'fascia tops', round(z_front, 3), round(z_rear, 3))
bm.faces.ensure_lookup_table()
for f in bm.faces:
    f.material_index = int(cls[f.index])
bm.to_mesh(body.data); bm.free()
print('CLASSES', {n: int((cls == k).sum()) for k, n in enumerate(CLASSES)})
select_only([body]); bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))

# ---------------------------------------------------------------- butterfly doors (outline from Tesla's side photo)
DOOR_OUTLINE = [(1.47, .79), (1.54, .29), (2.59, .29), (2.80, .92), (2.84, 1.30), (2.11, 1.30)]
DOOR_OPEN = math.radians(72)


def in_poly(x, z, poly):
    hit = False
    for (x1, z1), (x2, z2) in zip(poly, poly[1:] + poly[:1]):
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            hit = not hit
    return hit


def slice_outline(obj, side):
    bm = bmesh.new(); bm.from_mesh(obj.data)
    for (x1, z1), (x2, z2) in zip(DOOR_OUTLINE, DOOR_OUTLINE[1:] + DOOR_OUTLINE[:1]):
        p1, p2 = Vector((NOSE + x1, 0, z1)), Vector((NOSE + x2, 0, z2))
        d = (p2 - p1).normalized()
        geom = [f for f in bm.faces if side * f.calc_center_median().y > 0.35 and NOSE + 1.3 < f.calc_center_median().x < NOSE + 3.0]
        bmesh.ops.bisect_plane(bm, geom=list({v for f in geom for v in f.verts}) + list({e for f in geom for e in f.edges}) + geom,
                               plane_co=p1, plane_no=Vector((-d.z, 0, d.x)))
    bm.to_mesh(obj.data); bm.free()


def split(obj, test, name):
    select_only([obj]); bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='DESELECT')
    bm = bmesh.from_edit_mesh(obj.data); n = 0
    for f in bm.faces:
        if test(f.calc_center_median()):
            f.select = True; n += 1
    bmesh.update_edit_mesh(obj.data)
    if n:
        bpy.ops.mesh.separate(type='SELECTED')
    bpy.ops.object.mode_set(mode='OBJECT')
    new = [o for o in bpy.context.selected_objects if o is not obj]
    if not new:
        return None
    new[0].name = name
    return new[0]


body_bvh = BVHTree.FromObject(body, bpy.context.evaluated_depsgraph_get())


def surface_y(x, z, side):
    loc, *_ = body_bvh.ray_cast(Vector((x, side * 3, z)), Vector((0, -side, 0)))
    return loc.y if loc else side * 0.9


doors = []
for i, side in enumerate((-1, 1)):
    slice_outline(body, side)
    d = split(body, lambda c, side=side: side * c.y > 0.45 and in_poly(c.x - NOSE, c.z, DOOR_OUTLINE), f'Door{i}')
    if not d:
        continue
    A = Vector((NOSE + 1.47, surface_y(NOSE + 1.47, 0.79, side), 0.79))
    B = Vector((NOSE + 2.02, surface_y(NOSE + 2.02, 1.10, side), 1.10))
    d.data.transform(Matrix.Translation(-A)); d.location = A
    axis = (B - A).normalized()
    cen = sum((v.co for v in d.data.vertices), Vector()) / len(d.data.vertices)
    d['hingeAxis'] = [axis.x, axis.z, -axis.y]
    d['openAngle'] = max((DOOR_OPEN, -DOOR_OPEN), key=lambda a: (Matrix.Rotation(a, 3, axis) @ cen).z)
    doors.append(d)
print('DOORS', [(d.name, len(d.data.polygons)) for d in doors])

# ---------------------------------------------------------------- anchors for the page
body_bvh = BVHTree.FromObject(body, bpy.context.evaluated_depsgraph_get())
deck, *_ = body_bvh.ray_cast(Vector((NOSE + 4.40, 0, 3)), Vector((0, 0, -1)))
tail, *_ = body_bvh.ray_cast(Vector((5, 0, 0.67)), Vector((-1, 0, 0)))
anchors = bpy.data.objects.new('Anchors', None); bpy.context.collection.objects.link(anchors)
anchors['deckY'] = deck.z if deck else 0.95
anchors['tailX'] = tail.x if tail else TAIL - 0.05
anchors['axleX'] = AXLES
anchors['wheelR'] = WHEEL_R
if PREALIGNED:
    anchors['archR'] = 0.40                                  # retopo_roadster.py cut exact arches at this radius
anchors['plateY'], anchors['plateZ'], anchors['plateW'], anchors['plateH'] = 0.671, -0.01, 0.33, 0.134
anchors['plateX'] = (tail.x if tail else TAIL - 0.05)
# Light paths for the page's light tubes (page axes: x, y up, z = -Blender Y), seated on the surface.
def surface_path(z, from_front, ys, offset):
    pts = []
    for yb in ys:
        o = Vector((NOSE - 1 if from_front else TAIL + 1, yb, z))
        hit, *_ = body_bvh.ray_cast(o, Vector((1 if from_front else -1, 0, 0)))
        if hit is not None:
            pts.append([hit.x + (-offset if from_front else offset), hit.z, -hit.y])
    return pts


anchors['frontLightPath'] = surface_path(zf0 + 0.007, True, np.linspace(-0.66, 0.66, 45), 0.004)
anchors['tailLightPath'] = surface_path(zred0 if zred0 else 0.846, False, np.linspace(-0.85, 0.85, 65), 0.004)
print('ANCHORS', {k: anchors[k] for k in anchors.keys() if not k.endswith('Path')},
      'paths', len(anchors['frontLightPath']), len(anchors['tailLightPath']))

# ================================================================ modelled parts
before = set(bpy.context.scene.objects)
bpy.ops.import_scene.gltf(filepath=os.path.join(OUT_DIR, 'parts.glb'))
for o in set(bpy.context.scene.objects) - before:
    if o.name.split('.')[0] not in ('Wheel_Aero', 'Wheel_Turbine', 'Caliper'):
        bpy.data.objects.remove(o, do_unlink=True)
before = set(bpy.context.scene.objects)
bpy.ops.import_scene.gltf(filepath=os.path.join(HERE, 'source/parts-handbuilt.glb'))
for o in set(bpy.context.scene.objects) - before:
    if o.name.split('.')[0] not in ('Wing', 'Seat'):
        bpy.data.objects.remove(o, do_unlink=True)
bpy.data.objects.remove(ref, do_unlink=True)

# ================================================================ export: Draco GLB, then base64 parts for the artifact
glb = os.path.join(OUT_DIR, 'roadster-body.glb')
bpy.ops.export_scene.gltf(filepath=glb, export_format='GLB', export_apply=True, export_yup=True, export_extras=True,
                          export_materials='EXPORT', export_cameras=False, export_lights=False,
                          export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=7,
                          export_draco_position_quantization=16, export_draco_normal_quantization=12)
data = open(glb, 'rb').read()
b64 = base64.b64encode(data).decode()
PART = 9_000_000
parts = [b64[i:i + PART] for i in range(0, len(b64), PART)]
for old in os.listdir(OUT_DIR):
    if old.startswith('roadster-body.part'):
        os.remove(os.path.join(OUT_DIR, old))
for i, chunk in enumerate(parts):
    open(os.path.join(OUT_DIR, f'roadster-body.part{i}.txt'), 'w').write(chunk)
json.dump({'parts': len(parts), 'bytes': len(data), 'draco': True}, open(os.path.join(OUT_DIR, 'roadster-body.parts.json'), 'w'))
print('EXPORTED', len(data), 'bytes in', len(parts), 'parts')

# ================================================================ preview with real materials
if RENDER:
    def setm(name, rgb, rough, metal=0.0, coat=0.0, emit=None, alpha=None):
        m = bpy.data.materials.get(name)
        if not m:
            return
        m.use_nodes = True
        b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        b.inputs['Base Color'].default_value = (*rgb, 1); b.inputs['Roughness'].default_value = rough
        b.inputs['Metallic'].default_value = metal; b.inputs['Coat Weight'].default_value = coat
        if emit:
            b.inputs['Emission Color'].default_value = (*emit, 1); b.inputs['Emission Strength'].default_value = 6
    setm('Paint', (0.80, 0.81, 0.79), 0.25, coat=1.0)
    setm('Glass', (0.09, 0.06, 0.025), 0.03, metal=0.85)
    setm('Trim', (0.015, 0.015, 0.017), 0.4)
    setm('LightWhite', (0.2, 0.2, 0.2), 0.3, emit=(0.95, 0.97, 1))
    setm('LightRed', (0.2, 0, 0), 0.3, emit=(1, 0.03, 0.03))
    setm('LightAmber', (0.3, 0.15, 0), 0.3, emit=(1, 0.45, 0.05))
    wa = next(o for o in bpy.context.scene.objects if o.name.startswith('Wheel_Aero'))
    cal = next(o for o in bpy.context.scene.objects if o.name.startswith('Caliper'))
    for o in bpy.context.scene.objects:
        if o.name.split('.')[0] in ('Wheel_Turbine', 'Seat'):
            o.hide_render = True
    for ax in AXLES:
        for sd in (-1, 1):
            w = wa.copy(); bpy.context.collection.objects.link(w)
            w.location = (ax, sd * 0.78, WHEEL_R)
            if sd > 0:
                w.scale = (1, -1, 1)
            c2 = cal.copy(); bpy.context.collection.objects.link(c2)
            c2.location = w.location; c2.scale = w.scale
    wa.hide_render = cal.hide_render = True
    wing = next(o for o in bpy.context.scene.objects if o.name.startswith('Wing'))
    wing.location = (NOSE + 4.40, 0, anchors['deckY'] + 0.02)
    scn = bpy.context.scene
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
    scn.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'
    scn.render.resolution_x, scn.render.resolution_y = 1600, 900
    world = bpy.data.worlds.new('W'); world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.03, 0.03, 0.035, 1); scn.world = world
    for loc, e, sz in (((-2, -3, 5), 1500, 6), ((3, 3, 4), 700, 4), ((0, 0, 6), 900, 3), ((-6, 0, 1.5), 400, 3), ((6, 0, 1.5), 300, 3)):
        bpy.ops.object.light_add(type='AREA', location=loc); L = bpy.context.active_object
        L.data.energy, L.data.size = e, sz
        L.rotation_euler = (Vector((0, 0, 0.5)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    cam = bpy.data.objects.new('Cam', bpy.data.cameras.new('Cam')); scn.collection.objects.link(cam); scn.camera = cam
    views = {'34front': ((-6.2, -4.8, 1.9), (0, 0, 0.5), 45), 'side': ((0, -9, 0.7), (0, 0, 0.5), 45),
             '34rear': ((5.8, -4.4, 2.0), (0, 0, 0.5), 45), 'front': ((-8, 0, 0.8), (0, 0, 0.5), 45),
             # close-ups where artifacts showed before: rear quarter and arch, front lip
             'rq-close': ((4.6, -3.2, 1.2), (1.75, -0.6, 0.5), 75), 'front-close': ((-4.6, -2.4, 0.9), (NOSE + 0.3, -0.2, 0.3), 75)}
    for name, (loc, tgt, lens) in views.items():
        cam.location = loc; cam.data.lens = lens
        cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
        scn.render.filepath = os.path.join(OUT_DIR, f'assembled-{name}.png')
        bpy.ops.render.render(write_still=True)
    print('RENDERED')
