"""Retopologise the Roadster body into a clean, panelled model.

Run:  blender -b --python retopo_roadster.py -- <in.glb> <out_dir> [--stage fuse|quads|all] [--render]

The input is the current runtime model (roadster-body.glb): a generated triangle mesh with clipped
material regions, separate door pieces and procedural nose and rear patches laid over it. That stack
causes the artifacts (jagged material edges, gaps, overlapping surfaces). This script rebuilds it:

1. fuse   Join body, closed doors and patches; weld; voxel-remesh into one closed shell. Overlaps,
          gaps and z-fighting disappear because only one surface survives.
2. quads  QuadriFlow retopology of the shell into a clean quad mesh, projected back onto the shell
          and subdivided, so reflections run smoothly.
3. panels Materials transferred from the input and redrawn along exact design-line cuts; doors split
          with hinge data; lights seated on the surface.  (later stages)

Axes: Blender X = length, Y = width, Z = up (glTF import of the page's x, y-up, z).
"""
import math, os, sys, time
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
SRC, OUT = argv[0], argv[1]
STAGE = argv[argv.index('--stage') + 1] if '--stage' in argv else 'all'
RENDER = '--render' in argv
VOXEL = 0.007
os.makedirs(OUT, exist_ok=True)
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:6.1f}s]', *a, flush=True)


def select_only(objs, active=None):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or objs[0]


def faces(o):
    return len(o.data.polygons)


# ================================================================ load
# The base shell is the closed Hunyuan source (source/hunyuan31-pro-geometry.glb). The current runtime model
# (SRC) is only used to align it and, later, to transfer materials and anchors.
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
objs = {o.name: o for o in bpy.context.scene.objects}
anchors = dict(objs['Anchors'].items()) if 'Anchors' in objs else {}
AXLES = list(anchors.get('axleX', [-1.371, 1.532]))
WHEEL_R = float(anchors.get('wheelR', 0.345))
ref_parts = [objs[n] for n in ('Body', 'Door0', 'Door1') if n in objs]
for o in list(bpy.context.scene.objects):
    if o not in ref_parts:
        bpy.data.objects.remove(o, do_unlink=True)
select_only(ref_parts); bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.join(); refobj = bpy.context.view_layer.objects.active; refobj.name = 'MaterialReference'
log('reference model', faces(refobj), 'axles', AXLES)

before = set(bpy.context.scene.objects)
bpy.ops.import_scene.gltf(filepath=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'source/hunyuan31-pro-geometry.glb'))
new = [o for o in bpy.context.scene.objects if o not in before and o.type == 'MESH']
select_only(new)
if len(new) > 1:
    bpy.ops.object.join()
shell = bpy.context.view_layer.objects.active; shell.name = 'Shell'
bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM'); bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for o in list(bpy.context.scene.objects):
    if o not in (shell, refobj):
        bpy.data.objects.remove(o, do_unlink=True)


def verts_np(o):
    co = np.empty(len(o.data.vertices) * 3); o.data.vertices.foreach_get('co', co); return co.reshape(-1, 3)


# Same normalisation as finish_roadster.py: long axis on X, 4.64 m, centred, wheels on the ground;
# pick the nose direction that best matches the current model.
v = verts_np(shell)
if np.ptp(v[:, 1]) > np.ptp(v[:, 0]):
    shell.data.transform(Matrix.Rotation(math.pi / 2, 4, 'Z'))
v = verts_np(shell); mn, mx = v.min(0), v.max(0)
shell.data.transform(Matrix.Scale(4.64 / (mx[0] - mn[0]), 4) @ Matrix.Translation(Vector((-(mn[0] + mx[0]) / 2, -(mn[1] + mx[1]) / 2, -mn[2]))))
from mathutils.bvhtree import BVHTree
ref_bvh = BVHTree.FromObject(refobj, bpy.context.evaluated_depsgraph_get())


def align_err():
    vs = verts_np(shell)[::max(1, len(shell.data.vertices) // 3000)]
    return float(np.mean([ref_bvh.find_nearest(Vector(p))[3] for p in vs]))


e0 = align_err(); shell.data.transform(Matrix.Rotation(math.pi, 4, 'Z')); e1 = align_err()
if e0 < e1:
    shell.data.transform(Matrix.Rotation(math.pi, 4, 'Z'))
log('aligned shell, mean distance to current model cm', round(100 * min(e0, e1), 2))

# ================================================================ 1. fuse: cut the baked-in wheels, voxel remesh
for ax in AXLES:
    for sd in (-1, 1):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=96, radius1=WHEEL_R + 0.022, radius2=WHEEL_R + 0.022, depth=0.5)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, 'X'), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(ax, sd * 0.86, WHEEL_R), verts=bm.verts)
        me = bpy.data.meshes.new('WheelCut'); bm.to_mesh(me); bm.free()
        cut = bpy.data.objects.new('WheelCut', me); bpy.context.collection.objects.link(cut)
        mod = shell.modifiers.new('Cut', 'BOOLEAN'); # Manifold solver: EXACT collapsed this cage to a few faces on some arches (it passed at 0.375 m by luck).
        mod.operation, mod.solver, mod.object = 'DIFFERENCE', 'MANIFOLD', cut
        select_only([shell]); bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(cut, do_unlink=True)
log('wheels cut', faces(shell))
rem = shell.modifiers.new('Voxel', 'REMESH')
rem.mode, rem.voxel_size, rem.adaptivity = 'VOXEL', VOXEL, 0.0
select_only([shell]); bpy.ops.object.modifier_apply(modifier=rem.name)
log('voxel shell', faces(shell))
cs = shell.modifiers.new('Relax', 'CORRECTIVE_SMOOTH')
cs.iterations, cs.factor, cs.smooth_type, cs.use_only_smooth = 8, 0.5, 'LENGTH_WEIGHTED', True
select_only([shell]); bpy.ops.object.modifier_apply(modifier=cs.name)
# Keep only the car: voxelising leaves a few tiny stray specks, and QuadriFlow refuses any mesh that has them.
bm = bmesh.new(); bm.from_mesh(shell.data); bm.faces.ensure_lookup_table()
seen, isl = set(), []
for f in bm.faces:
    if f.index in seen:
        continue
    st, cur = [f], []
    seen.add(f.index)
    while st:
        g = st.pop(); cur.append(g)
        for e in g.edges:
            for h in e.link_faces:
                if h.index not in seen:
                    seen.add(h.index); st.append(h)
    isl.append(cur)
isl.sort(key=len, reverse=True)
bmesh.ops.delete(bm, geom=[f for i in isl[1:] for f in i], context='FACES')
bm.to_mesh(shell.data); bm.free()
bm = bmesh.new(); bm.from_mesh(shell.data)
log('shell boundary edges', sum(e.is_boundary for e in bm.edges), 'non-manifold', sum(not e.is_manifold for e in bm.edges))
bm.free()
bpy.ops.object.shade_smooth()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'stage-fuse.blend'))


def clay_render(objs_visible, name, views=None):
    scn = bpy.context.scene
    for o in scn.objects:
        o.hide_render = o not in objs_visible and o.type == 'MESH'
    m = bpy.data.materials.get('ClayPreview') or bpy.data.materials.new('ClayPreview')
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (0.78, 0.78, 0.78, 1); b.inputs['Roughness'].default_value = 0.16
    b.inputs['Coat Weight'].default_value = 1.0
    saved = {}
    for o in objs_visible:
        saved[o.name] = [s.material for s in o.material_slots]
        if not o.material_slots:
            o.data.materials.append(m)
        for s in o.material_slots:
            s.material = m
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
    scn.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'
    scn.render.resolution_x, scn.render.resolution_y = 1500, 900
    if not scn.world:
        w = bpy.data.worlds.new('W'); w.use_nodes = True
        w.node_tree.nodes['Background'].inputs[0].default_value = (0.03, 0.03, 0.035, 1); scn.world = w
        for loc, e, sz in (((-2, -3, 5), 1500, 6), ((3, 3, 4), 700, 4), ((0, 0, 6), 900, 3), ((-6, 0, 1.5), 400, 3), ((6, -2, 1.5), 400, 3)):
            bpy.ops.object.light_add(type='AREA', location=loc); L = bpy.context.active_object
            L.data.energy, L.data.size = e, sz
            L.rotation_euler = (Vector((0, 0, 0.5)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    cam = bpy.data.objects.get('PreviewCam')
    if not cam:
        cam = bpy.data.objects.new('PreviewCam', bpy.data.cameras.new('PreviewCam')); scn.collection.objects.link(cam)
    scn.camera = cam
    views = views or {'34front': (-5.4, -4.2, 1.8), '34rear': (5.2, -4.0, 1.9), 'side': (0, -8.5, 0.7)}
    for vname, loc in views.items():
        cam.location = loc; cam.data.lens = 42
        cam.rotation_euler = (Vector((0, 0, 0.5)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
        scn.render.filepath = os.path.join(OUT, f'{name}-{vname}.png'); bpy.ops.render.render(write_still=True)
    for o in objs_visible:
        for s, mat in zip(o.material_slots, saved[o.name]):
            s.material = mat


if RENDER and STAGE == 'fuse':
    clay_render([shell], 'fuse')
    log('rendered fuse')
if STAGE == 'fuse':
    sys.exit(0)

# ================================================================ 2. quads: QuadriFlow cage, projected and subdivided
QUAD_TARGET = int(argv[argv.index('--quads') + 1]) if '--quads' in argv else 60000
cage = shell.copy(); cage.data = shell.data.copy(); cage.name = 'Cage'
bpy.context.collection.objects.link(cage)
select_only([cage])
# Run on the clean voxel shell directly: decimating first leaves it non-manifold and QuadriFlow cancels.
res = bpy.ops.object.quadriflow_remesh(use_mesh_symmetry=False, use_preserve_sharp=False, use_preserve_boundary=False,
                                       preserve_attributes=False, smooth_normals=False, mode='FACES', target_faces=QUAD_TARGET, seed=0)
if res != {'FINISHED'}:
    raise SystemExit('QuadriFlow cancelled: ' + str(res))
quads = sum(1 for p in cage.data.polygons if len(p.vertices) == 4)
log('quadriflow cage', faces(cage), 'quads', quads)
sw = cage.modifiers.new('Project', 'SHRINKWRAP'); sw.target, sw.wrap_method = shell, 'NEAREST_SURFACEPOINT'
select_only([cage]); bpy.ops.object.modifier_apply(modifier=sw.name)
SUBDIV = int(argv[argv.index('--subdiv') + 1]) if '--subdiv' in argv else 1
sub = cage.modifiers.new('Subdiv', 'SUBSURF'); sub.levels = sub.render_levels = SUBDIV; sub.quality = 3
select_only([cage]); bpy.ops.object.modifier_apply(modifier=sub.name)
# Project the subdivided surface back onto the shell: subdivision alone rounds every crease away.
# The quad topology stays clean; the shape (and its creases) comes back from the shell.
if '--no-reproject' not in argv:
    sw2 = cage.modifiers.new('Reproject', 'SHRINKWRAP'); sw2.target, sw2.wrap_method = shell, 'NEAREST_SURFACEPOINT'
    select_only([cage]); bpy.ops.object.modifier_apply(modifier=sw2.name)
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(32))
log('subdivided body', faces(cage))
# How far did smoothing move the surface from the shell? (shape fidelity)
sh_bvh = BVHTree.FromObject(shell, bpy.context.evaluated_depsgraph_get())
vs = verts_np(cage)[::max(1, len(cage.data.vertices) // 5000)]
d = np.array([sh_bvh.find_nearest(Vector(p))[3] for p in vs])
log('deviation from shell mm: median', round(1000 * np.median(d), 1), 'p95', round(1000 * np.percentile(d, 95), 1), 'max', round(1000 * d.max(), 1))
# Calm the low fascia zones (rear diffuser, front splitter): the scan's detail there is lumpy at a few mm, and
# every material line drawn across it comes out ragged. Feathered Laplacian smoothing, zone edges fade to zero.
def zone_weight(v):
    def ramp(t, w):                      # 0 -> 1 over w metres
        return np.clip(t / w, 0, 1)
    rear = ramp(v[:, 0] - 1.95, 0.12) * ramp(0.62 - v[:, 2], 0.06)
    front = ramp(-1.95 - v[:, 0], 0.12) * ramp(0.40 - v[:, 2], 0.06)
    return np.maximum(rear, front)
me = cage.data
co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
ed = np.empty(len(me.edges) * 2, np.int64); me.edges.foreach_get('vertices', ed); ed = ed.reshape(-1, 2)
deg = np.bincount(ed.ravel(), minlength=len(co)).astype(float)[:, None]
w = zone_weight(co)[:, None] * 0.5
for _ in range(int(argv[argv.index('--zone-smooth') + 1]) if '--zone-smooth' in argv else 12):
    acc = np.zeros_like(co); np.add.at(acc, ed[:, 0], co[ed[:, 1]]); np.add.at(acc, ed[:, 1], co[ed[:, 0]])
    co = co + w * (acc / np.maximum(deg, 1) - co)
me.vertices.foreach_set('co', co.ravel()); me.update()
log('fascia zones smoothed, verts weighted', int((w > 0).sum()))
# Re-cut the wheel arches as exact circles: the voxel shell leaves their edges slightly wavy.
# The radius must clear the fuse stage's own arch wall (WHEEL_R + 0.022) plus its voxel ripple; a cut that
# grazes that wall tears the lip into a sawtooth.
ARCH_R = float(argv[argv.index('--arch') + 1]) if '--arch' in argv else 0.40
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'stage-cage.blend'))   # before the arch cuts, for experiments
for ax in AXLES:
    for sd in (-1, 1):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=128, radius1=ARCH_R, radius2=ARCH_R, depth=0.6)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, 'X'), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(ax, sd * 0.9, WHEEL_R), verts=bm.verts)
        me = bpy.data.meshes.new('ArchCut'); bm.to_mesh(me); bm.free()
        cut = bpy.data.objects.new('ArchCut', me); bpy.context.collection.objects.link(cut)
        mod = cage.modifiers.new('Arch', 'BOOLEAN'); mod.operation, mod.solver, mod.object = 'DIFFERENCE', 'EXACT', cut
        n0 = len(cage.data.polygons)
        select_only([cage]); bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(cut, do_unlink=True)
        if len(cage.data.polygons) < 0.8 * n0:
            raise SystemExit(f'arch cut at x={ax:.2f} side {sd} collapsed the body ({n0} -> {len(cage.data.polygons)} faces)')
log('arches re-cut', faces(cage))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'stage-quads.blend'))
# Export the clean body on its own; finish_roadster.py then fits design lines, splits doors and adds parts.
for o in list(bpy.context.scene.objects):
    o.select_set(o is cage)
bpy.context.view_layer.objects.active = cage
cage.name = 'Body'
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, 'retopo-body.glb'), export_format='GLB', use_selection=True,
                          export_apply=True, export_yup=True, export_materials='NONE')
log('exported retopo-body.glb')
if RENDER:
    clay_render([cage], 'quads')
    log('rendered quads')

