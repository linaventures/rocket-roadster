"""Detail parts for the Roadster, modelled from scratch: wheels, tyres, brakes.

Run:  blender -b --python parts_roadster.py -- <out_dir> [--render]
Writes <out_dir>/parts.glb with Wheel_Aero, Wheel_Turbine (each spins about its axle, outer face toward -Y)
and Caliper (stays put). Proportions follow Tesla's photos: about 0.345 m tyre radius, large rim,
six slim spokes over a flush grey aero disc.
"""
import math, os, sys
import bpy, bmesh
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT_DIR = argv[0] if argv else os.path.dirname(os.path.abspath(__file__))
RENDER = '--render' in argv

R_TYRE, R_RIM, W_TYRE = 0.345, 0.268, 0.285
bpy.ops.wm.read_factory_settings(use_empty=True)


def mat(name, rgb, rough, metal=0.0, coat=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1); b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal; b.inputs['Coat Weight'].default_value = coat
    return m


M = {
    'Tire': mat('Tire', (0.025, 0.025, 0.027), 0.85),
    'Rim': mat('Rim', (0.03, 0.03, 0.033), 0.22, metal=0.6, coat=0.6),
    'AeroDisc': mat('AeroDisc', (0.32, 0.33, 0.35), 0.38, metal=0.7),
    'Accent': mat('Accent', (0.62, 0.62, 0.64), 0.3, metal=1.0),
    'BrakeDisc': mat('BrakeDisc', (0.45, 0.45, 0.46), 0.42, metal=1.0),
    'Caliper': mat('Caliper', (0.62, 0.62, 0.64), 0.3, metal=1.0),
    'Dark': mat('Dark', (0.01, 0.01, 0.01), 0.7),
}


def obj_from_bm(name, bm, mats):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(M[m])
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o)
    return o


def smooth(o, angle=40):
    bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle))


def lathe(name, profile, material, steps=192, angle=40):
    """Spin a (radius, y) profile around the Y axis."""
    bm = bmesh.new()
    vs = [bm.verts.new((0, y, r)) for r, y in profile]
    es = [bm.edges.new((vs[i], vs[i + 1])) for i in range(len(vs) - 1)]
    bmesh.ops.spin(bm, geom=vs + es, cent=(0, 0, 0), axis=(0, 1, 0), angle=math.tau, steps=steps, use_merge=True)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = obj_from_bm(name, bm, [material]); smooth(o, angle)
    return o


def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join(); objs[0].name = name
    return objs[0]


def bevel(o, width, segs=3, angle=35):
    b = o.modifiers.new('Bevel', 'BEVEL')
    b.width, b.segments, b.limit_method, b.angle_limit = width, segs, 'ANGLE', math.radians(angle)
    b.use_clamp_overlap = True


# ---------------------------------------------------------------- tyre
def tyre():
    """Low-profile tyre: rounded shoulders, slight sidewall bulge, four circumferential tread grooves."""
    h = W_TYRE / 2
    side_out = [(R_RIM + 0.004, -h + 0.012), (R_RIM + 0.02, -h - 0.002), (R_RIM + 0.045, -h - 0.008),
                (0.318, -h - 0.007), (0.333, -h + 0.002), (0.341, -h + 0.016), (R_TYRE, -h + 0.032)]
    tread = []
    grooves = [-0.085, -0.03, 0.03, 0.085]
    ys = [-h + 0.032 + k * (W_TYRE - 0.064) / 60 for k in range(61)]
    for y in ys:
        r = R_TYRE
        for g in grooves:
            if abs(y - g) < 0.006:
                r = R_TYRE - 0.008
        tread.append((r, y))
    side_in = [(r, -y) for r, y in reversed(side_out)]
    o = lathe('Tyre', side_out + tread + side_in, 'Tire', steps=240, angle=30)
    return o


# ---------------------------------------------------------------- rim, aero disc, spokes
def rim_barrel():
    h = W_TYRE / 2
    prof = [(R_RIM + 0.012, -h + 0.004), (R_RIM + 0.016, -h + 0.012), (R_RIM + 0.012, -h + 0.02), (R_RIM, -h + 0.024),
            (R_RIM - 0.006, -h + 0.04), (R_RIM - 0.008, h - 0.04), (R_RIM - 0.002, h - 0.02), (R_RIM + 0.006, h - 0.004)]
    return lathe('Barrel', prof, 'Rim', angle=30)


def aero_disc():
    # Flush, very slightly dished disc with a fine step ring, sitting just inside the lip.
    y0 = -W_TYRE / 2 + 0.03
    prof = [(0.0, y0 + 0.032), (0.06, y0 + 0.03), (0.12, y0 + 0.022), (0.20, y0 + 0.012), (0.215, y0 + 0.01),
            (0.218, y0 + 0.006), (0.255, y0 + 0.002), (R_RIM - 0.002, y0), (R_RIM - 0.002, y0 + 0.012), (0.0, y0 + 0.045)]
    return lathe('AeroDisc', prof, 'AeroDisc', angle=25)


def spokes(n=6):
    """Slim tapered spokes standing proud of the disc, rounded by a bevel."""
    out = []
    y0 = -W_TYRE / 2 + 0.018
    for k in range(n):
        bm = bmesh.new()
        r0, r1 = 0.062, R_RIM - 0.004
        w0, w1, d = 0.034, 0.018, 0.022
        quad = [(-w0 / 2, r0), (w0 / 2, r0), (w1 / 2, r1), (-w1 / 2, r1)]
        front = [bm.verts.new((x, y0, z)) for x, z in quad]
        back = [bm.verts.new((x, y0 + d, z)) for x, z in quad]
        bm.faces.new(front[::-1]); bm.faces.new(back)
        for i in range(4):
            bm.faces.new((front[i], front[(i + 1) % 4], back[(i + 1) % 4], back[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > 0.1], cuts=8)
        o = obj_from_bm('Spoke', bm, ['Rim'])
        o.data.transform(Matrix.Rotation(k / n * math.tau, 4, 'Y'))
        bevel(o, 0.006, 4, 30); smooth(o, 50)
        out.append(o)
    return out


def turbine_blades(n=10):
    out = []
    y0 = -W_TYRE / 2 + 0.03
    for k in range(n):
        bm = bmesh.new()
        prof = [(-0.04, 0.07), (0.035, 0.07), (0.05, R_RIM - 0.01), (-0.02, R_RIM - 0.01)]
        front = [bm.verts.new((x, y0, z)) for x, z in prof]
        back = [bm.verts.new((x, y0 + 0.012, z)) for x, z in prof]
        bm.faces.new(front[::-1]); bm.faces.new(back)
        for i in range(4):
            bm.faces.new((front[i], front[(i + 1) % 4], back[(i + 1) % 4], back[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        o = obj_from_bm('Blade', bm, ['Rim'])
        o.data.transform(Matrix.Rotation(0.5, 4, 'Z'))          # pitch, like a fan blade
        o.data.transform(Matrix.Rotation(k / n * math.tau, 4, 'Y'))
        bevel(o, 0.004, 3, 30); smooth(o, 50)
        out.append(o)
    disc = lathe('TurbineBack', [(0.0, -0.06), (R_RIM - 0.004, -0.06), (R_RIM - 0.004, -0.05), (0.0, -0.05)], 'Dark')
    return out + [disc]


def centre_cap():
    y0 = -W_TYRE / 2 + 0.012
    prof = [(0.0, y0), (0.04, y0 + 0.001), (0.052, y0 + 0.006), (0.056, y0 + 0.016), (0.056, y0 + 0.03), (0.0, y0 + 0.03)]
    return lathe('Cap', prof, 'Accent', steps=96)


# ---------------------------------------------------------------- brakes
def brake_disc():
    """Two-piece vented disc: friction ring with slots, and a dark hat."""
    parts = [lathe('Ring', [(0.13, 0.03), (0.195, 0.03), (0.198, 0.034), (0.198, 0.066), (0.195, 0.07), (0.13, 0.07), (0.13, 0.03)], 'BrakeDisc', steps=144)]
    parts.append(lathe('Hat', [(0.0, 0.02), (0.135, 0.02), (0.135, 0.032), (0.07, 0.032), (0.0, 0.03)], 'Dark', steps=96))
    for k in range(24):                       # curved slots on the face
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(0.004, 0.003, 0.05), verts=bm.verts)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(0.5, 3, 'Y'), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(0, 0.0295, 0.165), verts=bm.verts)
        o = obj_from_bm('Slot', bm, ['Dark'])
        o.data.transform(Matrix.Rotation(k / 24 * math.tau, 4, 'Y'))
        parts.append(o)
    return parts


def caliper():
    bm = bmesh.new()
    # A curved bridge hugging the disc's top-rear, built as a swept box along an arc.
    arc = [math.radians(a) for a in range(20, 81, 4)]
    rings = []
    for a in arc:
        c, s = math.cos(a), math.sin(a)
        r_in, r_out = 0.15, 0.225
        pts = [(r_in, 0.012), (r_out, 0.012), (r_out, 0.088), (r_in, 0.088)]
        rings.append([bm.verts.new((r * s, y, r * c)) for r, y in pts])
    for a, b in zip(rings, rings[1:]):
        for i in range(4):
            bm.faces.new((a[i], a[(i + 1) % 4], b[(i + 1) % 4], b[i]))
    bm.faces.new(rings[0][::-1]); bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = obj_from_bm('Caliper', bm, ['Caliper'])
    bevel(o, 0.012, 4, 30); smooth(o, 40)
    return o


def wheel(style):
    objs = [tyre(), rim_barrel(), centre_cap()] + brake_disc()
    if style == 'Aero':
        objs += [aero_disc()] + spokes()
    else:
        objs += turbine_blades()
    return join(objs, f'Wheel_{style}')


wa = wheel('Aero')
wt = wheel('Turbine'); wt.location = (0, 0, 2)
cal = caliper(); cal.location = (0, 0, -2)
for o in (wa, wt, cal):
    dg = bpy.context.evaluated_depsgraph_get()
    me = o.evaluated_get(dg).to_mesh()
    print('TRIS', o.name, sum(len(p.vertices) - 2 for p in me.polygons))

bpy.ops.export_scene.gltf(filepath=os.path.join(OUT_DIR, 'parts.glb'), export_format='GLB', export_apply=True,
                          export_yup=True, export_materials='EXPORT', export_cameras=False, export_lights=False)
print('EXPORTED parts.glb')

if RENDER:
    cal.location = (0, 0, 0)
    wt.location = (0, 1.0, 0)
    wt.rotation_euler = (0, 0, math.pi)
    scn = bpy.context.scene
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
    scn.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'
    scn.render.resolution_x, scn.render.resolution_y = 1400, 900
    world = bpy.data.worlds.new('W'); world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.05, 0.05, 0.055, 1); scn.world = world
    for loc, e in (((-2, -3, 2), 300), ((2, -2, 1), 150), ((0, -1, 3), 200)):
        bpy.ops.object.light_add(type='AREA', location=loc); L = bpy.context.active_object
        L.data.energy, L.data.size = e, 2
        L.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    cam = bpy.data.objects.new('Cam', bpy.data.cameras.new('Cam')); scn.collection.objects.link(cam); scn.camera = cam
    cam.location = (-0.9, -1.6, 0.35); cam.data.lens = 50
    cam.rotation_euler = (Vector((0, 0.2, 0)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    scn.render.filepath = os.path.join(OUT_DIR, 'wheels.png')
    bpy.ops.render.render(write_still=True)
    print('RENDERED')
