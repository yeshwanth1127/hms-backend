# The clinic workspace
## A book of UX decisions

**Product:** Avocado Health staff workspace

**Version:** 1 — 1 October 2026

**Scope:** One clinic deployment, shared staff sign-in, core scheduling modules and optional patient communication modules.

**Audience:** Clinic owners, reception staff, growth managers, product designers and engineers.

This document records why the interface works as it does. It distinguishes decisions implemented in this release from operational checks that still require the real clinic and provider accounts. It is a working decision record, not evidence of user research or clinical approval.

---

## Contents

1. [The problem we are solving](#1-the-problem-we-are-solving)
2. [Users, work and boundaries](#2-users-work-and-boundaries)
3. [Product principles](#3-product-principles)
4. [The module map](#4-the-module-map)
5. [Information hierarchy](#5-information-hierarchy)
6. [Visual system and typography](#6-visual-system-and-typography)
7. [Sign-in and account lifecycle](#7-sign-in-and-account-lifecycle)
8. [Roles and optional modules](#8-roles-and-optional-modules)
9. [WhatsApp overview](#9-whatsapp-overview)
10. [Reception conversations](#10-reception-conversations)
11. [Issues, ratings and attachments](#11-issues-ratings-and-attachments)
12. [Doctor content](#12-doctor-content)
13. [Campaign creation](#13-campaign-creation)
14. [Preview, testing and approval](#14-preview-testing-and-approval)
15. [Follow-ups](#15-follow-ups)
16. [Appointment management](#16-appointment-management)
17. [Doctors and schedules](#17-doctors-and-schedules)
18. [Clinic details](#18-clinic-details)
19. [Delivery states](#19-delivery-states)
20. [Language, time and money](#20-language-time-and-money)
21. [Accessibility and responsive behavior](#21-accessibility-and-responsive-behavior)
22. [Empty, error and recovery states](#22-empty-error-and-recovery-states)
23. [Security as part of the experience](#23-security-as-part-of-the-experience)
24. [Deployment and data ownership](#24-deployment-and-data-ownership)
25. [Verification and acceptance criteria](#25-verification-and-acceptance-criteria)
26. [Trade-offs and next improvements](#26-trade-offs-and-next-improvements)

---

## 1. The problem we are solving

The previous WhatsApp page mixed account access, uploads, reception work, campaigns, follow-up rules, clinic details and delivery records into a long collection of forms. Its large editorial headings competed with the work. The user could not easily tell which action to take first or whether an action would send a message. Staff were asked to obtain an administrator API key, and typed staff names served as audit labels without proving who acted.

**Decision:** Replace that page with a task-oriented staff workspace served by the backend. Give each recurring task a predictable location, make preparation visibly different from sending, and establish a real named-account session.

**Acceptance:** A staff member can identify reception work from the overview, upload a specialty PDF in Doctor content, find a WhatsApp booking in Appointments, and create a campaign without seeing an API-key field.

## 2. Users, work and boundaries

| User | Main job | Access |
| --- | --- | --- |
| Reception / clinic staff | Manage visits, respond to patients and keep doctor introductions current | Core clinic modules and enabled WhatsApp |
| Clinic administrator | Manage the same work, provision accounts and choose optional modules | Clinic operations, enabled growth modules, account and module settings |
| Growth manager | Prepare booking links, inspect acquisition reports and review Google concepts | Enabled Google Business / growth analytics; no patient appointment or WhatsApp access |
| Patient | Book, manage a visit, request help and choose message preferences | WhatsApp patient flow; no staff workspace |

The interface is for operating a clinic, not making diagnoses. It does not infer clinical follow-up dates, promise emergency monitoring, prescribe care or convert marketing behavior into a medical judgment.

## 3. Product principles

1. **Start with the task.** Navigation uses Appointments, Conversations and Doctor content, rather than transport or database terms.
2. **One place for each record.** WhatsApp bookings remain authoritative backend appointments.
3. **Make consequences visible.** Saving, queuing, approving and delivering are different states.
4. **Show the next useful action.** Empty states explain where future records come from and how to proceed.
5. **Use progressive disclosure.** Edit forms and consequential confirmations open only when needed.
6. **Earn trust with accurate states.** A request accepted by a provider is not proof that a patient received it.
7. **Keep permission independent of appearance.** Hidden navigation is backed by server enforcement.
8. **Keep the interface calm.** Color and emphasis signal priority; decoration does not compete with patient work.

## 4. The module map

The workspace has persistent primary navigation:

- **Appointments:** existing bookings and status changes.
- **Doctors:** active directory, consultation fee and virtual consultation settings.
- **Schedules:** dated recurring availability rules.
- **WhatsApp:** overview, conversations, doctor content, campaigns, follow-ups, delivery history and clinic details.
- **Google Business:** optional profile setup, prepared booking links, illustrative patient journey and capability map.
- **Growth analytics:** optional backend appointment attribution and attendance reporting.
- **Settings:** staff accounts, password change and optional module configuration.
- **Design & UX guide:** this decision book, available inside the workspace.

WhatsApp is a module, not a separate application or separate login. `/whatsapp-assets` redirects to `/staff/whatsapp` to preserve the old entry point.

**Why:** A staff member should be able to move from a patient conversation to appointment management without re-authenticating or changing tools. Primary navigation represents the clinic's work; secondary tabs represent tasks within a module.

## 5. Information hierarchy

Each page follows the same order:

1. Workspace breadcrumb and environment label.
2. Module or page title and a short explanation.
3. Module navigation, if the page has sub-tasks.
4. A relevant operational state, such as patient outreach being paused.
5. The current task: inbox, table, editor or guided workflow.
6. Contextual guidance close to the action it affects.

A module title does not become a promotional hero. Page headings are approximately 28px, section headings 16–20px, task text 13–14px, and secondary labels 11–12px. Labels stay visible after a field is filled; placeholders are examples, not the only labels.

**Why:** A returning operator needs recognition and predictable scanning. Clear relative emphasis matters more than adding cards or decorative statistics.

## 6. Visual system and typography

**Components:** Generated shadcn/ui components provide buttons, inputs, selects, tables, tabs, dialogs, switches, badges, alerts, skeletons and the sidebar. The generated source is in `staff-web/src/components/ui`; this is an actual shadcn implementation, not a CSS imitation. The selected registry base is Base UI Nova with neutral tokens.

**Typeface:** Self-hosted DM Sans Variable. One family keeps forms, tables and navigation consistent. It is bundled with the build so the staff interface does not make an external font request.

**Palette:** White content surface, a pale neutral sidebar, dark green primary actions, muted green selected states and amber attention states. Borders organize information without heavy shadows. Status includes words; color is supplementary.

**Spacing:** A consistent 4px-based rhythm, 16–24px component gaps and a bounded content width. Dense tables are used for comparing records; cards group different kinds of work.

**Motion:** Component transitions remain brief. There are no decorative entrance animations that delay access to operational information. Reduced-motion preferences are respected.

**Trade-off:** This is a restrained staff interface. The patient's WhatsApp experience can remain warm and pictured without importing promotional styling into administration.

## 7. Sign-in and account lifecycle

**Decision:** Staff sign in with a username and password. Display name is the human label; username is the stable sign-in identifier. There is no API-key field in the staff interface.

- Passwords are stored as Argon2id hashes, not plaintext.
- The browser receives an opaque HttpOnly session cookie.
- The database stores a hash of the session token.
- Sessions expire after eight hours and after 30 minutes of inactivity.
- Sign-out revokes the session server-side.
- Password change revokes all sessions for that account.
- Account disablement is checked on every authenticated request.
- Sign-in attempts have persisted account and source-address limits.
- Unknown, incorrect and disabled accounts use the same failure message.

The first administrator is created through an operator CLI after migrations. There is no built-in password, public registration endpoint or reusable production demo account. Administrators can create individual staff accounts in Settings. Operator recovery and disablement use `app.staff_cli`.

**Local preview:** A generated local-only administrator exists in an isolated database. Its credentials are kept in a gitignored, permission-restricted local file. They are not deployment credentials.

**Why:** Staff should perform a familiar sign-in task. Service credentials belong to infrastructure, and a claimed staff name should not replace authentication.

## 8. Roles and optional modules

Module availability requires both clinic enablement and staff permission. Administrators can enable or disable optional modules independently. Core appointments, doctors and schedules remain included.

- Existing WhatsApp deployments stay enabled when no module record exists.
- A saved disabled WhatsApp record always overrides that compatibility default.
- Google Business and growth analytics start disabled.
- Disabling retains existing content, consent records, appointment records and audit history.
- WhatsApp worker claims and pre-send checks respect the module flag in addition to outreach settings.
- Signed incoming events and delivery outcomes can still persist while WhatsApp is disabled. Pending work is not dropped.
- A send already handed to an external provider cannot be recalled by a module switch.

**Scope:** These are configuration switches for one clinic deployment. They are not multi-tenant isolation, billing entitlements or a subscription system.

## 9. WhatsApp overview

The overview answers two questions: **What needs attention? What should I do next?**

Four compact metrics summarize open reception conversations, campaign drafts, offer subscribers and specialty PDF coverage. Each has a plain-language label and a route to the corresponding task. They are operational counts, not decorative charts.

The next-steps panel prioritizes reception, doctor introductions and approved message readiness. Recent drafts remind staff that preparation sends nothing. The right-hand guidance explains patient permission, testing and contact limits. Appointment management has a direct route because booking changes belong to the shared appointment module.

**Why:** The starting page needs to orient a new staff member and remain useful during repeated daily visits. It does not assume that a blank inbox means the WhatsApp provider is connected.

## 10. Reception conversations

Use a master-detail inbox: open conversations on the left, selected conversation on the right. Narrow screens stack the panels.

- A contact is shown by its verified sender phone when no authoritative patient name is available.
- The latest message provides list context.
- Assignment is taken from the signed-in staff identity.
- Incoming and outgoing messages have distinct alignment and an actor/time label.
- The bot-paused state is stated explicitly.
- Reply controls are disabled if the service window is closed or patient delivery is paused.
- Queueing a reply produces a queue confirmation, not a delivered claim.
- Closing requires a confirmation that explains the bot will resume.

**Why:** Reception needs continuity and ownership, not a series of unconnected cards. The interface does not invent a contact name or hide the provider's free-text reply window.

## 11. Issues, ratings and attachments

Issues and private feedback are a separate tab inside Conversations. A table distinguishes the sender, message, type and status. Ratings are shown without turning them into public reviews. Patient media links use authenticated private endpoints.

Reception messages and issue attachments remain different from clinic-owned campaign files. The campaign selector cannot reuse patient documents. Resolving an issue changes its support status; it does not imply a clinical case was resolved.

**Why:** Patient-provided media has different ownership and privacy expectations from a doctor brochure.

## 12. Doctor content

Two tabs separate **Specialty PDFs** and **Doctor portraits**. Search works by specialty or doctor name. Each row states current file, readiness and an upload/replace action. Files are linked to their corresponding backend record rather than a loose media library.

PDFs are limited to 10 MB; PNG/JPEG portraits to 5 MB. The upload control accepts drag-and-drop and an accessible file-picker button. A replacement affects future bot messages. Server-side type, file signature and parsing checks remain authoritative; production scanning fails closed when unavailable.

**Why:** “Upload a PDF” is incomplete unless the staff member knows which specialty will use it. The list provides that association and makes missing content visible.

## 13. Campaign creation

A campaign is a guided four-step sequence:

| Step | Staff decision | Outcome |
| --- | --- | --- |
| Message | Select a supported approved template; fill fields and choose required media | Live visual preview, no send |
| Audience & timing | Choose clinic/specialty filters, time, estimated rate and budget | Saved draft and audience preview, no send |
| Test | Choose a configured verified phone and explicitly request one test | Queued test; staff must observe receipt |
| Review | Check recipient count, estimate, message, timing and identity | Explicit approval of the current audience |

Saving does not implicitly send a test or approve a campaign. Drafts are fixed after saving because the approval record must refer to exact content and audience parameters. A changed message is created as a new draft. The UI explains this limitation rather than presenting a misleading edit button.

**Why:** The old long form exposed every field and action at once. Sequential steps reduce scanning and put consequences at the moment of decision.

## 14. Preview, testing and approval

The preview stays beside the composer on desktop and follows it on narrow screens. Template body fields update in place. The preview includes a static text header, approved image/PDF, footer and button labels when supported. It is explicitly illustrative; WhatsApp determines final rendering.

A test is restricted to configured phones. Queue acceptance is not the receipt checkbox. The staff member must check the actual phone; the backend also requires evidence of a provider-accepted test before approving patients.

Approval shows the exact consented audience count and budget estimate. The backend compares the current audience hash with the reviewed snapshot. Changed consent or audience produces a refresh requirement rather than silently approving different patients.

**Why:** Outreach is an external communication. The interface must make it hard to confuse preparation with sending, and must retain server checks even if a client changes its UI.

## 15. Follow-ups

Follow-ups are separate from marketing campaigns because their purpose and trigger differ.

- Post-visit feedback follows a staff-recorded completed visit.
- Missed-visit rebooking follows a staff-recorded no-show.
- Doctor-requested follow-up needs a completed visit and a staff-selected date.

Rules open in focused dialogs. Staff select an approved compatible template, delay and enabled state. Template fields are booking reference, doctor and visit time. Visit-message consent and the current appointment state are checked at send time. Marketing-classified care templates also require offer consent.

**Why:** The system should automate an agreed administrative workflow, not infer treatment schedules or interpret a patient's medical needs.

## 16. Appointment management

The Appointments module uses existing authoritative backend records. Search supports patient name, phone and booking reference. Status filtering narrows daily work; source labels distinguish website, voice and WhatsApp.

Status changes open a confirmation with patient, reference, visit time and new status. A reason can be recorded. The available actions reflect the backend transition rules; future visits cannot be marked completed or no-show. The interface explains that completion/no-show may trigger configured follow-ups and that cancellation releases a slot.

**Why:** Booking administration should remain one module regardless of the channel that created the record. A status change may affect scheduling and outbound communication, so it deserves context.

## 17. Doctors and schedules

Doctors show directory status, fee and specialty. Edit controls use the existing server contract. Fee changes apply to future bookings, preserving already-recorded fee snapshots.

Schedules use a first concrete date, clinic timezone, start/end time, slot duration and optional last date. The chosen doctor limits the clinic selector to assigned branches. The first date determines the recurring weekday. Removing a rule requires a confirmation and does not cancel existing booked appointments.

**Current limit:** This initial staff scheduler creates physical consultation rules. Backend virtual consultation and exception contracts remain separate; the interface must not imply that toggling a doctor's virtual flag automatically creates virtual availability.

## 18. Clinic details

Clinic cards show branch name, area, address, arrival instructions and a directions link. Editing opens one clinic at a time. Directions validation accepts approved HTTPS Google Maps forms; the UI does not turn arbitrary URLs into trusted clinic directions.

**Why:** Patient confirmations need accurate location guidance. Clinic-wide settings should not be mixed into every campaign draft or doctor upload form.

## 19. Delivery states

| State | Meaning shown to staff |
| --- | --- |
| Pending | Queued; waiting for eligibility and the delivery worker |
| Claimed / sending | A worker is preparing or attempting the request |
| Accepted | Provider accepted the request; receipt not established |
| Sent | Provider reports sent |
| Delivered | Provider reports delivery |
| Read | Provider reports read |
| Failed | A known failure; inspect the cause |
| Uncertain | A send may have started; manual provider review is required |
| Cancelled | Eligibility, pause or another guard prevented the send |

Delivery history includes proactive jobs; booking-reply and reminder problems have their own visible section. Uncertain messages are not offered a blind retry button. Campaign reporting calls button engagements and button opt-outs what they are; it does not attribute unrelated texts or unobserved conversions.

## 20. Language, time and money

Labels favor familiar clinic language. “Consented recipients” describes permission without exposing internal contact keys. “Send after” reflects quiet-hour deferral more accurately than a guaranteed send time.

Appointment and delivery displays use India Standard Time and say so in the workspace footer. Form date/time inputs use the computer's local timezone and label that explicitly; they convert to an offset-aware timestamp before submission. The scheduler separately explains branch-local hours.

Fees and estimates use Indian rupee formatting. Campaign estimates use a staff-entered per-message rate; they are not automatically current Meta prices and are not billing enforcement.

## 21. Accessibility and responsive behavior

Generated shadcn/Base UI primitives provide focus handling, keyboard interactions and dialog semantics. The implementation adds persistent labels, named icon buttons, form validation, readable empty/error text and explicit action states.

- Primary navigation becomes an off-canvas sidebar on small screens.
- Module tabs scroll inside their own region.
- Comparison tables scroll inside their containers rather than widening the page.
- The composer and inbox stack at narrower widths.
- Dialogs have bounded height and internal scrolling.
- Status is readable without color.
- Reduced motion is respected.
- Form controls preserve keyboard focus and disabled/loading feedback.

**Boundary:** This is implementation and browser-check evidence. It is not a claim of a formal WCAG audit or a study with disabled users.

## 22. Empty, error and recovery states

Loading uses skeletons instead of zero counts. A failed request displays the error and a retry action; failure is not rendered as a successful empty inbox.

Examples:

- No conversations explains that Talk to reception creates a handoff.
- No campaigns explains the draft/test/approval sequence.
- No templates asks for a provider sync, not an impossible campaign selection.
- A closed reply window asks for a fresh patient message.
- Missing doctor content identifies the affected specialty or doctor.
- Session expiry returns to sign-in and unmounts authenticated screens.
- A disabled module blocks its screen and offers module settings where appropriate.

The design does not claim online/provider health based on a successful page load. “Patient outreach paused” is configuration, not a diagnosis of Meta connectivity.

## 23. Security as part of the experience

The browser never asks for the backend's shared administrator key. Legacy keys remain only for compatible server-to-server integrations and developer tests. User actions derive identity from the authenticated session; supplied actor strings cannot impersonate another staff member through the staff interface.

State-changing cookie requests require a CSRF token and same-origin checks. Production cookies are Secure and HttpOnly with SameSite Strict. Sensitive API responses are not cached. The staff app and its assets share the backend origin; private files require authentication. A restrictive content security policy allows self-hosted scripts/fonts and blocks embedding by another page.

There is no secret storage in localStorage, no public account signup and no default production password. Service keys, Meta tokens and application secrets remain deployment configuration.

## 24. Deployment and data ownership

The React/Vite build is packaged into the FastAPI container by a Node build stage. Staff URLs and APIs are deployed together; a separate frontend host is not required. The existing Node WhatsApp runtime remains an optional process in the same backend repository.

Operator sequence:

1. Run database migrations.
2. Build/deploy the coupled API and staff UI.
3. Set the actual HTTPS `STAFF_ORIGIN`.
4. Create the first named administrator through `python -m app.staff_cli create`.
5. Confirm staff sign-in, roles and private file access.
6. Configure real clinic data, provider templates and scanning.
7. Test on the actual phones before enabling patient outreach.

Back up PostgreSQL, uploaded files and configuration. Module disablement retains stored data; retention/deletion policies are a separate clinic operational decision. Public internet access also needs HTTPS, network controls, adequate authentication monitoring and a reverse-proxy login rate limit. MFA/SSO and multi-tenant isolation are not implemented in this release.

## 25. Verification and acceptance criteria

Verification is layered; passing one layer does not establish the next.

| Layer | Required evidence |
| --- | --- |
| Component provenance | Generated shadcn component files and reproducible package lock |
| Build | TypeScript and production frontend build |
| Backend authentication | Wrong credentials, CSRF/origin rejection, hashed passwords, cookie attributes, expiry, logout and account disablement |
| Authorization | Clinic/growth role separation; administrator-only accounts and module switches |
| Module lifecycle | Disabled APIs/workers; retained incoming events; re-enabled pending claim; named change audit |
| Booking integration | Existing transaction, idempotency, consent, slot and fee checks still pass |
| Browser | Real local sign-in, sidebar navigation, content upload, campaign steps, error/empty states and responsive layout |
| Packaging | API image serves the built workspace and coupled bot integration passes |
| Provider / clinic | Actual Meta delivery, approved content, real availability and clinic staff acceptance |

The checked-in tests and GitHub run are the reproducible source of numerical results. Local preview records and synthetic template inventory are development fixtures, not Meta approval or real patient evidence. Production provider delivery and clinical acceptance remain separate rollout checks.

## 26. Trade-offs and next improvements

| Decision | Benefit | Current cost / follow-up |
| --- | --- | --- |
| One backend origin | Simple hosting and cookie boundaries | Deploy UI changes with the API |
| Fixed saved campaign drafts | Clear approval content | Revised content needs a new draft |
| One deployment per clinic | Straightforward module ownership | No shared-database tenant isolation |
| Named password accounts | Familiar, attributable staff actions | MFA/SSO and invitation/recovery delivery can follow |
| List/table-oriented operations | Fast comparison and clear status | Large datasets will need server pagination and richer filters |
| Patient outreach off in preview | Safe inspection of workflows | Real-phone proof still required |
| Explicit manual review of uncertain sends | Avoid duplicate patient communication | Staff need provider access and an escalation procedure |

Next validation should involve a receptionist performing five representative tasks: find today's booking, check in a patient, upload a specialty PDF, answer a reception handoff and prepare a campaign. Measure time, errors and hesitation before adding more visual decoration or dashboard statistics.

---

## References and related records

- [shadcn/ui Vite installation](https://ui.shadcn.com/docs/installation/vite) — actual generated component workflow.
- [shadcn/ui sidebar](https://ui.shadcn.com/docs/components/sidebar) — responsive navigation primitives.
- [Argon2-cffi password hashing guidance](https://argon2-cffi.readthedocs.io/en/stable/howto.html) — password verification and rehash behavior.
- `WHATSAPP_OUTREACH.md` — patient consent, campaigns, follow-ups and rollout contracts.
- `STAFF_WORKSPACE.md` — account setup, routes and deployment instructions.
- `GROWTH_UX_DECISION_BOOK.md` — detailed companion decisions for Google Business and growth analytics.
