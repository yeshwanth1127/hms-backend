import { useState } from "react";
import { CalendarDays, Plus, Search } from "lucide-react";
import {
  api,
  dateTime,
  type Appointment,
  type Catalogue,
  type StaffUser,
} from "@/lib/api";
import {
  Action,
  Choice,
  Empty,
  Field,
  PageTitle,
  Resource,
  StateBadge,
  useResource,
} from "@/components/workspace";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

type Doctor = {
  id: string;
  name: string;
  title: string;
  consultation_fee: number;
  is_active: boolean;
  accepts_virtual: boolean;
  departments: { id: string; name: string }[];
  branches: { id: string; name: string }[];
};
type Schedule = {
  id: string;
  doctor_id: string;
  branch_id: string;
  schedule_date: string;
  starts_at_local: string;
  ends_at_local: string;
  slot_minutes: number;
  consultation_type: string;
};
export function ClinicModule({ module }: { module: string; user: StaffUser }) {
  return module === "appointments" ? (
    <Appointments />
  ) : module === "doctors" ? (
    <Doctors />
  ) : (
    <Schedules />
  );
}
function Appointments() {
  const [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [submitted, setSubmitted] = useState(""),
    [change, setChange] = useState<{
      visit: Appointment;
      status: string;
    } | null>(null),
    [reason, setReason] = useState("");
  const r = useResource<Appointment[]>(
    `/api/v1/admin/appointments?status=${filter}&query=${encodeURIComponent(submitted)}`,
  );
  return (
    <>
      <PageTitle
        title="Appointments"
        description="Manage visits from WhatsApp, the website and voice in the same clinic records."
      />
      <form
        className="flex flex-wrap gap-4 mb-6 items-end"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(query);
        }}
      >
        <div className="flex-1 max-w-sm relative">
          <Search className="absolute left-3 top-3 size-4 text-muted-foreground" />
          <Input
            aria-label="Search appointments"
            className="pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Patient, phone or booking reference…"
          />
        </div>
        <Button variant="outline" type="submit">
          Search
        </Button>
        <div className="w-44">
          <Choice
            label="Status"
            value={filter}
            onChange={setFilter}
            options={[
              "all",
              "confirmed",
              "checked_in",
              "completed",
              "no_show",
              "cancelled",
            ].map((v) => [
              v,
              v.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()),
            ])}
          />
        </div>
      </form>
      <Resource {...r}>
        {r.data?.length ? (
          <Card className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Patient</TableHead>
                  <TableHead>Visit</TableHead>
                  <TableHead>Doctor & clinic</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {r.data.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <p className="font-medium">{a.patient_name}</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {a.confirmation_code} · {a.patient_phone}
                      </p>
                    </TableCell>
                    <TableCell>{dateTime(a.starts_at)}</TableCell>
                    <TableCell>
                      {a.doctor?.name}
                      <p className="text-xs text-muted-foreground mt-1">
                        {a.branch?.name}
                      </p>
                    </TableCell>
                    <TableCell>
                      <StateBadge value={a.origin_channel} />
                    </TableCell>
                    <TableCell>
                      <StateBadge value={a.status} />
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        {(a.status === "confirmed"
                          ? ["checked_in", "no_show", "cancelled"]
                          : a.status === "checked_in"
                            ? ["completed", "cancelled"]
                            : []
                        ).map((status) => (
                          <Button
                            key={status}
                            variant="outline"
                            disabled={
                              ["completed", "no_show"].includes(status) &&
                              new Date(a.starts_at) > new Date()
                            }
                            onClick={() => {
                              setChange({ visit: a, status });
                              setReason("");
                            }}
                          >
                            {
                              (
                                {
                                  checked_in: "Check in",
                                  no_show: "No-show",
                                  cancelled: "Cancel",
                                  completed: "Complete",
                                } as Record<string, string>
                              )[status]
                            }
                          </Button>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        ) : (
          <Empty
            title="No matching appointments"
            description="Try another patient or status. New confirmed bookings appear here automatically."
          />
        )}
      </Resource>
      <Dialog
        open={!!change}
        onOpenChange={(v) => {
          if (!v) setChange(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Update this appointment?</DialogTitle>
            <DialogDescription>
              {change?.visit.patient_name} · {change?.visit.confirmation_code}
              <br />
              {change && dateTime(change.visit.starts_at)}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm">
            New status: <StateBadge value={change?.status ?? ""} />
          </p>
          <Field label="Reason" id="status-reason">
            <Input
              id="status-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={240}
              placeholder="Optional note for the clinic record"
            />
          </Field>
          <p className="text-xs text-muted-foreground">
            Completed and no-show statuses can trigger configured follow-ups.
            Cancellation releases the appointment slot.
          </p>
          <Action
            run={async () => {
              await api(
                `/api/v1/admin/appointments/${change!.visit.id}/status`,
                { method: "PATCH", body: { status: change!.status, reason } },
              );
              setChange(null);
              r.refresh();
            }}
            success="Appointment updated"
          >
            Confirm status change
          </Action>
        </DialogContent>
      </Dialog>
    </>
  );
}
function Doctors() {
  const r = useResource<Doctor[]>("/api/v1/admin/doctors"),
    [edit, setEdit] = useState<Doctor | null>(null);
  return (
    <>
      <PageTitle
        title="Doctors"
        description="Keep booking fees and doctor availability accurate across all clinic channels."
      />
      <Resource {...r}>
        <Card className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Doctor</TableHead>
                <TableHead>Specialties</TableHead>
                <TableHead>Fee</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {r.data?.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="font-medium">
                    {d.name}
                    <p className="text-xs text-muted-foreground font-normal mt-1">
                      {d.title}
                    </p>
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    {d.departments.map((d) => d.name).join(", ")}
                  </TableCell>
                  <TableCell>
                    ₹{d.consultation_fee.toLocaleString("en-IN")}
                  </TableCell>
                  <TableCell>
                    <StateBadge value={d.is_active ? "active" : "inactive"} />
                  </TableCell>
                  <TableCell>
                    <Button variant="outline" onClick={() => setEdit(d)}>
                      Edit doctor
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </Resource>
      <Dialog
        open={!!edit}
        onOpenChange={(v) => {
          if (!v) setEdit(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit doctor</DialogTitle>
            <DialogDescription>{edit?.name}</DialogDescription>
          </DialogHeader>
          {edit && (
            <div className="space-y-5">
              <Field
                label="Consultation fee (₹)"
                id="doctor-fee"
                hint="Changes apply to future bookings; existing fee snapshots are preserved."
              >
                <Input
                  id="doctor-fee"
                  type="number"
                  min={0}
                  max={100000}
                  value={edit.consultation_fee}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      consultation_fee: Number(e.target.value),
                    })
                  }
                />
              </Field>
              <div className="flex justify-between">
                <Label htmlFor="doctor-active" className="text-sm">
                  Active in booking directory
                </Label>
                <Switch
                  id="doctor-active"
                  checked={edit.is_active}
                  onCheckedChange={(v) => setEdit({ ...edit, is_active: v })}
                />
              </div>
              <div className="flex justify-between">
                <Label htmlFor="doctor-virtual" className="text-sm">
                  Accepts virtual consultations
                </Label>
                <Switch
                  id="doctor-virtual"
                  checked={edit.accepts_virtual}
                  onCheckedChange={(v) =>
                    setEdit({ ...edit, accepts_virtual: v })
                  }
                />
              </div>
              <Action
                run={async () => {
                  await api(`/api/v1/admin/doctors/${edit.id}`, {
                    method: "PATCH",
                    body: {
                      is_active: edit.is_active,
                      consultation_fee: edit.consultation_fee,
                      accepts_virtual: edit.accepts_virtual,
                    },
                  });
                  setEdit(null);
                  r.refresh();
                }}
                success="Doctor updated"
              >
                Save doctor
              </Action>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
function Schedules() {
  const r = useResource<Schedule[]>("/api/v1/admin/schedules"),
    doctors = useResource<Doctor[]>("/api/v1/admin/doctors"),
    catalogue = useResource<Catalogue>("/api/v1/admin/catalogue"),
    [open, setOpen] = useState(false),
    [doctor, setDoctor] = useState(""),
    [branch, setBranch] = useState(""),
    [date, setDate] = useState(""),
    [endDate, setEndDate] = useState(""),
    [start, setStart] = useState("09:00"),
    [end, setEnd] = useState("17:00"),
    [minutes, setMinutes] = useState(30),
    [remove, setRemove] = useState<Schedule | null>(null);
  const chosen = doctors.data?.find((d) => d.id === doctor),
    branches =
      catalogue.data?.branches.filter(
        (b) => b.is_active && chosen?.branches.some((c) => c.id === b.id),
      ) ?? [];
  return (
    <>
      <PageTitle
        title="Schedules"
        description="Weekly doctor availability controls the slots patients can book."
        action={
          <Button onClick={() => setOpen(true)}>
            <Plus />
            Add schedule
          </Button>
        }
      />
      <Resource {...r}>
        {r.data?.length ? (
          <Card className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Doctor</TableHead>
                  <TableHead>Clinic</TableHead>
                  <TableHead>Weekly from</TableHead>
                  <TableHead>Hours</TableHead>
                  <TableHead>Slot duration</TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {r.data.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>
                      {doctors.data?.find((d) => d.id === s.doctor_id)?.name ??
                        "Loading doctor…"}
                    </TableCell>
                    <TableCell>
                      {catalogue.data?.branches.find(
                        (b) => b.id === s.branch_id,
                      )?.name ?? "Loading clinic…"}
                    </TableCell>
                    <TableCell>{s.schedule_date}</TableCell>
                    <TableCell>
                      {s.starts_at_local.slice(0, 5)}–
                      {s.ends_at_local.slice(0, 5)}
                    </TableCell>
                    <TableCell>{s.slot_minutes} minutes</TableCell>
                    <TableCell>
                      <Button variant="outline" onClick={() => setRemove(s)}>
                        Remove rule
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        ) : (
          <Empty
            title="No schedules yet"
            description="Add a dated weekly rule for a doctor and clinic to make booking slots available."
          />
        )}
      </Resource>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add weekly schedule</DialogTitle>
            <DialogDescription>
              Times use the selected clinic’s timezone. The first date
              determines the recurring weekday.
            </DialogDescription>
          </DialogHeader>
          <Resource
            loading={doctors.loading || catalogue.loading}
            error={doctors.error || catalogue.error}
            refresh={() => {
              doctors.refresh();
              catalogue.refresh();
            }}
          >
            <div className="space-y-4">
              <Choice
                label="Doctor"
                value={doctor}
                onChange={(v) => {
                  setDoctor(v);
                  setBranch("");
                }}
                options={[
                  ["", "Choose a doctor"],
                  ...(doctors.data
                    ?.filter((d) => d.is_active)
                    .map((d) => [d.id, d.name] as [string, string]) ?? []),
                ]}
              />
              <Choice
                label="Clinic"
                value={branch}
                onChange={setBranch}
                options={[
                  ["", "Choose a clinic"],
                  ...branches.map((b) => [b.id, b.name] as [string, string]),
                ]}
              />
              <Field label="First date" id="schedule-date">
                <Input
                  type="date"
                  id="schedule-date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                />
              </Field>
              <Field label="Last date (optional)" id="schedule-enddate">
                <Input
                  type="date"
                  id="schedule-enddate"
                  value={endDate}
                  min={date}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Starts at" id="schedule-start">
                  <Input
                    type="time"
                    id="schedule-start"
                    value={start}
                    onChange={(e) => setStart(e.target.value)}
                  />
                </Field>
                <Field label="Ends at" id="schedule-end">
                  <Input
                    type="time"
                    id="schedule-end"
                    value={end}
                    onChange={(e) => setEnd(e.target.value)}
                  />
                </Field>
              </div>
              <Field label="Slot duration (minutes)" id="schedule-minutes">
                <Input
                  type="number"
                  id="schedule-minutes"
                  min={10}
                  max={240}
                  value={minutes}
                  onChange={(e) => setMinutes(Number(e.target.value))}
                />
              </Field>
              <Action
                disabled={!doctor || !branch || !date || end <= start}
                run={async () => {
                  await api("/api/v1/admin/schedules", {
                    method: "POST",
                    body: {
                      doctor_id: doctor,
                      branch_id: branch,
                      schedule_date: date,
                      effective_until: endDate || null,
                      starts_at_local: start,
                      ends_at_local: end,
                      slot_minutes: minutes,
                      consultation_type: "in_person",
                    },
                  });
                  setOpen(false);
                  r.refresh();
                }}
                success="Schedule added"
              >
                <CalendarDays />
                Add schedule
              </Action>
            </div>
          </Resource>
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
            <DialogTitle>Remove this schedule rule?</DialogTitle>
            <DialogDescription>
              This removes future availability from this rule. Existing booked
              appointments are preserved.
            </DialogDescription>
          </DialogHeader>
          <Action
            variant="destructive"
            run={async () => {
              await api(`/api/v1/admin/schedules/${remove!.id}`, {
                method: "DELETE",
              });
              setRemove(null);
              r.refresh();
            }}
            success="Schedule rule removed"
          >
            Remove rule
          </Action>
        </DialogContent>
      </Dialog>
    </>
  );
}
