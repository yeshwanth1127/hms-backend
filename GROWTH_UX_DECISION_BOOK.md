# Google Business and growth: UX decision book

Version 1 · 1 October 2026 · Avocado Health backend

## 1. Purpose and primary task

A clinic growth manager needs to help a patient move from discovery to a committed appointment. They should know what is ready, what they can change and what still needs a provider connection. The first task is to prepare a verified clinic booking destination. The overview offers one dominant action, “Prepare booking link.” The interface does not start with every integration setting or metric.

Success means a real backend confirmation and, subsequently, a recorded visit outcome. A button click, chat opening or appointment draft is a distinct event. UI copy and metric names preserve that distinction.

## 2. Product boundaries

Appointments, doctors and schedules form the core clinic workspace. Google Business, growth analytics and WhatsApp are separate optional modules. A client may enable Google Business while using only website booking, or keep appointment analytics without any Google integration. Disabling a module retains its data, denies feature APIs and removes feature navigation; it does not delete a profile or cancel appointments.

This implementation configures one clinic deployment. It does not pretend the current backend is a multi-tenant SaaS system. Shared-host client isolation, billing entitlements and tenant-specific credentials need a separate data-model boundary before hosting unrelated clinics in one database.

## 3. Identity and permissions

Staff sign in with a username and password. There is no shared admin key or bearer-token entry field in the normal staff UI. The shared authentication workstream supplies Argon2 password hashes, HttpOnly sessions, eight-hour absolute and thirty-minute idle expiry, origin and CSRF checks, throttled sign-in and server-side revocation.

A clinic administrator controls module switches. A growth manager can access Google and aggregate growth information when enabled. Reception staff cannot access either growth module. Role and module status are read on requests, so changing a role or disabling a module takes effect without waiting for a new sign-in. A module switch never upgrades a staff member's permissions.

## 4. Information architecture

| Surface | Question it answers | Primary action |
| --- | --- | --- |
| Google / Overview | What should I do next? | Prepare booking link |
| Google / Booking links | Where will patients book? | Save clinic link |
| Google / Patient preview | What happens when a patient clicks? | Try a labelled walkthrough |
| Google / Options | What capabilities are possible or conditional? | Read the supporting documentation |
| Google / Change history | Who changed a prepared link? | Inspect recorded changes |
| Growth analytics | What happened to persisted appointments? | Apply report scope |
| Modules | Which optional tools does this clinic use? | Administrator toggles a module |

Tabs reduce competing headings within the Google module. Shared sidebar navigation handles movement between modules. The canonical shell owns routes, identity, mobile navigation and the sign-out action; growth exports feature components rather than another application shell.

## 5. Visual system

All interactive controls use generated shadcn components: buttons, inputs, labels, select, tabs, switch, dialog, alerts and tables. Cards group a task rather than decorating every paragraph. Neutral surfaces, subtle borders and a restrained emerald primary token fit the shared staff interface. DM Sans is used throughout for a consistent hierarchy; no competing display typeface is introduced.

Screen titles use 30px semibold text, task titles use the card heading style, explanatory copy uses 14px with comfortable line height. Metric values are large but always paired with a denominator or definition. Spacing follows the existing Tailwind/shadcn scale. Destructive colours communicate failed requests, not ordinary unavailable integrations.

## 6. Setup hierarchy and state language

“Google not connected” remains visible on overview. Creating a Google profile elsewhere does not prove this backend has access. “Local draft,” “Link prepared” and “Not published to Google” are distinct from “Live.” Saved links are shown as text; a saved URL is not advertised as a working website until the patient journey is actually tested.

The initial setup has three understandable steps: complete factual clinic details, verify with Google, test the patient journey. OAuth, API approval and partner eligibility are explained where they affect a task, rather than appearing as unexplained fields on the first screen.

## 7. Booking link preparation

The form asks for an active physical clinic and an approved HTTPS booking URL. Virtual or inactive branches are rejected. The backend adds the clinic slug and Google attribution source and accepts no patient-specific query parameters. Approved origins are deployment settings controlled by operators. Saving is disabled until a clinic is selected and while a write is in progress.

A success alert explicitly says the link is saved locally. A failed write leaves the user's clinic and URL in place so they can correct it. The save is idempotent: unchanged links do not produce misleading extra history rows.

## 8. Patient preview and illustrations

The preview has Google-style content hierarchy using our own interface components. It is explicitly illustrative. Concept clinic drawings are labelled and must be replaced by approved photographs of the real premises. No fabricated reviews, star ratings, clinicians, fees or operating hours are added.

Every action opens a local dialog showing its intended destination. Website and WhatsApp concepts demonstrate time choice, confirmation and unavailable-slot recovery. Directions and call explain the missing verified destination rather than inventing a map pin or phone number. No patient details or OTPs are collected in the walkthrough.

Native slots remain a separate conditional concept. Ordinary Google Business management does not establish healthcare partner acceptance or in-profile time-slot eligibility. The production first path is the Book action to website availability; WhatsApp requires an official number and actual profile eligibility.

## 9. Optional WhatsApp relationship

Google Business works without WhatsApp. The preview can explain a proposed WhatsApp channel while saying that no business number is configured. It does not provision a number, send messages or enable the bot. The canonical WhatsApp module remains responsible for transport, consent, handoff, message delivery and bot operations.

For production, module-off must block worker dispatch as well as staff APIs. Stored inbound events and uncertain sends should be retained; an external send already in flight cannot be recalled. Existing outreach enablement and consent checks remain additional conditions, never replaced by the module switch.

## 10. Analytics semantics

The default report includes production records only. Historic records with unverified provenance are migrated to demo/unknown. The user can choose booking date or visit date, date range and clinic. A reporting timezone controls calendar boundaries. Empty results show an honest empty state rather than example numbers.

Appointments means persisted bookings in the cohort. Retained confirmation share means currently confirmed, checked-in or completed appointments divided by all cohort records. Attendance means attended divided by attended plus no-show among ended visits; unresolved and cancelled outcomes do not silently become attendance failures. These are operational measures, not visitor conversion.

Entry attribution and delivery channel are distinct: a Google-origin appointment may be booked through the website. PostHog visitor conversion, Google impressions and slot utilization remain unavailable until real contracts exist. No chart pretends that booking records alone supply these denominators. Aggregate endpoints omit names, phones and clinical details.

## 11. Failure, loading and feedback

Skeletons show that authenticated feature data is loading. Request failures show an alert and a Retry action; link form input is preserved after failure. Saved links and module switches show explicit success feedback. Switches are controlled by persisted state and disabled during mutation, rather than optimistically implying a server update succeeded.

The shared shell must route an ended session back to sign-in, unmount features when module status changes and refresh module navigation after settings updates. Direct links to inaccessible modules show a clear unavailable state and a path back to Modules.

## 12. Accessibility and responsive behaviour

Inputs have associated labels and autocomplete values. Dialogs and tabs use shadcn keyboard/focus behaviour. Status messages use alert/status semantics. Text accompanies action icons. The preview and report cards stack at smaller widths; the tab row wraps. Tables retain semantic headings and scroll within their container when necessary.

Use genuine device/browser checks before claiming complete accessibility. Local visual and clickthrough verification supports the tested desktop interface; it is not a screen-reader audit, clinical validation or deployed-provider proof.

## 13. Validation and open work

Local tests cover permissions, live role/active/expiry changes, logout, CSRF on mutations, default-off and independent module flags, strict switch input, attribution privacy, branch/timezone reports, URL restrictions and named audit history. Fresh SQLite migration and TypeScript/production build are checked. The integration packet avoids duplicating the canonical staff schema.

Provider OAuth, public profile visibility, real WhatsApp number, PostHog events, production PostgreSQL deployment and actual appointment delivery remain outside this local verification. The shared WhatsApp workstream owns integrating the final shell and enforcing its dispatch gates. This book should be updated after usability testing with a clinic administrator and a designated growth manager.

## 14. PostHog activity alongside appointment outcomes

Website engagement now has a separate PostHog card with production/demo controls, whole-website scope, per-event anonymous visitor counts and setup/unavailable states. It never presents absent data as zeros or labels independent activity counts as an ordered funnel. Current preview completions remain demo activity. Credentials stay in the backend's secret store, and the existing growth module/role permissions apply. Setup details and remaining provider verification are recorded in POSTHOG_BACKEND_INTEGRATION.md.
