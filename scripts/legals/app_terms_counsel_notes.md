# Counsel notes for app_terms_and_conditions_draft.md

Internal working memo. Not part of the published Terms. Records the
functionality-driven open questions, the owner-confirmed decisions
already applied to the draft, and the product work the draft depends
on. Vendor names appear here only; the published body refers to all
vendors generically.

## Open questions for counsel

1. **No-custody position (asserted).** The document asserts, as the
   operating position: no custody or custody arrangements of any
   kind; a technology platform that helps users manage their own
   keys; no direct fiat activity (every fiat leg via licensed third
   parties, currently Stripe for billing and payouts, Cointree for
   virtual accounts in Australia); token operations facilitated, with
   the value-transfer characterisation left to the user. The
   architecture supports it: keys stored encrypted in the identity
   service; transaction and AI services physically separated and
   never holding key material; signatures producible only under the
   user's own authenticated credential. Counsel should (a)
   stress-test that the assertion holds in each target jurisdiction,
   in particular for signatures made under standing instructions and
   for the key-storage service itself, and (b) align the website ToS
   wording ("you confirm and sign each action") with the formulation
   in the draft ("every signature is made with your keys under your
   authority"), so the two instruments match. The website entity name
   is also still unfilled.

2. **Automations vs "you act for yourself".** Standing instructions
   (auto-accept, scheduled rent, deal runners, NFT-holder policies)
   execute without in-the-moment user confirmation. The signature is
   still made with the user's key under their credential, but the
   authorisation was given in advance. Section 8 frames this as
   advance authorisation with user-set bounds; counsel should confirm
   this framing supports the non-discretionary position.

3. **Wind-down window: DECIDED, up to 5 business days.** Section 17
   commits to a post-termination window of up to 5 business days in
   which platform-managed keys stay usable solely for transfer-out
   (carve-out: legal requirement or fraud prevention). Product must
   BUILD it: a restricted post-termination mode where signing works
   only for transfers to an external wallet or another account the
   user controls. Nothing like this exists today. Counsel notes:
   (a) 5 business days is short; a user who misses the window ends up
   with assets reachable only at our discretion, which revives the
   custody-optics problem the clause exists to avoid. Recommend a
   reactivation-on-request path (window re-opens on written request)
   so the commitment stays credible. (b) "Business day" is defined
   inline in Section 17 (NSW convention).

4. **Creator earnings moved out of T&C scope (owner decision
   2026-07-22).** Section 13 is now a pointer clause: earnings are
   governed by a separate partner agreement, which must be in place
   before earnings arise and which prevails for earnings matters. The
   PARTNER AGREEMENT is therefore a new, undrafted deliverable and
   inherits the open analysis (managed investment scheme?
   employee-like income? payment facility?) plus the mechanics
   removed from the Terms: applicable share (variable, deal by deal),
   accrual on billed usage, paid-invoice condition, 14-day hold,
   US$25 payout threshold, payout onboarding with the third-party
   payout provider, self-dealing exclusion, and clawbacks on
   refunds and reversals. Product note: onboarding must gate earning
   features on the partner agreement being accepted, or the "must be
   in place before earnings arise" statement will not be true.

5. **Credits: DECIDED, monthly-cycle expiry.** Credits expire at the
   end of the monthly billing cycle in which they are granted, with
   no rollover. Remaining check: whether purchased platform credit
   falls under the ACL gift-card regime (3-year minimum expiry for
   in-scope products). If it does, the monthly expiry is
   unenforceable for the purchased portion and the clause needs a
   carve-out. Promotional bonus credit is the clearly exempt part.

6. **AML/CTF.** Section 14's closing paragraph is aligned with the
   no-designated-service posture: law-generic cooperation language
   ("any reports that applicable law requires or permits"), plus
   information-sharing to support the licensed fiat providers' own
   compliance programs. It no longer implies YieldFabric is a
   reporting entity. The open item is the underlying scoping
   analysis: counsel to confirm that no YieldFabric activity is a
   designated service under the amended AML/CTF Act (especially
   virtual-asset safekeeping and transfer-on-behalf, per item 1). If
   that analysis ever concludes reporting-entity status, the
   paragraph must be upgraded to reference the AML/CTF program and
   tipping-off constraints.

7. **Obligation-class third-party control and gate-on-return.** A
   class owner can flip transferability after tokens are held, and
   the verified-recipient rule can block returning an asset to a
   holder whose verification lapsed. Sections 3 and 6 disclose both;
   confirm disclosure is sufficient.

8. **Model-training posture: RESOLVED in draft.** Section 10 commits:
   no training of foundation models on user content, by us or by
   third-party model providers (whose agreements must not permit it).
   Ops note: this is a promise about vendor contracts. Keep
   model-provider agreements on no-training terms (standard
   commercial API terms qualify; consumer-tier or "improve our
   services" terms do not), and re-check on every new provider or
   plan change.

9. **Age and capacity handled by responsibility allocation, not a
   gate.** Section 3 places capacity (including legal age) on the
   user and counterparty diligence on the parties, with no explicit
   18+ representation and no technical gate: sign-up does not capture
   or verify date of birth, and pre-KYC features (chat, AI
   assistants, test mode) are open on that basis. Live-tier KYC
   returns date of birth, so age is effectively verified only at that
   tier. Counsel to confirm (a) the responsibility framing is
   sufficient contractually (a minor's agreement may be voidable
   against us regardless of whose "responsibility" capacity was), and
   (b) whether statutory age-assurance duties (online-safety and
   children's-privacy regimes, especially for the AI-chat surface)
   apply irrespective of contract wording. If so, sign-up DOB capture
   or a KYC-DOB hard gate is product work, not currently built.

10. **Two-instrument strategy.** Website ToS serves marketing-site
    visitors; the app document is accepted at onboarding with
    version, timestamp, and account recorded in internal records
    (each version's exact text retained). Keep the risk and liability
    spine textually consistent between them.

11. **Privacy Policy is a separate, undrafted deliverable.**
    Effectively required under the Privacy Act / APPs. It must cover:
    verification data to verification providers; prompts and context
    to model providers; room ingestion (including copied-in email)
    visible to members; crypto-shred irreversibility; billing data;
    and the compliance information-sharing with licensed fiat
    providers described in Section 14. Section 11 of the draft says
    the policy is "available in the app"; that must become true at
    publication.

## Decisions applied (owner-confirmed, 2026-07-22)

- Contact mailboxes security@ and legal@yieldfabric.com confirmed
  correct.
- Credits expire monthly (see item 5 for the remaining ACL check).
- Fees are GST-inclusive.
- Liability posture: total exclusion to the maximum extent permitted
  by law, no cap formula. The ACL consumer-law clause in Section 16
  MUST stay: a bare "no liability" term is partially void against
  consumers and can itself contravene the ACL.
- Governing law: NSW, non-exclusive NSW courts. Arbitration and
  class-waiver deliberately not adopted. Website ToS aligned
  2026-07-22 (its arbitration, class-waiver, and one-year-bar clause
  replaced with the same NSW-courts formulation).
- No partner naming in the published body; all vendors referred to
  generically.
- Wind-down window: up to 5 business days (item 3).
- Entity: YieldFabric Pty Ltd, ACN 691 006 898.
- AI pricing not stated in the Terms (owner decision 2026-07-22:
  prices are and will be variable); the Terms point to "the rate
  shown in the app before you use it", and the in-app fee schedule
  clause makes that schedule the authoritative price list.
- Platform share not stated in the Terms (owner decision 2026-07-22:
  variable, negotiated deal by deal); the Terms say "net of the
  applicable platform share". The share applying to a given room or
  knowledge graph should be disclosed to the owner in-app or in the
  relevant arrangement, so "applicable" is ascertainable. Remaining
  "currently" figures: hold 14 days, payout threshold US$25.

## Implementation status (app, 2026-07-22)

The Terms are wired into yieldfabric-app onboarding, frontend-only:
the text is bundled versioned in src/legal/termsContent.ts (generated
from the draft), a blocking TermsGate renders ahead of every
/onboarding/* path (email signup, provider ceremonies, invite
continuations, platform setup all mount through the one gated route),
and /terms serves the same text publicly. Acceptance is stored
per-version in localStorage; bumping TERMS_VERSION re-gates.

Proof model under Section 1: completing onboarding is only possible
through the gate, so a completed onboarding at time T proves
acceptance of the version published at T (deployed version history
establishes which version that was; the backend's existing account
records establish T). The localStorage entry is UX state, not the
record. LIMITS: existing pre-gate accounts never pass through
onboarding again and so are not covered; direct API signups bypass
the app entirely; there is no per-account server-side acceptance row.
When a backend change becomes acceptable, add a per-account
acceptance record (version + timestamp) at signup and a re-acceptance
sweep for existing users, which would make Section 1's internal-records
description literally per-account.

## Remaining to publish

- Privacy Policy drafted and linked in-app (item 11).
- Partner agreement for creator earnings drafted; earning features
  gated on its acceptance (item 4).
- Wind-down mode built (item 3).
- Counsel sign-off on items 1, 2, 4, 5 (ACL check), 6, 7, 9.
- Header date set to 1 May 2026 (owner-directed, 2026-07-22).
