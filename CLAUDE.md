# Dumi — working rules

Dumi is a chatbot on Swiss cantonal government websites. Residents use it to
find out how to register an address, dispose of bulky waste, renew an ID, file
a tax return. Two things follow from that and govern everything below: the
people using it are often stressed and on a deadline, and the canton's name is
on the page.

## Never fake presence

Dumi is a model. Nothing in the interface may suggest otherwise.

* No green "online" or "live" status dot. There is no person at the other end
  and no service whose uptime that dot would honestly report.
* No three-dot typing indicator. It imitates a human composing a message. The
  mark already reports thinking through its own motion, so it would be a
  second, less honest indicator of the same thing.
* No artificial delay to make replies feel human.
* No language implying a person read the question ("someone will look at
  this", "let me check with the office").

The one exception: when Dumi hands off to an actual human service, say so
plainly, with the office name and its real opening hours.

## Answers

* Every factual answer cites the canton page it came from. An answer with no
  source is a bug.
* When Dumi does not know, it says so and points to the office that does. It
  never fills the gap with plausible text.
* Deadlines, fees and legal requirements are quoted from the source, never
  paraphrased into something that could shift their meaning.
* Getting German, French and Italian right is not optional. A mistranslated
  deadline is a real problem for a real person.

## Interface

* No device-frame mockups. Never present the product inside a drawn tablet,
  phone or laptop. Show the real interface at real size, on a plain ground.
  That framing is decoration, it hides what things actually look like, and it
  is the first thing that makes a page read as machine-made.
* The Dumi mark is the only status indicator. No separate spinners, progress
  bars or loading dots anywhere.
* One accent token per canton. Everything else in the UI is shared. If a
  canton folder starts collecting layout or component code, that code belongs
  in `shared/`.

## Writing

This applies to interface copy, documentation and commit messages alike.

* Plain sentences. Say the thing.
* Avoid the "X, not Y" construction. One per document is a stylistic choice,
  five is a tic, and it is the single clearest sign that nobody edited the
  text.
* Em dashes sparingly. A colon, a full stop or a rewrite is usually better.
* No emoji as section markers or bullets.
* Tables are for reference material with real columns. Prose chopped into a
  grid is harder to read.
* Name things the way a resident would: people renew a passport, they do not
  submit an identity document request.

## Repository

```
shared/          identical for every canton
└─ brand/        the Dumi mark, palette, type and motion tokens
   └─ favicon/   the icon set every canton serves

cantons/         one folder per canton
└─ zug/          name, coat of arms, accent token, languages, content source
```

Development happens on `ChweyasBranch`.
