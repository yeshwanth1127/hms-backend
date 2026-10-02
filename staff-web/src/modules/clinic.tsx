import { ScheduleBlocks, WaitlistDesk } from "./BookingOperations";
import { NurseDesk } from "./NurseDesk";
import { useState } from "react";
import { CalendarDays, Plus } from "lucide-react";
import { api, type Catalogue, type StaffUser } from "@/lib/api";
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
  weekday: number;
  effective_until?: string | null;
  is_active: boolean;
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
  const doctors = useResource<Doctor[]>("/api/v1/admin/doctors");
  const catalogue = useResource<Catalogue>("/api/v1/admin/catalogue");
  return (
    <Resource
      loading={doctors.loading || catalogue.loading}
      error={doctors.error || catalogue.error}
      refresh={() => {
        doctors.refresh();
        catalogue.refresh();
      }}
    >
      <>
        <NurseDesk
          api={api}
          doctors={doctors.data ?? []}
          branches={catalogue.data?.branches ?? []}
        />
        <WaitlistDesk />
      </>
    </Resource>
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
                <TableHead>Specialties & clinics</TableHead>
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
                    <p className="text-xs text-muted-foreground mt-1">
                      {d.branches.map((b) => b.name).join(", ")}
                    </p>
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
    [doctorFilter, setDoctorFilter] = useState("all"),
    [visitType, setVisitType] = useState("in_person"),
    [weekday, setWeekday] = useState("0"),
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
        (b) =>
          b.is_active &&
          (visitType === "virtual"
            ? b.is_virtual && chosen?.accepts_virtual
            : !b.is_virtual && chosen?.branches.some((c) => c.id === b.id)),
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
      <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
        <div className="w-64">
          <Choice
            label="Filter schedules by doctor"
            value={doctorFilter}
            onChange={setDoctorFilter}
            options={[
              ["all", "All doctors"],
              ...(doctors.data ?? []).map(
                (d) => [d.id, d.name] as [string, string],
              ),
            ]}
          />
        </div>
        <Button variant="outline" onClick={r.refresh}>
          Refresh schedules
        </Button>
      </div>
      <ScheduleBlocks />
      <Resource {...r}>
        {r.data?.some(
          (s) => doctorFilter === "all" || s.doctor_id === doctorFilter,
        ) ? (
          <Card className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Doctor</TableHead>
                  <TableHead>Clinic</TableHead>
                  <TableHead>Weekly from</TableHead>
                  <TableHead>Visit type</TableHead>
                  <TableHead>Hours</TableHead>
                  <TableHead>Slot duration</TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {r.data
                  ?.filter(
                    (s) =>
                      doctorFilter === "all" || s.doctor_id === doctorFilter,
                  )
                  .map((s) => (
                    <TableRow key={s.id}>
                      <TableCell>
                        {doctors.data?.find((d) => d.id === s.doctor_id)
                          ?.name ?? "Loading doctor…"}
                      </TableCell>
                      <TableCell>
                        {catalogue.data?.branches.find(
                          (b) => b.id === s.branch_id,
                        )?.name ?? "Loading clinic…"}
                      </TableCell>
                      <TableCell>
                        {
                          [
                            "Monday",
                            "Tuesday",
                            "Wednesday",
                            "Thursday",
                            "Friday",
                            "Saturday",
                            "Sunday",
                          ][s.weekday]
                        }
                        <p className="text-xs text-muted-foreground">
                          {s.schedule_date}
                          {s.effective_until
                            ? ` – ${s.effective_until}`
                            : " · ongoing"}
                        </p>
                      </TableCell>
                      <TableCell>
                        <StateBadge value={s.consultation_type} />
                      </TableCell>
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
              Times use the selected clinic’s timezone. The first date begins
              the weekly rule on the selected weekday.
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
                  setVisitType("in_person");
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
                label="Visit type"
                value={visitType}
                onChange={(v) => {
                  setVisitType(v);
                  setBranch("");
                }}
                options={[
                  ["in_person", "In person"],
                  ...(chosen?.accepts_virtual
                    ? [["virtual", "Virtual consultation"] as [string, string]]
                    : []),
                ]}
              />
              <Choice
                label="Recurring weekday"
                value={weekday}
                onChange={setWeekday}
                options={[
                  "Monday",
                  "Tuesday",
                  "Wednesday",
                  "Thursday",
                  "Friday",
                  "Saturday",
                  "Sunday",
                ].map((d, i) => [String(i), d])}
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
              <Field label="Effective from" id="schedule-date">
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
                      effective_from: date,
                      weekday: Number(weekday),
                      effective_until: endDate || null,
                      starts_at_local: start,
                      ends_at_local: end,
                      slot_minutes: minutes,
                      consultation_type: visitType,
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
