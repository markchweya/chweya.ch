# Cantons

One folder per canton. Each holds a single `canton.json` with everything
that differs between deployments of the same interface:

* `label` — the word beside "Dumi" in the header and the canton menu.
* `portal_label`, `portal_url` — the official portal residents verify
  against. The disclaimer under the composer links here.
* `hosts` — hostnames this canton's sources may use. The global crawl
  allowlist in the application settings still applies at fetch time.
* `languages` — languages the canton publishes in. Interface languages
  are shared and unaffected.
* `accent_rgb` — the one design token a canton overrides, as an
  `R G B` triple. See `shared/brand/dumi-tokens.css`.
* `names`, `of_phrases`, `by_phrases` — per-language pieces the
  interface strings splice in. Full phrases, because grammar differs by
  canton: French writes "de Zoug" but "d'Uri".

Adding a canton is adding a folder. The chat header offers whatever this
directory contains; sources created in the administration are tagged with
a canton, and retrieval only reads sources of the canton being served.

Layout and component code never lives here. If a canton folder starts
collecting any, that code belongs in `shared/`.
