import { useEffect, useState } from "react";
import { api, type Catalogue } from "@/lib/api";
import {
  Action,
  Choice,
  Field,
  Resource,
  usePermissions,
  useResource,
} from "@/components/workspace";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { DeskAppointment } from "./NurseDesk";
type Doctor = { id: string; name: string };
type Block = {
  id: string;
  doctor_id: string;
  branch_id: string | null;
  starts_at: string;
  ends_at: string;
  reason: string;
};
type Slot = { starts_at: string; ends_at: string };
type Wait = {
  id: string;
  patient_name: string;
  phone: string;
  doctor_id: string;
  branch_id: string;
  consultation_type: string;
  start_date: string;
  end_date: string;
  status: string;
};
const time = (s: string) =>
  new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(s));
const ist = (s: string) => (s ? new Date(s + ":00+05:30").toISOString() : "");
export function ScheduleBlocks() {
  const r = useResource<Block[]>("/api/v1/admin/schedule-exceptions"),
    d = useResource<Doctor[]>("/api/v1/admin/doctors"),
    c = useResource<Catalogue>("/api/v1/admin/catalogue");
  const [open, setOpen] = useState(false),
    [doctor, setDoctor] = useState(""),
    [branch, setBranch] = useState("all"),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [reason, setReason] = useState(""),
    [preview, setPreview] = useState<DeskAppointment[] | null>(null),
    [remove, setRemove] = useState<Block | null>(null),
    canBlock = usePermissions().can("schedule.block");
  const body = {
    doctor_id: doctor,
    branch_id: branch === "all" ? null : branch,
    starts_at: ist(start),
    ends_at: ist(end),
    reason,
  };
  function change(set: (v: string) => void, v: string) {
    set(v);
    setPreview(null);
  }
  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>Doctor leave and blocked time</CardTitle>
        <CardDescription>
          Blocks prevent new bookings. Existing visits stay booked until
          reception reviews and reschedules them.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button
          variant="outline"
          disabled={!canBlock}
          onClick={() => {
            setOpen(true);
            setPreview(null);
          }}
        >
          Block unavailable time
        </Button>
        <Resource {...r}>
          {r.data?.length ? (
            r.data.map((b) => (
              <div
                key={b.id}
                className="flex flex-wrap justify-between gap-3 border-t pt-4"
              >
                <div>
                  <p className="font-medium">
                    {d.data?.find((a) => a.id === b.doctor_id)?.name} ·{" "}
                    {b.reason}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {time(b.starts_at)} – {time(b.ends_at)} ·{" "}
                    {b.branch_id
                      ? c.data?.branches.find((a) => a.id === b.branch_id)?.name
                      : "All clinics"}
                  </p>
                </div>
                <Button
                  variant="outline"
                  disabled={!canBlock}
                  onClick={() => setRemove(b)}
                >
                  Unblock
                </Button>
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">No blocked time.</p>
          )}
        </Resource>
      </CardContent>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Block unavailable time</DialogTitle>
            <DialogDescription>
              Times entered here are India Standard Time. Check affected
              visits before saving. No patient notification is sent by this
              action.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Choice
              label="Doctor"
              value={doctor}
              onChange={(v) => change(setDoctor, v)}
              options={(d.data ?? []).map((a) => [a.id, a.name])}
            />
            <Choice
              label="Clinic"
              value={branch}
              onChange={(v) => change(setBranch, v)}
              options={[
                ["all", "All clinics"],
                ...(c.data?.branches ?? []).map(
                  (a) => [a.id, a.name] as [string, string],
                ),
              ]}
            />
            <Field label="From · IST" id="block-from">
              <Input
                id="block-from"
                type="datetime-local"
                value={start}
                onChange={(e) => change(setStart, e.target.value)}
              />
            </Field>
            <Field label="To · IST" id="block-to">
              <Input
                id="block-to"
                type="datetime-local"
                value={end}
                onChange={(e) => change(setEnd, e.target.value)}
              />
            </Field>
            <Field label="Reason" id="block-reason">
              <Input
                id="block-reason"
                value={reason}
                onChange={(e) => change(setReason, e.target.value)}
              />
            </Field>
            <Action
              disabled={!doctor || !start || !end || reason.trim().length < 2}
              run={async () =>
                setPreview(
                  (
                    await api<{ affected_appointments: DeskAppointment[] }>(
                      "/api/v1/admin/schedule-exceptions/preview",
                      { method: "POST", body },
                    )
                  ).affected_appointments,
                )
              }
              success="Affected visits reviewed"
            >
              Check affected visits
            </Action>
            {preview && (
              <>
                <Alert>
                  <AlertDescription>
                    {preview.length} existing visits need reception review.
                    Saving acknowledges these visits; it does not cancel or
                    notify them.
                  </AlertDescription>
                </Alert>
                <div className="max-h-40 overflow-auto space-y-2">
                  {preview.map((a) => (
                    <p key={a.id} className="text-sm">
                      {a.patient_name} · {time(a.starts_at)} ·{" "}
                      {a.confirmation_code}
                    </p>
                  ))}
                </div>
                <Action
                  run={async () => {
                    await api("/api/v1/admin/schedule-exceptions", {
                      method: "POST",
                      body: {
                        ...body,
                        acknowledged_appointments: preview.map((a) => a.id),
                      },
                    });
                    setOpen(false);
                    r.refresh();
                  }}
                  success="Unavailable time blocked"
                >
                  Acknowledge visits and block time
                </Action>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!remove}
        onOpenChange={(v) => {
          if (!v) setRemove(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove this block?</DialogTitle>
            <DialogDescription>
              This can make unoccupied times bookable again. It does not change
              appointments.
            </DialogDescription>
          </DialogHeader>
          <Action
            run={async () => {
              await api("/api/v1/admin/schedule-exceptions/" + remove!.id, {
                method: "DELETE",
              });
              setRemove(null);
              r.refresh();
            }}
            success="Time unblocked"
          >
            Unblock time
          </Action>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
export function RescheduleVisit({
  item,
  onSaved,
}: {
  item: DeskAppointment;
  onSaved: (item: DeskAppointment) => void;
}) {
  const [open, setOpen] = useState(false),
    [date, setDate] = useState(""),
    [slots, setSlots] = useState<Slot[]>([]),
    [chosen, setChosen] = useState(""),
    [reason, setReason] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setChosen("");
    setSlots([]);
    if (!open || !date || !item.doctor || !item.branch) return;
    api<{ slots: Slot[] }>(
      "/api/v1/availability?" +
        new URLSearchParams({
          doctor_id: item.doctor.id,
          branch_id: item.branch.id,
          start_date: date,
          end_date: date,
          consultation_type: item.consultation_type,
        }),
    )
      .then((r) => {
        if (live) setSlots(r.slots);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [open, date, item]);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        Reschedule visit
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Agree a replacement time</DialogTitle>
            <DialogDescription>
              Same doctor, clinic and fee. The old time remains booked until
              this change commits. An outbox event is not proof of patient
              notification.
            </DialogDescription>
          </DialogHeader>
          <Field label="Date" id="move-date">
            <Input
              id="move-date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </Field>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Choice
            label="Available replacement"
            value={chosen}
            onChange={setChosen}
            options={slots.map((s) => [s.starts_at, time(s.starts_at)])}
          />
          <Field label="Agreement / reason" id="move-reason">
            <Input
              id="move-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          <Action
            disabled={!chosen || reason.trim().length < 2}
            run={async () => {
              const slot = slots.find((s) => s.starts_at === chosen)!;
              const result = await api<DeskAppointment>(
                "/api/v1/admin/appointments/" + item.id + "/reschedule",
                {
                  method: "POST",
                  body: {
                    ...slot,
                    reason,
                    idempotency_key: crypto.randomUUID(),
                  },
                },
              );
              onSaved(result);
              setOpen(false);
            }}
            success="Visit rescheduled"
          >
            Confirm agreed replacement
          </Action>
        </DialogContent>
      </Dialog>
    </>
  );
}
export function WaitlistDesk() {
  const r = useResource<Wait[]>("/api/v1/admin/waitlist"),
    d = useResource<Doctor[]>("/api/v1/admin/doctors");
  const [item, setItem] = useState<Wait | null>(null),
    [date, setDate] = useState(""),
    [slots, setSlots] = useState<Slot[]>([]),
    [chosen, setChosen] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setChosen("");
    setSlots([]);
    if (!item || !date) return;
    api<{ slots: Slot[] }>(
      "/api/v1/availability?" +
        new URLSearchParams({
          doctor_id: item.doctor_id,
          branch_id: item.branch_id,
          start_date: date,
          end_date: date,
          consultation_type: item.consultation_type,
        }),
    )
      .then((r) => {
        if (live) setSlots(r.slots);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [item, date]);
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Cancellation waitlist</CardTitle>
        <CardDescription>
          Verified, explicitly requested preferences. Offer slots individually;
          no automatic outbound message is sent.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Resource {...r}>
          {r.data?.length ? (
            r.data.map((w) => (
              <div
                key={w.id}
                className="flex flex-wrap justify-between gap-3 border-t py-4"
              >
                <div>
                  <p className="font-medium">
                    {w.patient_name} · {w.status}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {w.phone} ·{" "}
                    {d.data?.find((a) => a.id === w.doctor_id)?.name} ·{" "}
                    {w.start_date} – {w.end_date}
                  </p>
                </div>
                {w.status === "waiting" && (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setItem(w);
                      setDate(w.start_date);
                      setError("");
                    }}
                  >
                    Prepare slot offer
                  </Button>
                )}
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">
              No waitlist requests.
            </p>
          )}
        </Resource>
      </CardContent>
      <Dialog
        open={!!item}
        onOpenChange={(v) => {
          if (!v) setItem(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Prepare an expiring offer</DialogTitle>
            <DialogDescription>
              Saving reserves a real slot briefly. Contact the patient through
              the approved reception workflow and ask them to refresh offers on
              the booking page. STOP prevents new proactive offers.
            </DialogDescription>
          </DialogHeader>
          <Field label="Preferred date" id="offer-date">
            <Input
              id="offer-date"
              type="date"
              value={date}
              min={item?.start_date}
              max={item?.end_date}
              onChange={(e) => setDate(e.target.value)}
            />
          </Field>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Choice
            label="Available time"
            value={chosen}
            onChange={setChosen}
            options={slots.map((s) => [s.starts_at, time(s.starts_at)])}
          />
          <Action
            disabled={!chosen}
            run={async () => {
              await api("/api/v1/admin/waitlist/" + item!.id + "/offer", {
                method: "POST",
                body: {
                  ...slots.find((s) => s.starts_at === chosen),
                  idempotency_key: crypto.randomUUID(),
                },
              });
              setItem(null);
              r.refresh();
            }}
            success="Offer saved; reception notification still required"
          >
            Save expiring offer
          </Action>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
