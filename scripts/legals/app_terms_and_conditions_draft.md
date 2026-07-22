# YieldFabric Terms and Conditions

Draft for review by counsel. Not yet published. Internal working notes
are maintained separately in app_terms_counsel_notes.md.

**Last updated:** 1 May 2026
**Version:** v1.0
**Entity:** YieldFabric Pty Ltd (ACN 691 006 898) ("YieldFabric",
"we", "us", "our")

---

## 1. Agreement and acceptance

These Terms are a binding agreement between you and YieldFabric Pty
Ltd (ACN 691 006 898). You accept them during onboarding.

When you accept, we record your acceptance in our internal records,
including the version of the Terms you accepted (for example, v1.0),
your account, and the date and time of acceptance. Each published
version of the Terms is identified by a version number, and we retain
the exact text of every version, so that the terms you accepted can
always be established.

If we materially change the Terms, we will publish a new version and
ask you to accept it in the same way before you continue using the
affected features.

If you use the app on behalf of a company, trust, or other group, you
represent that you are authorised to bind it, and "you" includes that
entity.

## 2. What YieldFabric is

YieldFabric is a platform that combines messaging, group coordination,
AI assistants, and blockchain-based tools for creating and managing
bilateral and multilateral agreements. Through the app you can, among
other things:

- chat with other users and with AI agents, individually and in
  shared rooms;
- create, accept, transfer, and cancel obligations (tokenised
  promises, with or without attached token transfers);
- make confidential token transfers whose amounts are encrypted and
  proven with zero-knowledge proofs;
- enter swaps, including collateralised and repo-style structures;
- structure multi-step deals with other parties in deal rooms;
- build and share knowledge graphs from documents, emails, and
  conversations; and
- set up automations that act under authority you grant them, on a
  schedule or trigger.

**What these Terms cover.** In these Terms, "the app" means the
services we operate (the "Services"): the YieldFabric applications
and logged-in web surfaces, our APIs and SDKs, and every feature made
available through them, however you access them. Applications built
by third parties on top of our APIs are the products of their
developers and are governed by those developers' own terms. These
Terms govern only the underlying Services that we provide.

**Technology only; no custody; no fiat.** YieldFabric is a technology
platform. We are not a bank, deposit-taker, custodian, exchange,
broker, payment processor, money transmitter, or adviser. We have no
custody arrangement of any kind with you. We do not hold, control, or
take title to your assets or funds, and we do not accept, hold, or
transmit fiat currency for you. The software helps you manage your
own keys (Section 4) and facilitates operations on tokens that you
and your counterparties create and control (Section 6). Whether any
token is used to represent or transfer value is a choice you make and
a responsibility you bear. Where a feature touches fiat money, such
as paying our fees or moving fiat in or out, that activity is
performed entirely by authorised third-party providers holding the
appropriate regulatory licences (Sections 9 and 15), and never by us.
Nothing in the app is financial, legal, accounting, or tax advice.

## 3. Eligibility and verification

**Capacity is your responsibility.** It is your responsibility to
ensure that you are legally capable of entering into these Terms, and
into any agreement you make through the app, on your own behalf. This
includes ensuring that you are of legal age where you live and that
you hold any authority you claim, for example to act for a group or
legal entity. We rely on this and do not independently verify it.

**Know your counterparty.** Each party to an agreement is responsible
for satisfying itself about who it is dealing with, including that
party's identity, capacity, and authority to enter into the
agreement. The verification tiers described below show which checks a
counterparty has completed. They are information, not a warranty from
us. YieldFabric takes no responsibility for the decisions
counterparties make, for their identities, or for their capacity or
authority to enter into agreements.

**Sanctions and location.** You represent that you are not located
in, a resident of, or a national of a comprehensively sanctioned
jurisdiction; that you are not on any sanctions or denied-party list;
and that you are not acting for anyone who is.

**Tiered verification.** The app has verification tiers, and features
unlock by tier:

- Email verification is required before you can register signing keys
  or transact on test networks.
- Identity verification (KYC) with the third-party verification
  providers shown in the app (which may vary by region and flow) is
  required before you can transact on live networks.
- Business verification (KYB) is required before a group that
  represents a legal entity can transact on live networks. Group
  verification is separate from, and additional to, the verification
  of its individual members.

**Verification is tooling, not a guarantee.** The verification tiers
are tooling that the platform offers so that an auditable set of
records, tied to reasonable information about its users, exists
alongside activity on the platform. Verification outcomes are
produced by third-party providers from the documents and data each
user supplies. A user passing identity or business verification does
not mean that YieldFabric guarantees that the user's identity is
accurate. Nor does it mean that the user has been verified for anyone
else's purposes: if you have your own know-your-customer, anti-money
laundering, or onboarding obligations, verification on the platform
does not discharge them, and a counterparty's platform verification
does not discharge yours. If a party chooses to accept or rely on the
platform's verification process as part of its own onboarding or
compliance program, that choice is entirely that party's own and
falls entirely under that party's responsibility. YieldFabric carries
no responsibility for it.

**Your information.** You agree to provide accurate and current
information, to complete any re-verification we reasonably require,
and that we may share your verification data with the third-party
providers that perform the checks. If you have not completed the tier
a feature requires, or your verification lapses or is withdrawn, the
app will restrict that feature, including pausing your ability to
sign transactions, until the requirement is met. Some restrictions
have on-chain effect. For example, a compliance-gated token cannot be
transferred to a recipient whose verification has lapsed, even to
return an asset that recipient previously held.

## 4. Accounts, keys, and signing

**Two ways to hold keys.** Your account is backed by cryptographic
keys, and how they are held determines who can sign:

1. **Platform-managed keys (default).** Unless you register your own
   external key, the app generates signing and encryption keys for
   you and stores them encrypted in our identity service. These keys
   are yours, and only you use them. The platform facilitates that
   use; it does not use your keys itself. Every signature is produced
   under your own authenticated credential: a signing operation
   happens only when (a) you initiate an action in the app, or (b) a
   standing instruction or automation that you configured acts under
   the authority you granted it (Section 8). The platform cannot sign
   with your keys on its own initiative and never uses them for its
   own account. As a structural safeguard, the identity service that
   stores your keys is operated separately from the
   transaction-processing and AI services. Those services never hold
   your key material and can only request a signature by presenting
   your credential to the identity service. Storing an encrypted copy
   of your key is a technical service that helps you manage your own
   key. It is not a custody arrangement: we do not hold your assets,
   take title to them, or acquire any right to deal with them.
2. **External keys (self-custody).** You may instead, or in addition,
   register an external wallet (for example, a browser-extension
   wallet or a passkey). External keys never leave your control, and
   every transaction they authorise requires your manual signature at
   the time. We cannot recover an external key. If you lose it, you
   may permanently lose access to the associated assets.

**Credentials.** You are responsible for your login credentials, API
keys, connected devices, and anyone you allow to act through them.
Notify security@yieldfabric.com immediately if you suspect
unauthorised access. API keys you issue for backend automation can be
revoked by you at any time in the app; until revoked, actions taken
with a valid key are treated as yours.

**Deletion of encrypted data.** Some of your data (for example,
private position amounts) is encrypted under keys derived from your
account's encryption keypair. If that keypair is destroyed, including
at your request as part of account deletion, that data becomes
permanently unreadable by anyone, including us. Records on blockchain
networks cannot be deleted by anyone (Section 6).

## 5. Test mode and live mode

The app operates in two modes:

- Test mode uses test blockchain networks. Test assets, balances, and
  transfers have no monetary value, may be reset or discarded at any
  time, and exist only for evaluation.
- Live mode uses production networks and real value, and requires
  identity verification (Section 3) and, where indicated in the app,
  a payment method on file (Section 9).

You must not treat anything in test mode as a representation of
value.

## 6. On-chain activity: obligations, token transfers, and swaps

**Terminology.** In these Terms, a "transfer" means moving tokens
between blockchain accounts. We reserve the word "payment" for fiat
money, and fiat payments happen only through licensed third-party
providers (Sections 9 and 15), never through us. The app does not
provide a payment service. It facilitates token operations whose
meaning you and your counterparties define, as described below.

**Finality.** Blockchain transactions are generally final and
irreversible once settled. We cannot reverse, recall, or charge back
a settled transaction. Review every action before you authorise it.

**You transact with counterparties, not with us.** Obligations,
deals, and swaps are between you and the other party. We do not
guarantee or underwrite any counterparty's identity (verification
tiers are third-party tooling, not our warranty, as described in
Section 3), solvency, or performance. You bear counterparty risk.

**Tokens, and what they mean, are yours.** The app facilitates
operations on tokens: minting, accepting, transferring, escrowing,
and settling them on-chain. Tokens are created and controlled by
users and the protocol, not by us. Some tokens could be used as
value-transfer instruments. Whether a token carries, represents, or
transfers value is determined by how you and your counterparties
choose to use it, and that choice, including its legal, regulatory,
and tax consequences, is yours. We take no part in any fiat
settlement between you and a counterparty.

**Escrow and expiry.** Tokens committed to an obligation or swap are
held in escrow by the protocol's on-chain smart contracts, not by us,
until the obligation is accepted, cancelled, or expires. Once an
obligation's expiry time passes, it can no longer be accepted or
cancelled. Recovering escrowed tokens after expiry requires the
separate "expire" action available in the app, which any party may
trigger. Until a linked obligation reaches a final state, an escrowed
transfer cannot be individually withdrawn.

**Confidential amounts.** Transfer amounts in confidential flows are
encrypted. They are visible to the transacting parties (and, to the
extent required to operate the service, to us) but are not published
in plaintext on-chain. Confidentiality is a technical feature, not a
guarantee: metadata such as parties, timing, and token classes may
still be observable on public networks.

**Obligation classes.** Obligations are minted into "classes" that
carry policies set by the class owner, including whether anyone can
mint into the class and whether its tokens are transferable or
non-transferable. A class owner can change these policies after you
hold a token of that class. If you transact in a class you do not
own, you accept that the class owner controls those settings.
Compliance-gated classes additionally restrict transfers to verified
recipients.

**Automatic acceptance.** In defined cases the protocol completes
steps for you automatically. For example, an obligation you mint to
yourself with no attached token transfers is accepted at mint, and
certain incoming transfers are accepted automatically where you have
enabled an automation. The app discloses these behaviours where they
apply.

**Network risk.** Blockchains can fork, congest, fail, or be
exploited, and smart contracts can contain defects. You accept these
risks (Section 16).

## 7. Groups, deal rooms, and acting for others

**Groups.** A group (including a deal room's group account) can hold
its own wallet and assets. Members with the relevant role can act for
the group. When you act for a group you bind it, and when others with
authority do so, the group is bound even if you disagree. Group
owners and administrators are responsible for managing membership and
roles.

**Deal rooms.** Content you post, documents you upload, and emails
you copy into a deal room (via the room's ingestion email address)
are visible to room members and may be processed by AI features
(Section 10) to extract claims, terms, and structure. Do not share
content in a room unless you intend every member to see it.

**Delegation.** When you act for a group, the app issues a scoped
delegation credential. Its scope is limited by your role, the group's
verification status, and policy. Some permissions are removed on live
networks until the group's business verification is complete.

## 8. Automations and standing instructions

The app lets you configure software that acts without your presence.
Automations use your keys (or your group's keys) under the authority
you grant them, and each action they take is signed under your
credential, within the scope you configured. Examples include:

- recurring or scheduled token transfers under a deal (for example,
  rent under a lease deal);
- automatic acceptance of incoming token transfers so that received
  tokens become usable;
- multi-step deal execution that advances a deal as counterpart steps
  complete; and
- policies that authorise a named executor, or the current holder of
  a specific NFT, to initiate token transfers within bounds you set
  (amount limits, use counts, and time windows).

By enabling an automation you authorise in advance every action
within its configured scope, and those actions bind you as if you had
signed them individually. You are responsible for the bounds you set.
Transferring an NFT that carries an executor policy transfers that
authority with it; such an NFT functions in practice as a bearer
instrument and should be safeguarded accordingly. You can stop an
automation at any time in the app, which also revokes its
credentials. Stopping does not undo actions already taken or
transactions already submitted.

## 9. Fees and billing

**Metered usage.** Paid features are billed on usage, including:

- AI usage, displayed and billed as agent time at the rate shown in
  the app before you use it, covering model inference across chat,
  agents, extraction, and knowledge features;
- network fees for blockchain transactions we relay for you, priced
  per the fee schedule in the app, which may include a margin over
  raw network cost; and
- knowledge and content fees where a room or knowledge graph owner
  (Section 10) has set a price for access (Section 13).

The in-app fee schedule at the time of use is the authoritative price
list. We may change prices prospectively with notice in the app.

**Payment methods and plans.** All fiat payments for our fees are
processed by an authorised third-party payment provider. We never
receive, hold, or process your card details or fiat funds ourselves.
Depending on configuration, you may be billed post-paid on a card on
file, or pre-paid via credit plans (packs of platform credit, which
may carry bonus credit and promotional pricing). Credits are
non-refundable except as required by law, have no cash value, are not
transferable, and expire at the end of the monthly billing cycle in
which they are granted. Unused credit does not roll over to the next
cycle. Where the app indicates that a card is required before paid
use, you must add one before those features activate.

**Group billing.** A group's usage is billed under the group's
billing policy: either to the group's billing administrator
("admin-pays", the default) or to the acting member ("member-pays").
If you join or act in a group with a member-pays policy, your account
is charged for what you do there. Group owners and administrators are
responsible for choosing the policy and informing members.

**Non-payment.** If your account becomes delinquent, or a required
card is missing, we may pause paid features, including AI usage and
transaction signing, until the issue is resolved. Pausing does not
cancel amounts already owed. On-chain assets you hold are unaffected
by a billing pause, but actions that require our systems will be
unavailable.

**Billing errors.** If you believe a charge or metered usage is
wrong, contact us via in-app support or legal@yieldfabric.com within
30 days of the charge. We will investigate and correct verified
errors. You may withhold a disputed amount in good faith while we
investigate; undisputed amounts remain payable. This clause does not
limit any non-excludable rights you have under consumer law.

**Taxes.** Our fees are inclusive of GST and any other applicable
sales taxes. You remain responsible for taxes arising from your own
transactions and earnings.

## 10. AI features and your content

**AI output is not advice.** AI agents, deal briefs, extracted terms,
pricing models, and similar outputs are generated tools. They can be
wrong, incomplete, or out of date. You must independently verify
anything you rely on, and you make your own decisions.

**Ingestion.** When you upload documents, connect sources, or email
content into a room, we process that content, including with AI
models, to index it, extract entities and claims, and build knowledge
graphs. By submitting content you confirm that you have the right to
share it and to have it processed in this way.

**Knowledge graphs.** A "knowledge graph" is a structured index that
the platform derives from ingested content: the entities, claims, and
relationships extracted from documents, messages, and other material
in a room or workspace. A knowledge graph belongs to the room or
workspace in which it was created, and its "owner" in these Terms is
the account or group that controls that room or workspace. The
underlying content remains the property of whoever submitted it (see
"Your licence to us" below); the knowledge graph is a derived index
that we host and process under that licence.

**Visibility.** Knowledge derived from your content is scoped to the
room or workspace in which it was created and is visible to that
room's members. Content explicitly marked platform-visible is
available to all users. AI answers show provenance (which graph or
room a fact came from) only for sources you can access.

**Your licence to us.** You retain ownership of your content. You
grant us a worldwide, non-exclusive licence to host, process,
transform (for example, into embeddings and graph structures), and
display it as needed to operate the features that you and your rooms
use.

**No model training on your content.** Your content, prompts, and
documents are used to serve you and your rooms, through indexing,
retrieval, and generating responses. They are not used to train
foundation models, whether ours or anyone else's.

**Third-party models.** AI features may be powered by third-party
model providers. Your prompts and relevant context are shared with
them to generate output, under agreements that do not permit them to
use your content to train their models.

## 11. Privacy and your data

Our Privacy Policy, available in the app, explains how we collect,
use, and share personal information. It forms part of these Terms. In
particular:

- verification data is shared with the third-party verification
  providers that perform the checks (Section 3);
- your prompts and relevant context are shared with third-party model
  providers to generate AI output (Section 10);
- content submitted for ingestion, including email copied into a deal
  room, is processed, indexed, and made visible to the room's members
  (Sections 7 and 10);
- some of your data is encrypted such that destroying your account's
  encryption keypair makes it permanently unreadable by anyone
  (Section 4); and
- on-chain records live on blockchain networks and cannot be deleted
  by us or by anyone else (Section 6).

## 12. Intellectual property and your licence to use the app

The Services, including the software, the smart-contract code we
author, designs, text, and trademarks, are owned by YieldFabric or
its licensors. We grant you a limited, non-exclusive,
non-transferable, revocable licence to use the Services as these
Terms permit. Nothing in these Terms transfers our intellectual
property to you. Your content remains yours (Section 10), and the
tokens and agreements you create through the Services are yours
(Section 6). Owning a token minted through our contract code gives
you the token, not rights in the code. Open-source components
included in the Services are licensed under their own terms.

## 13. Creator earnings

Room owners and knowledge graph owners (Section 10) may be offered
the opportunity to earn a share of the revenue their content or rooms
generate, for
example a margin on AI usage in their room or per-access fees on
their knowledge graphs. Any such earnings are governed by a separate
partner agreement between you and YieldFabric, which must be in place
before earnings arise. That agreement, and not these Terms, sets the
applicable revenue share, accrual, holds, payout conditions, and any
adjustments, and it prevails over these Terms in relation to
earnings. Earnings are a contractual revenue share for making content
and rooms available. They are not interest, an investment return, or
employment income, and we make no representation about how much, if
anything, you will earn. You are responsible for your own taxes on
earnings.

## 14. Acceptable use

You must not use the app to:

- break any law, regulation, or sanctions regime, or launder money or
  finance terrorism;
- deal in proceeds of crime, or structure transactions to evade
  reporting or verification requirements;
- offer regulated financial services to others, for example by
  running an unlicensed lending, exchange, custody, or advisory
  business through your account or rooms;
- manipulate markets or engage in fraud or deceptive transactions;
- misrepresent your identity or authority, or circumvent verification
  tiers, billing gates, or usage restrictions, including through
  multiple accounts;
- upload content that is unlawful or infringing or that you have no
  right to share, or ingest other people's personal information
  without a lawful basis; or
- probe, disrupt, overload, or reverse-engineer the Services, scrape
  at scale, or access other tenants' data.

We may investigate suspected violations, restrict features while we
do, and cooperate with law enforcement and regulators, including by
making any reports that applicable law requires or permits us to
make. The licensed third-party providers that deliver fiat activity
(Section 15) have their own compliance obligations, and we may share
relevant information with them to support their compliance.

## 15. Third-party services

The app depends on third parties that we do not control: blockchain
networks, AI model providers, payment and billing providers, identity
verification providers, and any fiat on-ramp or off-ramp providers
offered in your region. Every fiat-money activity offered in or
around the app, including fee billing, payouts, and moving fiat in or
out, is delivered by authorised third parties holding the appropriate
regulatory licensing for that activity. We perform none of it
ourselves, and when you use such a service your relationship for that
activity is with the licensed provider. The availability and conduct
of third parties are outside our control, and your use of them may be
subject to their own terms, which we will surface where practical.

## 16. Risk, disclaimers, liability, and indemnity

**Assumption of risk.** Digital assets and on-chain activity carry
significant risk. By using the Services you acknowledge and accept,
among others, the following risks: digital asset values can be
volatile and you may suffer total loss; smart contracts and
blockchains can contain defects, fail, fork, or be exploited; the
regulatory treatment of digital assets is evolving and uncertain;
transactions are typically irreversible and mistakes may be
unrecoverable; loss of an external key means loss of access; your
assets are not insured or guaranteed by any government scheme; and a
counterparty may default or fail to perform.

**Release.** To the fullest extent permitted by law, you release
YieldFabric and its officers, employees, and contractors from all
claims, demands, and damages arising out of or related to: your own
decisions and transactions; the acts or omissions of your
counterparties; loss of, or unauthorised access to, your keys,
credentials, or assets; price or market movements; and the failure,
exploitation, fork, congestion, or unavailability of any blockchain,
smart contract, wallet, or third-party service.

**No warranties.** The Services, including all AI output, are
provided "as is" and "as available", without warranties of any kind,
express or implied, including merchantability, fitness for a
particular purpose, title, accuracy, and non-infringement, to the
maximum extent permitted by law. We do not warrant that the Services
will be uninterrupted, error-free, accurate, or secure.

**Liability.** To the maximum extent permitted by law, YieldFabric
and its officers, employees, and contractors accept no liability to
you for any loss or damage arising out of or in connection with the
Services, however caused, including by negligence, and whether direct,
indirect, incidental, special, or consequential.

**Consumer law.** Nothing in these Terms excludes, restricts, or
modifies any right or remedy that cannot be excluded, restricted, or
modified by law, including the consumer guarantees under the
Australian Consumer Law. Where liability for breach of a
non-excludable guarantee can be limited, our liability is limited, at
our option, to supplying the relevant services again or paying the
cost of having them supplied again.

**Indemnity.** You indemnify YieldFabric and its officers, employees,
and contractors against all claims, losses, liabilities, and expenses
(including reasonable legal fees) arising from your content, your
deals and transactions, your automations acting within the scope you
configured, your breach of law, or your breach of these Terms. This
obligation survives termination.

## 17. Suspension, termination, and survival

**Ending use.** You may stop using the app at any time and may
request account deletion. Section 4 describes the effect of deletion
on encrypted data.

**Our rights.** We may suspend or restrict features, or terminate
your access, for breach of these Terms, to comply with law, to
protect other users or the Services, or for non-payment, using the
least restrictive measure reasonably available. Where lawful, we will
give notice and an opportunity to remedy.

**The Services will evolve.** We may add, change, or retire features,
and may suspend or discontinue the Services in whole or in part.
Where a change materially reduces what you can do with existing
assets or in-flight deals, we will give reasonable advance notice
where practicable. Any discontinuation that affects access through
platform-managed keys triggers the wind-down commitment below.

**Your on-chain assets are yours.** They are yours before, during,
and after termination. We never hold them (Section 2), and ending
your app access does not change who owns them. If your assets are
accessible through platform-managed keys, we provide a wind-down
window: for up to 5 business days after termination takes effect
(a "business day" being a day other than a Saturday, Sunday, or
public holiday in New South Wales), you may continue to use your keys
through the app solely to transfer your assets to an external wallet
or another account you control. We may shorten or withhold the window
only where the law requires it or where continued access would enable
fraud or harm to others.

**Survival.** Accrued fees, on-chain records, and Sections 12, 16,
18, and 19 survive termination. Amounts payable under a separate
partner agreement (Section 13) are governed by that agreement.

## 18. Governing law and disputes

These Terms are governed by the laws of New South Wales, Australia,
without regard to conflict-of-laws rules. The courts of New South
Wales have non-exclusive jurisdiction over any dispute relating to
the Services.

Before starting any formal proceeding, contact us at
legal@yieldfabric.com. Both parties agree to attempt in good faith to
resolve any dispute for at least 30 days before commencing formal
proceedings.

## 19. Changes, notices, and general terms

**Changes.** We may update these Terms. Material changes require
re-acceptance, recorded as described in Section 1, before continued
use of the affected features.

**Notices.** Notices will be sent to your registered email address or
presented in-app. You consent to receiving these Terms, notices, and
other communications electronically.

**Feedback.** If you send us feedback or suggestions, we may use them
without restriction or obligation to you.

**General.** These Terms, together with the Privacy Policy (Section
11) and any feature-specific terms presented in-app, are the entire
agreement between us regarding the Services and supersede any prior
understanding. If any provision is held unenforceable, it will be
modified to the minimum extent necessary or severed, and the
remainder continues in full effect. A failure to enforce a right is
not a waiver of it. You may not assign these Terms without our
consent; we may assign them as part of a corporate reorganisation,
financing, or sale of assets. Nothing in these Terms creates a
partnership, joint venture, agency, or employment relationship.
Neither party is liable for delay or failure caused by events beyond
its reasonable control, including blockchain or third-party failures
and changes in law or regulatory action.

**Contact.** Questions about these Terms can be sent to
legal@yieldfabric.com.
