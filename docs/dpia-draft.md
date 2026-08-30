# Data protection impact assessment: draft template

**This is a template with open questions, not a completed assessment.** It
cannot be completed here, because several answers depend on decisions nobody
has made yet and on a deployment that does not exist.

**Requires completion and review by a qualified Swiss privacy professional
before any public deployment.**

## 1. The processing

**What.** An AI assistant answering questions about published Canton of Zug
information, grounded in retrieved official content.

**Why.** To help residents find published information faster than site search.

**Legal basis.** OPEN. For an unofficial prototype this is likely legitimate
interest with no personal data processing. Once the canton adopts it, the
basis is probably a public task under cantonal law, and someone must identify
which provision.

**Controller.** OPEN. The operator today. The canton after adoption. The
transition needs a written agreement.

## 2. Necessity and proportionality

Minimal by construction: no account, no transcripts, no raw addresses. The
open question is whether the hashed client address for abuse control is
necessary, or whether a shared rate-limit bucket would do. A shared bucket is
stricter for users and simpler to justify.

## 3. Data categories

See `docs/privacy.md`. No special-category data is intended. The residual risk
is that a resident types some anyway, which the notice warns against and which
the system cannot prevent.

## 4. Risks

| Risk | Likelihood | Impact | Mitigation | Residual |
|---|---|---|---|---|
| Resident enters personal data in a question | Medium | Medium | Non-dismissible warning; transcripts not stored | The text still reaches Apertus in memory |
| Answer is wrong on a deadline or fee | Medium | High | Citations, confidence policy, refusal on insufficient evidence | Not eliminated |
| Administrator account compromised | Low | High | Argon2id, lockout, audit, forced change | No MFA yet |
| Question text reaches non-Swiss infrastructure | OPEN | High | Self-hosted Apertus | Depends entirely on deployment |
| Audit log altered | Low | Medium | Hash chain, revoked grants | Superuser can rewrite both |

## 5. Open questions

1. Where will Apertus run, and who verifies it?
2. Where will the database and backups be located?
3. Is the hashed client address necessary, or is a shared bucket sufficient?
4. What is the audit retention period, and who decides?
5. Will transcripts ever be stored? If so, on what basis and for how long?
6. Who is the controller, and when does that change?
7. Does the canton's own DPO need to be consulted before a pilot?
8. Is a formal impact assessment required at all under cantonal law, or is
   this document a voluntary exercise?

## 6. Conclusion

**Cannot be reached in this document.** The processing as currently designed
is low risk because it stores almost nothing, but the location questions are
unanswered and the controller is undetermined. Both must be settled before a
conclusion means anything.
