# Dumi — favicon

One icon set, shared by every canton. Generated from the mark, not hand-drawn.

## Install

Copy `favicon.ico` to the site's **web root** — browsers request `/favicon.ico`
directly, before parsing any markup — then include [`head.html`](head.html)
verbatim in `<head>`:

```html
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="icon" href="/shared/brand/favicon/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/shared/brand/favicon/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="#0B3B57">
```

That's the whole set. Modern browsers take the SVG, older ones fall back to the
`.ico`, iOS takes the touch icon, and installed-app surfaces read the manifest.

## Files

| File | Where it's used |
|---|---|
| `favicon.svg` | Modern browsers — the icon they prefer |
| `favicon.ico` | Legacy fallback and the bare `/favicon.ico` request · 16, 32, 48 |
| `favicon-16/32/48.png` | The `.ico` members, also useful standalone |
| `apple-touch-icon.png` | iOS home screen · 180px, opaque |
| `icon-192.png`, `icon-512.png` | Web app manifest · opaque |
| `icon-512-maskable.png` | Android adaptive icons · mark inside the 40% safe zone |
| `site.webmanifest` | Manifest template — copy to the web root |

## The two source drawings

The favicon is **not** `shared/brand/dumi-mark.svg`. That one animates and uses
blend modes; favicons render in a restricted context where neither is reliable,
and they have to survive 16 pixels. So there are two static cuts:

- **`dumi-favicon.svg`** — one composed frame of the orbit. Used from 32px up.
- **`dumi-favicon-small.svg`** — the 16px cut. Body lifted out of near-black,
  core enlarged, blur tightened, rim dropped (at 16px the rim costs a whole
  pixel of the 16 available). Same composition, louder.

Both were tuned by rendering and looking, not by scaling one down.

## Rebuilding

```bash
./build.sh
```

Needs Chromium and Python 3 with Pillow. Every size is rendered independently
rather than downscaled from one large render, so the small icons get Chromium's
gradient sampling at their real size instead of a smudged resample.

One trap worth knowing if you touch the script: headless Chromium reserves
vertical space, so a `--window-size` exactly equal to the target silently clips
the bottom of the image. The script renders into a taller viewport and crops
back — that's what `PAD` is for.

## A canton wanting its own accent

Edit the spark gradient stops (`#FFC66B` / `#E8A33D` in `dumi-favicon.svg`,
`#FFD285` / `#E8A33D` in `dumi-favicon-small.svg`) to match the canton's
`--dumi-accent-rgb`, then re-run `./build.sh` into that canton's folder. Leave
the body and core alone — those are what make it Dumi.
