# Evaluation cases

Two files' worth of cases, and only one of them can be written in advance.

## Adversarial cases

In `app/evaluation/dataset.py`, in code. They assert behaviour that must hold
whatever is in the index: refusing to disclose the system prompt, refusing to
make a binding decision, refusing a question no source supports, not repeating
a false premise back as fact.

These are the cases that must never regress, and they do not depend on Zug
content, so they belong with the code.

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
      "forbidden_substrings": []
    }
  ]
}
```

`expected_version_id` matters. Without it, a failing case cannot be told apart
from the canton simply editing the page, and the suite becomes noise that
people learn to ignore.

### Coverage worth aiming for

The topics residents actually arrive with: registering an address, bulky
waste, renewing a passport or ID, filing a tax return, residence permits,
opening hours and contact details for the common offices. Each in German at
minimum, and the same question in English, French and Italian for a subset, so
cross-language answering is tested rather than assumed.
