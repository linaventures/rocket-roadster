"""Textures for the trip to orbit.
  python tools/prep_orbit.py <dir with the NASA images> <tile cache dir> <canyon.json> <out dir>

  - Earth by day:   NASA Blue Marble Next Generation, Dec 2004 (world.topo.bathy.200412), public domain
  - Earth at night: NASA Black Marble 2016 city lights, public domain
  - Clouds:         NASA Visible Earth cloud_combined_2048, public domain
  - Region:         USGS The National Map imagery (public domain), zoom 8, a 640 km square around the canyon,
                    so the ground stays sharp between the canyon terrain and the whole-Earth texture
Writes base64 JPEG text parts (the page decodes them through blob: URLs).
"""
import base64, io, json, math, os, sys, urllib.request
from PIL import Image, ImageEnhance

SRC, CACHE, CANYON, OUT = sys.argv[1:5]
os.makedirs(OUT, exist_ok=True); os.makedirs(CACHE, exist_ok=True)
UA = {'User-Agent': 'RocketRoadsterFanProject/1.0 (personal, non-commercial)'}


def jpg(img, q):
    b = io.BytesIO(); img.save(b, 'JPEG', quality=q, optimize=True, progressive=True); return b.getvalue()


def write(name, data):
    open(os.path.join(OUT, name + '.part0.txt'), 'w').write(base64.b64encode(data).decode())
    print('  %-24s %8d bytes' % (name, len(data)))


day = Image.open(os.path.join(SRC, 'world.topo.bathy.200412.3x5400x2700.jpg')).convert('RGB').resize((4096, 2048), Image.LANCZOS)
write('earth-day', jpg(day, 80))
night = Image.open(os.path.join(SRC, 'BlackMarble_2016_01deg.jpg')).convert('RGB').resize((2048, 1024), Image.LANCZOS)
write('earth-night', jpg(night, 78))
clouds = Image.open(os.path.join(SRC, 'cloud_combined_2048.jpg')).convert('L').resize((2048, 1024), Image.LANCZOS)
write('earth-clouds', jpg(clouds, 78))

# Regional imagery: a 640 km square, north up, centred on the canyon's origin.
o = json.load(open(CANYON))['origin']; lat0, lon0 = o['lat'], o['lon']
SIZE, Z, PX = 640000.0, 8, 1024
MLAT, MLON = 110950.0, 111320.0 * math.cos(math.radians(lat0))
def ll(x, z): return (lat0 - z / MLAT, lon0 + x / MLON)
def merc(lat, lon, z):
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
corners = [ll(-SIZE / 2, -SIZE / 2), ll(-SIZE / 2, SIZE / 2), ll(SIZE / 2, SIZE / 2), ll(SIZE / 2, -SIZE / 2)]   # NW, SW, SE, NE
xs, ys = zip(*[merc(*c, Z) for c in corners])
tx0, tx1, ty0, ty1 = int(min(xs) // 256), int(max(xs) // 256), int(min(ys) // 256), int(max(ys) // 256)
mosaic = Image.new('RGB', ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
for tx in range(tx0, tx1 + 1):
    for ty in range(ty0, ty1 + 1):
        p = os.path.join(CACHE, f'img-{Z}-{tx}-{ty}.jpg')
        if not os.path.exists(p):
            url = f'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{Z}/{ty}/{tx}'
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: open(p, 'wb').write(r.read())
        mosaic.paste(Image.open(p).convert('RGB'), ((tx - tx0) * 256, (ty - ty0) * 256))
quad = []
for c in corners: px, py = merc(*c, Z); quad += [px - tx0 * 256, py - ty0 * 256]
region = mosaic.transform((PX, PX), Image.QUAD, quad, Image.BICUBIC)
region = ImageEnhance.Contrast(ImageEnhance.Color(region).enhance(1.25)).enhance(1.06)   # match the canyon imagery
write('region', jpg(region, 80))
json.dump({'regionSize': SIZE, 'lat': lat0, 'lon': lon0,
           'credits': 'Earth: NASA Blue Marble, Black Marble and Visible Earth. Region: USGS The National Map.'},
          open(os.path.join(OUT, 'orbit.json'), 'w'))
print('region tiles', (tx1 - tx0 + 1) * (ty1 - ty0 + 1))
