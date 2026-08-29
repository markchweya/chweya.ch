# Dumi — brand

The assistant's mark and the tokens every canton shares. No build step, no
dependencies: plain CSS custom properties.

## Files

| File | What it's for |
|---|---|
| `dumi-tokens.css` | Palette, type and motion tokens. Load first. |
| `dumi-mark.css` | The mark, its states, the lockups and the launcher button. |
| `dumi-mark.svg` | Standalone animated mark — inline, `<img>`, OG image, print. |
| `preview.html` | Specimen sheet: scale, states, palette, favicon, in-context mock. |
| `favicon/` | The shared icon set, its two source drawings, and `build.sh`. See [its README](favicon/README.md). |

## Use it

```html
<link rel="stylesheet" href="/shared/brand/dumi-tokens.css">
<link rel="stylesheet" href="/shared/brand/dumi-mark.css">

<span class="dumi" data-state="idle" role="img" aria-label="Dumi">
  <span class="dumi__orb">
    <i class="dumi__blob dumi__blob--a"></i>
    <i class="dumi__blob dumi__blob--b"></i>
    <i class="dumi__blob dumi__blob--c"></i>
    <i class="dumi__core"></i>
    <i class="dumi__sheen"></i>
  </span>
</span>
```

Two knobs, and that's the whole API:

- `style="--dumi-size: 96px"` — everything inside scales from this.
- `data-state="idle | listening | thinking"` — see below.

Decorative instances (specimen rows, repeated avatars) should carry
`aria-hidden="true"` instead of the `role`/`aria-label` pair, so a screen
reader announces "Dumi" once per view rather than once per orb.

## States

The mark is the launcher, the message avatar **and** the thinking indicator,
so its motion is functional. There is no separate spinner anywhere in the UI.

| State | Meaning | What changes |
|---|---|---|
| `idle` | Present, not working | 13s drift, no halo |
| `listening` | Taking the question | Halo blooms and pulses; orbits hold pace |
| `thinking` | Searching the records | Orbits ~4× faster, core lights up |

One unitless multiplier, `--dumi-tempo`, scales all three orbit durations
via `calc()`. Under `prefers-reduced-motion` the orbits freeze at composed
resting angles and state is carried by halo and core opacity alone.

## Per-canton theming

A canton overrides **one** token. Everything else is shared, so Dumi stays
recognisably one assistant across all 26.

```css
/* cantons/zug/canton.css */
:root { --dumi-accent-rgb: 232 163 61; }  /* amber — the default */
```

Pick an accent that stays legible as a small glint against the glacier-blue
body. Deep or desaturated hues disappear; the accent blob is the smallest and
fastest of the three by design.

## Palette

| Token | Hex | Role |
|---|---|---|
| `--dumi-deep` | `#0B3B57` | Glacier blue — the orb body |
| `--dumi-flow` | `#1E88A8` | Mid teal — primary orbiting light |
| `--dumi-ice` | `#6FD6D2` | Pale aqua — fast highlight |
| `--dumi-accent` | `#E8A33D` | Amber — the warm spark, and the canton slot |

Each is also exposed as a space-separated RGB triplet
(`--dumi-flow-rgb: 30 136 168`) so any value can take an alpha:
`rgb(var(--dumi-flow-rgb) / .4)`.

## Type

- **Archivo** — display, 600/700, tight tracking.
- **Public Sans** — body. Drawn for government digital services, which is the
  reason it's here rather than a generic grotesk.
- **IBM Plex Mono** — reference numbers, token values, data.

## Favicon

Every canton uses the same icon set, in [`favicon/`](favicon). It is generated
from the mark rather than hand-drawn, but it is a **separate static drawing**:
favicons render where animation and blend modes aren't reliable, and they have
to survive 16 pixels. Install instructions are in that folder's README.
