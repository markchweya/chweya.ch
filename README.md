# chweya.ch — Dumi

**Dumi** is a website chatbot for Swiss cantonal administrations. It answers
residents' questions about canton services — registering an address, disposing
of bulky waste, renewing an ID, filing a tax return — and cites the official
pages it drew the answer from.

One assistant, one shell, one brand. A canton supplies only what is genuinely
its own.

**Zug is first.**

## Where things live

```
shared/          identical for every canton
└─ brand/        the Dumi mark, palette, type and motion tokens

cantons/         one folder per canton
└─ zug/          name, coat of arms, accent token, languages, content source
```

The split is deliberate: if a canton folder starts accumulating layout or
component code, that code belongs in `shared/` instead.

## Status

| Piece | State |
|---|---|
| Brand — the Dumi mark | Draft 01 · see [`shared/brand`](shared/brand) |
| Chat shell (launcher, consent gate, transcript, citations) | Not started |
| Zug content source | Not started |
| Accounts and sign-in | Out of scope for now |

## Reference

The Canton of Basel-Stadt runs a comparable assistant, **Alva**, at
[bs.ch](https://www.bs.ch). Its structure is worth reading as prior art: a
launcher orb, a consent gate before activation, canton branding on the left
and assistant branding on the right, suggestion chips, cited sources, and
per-answer feedback.
