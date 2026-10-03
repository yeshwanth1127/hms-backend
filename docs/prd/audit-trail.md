# PRD: Clinic-wide audit trail

## Problem
Clinic actions are only partly traceable. Appointment status changes, reschedules, blocked time,
module toggles and recording access keep history, but doctor fee changes, schedule edits, staff
account changes, media uploads, campaign steps, reception replies, patient web actions and failed
or denied attempts leave no record. With several nurses changing the same day, the clinic cannot
answer "who did what, when, to which record, and did it work?"

## Goal
Every state-changing action in the clinic system leaves one append-only audit record that a clinic
administrator can search and explain, without storing passwords or free-text clinical details.

## Scope
In:
- One `audit_events` record for every POST/PUT/PATCH/DELETE request, including failed (4xx/5xx),
  denied (401/403) and conflicting (409) attempts and staff sign-in success/failure.
- Who: staff user (id, name, username), patient web session (pseudonymous session id, resolvable to
  the verified phone by an administrator), integration service (WhatsApp, voice), legacy key, or
  anonymous. Client IP and request id for security investigations.
- What: action name (method + route template), affected record ids (path parameters), outcome
  status code, and a "change" with before/after values where the action edits clinic data
  (doctor fee/visibility, schedules, staff accounts, modules, appointment status, reschedules).
- Admin-only "Activity log" page in Staff > Settings with filters (person, record id, action, date)
  and CSV export.
- If the audit database write fails, the event is written to the server log so nothing is lost.

Out:
- Request bodies, passwords, OTP/verification codes, message text and clinical free text.
- Rate-limited floods (429 at the edge); counted in server logs only.
- Retention/deletion tooling (records are kept; deletion is not exposed).
- Staff views of patient data — see open question.

## User flows
1. A nurse checks in a patient. The log shows "Asha (@asha) · appointment status · AVO-… ·
   confirmed → checked_in · 200 · 10:42 IST".
2. Two nurses act on the same visit; the second gets a conflict. Both attempts appear, the second
   with status 409.
3. The owner changes a doctor's fee; the log shows fee 800 → 900 with the owner's name.
4. Owner filters the log by an appointment id to explain every change to that visit.

## Acceptance criteria
- Every mutating route produces exactly one audit record (enforced by a test that walks all routes).
- Staff actor name and username are recorded for cookie sessions; services are labelled by service.
- Doctor update, schedule create/delete, staff create/password change record before/after values.
- Failed and denied attempts are recorded with their status code.
- No password, verification code, or request body text is stored (test asserts on a login).
- Only `admin` can read the activity log; `staff` receives 403.
- An audit write failure does not fail the user's action and is emitted to the server log.
