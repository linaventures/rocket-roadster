"""Build the drive world from real public data: the Shafer Trail run to Thelma & Louise Point (near Moab, Utah,
where the film's final chase and leap were shot, standing in for Arizona's Grand Canyon).

  python tools/prep_canyon.py <osm.json> <tile cache dir> <out dir>

Sources (fetched on demand, cached):
  - Elevation: AWS Terrain Tiles (terrarium encoding; USGS 3DEP and others), z14 near, z11 far
  - Imagery:   USGS The National Map "USGSImageryOnly" (public domain), z15 near, z12 far
  - Road:      OpenStreetMap (ODbL), from an Overpass export of highways around Dead Horse Point
Writes canyon.json (route, sizes, attributions) and base64 text parts for heights and imagery.
"""
import base64, io, json, math, os, sys, urllib.request
import numpy as np
from PIL import Image, ImageEnhance

OSM, CACHE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(CACHE, exist_ok=True); os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'RocketRoadsterFanProject/1.0 (personal, non-commercial)'}
TL = (38.4519418, -109.7346153)            # Thelma & Louise Point (OSM viewpoint)
SHAFER, SPUR = 27230983, 338153573         # Shafer Trail, and the track out to the point
ROUTE_KM = 6.5                             # how much Shafer Trail to drive before the turn-off
NEAR, NN = 9000.0, 512                     # near terrain: 9 km square, 512 cells (17.6 m)
CELL_N = NEAR / NN
FAR, NF = 48000.0, 192                     # horizon terrain: 48 km square, 192 cells (250 m)
PATCH, NP = 1400.0, 350                    # rim patch: 1.4 km square, 350 cells (4 m), so the cliff is a real cliff


def fetch(url, path):
    if not os.path.exists(path):
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: open(path, 'wb').write(r.read())
    return path


def merc(lat, lon, z):                     # global pixel coordinates at zoom z (256 px tiles)
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def mosaic(kind, z, lat0, lat1, lon0, lon1):
    x0, y1 = merc(lat0, lon0, z); x1, y0 = merc(lat1, lon1, z)
    tx0, tx1, ty0, ty1 = int(x0 // 256), int(x1 // 256), int(y0 // 256), int(y1 // 256)
    img = Image.new('RGB', ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if kind == 'dem': url, ext = f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{tx}/{ty}.png', 'png'
            else: url, ext = f'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{ty}/{tx}', 'jpg'
            p = fetch(url, os.path.join(CACHE, f'{kind}-{z}-{tx}-{ty}.{ext}'))
            img.paste(Image.open(p).convert('RGB'), ((tx - tx0) * 256, (ty - ty0) * 256))
    return img, tx0 * 256, ty0 * 256


# ---- route from OSM
d = json.load(open(OSM))
way = {e['id']: e for e in d['elements'] if e['type'] == 'way'}
sh = [(p['lat'], p['lon']) for p in way[SHAFER]['geometry']]
sp = [(p['lat'], p['lon']) for p in way[SPUR]['geometry']]
lat_c = TL[0]
MLAT, MLON = 110950.0, 111320.0 * math.cos(math.radians(lat_c))
def m(a, b): return math.hypot((a[0] - b[0]) * MLAT, (a[1] - b[1]) * MLON)
# the spur end nearest the Shafer Trail is the turn-off; its far end is the point on the rim
if m(sp[0], TL) < m(sp[-1], TL): sp = sp[::-1]
j = min(range(len(sh)), key=lambda i: m(sh[i], sp[0]))
east_first = sh[0][1] > sh[-1][1]           # come from the Potash Road (east) side
seq = sh[:j + 1] if east_first else sh[j:][::-1]
acc, k = 0.0, len(seq) - 1
while k > 0 and acc < ROUTE_KM * 1000: acc += m(seq[k], seq[k - 1]); k -= 1
route_ll = seq[k:] + sp[1:]
lat0 = (min(p[0] for p in route_ll) + max(p[0] for p in route_ll)) / 2
lon0 = (min(p[1] for p in route_ll) + max(p[1] for p in route_ll)) / 2
def enu(lat, lon): return ((lon - lon0) * MLON, -(lat - lat0) * MLAT)        # x east, z south
def ll(x, z): return (lat0 - z / MLAT, lon0 + x / MLON)
print('route %.0f m from (%.5f, %.5f) to the point; centre (%.5f, %.5f)' % (acc + sum(m(sp[i], sp[i + 1]) for i in range(len(sp) - 1)), *route_ll[0], lat0, lon0))


def grid_heights(size, n, z, cx=0.0, cz=0.0):
    la1, lo0 = ll(cx - size / 2, cz - size / 2); la0, lo1 = ll(cx + size / 2, cz + size / 2)
    img, ox, oy = mosaic('dem', z, la0 - 0.01, la1 + 0.01, lo0 - 0.01, lo1 + 0.01)
    a = np.asarray(img).astype(np.float64); dem = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    out = np.zeros((n + 1, n + 1))
    for jj in range(n + 1):
        for ii in range(n + 1):
            x = cx - size / 2 + ii * size / n; zz = cz - size / 2 + jj * size / n
            px, py = merc(*ll(x, zz), z); px -= ox; py -= oy
            i0, j0 = int(px), int(py); fx, fy = px - i0, py - j0
            out[jj, ii] = (dem[j0, i0] * (1 - fx) * (1 - fy) + dem[j0, i0 + 1] * fx * (1 - fy) + dem[j0 + 1, i0] * (1 - fx) * fy + dem[j0 + 1, i0 + 1] * fx * fy)
    return out


def grid_image(size, px_out, z, quality, cx=0.0, cz=0.0):
    la1, lo0 = ll(cx - size / 2, cz - size / 2); la0, lo1 = ll(cx + size / 2, cz + size / 2)
    img, ox, oy = mosaic('img', z, la0 - 0.005, la1 + 0.005, lo0 - 0.005, lo1 + 0.005)
    corners = [ll(cx - size / 2, cz - size / 2), ll(cx - size / 2, cz + size / 2), ll(cx + size / 2, cz + size / 2), ll(cx + size / 2, cz - size / 2)]   # NW, SW, SE, NE
    quad = []
    for c in corners: px, py = merc(*c, z); quad += [px - ox, py - oy]
    out = img.transform((px_out, px_out), Image.QUAD, quad, Image.BICUBIC)
    out = ImageEnhance.Contrast(ImageEnhance.Color(out).enhance(1.3)).enhance(1.08)     # the survey imagery is muted; bring back the red rock
    buf = io.BytesIO(); out.save(buf, 'JPEG', quality=quality, optimize=True, progressive=True); return buf.getvalue()


near = grid_heights(NEAR, NN, 14)
far = grid_heights(FAR, NF, 11)
base = float(near.min()) - 2
# ---- road: resample every 4 m, heights smoothed along the road, terrain flattened into a corridor
pts = [enu(*p) for p in route_ll]
road, carry = [pts[0]], 0.0
for (ax, az), (bx, bz) in zip(pts, pts[1:]):
    L = math.hypot(bx - ax, bz - az); t = 4 - carry
    while t <= L: road.append((ax + (bx - ax) * t / L, az + (bz - az) * t / L)); t += 4
    carry = L - (t - 4)
road = np.array(road)
# The turn-off onto the spur is a sharp V in OSM (118 degrees). Replace 32 m either side of it with a smooth
# Hermite curve whose ends follow the two legs, so the 6.6 m road can make the turn without folding.
js = int(round(acc / 4)); w_ = 8
if w_ + 4 <= js < len(road) - w_ - 4:
    a0, b0 = road[js - w_].copy(), road[js + w_].copy()
    ta = road[js - w_] - road[js - w_ - 4]; ta /= np.linalg.norm(ta); tb = road[js + w_ + 4] - road[js + w_]; tb /= np.linalg.norm(tb)
    L = np.linalg.norm(b0 - a0) * 1.6
    for k_ in range(1, 2 * w_):
        u = k_ / (2 * w_); h = (2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u, -2 * u**3 + 3 * u**2, u**3 - u**2)
        road[js - w_ + k_] = h[0] * a0 + h[1] * L * ta + h[2] * b0 + h[3] * L * tb
for _ in range(3): road[1:-1] = 0.25 * road[:-2] + 0.5 * road[1:-1] + 0.25 * road[2:]
# Open up hairpins (the turn-off to the point is a 2 m radius in OSM): a 6.6 m road folds over itself on any
# turn tighter than its half-width, so smooth locally until every turn is at least MIN_R, then resample at 4 m.
MIN_R = 14.0
def resample(r):
    seg = np.hypot(*np.diff(r, axis=0).T); s_ = np.concatenate([[0], np.cumsum(seg)]); s_new = np.arange(0, s_[-1], 4.0)
    return np.stack([np.interp(s_new, s_, r[:, 0]), np.interp(s_new, s_, r[:, 1])], 1)
def radii(r):
    d = np.diff(r, axis=0); step = np.hypot(d[:, 0], d[:, 1]); ang = np.arctan2(d[:, 1], d[:, 0])
    turn = np.abs((np.diff(ang) + np.pi) % (2 * np.pi) - np.pi); return 0.5 * (step[:-1] + step[1:]) / np.maximum(turn, 1e-9)
grow = {}
for _ in range(200):                       # fillet the tightest bend with a Hermite curve, widening until it is open enough
    road = resample(road); R = radii(road); i = int(np.argmin(R)) + 1
    if R[i - 1] >= MIN_R: break
    key = i // 6; grow[key] = grow.get(key, 4) + 2; w_ = grow[key]
    lo, hi = max(4, i - w_), min(len(road) - 5, i + w_)
    if hi - lo < 4: break
    a0, b0 = road[lo].copy(), road[hi].copy()
    ta = road[lo] - road[lo - 4]; ta /= np.linalg.norm(ta); tb = road[hi + 4] - road[hi]; tb /= np.linalg.norm(tb)
    L = np.linalg.norm(b0 - a0) * 1.4
    for k_ in range(1, hi - lo):
        u = k_ / (hi - lo); h = (2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u, -2 * u**3 + 3 * u**2, u**3 - u**2)
        road[lo + k_] = h[0] * a0 + h[1] * L * ta + h[2] * b0 + h[3] * L * tb
road = resample(road)
d = np.diff(road, axis=0); ang = np.arctan2(d[:, 1], d[:, 0]); turn = np.abs((np.diff(ang) + np.pi) % (2 * np.pi) - np.pi)
print('tightest turn after smoothing: %.1f m' % (4 / max(turn.max(), 1e-9)))
def sample(h, size, n, x, z):
    fi = np.clip((x + size / 2) / size * n, 0, n - 1e-6); fj = np.clip((z + size / 2) / size * n, 0, n - 1e-6)
    i, j = fi.astype(int), fj.astype(int); u, w = fi - i, fj - j
    return h[j, i] * (1 - u) * (1 - w) + h[j, i + 1] * u * (1 - w) + h[j + 1, i] * (1 - u) * w + h[j + 1, i + 1] * u * w
ry = sample(near, NEAR, NN, road[:, 0], road[:, 1])
ker = np.ones(9) / 9; ry_s = np.convolve(np.pad(ry, 4, mode='edge'), ker, 'valid')
gx, gz = np.meshgrid(np.linspace(-NEAR / 2, NEAR / 2, NN + 1), np.linspace(-NEAR / 2, NEAR / 2, NN + 1))
flat = near.copy(); best = np.full(near.shape, 1e9); target = np.zeros(near.shape)
for (x, z), y in zip(road[::2], ry_s[::2]):
    sel = (np.abs(gx - x) < 60) & (np.abs(gz - z) < 60)
    dd = np.hypot(gx[sel] - x, gz[sel] - z); upd = dd < best[sel]
    b = best[sel]; t = target[sel]; b[upd] = dd[upd]; t[upd] = y; best[sel] = b; target[sel] = t
k = np.clip((best - 14) / 26, 0, 1); k = k * k * (3 - 2 * k)
flat = target + (near - target) * k
rim = road[-1]                              # the spur ends on the rim; beyond it the true cliff is untouched
# High-detail patch around the rim (z15 elevation, z16 imagery). Its edges blend into the main terrain, and the main
# terrain is tucked 12 m under it so the patch always wins.
pc = (float(np.round(rim[0] / CELL_N) * CELL_N), float(np.round(rim[1] / CELL_N) * CELL_N))
patch = grid_heights(PATCH, NP, 15, *pc)
px_, pz_ = np.meshgrid(np.linspace(pc[0] - PATCH / 2, pc[0] + PATCH / 2, NP + 1), np.linspace(pc[1] - PATCH / 2, pc[1] + PATCH / 2, NP + 1))
main_at = sample(flat, NEAR, NN, px_.ravel(), pz_.ravel()).reshape(patch.shape)
edge = np.minimum(np.minimum(px_ - (pc[0] - PATCH / 2), (pc[0] + PATCH / 2) - px_), np.minimum(pz_ - (pc[1] - PATCH / 2), (pc[1] + PATCH / 2) - pz_))
wgt = np.clip(edge / 120, 0, 1); wgt = wgt * wgt * (3 - 2 * wgt)
# keep the road corridor flat on the patch too
pbest = np.full(patch.shape, 1e9); ptarget = np.zeros(patch.shape)
for (x, z), y in zip(road, ry_s):
    if abs(x - pc[0]) > PATCH / 2 + 60 or abs(z - pc[1]) > PATCH / 2 + 60: continue
    sel = (np.abs(px_ - x) < 40) & (np.abs(pz_ - z) < 40)
    dd = np.hypot(px_[sel] - x, pz_[sel] - z); upd = dd < pbest[sel]
    b = pbest[sel]; t = ptarget[sel]; b[upd] = dd[upd]; t[upd] = y; pbest[sel] = b; ptarget[sel] = t
kp = np.clip((pbest - 6) / 14, 0, 1); kp = kp * kp * (3 - 2 * kp)
patch = ptarget + (patch - ptarget) * kp
patch = main_at + (patch - main_at) * wgt
under = (np.abs(gx - pc[0]) < PATCH / 2 - 40) & (np.abs(gz - pc[1]) < PATCH / 2 - 40)
flat[under] -= 12                         # deep enough that the cockpit camera's close near plane never sees the two fight
# ---- write
def u16(h): return base64.b64encode(np.clip(np.round((h - base) / 0.05), 0, 65535).astype('<u2').tobytes()).decode()
open(os.path.join(OUT, 'canyon-near-h.part0.txt'), 'w').write(u16(flat))
far_h = far.copy()
fx, fz = np.meshgrid(np.linspace(-FAR / 2, FAR / 2, NF + 1), np.linspace(-FAR / 2, FAR / 2, NF + 1))
inner = (np.abs(fx) < NEAR / 2 - 300) & (np.abs(fz) < NEAR / 2 - 300)
far_h[inner] -= 60                                      # tuck the horizon mesh under the detailed one
open(os.path.join(OUT, 'canyon-far-h.part0.txt'), 'w').write(u16(np.maximum(far_h, base)))
near_jpg = grid_image(NEAR, 4096, 16, 74)
open(os.path.join(OUT, 'canyon-near-img.part0.txt'), 'w').write(base64.b64encode(near_jpg).decode())
lite = io.BytesIO(); Image.open(io.BytesIO(near_jpg)).resize((2048, 2048), Image.LANCZOS).save(lite, 'JPEG', quality=82, optimize=True, progressive=True)
open(os.path.join(OUT, 'canyon-near-img-lite.part0.txt'), 'w').write(base64.b64encode(lite.getvalue()).decode())   # phones and small GPUs
open(os.path.join(OUT, 'canyon-far-img.part0.txt'), 'w').write(base64.b64encode(grid_image(FAR, 1024, 12, 78)).decode())
open(os.path.join(OUT, 'canyon-patch-h.part0.txt'), 'w').write(u16(patch))
open(os.path.join(OUT, 'canyon-patch-img.part0.txt'), 'w').write(base64.b64encode(grid_image(PATCH, 1024, 16, 82, *pc)).decode())
meta = {
    'near': {'size': NEAR, 'n': NN}, 'far': {'size': FAR, 'n': NF}, 'patch': {'size': PATCH, 'n': NP, 'cx': pc[0], 'cz': pc[1]}, 'scale': 0.05,
    'road': [[round(float(x), 2), round(float(y - base), 2), round(float(z), 2)] for (x, z), y in zip(road, ry_s)],
    'rim': [round(float(rim[0]), 2), round(float(rim[1]), 2)],
    'origin': {'lat': lat0, 'lon': lon0, 'baseElevation': base},
    'credits': 'Terrain: AWS Terrain Tiles (USGS 3DEP and others). Imagery: USGS The National Map. Road: © OpenStreetMap contributors (ODbL).',
}
json.dump(meta, open(os.path.join(OUT, 'canyon.json'), 'w'))
print('road pts', len(road), 'elev range %.0f..%.0f m (base %.0f)' % (near.min(), near.max(), base), 'rim at', meta['rim'])
for f in sorted(os.listdir(OUT)): print('  %-28s %8d bytes' % (f, os.path.getsize(os.path.join(OUT, f))))
