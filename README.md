# chweya.ch — Dumi

**Dumi** is a website chatbot for Swiss cantonal administrations. It answers
residents' questions about canton services, such as registering an address,
disposing of bulky waste, renewing an ID or filing a tax return, and it cites
the official page each answer came from.

One assistant, one shell, one brand. A canton supplies only what is genuinely
its own.

**Zug is first.**

Working rules for the project are in [CLAUDE.md](CLAUDE.md). The short version:
never fake presence, always cite the source, and no device-frame mockups.

## Where things live

```
shared/          identical for every canton
└─ brand/        the Dumi mark, palette, type and motion tokens
   └─ favicon/   the icon set every canton serves

cantons/         one folder per canton
└─ zug/          name, coat of arms, accent token, languages, content source
```

The split is deliberate. If a canton folder starts collecting layout or
component code, that code belongs in `shared/` instead.

## Status

| Piece | State |
|---|---|
| Brand, the Dumi mark | Draft 01. See [`shared/brand`](shared/brand) |
| Favicon set | Done. See [`shared/brand/favicon`](shared/brand/favicon) |
| Chat shell (launcher, consent gate, transcript, citations) | Not started |
| Zug content source | Not started |
| Accounts and sign-in | Out of scope for now |

## Reference

The Canton of Basel-Stadt runs a comparable assistant, **Alva**, at
[bs.ch](https://www.bs.ch). Its structure is worth reading as prior art: a
launcher orb, a consent gate before activation, canton branding on the left and
assistant branding on the right, suggestion chips, cited sources, and per-answer
feedback.
