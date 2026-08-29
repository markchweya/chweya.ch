# Dumi — favicon

One icon set, shared by every canton, generated from the mark.

## Install

Copy `favicon.ico` to the site's **web root**. Browsers request `/favicon.ico`
directly, before they have parsed any markup. Then include
[`head.html`](head.html) verbatim in `<head>`:

```html
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="icon" href="/shared/brand/favicon/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/shared/brand/favicon/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="#0B3B57">
```

That covers everything: modern browsers take the SVG, older ones fall back to
the `.ico`, iOS takes the touch icon, and installed-app surfaces read the
manifest.

## Files

| File | Where it's used |
|---|---|
| `favicon.svg` | Modern browsers, which prefer it |
| `favicon.ico` | Legacy fallback and the bare `/favicon.ico` request. 16, 32, 48 |
| `favicon-16/32/48.png` | The `.ico` members, also useful standalone |
| `apple-touch-icon.png` | iOS home screen. 180px, opaque |
| `icon-192.png`, `icon-512.png` | Web app manifest. Opaque |
| `icon-512-maskable.png` | Android adaptive icons, mark inside the 40% safe zone |
| `site.webmanifest` | Manifest template. Copy to the web root |

## The two source drawings

The favicon is not `shared/brand/dumi-mark.svg`. That one animates and uses
blend modes. Favicons render in a restricted context where neither is reliable,
and they have to survive 16 pixels. So there are two static cuts:

* **`dumi-favicon.svg`** is one composed frame of the orbit, used from 32px up.
* **`dumi-favicon-small.svg`** is the 16px cut. The body is lifted out of near
  black, the core is enlarged, the blur is tightened, and the rim is dropped,
  because at 16px that rim costs a whole pixel of the 16 available.

Both were tuned by rendering them and looking at the result. Neither is a
scaled copy of the other.

## Rebuilding

```bash
./build.sh
```

Needs Chromium and Python 3 with Pillow. Every size is rendered independently
so the small icons get Chromium's gradient sampling at their real size, instead
of the smudge you get from downscaling one large render.

One trap if you edit the script: headless Chromium reserves vertical space, so
a `--window-size` exactly equal to the target silently clips the bottom of the
image. The first run of this script produced icons that were only the top half
of the orb. It now renders into a taller viewport and crops back, which is what
`PAD` is for.

## A canton wanting its own accent

Edit the spark gradient stops (`#FFC66B` and `#E8A33D` in `dumi-favicon.svg`,
`#FFD285` and `#E8A33D` in `dumi-favicon-small.svg`) to match that canton's
`--dumi-accent-rgb`, then run `./build.sh` into the canton's folder. Leave the
body and core alone, since those are what make it Dumi.
