# PRD: Patient notifications for staff-initiated visit changes

## Problem
When staff reschedule or cancel a visit, the system records an outbox event that nothing delivers.
Patients are not told; reception has no clear list of who still needs a call.

## Goal
Patients who agreed to WhatsApp service messages are told automatically when staff move or cancel
their visit; everyone else is clearly flagged to reception for a phone call.

## Scope
In:
- Two new care message kinds alongside feedback/no_show/followup: `rescheduled` and `cancelled`,
  configured by the clinic owner in WhatsApp > Follow-ups with an approved Meta template
  (three fields: booking reference, doctor, visit time). Sent immediately (no delay).
- Triggered by staff reschedule and staff cancellation. Patient-initiated changes already confirm
  in the channel the patient used and are not re-notified.
- Eligible: WhatsApp and website bookings (phone verified through WhatsApp) with reminder consent,
  contact not stopped. Uses the existing de-duplicated outbound queue and delivery tracking.
- The staff response and Nurse desk show the result per visit: "WhatsApp queued", or
  "Call patient" with the reason (no consent, contacted stopped, template not configured).

Out:
- SMS/email channels; free-form messages outside approved templates; notifying for blocked time
  before staff decide to move or cancel each affected visit.

## User flows
1. Nurse moves a consenting patient from 10:00 to 11:30 → patient receives the approved
   "rescheduled" template with the new time; the desk shows "WhatsApp queued".
2. Nurse cancels a visit for a patient without consent → desk shows "Call patient: no WhatsApp consent".

## Acceptance criteria
- Staff reschedule/cancel of an eligible visit queues exactly one outbound message per change.
- Ineligible visits queue nothing and return `notification_state = call_patient` with a reason.
- Re-sending the same request (idempotent retry) does not queue a second message.
- Rules can be enabled only with an approved three-field template, like existing care rules.
- Each queued notification appears in the audit trail.
