#!/usr/bin/env bash
# Rasterise the Dumi favicon set from dumi-favicon.svg.
#
#   ./build.sh
#
# Needs Chromium (rendering) and Python 3 with Pillow (cropping, ICO assembly).
#
# Each size is rendered independently rather than downscaled from one large
# render, so the 16px icon gets Chromium's own gradient sampling at 16px
# instead of a smudged resample.
#
# Note the PAD below: headless Chromium reserves some vertical space, so a
# --window-size exactly equal to the target silently clips the bottom of the
# image. Render into a taller viewport, then crop back to the top-left square.
set -euo pipefail

cd "$(dirname "$0")"

PAD=400

CHROME="${CHROME:-}"
if [ -z "$CHROME" ]; then
  for c in /opt/pw-browsers/chromium-*/chrome-linux/chrome \
           "$(command -v chromium || true)" "$(command -v google-chrome || true)"; do
    [ -x "${c:-}" ] && CHROME="$c" && break
  done
fi
[ -n "$CHROME" ] || { echo "No Chromium found. Set CHROME=/path/to/chrome" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp dumi-favicon.svg dumi-favicon-small.svg "$TMP/"

# $1 size  $2 output  $3 card background  $4 orb size as % of card  $5 source svg
render() {
  local size="$1" out="$2" bg="$3" pct="$4" src="${5:-dumi-favicon.svg}"
  local orb off
  orb=$(( size * pct / 100 ))
  off=$(( (size - orb) / 2 ))

  cat > "$TMP/page.html" <<EOF
<style>
  html, body { margin:0; padding:0; background:transparent; }
  #card { position:absolute; left:0; top:0;
          width:${size}px; height:${size}px; background:${bg}; }
  #card img { position:absolute; left:${off}px; top:${off}px;
              width:${orb}px; height:${orb}px; display:block; }
</style>
<div id="card"><img src="${src}" alt=""></div>
EOF

  "$CHROME" --headless --no-sandbox --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=1 \
    --default-background-color=00000000 \
    --virtual-time-budget=3000 \
    --window-size="${size},$(( size + PAD ))" \
    --screenshot="$TMP/raw.png" "file://$TMP/page.html" >/dev/null 2>&1

  python3 -c "
from PIL import Image
Image.open('$TMP/raw.png').convert('RGBA').crop((0, 0, $size, $size)).save('$out')
"
  printf '  %-26s %sx%s\n' "$(basename "$out")" "$size" "$size"
}

echo "Rendering..."
# Browser tab and bookmark icons: transparent, full bleed.
render 16 "$PWD/favicon-16.png" transparent 100 dumi-favicon-small.svg
render 32 "$PWD/favicon-32.png" transparent 100
render 48 "$PWD/favicon-48.png" transparent 100

# Touch and installed-app icons: opaque and inset. iOS composites onto its own
# ground and applies a squircle mask, so a transparent full-bleed circle would
# show up as a circle floating on black.
render 180 "$PWD/apple-touch-icon.png"  "#071F2E" 74
render 192 "$PWD/icon-192.png"          "#071F2E" 74
render 512 "$PWD/icon-512.png"          "#071F2E" 74
# Maskable icons get cropped to a platform-chosen shape, so the mark has to sit
# inside the 40% safe zone.
render 512 "$PWD/icon-512-maskable.png" "#071F2E" 56

cp dumi-favicon.svg favicon.svg

echo "Packing favicon.ico..."
python3 - <<'PY'
import struct, pathlib

sizes = [16, 32, 48]
blobs = [pathlib.Path(f"favicon-{s}.png").read_bytes() for s in sizes]

# ICONDIR, then one ICONDIRENTRY per image, then the PNG payloads. Embedding
# PNG rather than BMP keeps the alpha clean and the file small.
offset = 6 + 16 * len(sizes)
out = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
for size, blob in zip(sizes, blobs):
    out += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(blob), offset)
    offset += len(blob)
out += b"".join(blobs)
pathlib.Path("favicon.ico").write_bytes(out)
print(f"  favicon.ico                {len(out)} bytes  "
      f"({', '.join(f'{s}x{s}' for s in sizes)})")
PY

echo "Done."
