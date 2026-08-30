# Accessibility report

Target: WCAG 2.2 Level AA, and applicable Swiss public-sector requirements.

**This is not a conformance claim.** Automated checks cover a minority of the
success criteria, and no screen-reader or keyboard-only testing by a person
has been done. Section 15 requires manual testing and it has not happened.

## What is implemented

| Criterion | Implementation |
|---|---|
| 1.3.1 Info and relationships | Semantic HTML: `header`, `main`, `nav`, `article`, `section`, ordered lists for citations, a real `table` with `caption` and `th scope` |
| 1.4.1 Use of colour | Confidence is a border style plus caution text; the active language is weight plus underline plus background; source state is a word |
| 1.4.4 Resize text | All sizes in `rem` |
| 1.4.10 Reflow | Single column, no horizontal scroll; wide tables scroll inside their own container |
| 2.1.1 Keyboard | No custom widgets. Every control is a native element |
| 2.4.1 Bypass blocks | Skip link, first in tab order, visible on focus, localised |
| 2.4.7 Focus visible | 3px outline with offset; never removed without replacement |
| 2.5.8 Target size | Minimum 44×44 on language links, buttons and inputs |
| 3.1.1 Language of page | `<html lang>` from the negotiated language |
| 3.1.2 Language of parts | `lang` on each language link |
| 3.3.1 Error identification | Errors in text with `role="alert"`, tied to fields with `aria-describedby` |
| 3.3.2 Labels | Every input has a real `<label>`. Placeholders are never the only label |
| 4.1.3 Status messages | Transcript is `role="log"` with `aria-live="polite"`; a separate `role="status"` region |
| 2.3.3 Animation from interactions | The only motion is the mark, which respects `prefers-reduced-motion` |

## Decisions worth explaining

**No JavaScript required.** The form posts and the server renders the page.
That is not nostalgia: it removes an entire class of accessibility failure and
makes the page work when a script fails.

**A live region, not a spinner.** The Dumi mark carries status visually, and a
`role="status"` region carries it for anyone not looking at the mark. There is
no spinner or typing indicator anywhere in the product.

**Placeholders are not labels.** A placeholder disappears on focus, which is
exactly when someone needs it, and several screen readers skip it.

**A stop control exists** for generated output, as section 15 requires.

**Emergency notices use `role="alert"`** so they interrupt. Everything else
uses `role="note"` or `role="status"`, because an interface that interrupts
constantly trains people to ignore it.

## Not done

- **No manual screen-reader testing.** NVDA with Firefox, JAWS with Chrome,
  and VoiceOver with Safari are the minimum, and none has run.
- **No keyboard-only walkthrough by a person.**
- **No automated axe or Lighthouse run.** No CI check.
- **Contrast ratios not measured.** The palette was designed with contrast in
  mind and nobody has put a meter on it.
- **Streaming announcement untested.** The live region is built for streamed
  text and the endpoint currently returns complete answers, so the behaviour
  that matters most has never been exercised.
- **No testing with real assistive technology users**, which is the only test
  that actually settles anything.

## Recommended before public use

1. Automated axe-core run in CI on the chat and admin pages.
2. Manual pass with NVDA, JAWS and VoiceOver.
3. Keyboard-only walkthrough of ask, read, follow a citation, change language,
   sign in, change password.
4. Contrast measurement of every token pair in both themes.
5. A session with at least one person who uses assistive technology daily.

Items 2 and 5 cannot be substituted with tooling.
