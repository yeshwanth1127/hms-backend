import { useCallback, useEffect, useRef, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";

export interface DeskAppointment {
  id: string;
  confirmation_code: string;
  patient_name: string;
  patient_phone: string;
  patient_email?: string;
  reason?: string;
  status: string;
  origin_channel: string;
  starts_at: string;
  ends_at: string;
  consultation_type: string;
  doctor?: { id: string; name: string };
  branch?: { id: string; name: string; area: string };
}
type Api = <T>(
  path: string,
  options?: { method?: string; body?: unknown },
) => Promise<T>;
const today = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
const time = (value: string) =>
  new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
const names: Record<string, string> = {
  confirmed: "Expected",
  checked_in: "Checked in",
  completed: "Completed",
  cancelled: "Cancelled",
  no_show: "No show",
  voice: "Voice assistant",
  web: "Website",
  whatsapp: "WhatsApp",
  staff: "Staff",
  in_person: "In person",
  web_voice: "Website voice",
  phone: "Phone voice",
  virtual: "Virtual",
};
const title = (v: string) => names[v] || v.split("_").join(" ");
const pageSize = 50;

export function NurseDesk({
  api,
  doctors,
  branches,
}: {
  api: Api;
  doctors: { id: string; name: string }[];
  branches: { id: string; name: string }[];
}) {
  const [day, setDay] = useState(today);
  const [query, setQuery] = useState("");
  const [doctor, setDoctor] = useState("all");
  const [branch, setBranch] = useState("all");
  const [status, setStatus] = useState("all");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<DeskAppointment[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<DeskAppointment | null>(null);
  const [pending, setPending] = useState<{
    item: DeskAppointment;
    status: string;
  } | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [updated, setUpdated] = useState("");
  const generation = useRef(0);
  const [clock, setClock] = useState(() => Date.now());
  const invalidateRequests = useCallback(() => {
    generation.current++;
  }, []);
  const load = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(pageSize + 1),
    });
    if (day) params.set("day", day);
    if (query.trim()) params.set("query", query.trim());
    if (doctor !== "all") params.set("doctor_id", doctor);
    if (branch !== "all") params.set("branch_id", branch);
    if (status !== "all") params.set("status", status);
    try {
      const result = await api<DeskAppointment[]>(
        `/api/v1/admin/appointments?${params}`,
      );
      if (request !== generation.current) return;
      setItems(result.slice(0, pageSize));
      setMore(result.length > pageSize);
      setUpdated(time(new Date().toISOString()));
      setClock(Date.now());
    } catch (e) {
      if (request === generation.current)
        setError(
          e instanceof Error ? e.message : "Could not load appointments.",
        );
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [api, offset, day, query, doctor, branch, status]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 250);
    return () => {
      window.clearTimeout(timer);
      invalidateRequests();
    };
  }, [load, invalidateRequests]);
  const change = (setter: (v: string) => void, value: string) => {
    setter(value);
    setOffset(0);
  };
  async function update(item: DeskAppointment, next: string, detail: string) {
    if (saving) return;
    setSaving(item.id);
    setError("");
    try {
      const result = await api<DeskAppointment>(
        `/api/v1/admin/appointments/${item.id}/status`,
        { method: "PATCH", body: { status: next, reason: detail } },
      );
      setSelected((current) => (current?.id === result.id ? result : current));
      setPending(null);
      setReason("");
      setNotice(`${item.patient_name}: ${title(next).toLowerCase()}.`);
      await load();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not update appointment.",
      );
    } finally {
      setSaving("");
    }
  }
  const filters = (
    label: string,
    value: string,
    setter: (v: string) => void,
    options: { id: string; name: string }[],
  ) => (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Select
        items={[
          { value: "all", label: `All ${label.toLowerCase()}` },
          ...options.map((o) => ({ value: o.id, label: o.name })),
        ]}
        value={value}
        onValueChange={(v) => change(setter, String(v ?? "all"))}
      >
        <SelectTrigger className="w-full" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All {label.toLowerCase()}</SelectItem>
          {options.map((o) => (
            <SelectItem key={o.id} value={o.id}>
              {o.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Nurse desk</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Appointments, arrivals, and visit follow-through.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            {updated ? `Updated ${updated} IST` : "Clinic time · IST"}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={loading || !!saving}
          >
            <RefreshCw className={loading ? "animate-spin" : ""} />
            Refresh
          </Button>
        </div>
      </div>
      <Card>
        <CardHeader className="pb-4">
          <CardTitle>
            {day === today()
              ? "Today’s appointments"
              : day
                ? "Daily appointments"
                : "All appointments"}
          </CardTitle>
          <CardDescription>
            Bookings in appointment-time order. Search is applied across stored
            bookings.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <div className="space-y-2">
              <Label htmlFor="desk-day">Date · IST</Label>
              <Input
                id="desk-day"
                type="date"
                value={day}
                onChange={(e) => change(setDay, e.target.value)}
              />
            </div>
            <div className="space-y-2 xl:col-span-2">
              <Label htmlFor="desk-search">Find a booking</Label>
              <div className="relative">
                <Search className="absolute left-3 top-3 size-4 text-muted-foreground" />
                <Input
                  id="desk-search"
                  className="pl-9"
                  placeholder="Patient, phone, doctor, or reference"
                  value={query}
                  onChange={(e) => change(setQuery, e.target.value)}
                />
              </div>
            </div>
            {filters("Doctors", doctor, setDoctor, doctors)}
            {filters("Branches", branch, setBranch, branches)}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-48">
              {filters(
                "Statuses",
                status,
                setStatus,
                [
                  "confirmed",
                  "checked_in",
                  "completed",
                  "cancelled",
                  "no_show",
                ].map((id) => ({ id, name: title(id) })),
              )}
            </div>
            <Button variant="outline" onClick={() => change(setDay, today())}>
              Today
            </Button>
            <Button variant="ghost" onClick={() => change(setDay, "")}>
              All dates
            </Button>
            <span className="ml-auto text-sm text-muted-foreground">
              {loading
                ? "Loading appointments…"
                : `${items.length} on this page`}
            </span>
          </div>
        </CardContent>
      </Card>
      {error && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>
            {error} Your access and filters are preserved. Retry refresh when
            ready.
          </AlertDescription>
        </Alert>
      )}
      {notice && (
        <p role="status" className="text-sm text-primary">
          {notice}
        </p>
      )}
      <Card>
        <CardContent className="px-0" aria-busy={loading}>
          {loading ? (
            <div className="space-y-4 p-6">
              {[1, 2, 3, 4].map((n) => (
                <Skeleton key={n} className="h-12 w-full" />
              ))}
            </div>
          ) : items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Time · IST</TableHead>
                  <TableHead>Patient</TableHead>
                  <TableHead>Doctor / location</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="pr-6 text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="pl-6 tabular-nums whitespace-nowrap">
                      {time(item.starts_at)}
                      {!day && (
                        <p className="text-xs text-muted-foreground">
                          {new Intl.DateTimeFormat("en-IN", {
                            timeZone: "Asia/Kolkata",
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          }).format(new Date(item.starts_at))}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="link"
                        className="h-auto p-0"
                        onClick={() => setSelected(item)}
                      >
                        {item.patient_name}
                      </Button>
                      <p className="text-xs text-muted-foreground mt-1">
                        {item.confirmation_code}
                      </p>
                    </TableCell>
                    <TableCell>
                      <p>{item.doctor?.name || "Unassigned"}</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {item.branch?.name || "—"} ·{" "}
                        {title(item.consultation_type)}
                      </p>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {title(item.origin_channel)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          item.status === "checked_in" ? "default" : "secondary"
                        }
                      >
                        {title(item.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className="pr-6 text-right">
                      {item.status === "confirmed" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!!saving}
                          onClick={() =>
                            void update(
                              item,
                              "checked_in",
                              "Patient arrival confirmed from nurse desk",
                            )
                          }
                        >
                          <Check />
                          Check in
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setSelected(item)}
                        >
                          Details
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-16 px-6 text-center">
              <h3 className="font-medium">No appointments found</h3>
              <p className="text-sm text-muted-foreground mt-2">
                Try another date or clear the filters.
              </p>
              <Button
                className="mt-4"
                variant="outline"
                onClick={() => {
                  setQuery("");
                  setDoctor("all");
                  setBranch("all");
                  setStatus("all");
                  setOffset(0);
                }}
              >
                Clear filters
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      <div className="flex justify-between items-center">
        <span className="text-xs text-muted-foreground">
          Page {offset / pageSize + 1} · Clinic timezone: Asia/Kolkata
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!offset || loading}
            onClick={() => setOffset((v) => Math.max(0, v - pageSize))}
          >
            <ChevronLeft />
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!more || loading}
            onClick={() => setOffset((v) => v + pageSize)}
          >
            Next
            <ChevronRight />
          </Button>
        </div>
      </div>
      <Sheet
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <SheetContent className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{selected?.patient_name}</SheetTitle>
            <SheetDescription>
              {selected?.confirmation_code} ·{" "}
              {selected && title(selected.status)}
            </SheetDescription>
          </SheetHeader>
          {selected && (
            <div className="px-4 space-y-6">
              <dl className="space-y-4 text-sm">
                {[
                  [
                    "Appointment",
                    `${new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" }).format(new Date(selected.starts_at))} · ${time(selected.starts_at)}–${time(selected.ends_at)} IST`,
                  ],
                  ["Doctor", selected.doctor?.name],
                  ["Location", selected.branch?.name],
                  ["Visit type", title(selected.consultation_type)],
                  ["Phone", selected.patient_phone],
                  ["Email", selected.patient_email],
                  ["Reason for visit", selected.reason],
                  ["Booked through", title(selected.origin_channel)],
                ].map(([key, value]) => (
                  <div key={key}>
                    <dt className="text-muted-foreground mb-1">{key}</dt>
                    <dd className="break-words">{value || "Not provided"}</dd>
                  </div>
                ))}
              </dl>
              <Separator />
              <div className="flex flex-wrap gap-2">
                {selected.status === "confirmed" && (
                  <Button
                    disabled={!!saving}
                    onClick={() =>
                      void update(
                        selected,
                        "checked_in",
                        "Patient arrival confirmed from nurse desk",
                      )
                    }
                  >
                    <Check />
                    Check in patient
                  </Button>
                )}
                {selected.status === "checked_in" && (
                  <Button
                    disabled={
                      !!saving || new Date(selected.starts_at).getTime() > clock
                    }
                    onClick={() =>
                      void update(
                        selected,
                        "completed",
                        "Visit completion recorded from nurse desk",
                      )
                    }
                  >
                    Mark visit complete
                  </Button>
                )}
                {["confirmed", "checked_in"].includes(selected.status) && (
                  <Button
                    variant="outline"
                    disabled={!!saving}
                    onClick={() => {
                      setReason("");
                      setPending({ item: selected, status: "cancelled" });
                    }}
                  >
                    Cancel booking
                  </Button>
                )}
                {selected.status === "confirmed" && (
                  <Button
                    variant="ghost"
                    disabled={
                      !!saving || new Date(selected.starts_at).getTime() > clock
                    }
                    onClick={() => {
                      setReason("");
                      setPending({ item: selected, status: "no_show" });
                    }}
                  >
                    Mark no-show
                  </Button>
                )}
              </div>
              {saving && (
                <p role="status" className="text-sm">
                  Saving appointment…
                </p>
              )}
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
      <AlertDialog
        open={!!pending}
        onOpenChange={(open) => {
          if (!open && !saving) setPending(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pending?.status === "no_show"
                ? "Mark patient as no-show?"
                : "Cancel this booking?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pending?.item.patient_name} ·{" "}
              {pending && time(pending.item.starts_at)} IST. This status cannot
              be reversed from the desk.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="status-reason">Reason</Label>
            <Textarea
              id="status-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Record why you are changing this appointment"
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={!!saving}>
              Keep booking
            </AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={!reason.trim() || !!saving}
              onClick={() =>
                pending &&
                void update(pending.item, pending.status, reason.trim())
              }
            >
              {saving ? "Saving…" : "Confirm change"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
