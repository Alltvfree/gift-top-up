# The UI shows the official logo unaltered (frontend/assets/satlink-logo.jpg).
# This script only builds frontend/assets/favicon.png (the swoosh mark) from it:
#   python3 scripts/make-logo-assets.py frontend/assets/satlink-logo.jpg /tmp/out && cp /tmp/out/favicon.png frontend/assets/
# (needs: pip install pillow; it also writes recoloured logo variants to the output folder, unused by the UI)
import sys
from PIL import Image
src, outdir = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGB")
W, H = im.size
dark = Image.new("RGBA", (W, H))
light = Image.new("RGBA", (W, H))
px, dp, lp = im.load(), dark.load(), light.load()
for y in range(H):
    for x in range(W):
        r, g, b = px[x, y]
        mx, mn = max(r, g, b), min(r, g, b)
        sat = mx - mn
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        if sat < 28:                      # neutral: black lettering or white paper
            a = max(0.0, min(1.0, (250 - lum) / 235))
            dp[x, y] = (255, 255, 255, int(a * 255))      # lettering turns white on dark UI
            lp[x, y] = (0, 0, 0, int(a * 255))            # same shape, black, for light backgrounds
        else:                             # blue swoosh, blue "i", "Private Limited"
            a = max(0.0, min(1.0, sat / 45))
            dp[x, y] = (r, g, b, int(a * 255))
            lp[x, y] = (r, g, b, int(a * 255))
bbox = dark.getbbox()
pad = 6
bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(W, bbox[2] + pad), min(H, bbox[3] + pad))
dark, light = dark.crop(bbox), light.crop(bbox)
dark.save(f"{outdir}/satlink-logo-dark.png", optimize=True)
light.save(f"{outdir}/satlink-logo.png", optimize=True)
print("logo", dark.size, bbox)
# Favicon: the swoosh + "S" mark, squared, on the UI's dark background
mark = dark.crop(dark.crop((0, 0, int(dark.size[0] * 0.30), dark.size[1])).getbbox())
side = int(max(mark.size) * 1.15)
sq = Image.new("RGBA", (side, side), (12, 20, 35, 255))
sq.alpha_composite(mark, ((side - mark.size[0]) // 2, (side - mark.size[1]) // 2))
sq.resize((64, 64), Image.LANCZOS).save(f"{outdir}/favicon.png", optimize=True)
