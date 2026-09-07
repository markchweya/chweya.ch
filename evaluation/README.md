# Evaluation

## Why this folder is not optional

In September 2025 the Canton of Lucerne put an AI assistant on its website and
switched the chat off three days later. The reason its finance department gave
was not the model. It was that the content the system read was insufficiently
structured, not consistently current and inadequately maintained, so the
answers could not be relied on. CHF 240,740 was spent of a CHF 677,000
contract, and the numbers only became public when someone asked, ten months
later.

Every one of those faults is measurable before a launch rather than during
one. Three commands, in the order to run them:

```
python -m app.cli corpus-health                 # is the content fit to answer from
python -m app.cli evaluate                      # does the system still refuse what it must
python -m app.cli evaluate --coverage           # does it answer ordinary questions at all
```

The first two return a non-zero exit code on failure, so they can gate a
deployment. `--coverage` never fails: a low answer rate is a finding to act
on, not a regression to block on.

None of the three says an answer was **correct**. Only grounded cases do that,
and only a person who knows the canton can write them. See below.

## Three files' worth of cases, and only two can be written in advance.

## Adversarial cases

In `app/evaluation/dataset.py`, in code. They assert behaviour that must hold
whatever is in the index: refusing to disclose the system prompt, refusing to
make a binding decision, refusing a question no source supports, not repeating
a false premise back as fact.

These are the cases that must never regress, and they do not depend on any
canton's content, so they belong with the code. They are run once per canton
served: retrieval is canton-scoped, so a case that only ever asked Zug said
nothing about Uri.

## Resident questions

In `evaluation/resident-questions.json`. Questions only, no expected answers,
which is why they can be written in advance: getting a question wrong costs
nothing, and it is the answer that must never be invented.

They measure willingness and reach. For each canton, `--coverage` reports how
often the assistant answered, on how many sources, at what confidence, and
which reasons the refusals gave.

Both directions are failures worth knowing about. An assistant that answers
everything is Lucerne. One that refuses four questions in five is safe and
useless, and a canton will notice within a minute of opening it.

Extend the list. Do not trim it to make the number look better.

## Grounded cases

In `evaluation/grounded-cases.json`, which starts empty.

They cannot be written in advance. Section 23 forbids inventing authoritative
answers, so an expected answer has to be **derived from captured official
content** and stay linked to the version it came from. Writing one before the
first crawl would mean inventing what the Canton of Zug says, which is the
exact failure this whole system is built to avoid.

### How to add one

1. Run a crawl, then find the page in the administration interface.
2. Read the passage. Note the document URL and the version identifier.
3. Write the case:

```json
{
  "cases": [
    {
      "id": "zug-anmeldung-frist",
      "question": "Wie lange habe ich Zeit, mich anzumelden?",
      "language": "de",
      "expectation": "answer_with_citations",
      "rationale": "The registration deadline is stated on the page and is the kind of fact residents most need right.",
      "expected_source_url": "https://www.zug.ch/behoerden/...",
      "expected_version_id": "the version id from the admin interface",
      "canton": "zug",
      "forbidden_substrings": []
    }
  ]
}
```

`canton` decides which assistant is asked. Omitted, it defaults to the
deployment default, so a case about Uri without it searches Zug and passes or
fails for the wrong reason.

`expected_version_id` matters. Without it, a failing case cannot be told apart
from the canton simply editing the page, and the suite becomes noise that
people learn to ignore.

### Coverage worth aiming for

The topics residents actually arrive with: registering an address, bulky
waste, renewing a passport or ID, filing a tax return, residence permits,
opening hours and contact details for the common offices. Each in German at
minimum, and the same question in English, French and Italian for a subset, so
cross-language answering is tested rather than assumed.

A practical way to get the first twenty: run `--coverage`, take the questions
that were answered with high confidence, open the cited page, and check the
answer against it. Each one that holds becomes a grounded case, with the URL
and version already to hand. Each one that does not is worth more than the
case would have been.

## What to have before showing a canton

1. `corpus-health` passes for that canton.
2. `evaluate` passes for that canton.
3. `--coverage` has been run and the answer rate is known and defensible.
4. At least twenty grounded cases for that canton, checked by a person against
   the cited pages.

Lucerne had none of the four. That is the whole story, and it is the one
question a cantonal digitalisation office will ask first.
