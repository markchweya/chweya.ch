# Dumi — brand

The assistant's mark and the tokens every canton shares. No build step and no
dependencies, just CSS custom properties.

| File | What it's for |
|---|---|
| `dumi-tokens.css` | Palette, type and motion tokens. Load first. |
| `dumi-mark.css` | The mark, its states, the lockups and the launcher button. |
| `dumi-mark.svg` | Standalone animated mark, for inline use, `<img>`, OG images and print. |
| `preview.html` | Specimen sheet: scale, states, palette, favicon, in-context mock. |
| `favicon/` | The shared icon set and its build script. See [its README](favicon/README.md). |

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

There are two knobs and that is the whole API:

* `style="--dumi-size: 96px"` sets the size, and everything inside scales from it.
* `data-state="idle | listening | thinking"` sets what the motion reports.

Give decorative instances `aria-hidden="true"` in place of the `role` and
`aria-label` pair. Specimen rows and repeated message avatars should not make a
screen reader announce "Dumi" once per orb.

## States

The mark is the launcher, the message avatar and the thinking indicator all at
once, so its motion has a job to do. The product has no separate spinner and no
typing dots.

| State | Meaning | What changes |
|---|---|---|
| `idle` | Present, waiting | 13s drift, no halo |
| `listening` | Taking the question | Halo blooms and pulses, orbits hold pace |
| `thinking` | Searching the records | Orbits roughly 4× faster, core lights up |

One unitless multiplier, `--dumi-tempo`, scales all three orbit durations
through `calc()`. Under `prefers-reduced-motion` the orbits freeze at composed
resting angles and state is carried by halo and core opacity.

## Per-canton theming

A canton overrides one token. Everything else is shared, which keeps Dumi
recognisably one assistant across all 26.

```css
/* cantons/zug/canton.css */
:root { --dumi-accent-rgb: 232 163 61; }  /* amber, the default */
```

Pick an accent that stays legible as a small glint against the glacier blue
body. Deep or desaturated hues disappear at that size, because the accent blob
is by design the smallest and fastest of the three.

## Palette

| Token | Hex | Role |
|---|---|---|
| `--dumi-deep` | `#0B3B57` | Glacier blue, the orb body |
| `--dumi-flow` | `#1E88A8` | Mid teal, the primary orbiting light |
| `--dumi-ice` | `#6FD6D2` | Pale aqua, the fast highlight |
| `--dumi-accent` | `#E8A33D` | Amber, the warm spark and the canton slot |

Each is also exposed as a space-separated RGB triplet
(`--dumi-flow-rgb: 30 136 168`), so any value can take an alpha:
`rgb(var(--dumi-flow-rgb) / .4)`.

## Type

**Archivo** for display sizes, 600 and 700, with tight tracking. **Public Sans**
for body text; it was drawn for government digital services, which is why it is
here instead of a generic grotesk. **IBM Plex Mono** for reference numbers,
token values and data.

## Favicon

Every canton serves the same icon set, in [`favicon/`](favicon). It is generated
from the mark but drawn separately, because favicons render where animation and
blend modes are unreliable and they have to survive 16 pixels. Install
instructions are in that folder.
