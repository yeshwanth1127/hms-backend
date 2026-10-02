import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Choice, Field } from "@/components/workspace";
import "./index.css";
type Branch = {
  id: string;
  slug: string;
  name: string;
  timezone: string;
  is_virtual: boolean;
};
type Doctor = {
  id: string;
  slug: string;
  name: string;
  consultation_fee: number;
  accepts_virtual: boolean;
  branches: Branch[];
};
type Slot = {
  doctor_id: string;
  branch_id: string;
  consultation_type: string;
  starts_at: string;
  ends_at: string;
};
type Hold = Slot & { id: string; expires_at: string };
type Receipt = {
  id: string;
  confirmation_code: string;
  status: string;
  doctor_name: string;
  branch_name: string;
  timezone: string;
  address: string;
  directions_url: string;
  arrival_instructions: string;
  consultation_fee: number;
  is_demo: boolean;
  consent_to_reminders: boolean;
  delivery_state: string;
  reservation: Hold;
};
type Entry = { id: string; status: string; doctor_id: string; offer?: Hold };
const ROOT = "/api/v1/web/booking";
let csrf = "";
class BookingRequestError extends Error {
  readonly status: number;
  readonly code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}
async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const r = await fetch(path, {
    method,
    credentials: "same-origin",
    redirect: "error",
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(method !== "GET" ? { "X-Booking-CSRF": csrf } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new BookingRequestError(
      (data.error?.message ?? "Could not complete the request.") +
        " Reference: " +
        (r.headers.get("X-Request-ID") ?? "unknown"),
      r.status,
      data.error?.code,
    );
  }
  return r.status === 204 ? (undefined as T) : r.json();
}
const params = new URLSearchParams(window.location.search);
const today = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
const pretty = (s: string, tz = "Asia/Kolkata") =>
  new Intl.DateTimeFormat("en-IN", {
    timeZone: tz,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(s));
const safeLink = (s: string) => {
  try {
    const u = new URL(s);
    return u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
};
function calendar(v: Receipt) {
  const stamp = (s: string) =>
    new Date(s).toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
  const escape = (s: string) =>
    s.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/[,;]/g, "\\$&");
  const text = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Avocado Health//Appointments//EN",
    "BEGIN:VEVENT",
    "UID:" + v.id + "@avocado-booking",
    "DTSTAMP:" + stamp(new Date().toISOString()),
    "DTSTART:" + stamp(v.reservation.starts_at),
    "DTEND:" + stamp(v.reservation.ends_at),
    "SUMMARY:" + escape("Clinic visit · " + v.doctor_name),
    "LOCATION:" + escape(v.branch_name + " " + v.address),
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/calendar;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "clinic-appointment.ics";
  a.click();
  URL.revokeObjectURL(url);
}
function Booking() {
  const [doctors, setDoctors] = useState<Doctor[]>([]),
    [branches, setBranches] = useState<Branch[]>([]),
    [doctor, setDoctor] = useState(""),
    [branch, setBranch] = useState(""),
    [day, setDay] = useState(today),
    [kind, setKind] = useState("in_person");
  const [slots, setSlots] = useState<Slot[]>([]),
    [hold, setHold] = useState<Hold | null>(null),
    [name, setName] = useState(""),
    [phone, setPhone] = useState(""),
    [privacy, setPrivacy] = useState(false),
    [reminders, setReminders] = useState(false),
    [waitConsent, setWaitConsent] = useState(false);
  const [verified, setVerified] = useState(false),
    [verifyLink, setVerifyLink] = useState(""),
    [visits, setVisits] = useState<Receipt[]>([]),
    [waitlist, setWaitlist] = useState<Entry[]>([]),
    [saved, setSaved] = useState<Receipt | null>(null),
    [moving, setMoving] = useState<Receipt | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [note, setNote] = useState(""),
    [enabled, setEnabled] = useState(false),
    [demo, setDemo] = useState(false),
    [loading, setLoading] = useState(true),
    [loadingSlots, setLoadingSlots] = useState(false),
    [clock, setClock] = useState(() => Date.now());
  const [confirmation, setConfirmation] = useState<{
    message: string;
    run: () => void;
  } | null>(null);
  const confirmKey = useRef("");
  const chosen = doctors.find((d) => d.id === doctor),
    clinic = branches.find((b) => b.id === branch);
  const places =
    kind === "virtual"
      ? branches.filter((b) => b.is_virtual)
      : branches.filter(
          (b) =>
            !b.is_virtual &&
            (!chosen || chosen.branches.some((a) => a.id === b.id)),
        );
  const [slotVersion, setSlotVersion] = useState(0);
  async function refresh() {
    setSlotVersion((v) => v + 1);
    const [v, w] = await Promise.all([
      request<Receipt[]>(ROOT + "/appointments"),
      request<Entry[]>(ROOT + "/waitlist"),
    ]);
    setVisits(v);
    setWaitlist(w);
  }
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNote("");
    try {
      await fn();
    } catch (e) {
      if (e instanceof BookingRequestError && e.status === 401) {
        setVerified(false);
        setVisits([]);
        setWaitlist([]);
        setHold(null);
        setSaved(null);
        setMoving(null);
        setName("");
        csrf = "";
        setVerifyLink("");
      }
      if (e instanceof BookingRequestError && e.code === "PRICE_CHANGED") {
        setDoctors(await request<Doctor[]>("/api/v1/doctors"));
        if (hold)
          await request(ROOT + "/holds/" + hold.id, "DELETE").catch(
            () => undefined,
          );
        setHold(null);
        setSlotVersion((v) => v + 1);
      }
      setError(e instanceof Error ? e.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let live = true;
    Promise.all([
      request<{ is_demo: boolean }>(ROOT + "/config"),
      request<Doctor[]>("/api/v1/doctors"),
      request<Branch[]>("/api/v1/branches"),
    ])
      .then(async ([c, d, b]) => {
        if (!live) return;
        setEnabled(true);
        setDemo(c.is_demo);
        setDoctors(d);
        setBranches(b);
        const requestedDoctor = params.get("doctor");
        const matches = d.filter((a) => requestedDoctor
          ? a.id === requestedDoctor || a.slug === requestedDoctor
          : a.name === params.get("doctor_name"));
        // Names bridge website profiles to the live roster, but are not unique
        // identifiers. Require an explicit choice rather than guessing.
        const match = matches.length === 1 ? matches[0] : undefined;
        const place = b.find(
          (a) =>
            a.slug === params.get("branch") || a.id === params.get("branch"),
        );
        if (match) setDoctor(match.id);
        if (place) setBranch(place.id);
        if ((params.has("doctor_name") || params.has("doctor")) && !match)
          setNote(
            "Choose a doctor from the current clinic roster. The website profile could not be matched.",
          );
        try {
          const s = await request<{ status: string; csrf_token: string }>(
            ROOT + "/session",
          );
          if (live) {
            csrf = s.csrf_token;
            setVerified(s.status === "verified");
            if (s.status === "verified") await refresh();
          }
        } catch {
          /* No existing verified session. */
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    let live = true;
    setSlots([]);
    if (!doctor || !branch) return;
    setLoadingSlots(true);
    request<{ slots: Slot[] }>(
      "/api/v1/availability?" +
        new URLSearchParams({
          doctor_id: doctor,
          branch_id: branch,
          start_date: day,
          end_date: day,
          consultation_type: kind,
        }),
    )
      .then((r) => {
        if (live) setSlots(r.slots);
      })
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setLoadingSlots(false);
      });
    return () => {
      live = false;
    };
  }, [doctor, branch, day, kind, slotVersion]);
  async function check() {
    const s = await request<{ status: string; csrf_token: string }>(
      ROOT + "/session",
    );
    csrf = s.csrf_token;
    if (s.status !== "verified") {
      setNote(
        "Still waiting for the message from your entered WhatsApp number.",
      );
      return;
    }
    setVerified(true);
    setVerifyLink("");
    await refresh();
    setNote("Number verified. Select an available time above.");
  }
  const source = [
    "direct",
    "google_business",
    "organic_search",
    "paid",
    "referral",
  ].includes(params.get("source") ?? "")
    ? params.get("source")!
    : "direct";
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto max-w-4xl p-5 flex justify-between items-center">
          <a href="/" className="font-semibold">
            Avocado Health
          </a>
          <Badge variant="outline">
            {demo
              ? "Test environment · no live clinic visit"
              : "Clinic booking"}
          </Badge>
        </div>
      </header>
      <main className="mx-auto max-w-4xl space-y-6 p-5 py-10">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            Book your clinic visit
          </h1>
          <p className="mt-3 text-muted-foreground">
            Choose a doctor, verify your WhatsApp number and confirm an
            available time.
          </p>
        </div>
        {error && (
          <Alert variant="destructive">
            <AlertTitle>Request could not complete</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {note && (
          <Alert>
            <AlertDescription>{note}</AlertDescription>
          </Alert>
        )}
        {loading ? (
          <p>Loading clinic information…</p>
        ) : !enabled ? (
          <Card>
            <CardHeader>
              <CardTitle>Contact reception to book</CardTitle>
              <CardDescription>
                Online booking needs clinic configuration before it can accept
                appointments.
              </CardDescription>
            </CardHeader>
          </Card>
        ) : (
          <>
            {saved ? (
              <Card>
                <CardHeader>
                  <CardTitle>
                    {saved.is_demo
                      ? "Test booking saved"
                      : "Appointment confirmed"}
                  </CardTitle>
                  <CardDescription>
                    {saved.confirmation_code} · {saved.status}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="font-medium">{saved.doctor_name}</p>
                  <p>
                    {pretty(saved.reservation.starts_at, saved.timezone)} ·{" "}
                    {saved.branch_name}
                  </p>
                  <p>{saved.address}</p>
                  <p>{saved.arrival_instructions}</p>
                  <p>Consultation ₹{saved.consultation_fee} · Pay at clinic</p>
                  <p className="text-sm text-muted-foreground">
                    {saved.delivery_state === "not_requested"
                      ? "No reminder requested."
                      : saved.delivery_state === "uncertain"
                        ? "Reminder delivery needs clinic review."
                        : saved.delivery_state === "cancelled"
                          ? "Reminder cancelled."
                          : saved.delivery_state === "sent"
                            ? "Reminder sent to WhatsApp. This does not confirm it was read."
                            : "WhatsApp reminder queued, subject to current preferences. Queued does not mean delivered."}
                  </p>
                  <div className="flex flex-wrap gap-3">
                    {safeLink(saved.directions_url) && (
                      <a
                        href={safeLink(saved.directions_url)!}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        Open directions
                      </a>
                    )}
                    <Button variant="outline" onClick={() => calendar(saved)}>
                      Add to calendar
                    </Button>
                    <Button variant="outline" onClick={() => setSaved(null)}>
                      Manage visits or book another
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle>
                    {moving
                      ? "Choose a replacement time"
                      : "1. Choose your visit"}
                  </CardTitle>
                  <CardDescription>
                    Times come from the clinic backend. Selecting a time
                    reserves it briefly; confirmation saves the appointment.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Choice
                      label="Doctor"
                      value={doctor}
                      disabled={!!hold || !!moving || busy}
                      onChange={(v) => {
                        setDoctor(v);
                        if (
                          !doctors
                            .find((d) => d.id === v)
                            ?.branches.some((b) => b.id === branch)
                        )
                          setBranch("");
                      }}
                      options={doctors.map((d) => [d.id, d.name])}
                    />
                    <Choice
                      label="Visit type"
                      value={kind}
                      disabled={!!hold || !!moving || busy}
                      onChange={(v) => {
                        setKind(v);
                        setBranch("");
                      }}
                      options={
                        chosen?.accepts_virtual
                          ? [
                              ["in_person", "In person"],
                              ["virtual", "Video visit"],
                            ]
                          : [["in_person", "In person"]]
                      }
                    />
                    <Choice
                      label="Clinic"
                      value={branch}
                      disabled={!!hold || !!moving || busy}
                      onChange={setBranch}
                      options={places.map((b) => [b.id, b.name])}
                    />
                    <Field label="Date" id="visit-date">
                      <Input
                        id="visit-date"
                        type="date"
                        value={day}
                        min={today()}
                        disabled={!!hold || busy}
                        onChange={(e) => setDay(e.target.value)}
                      />
                    </Field>
                  </div>
                  {chosen && (
                    <p>
                      Consultation ₹{chosen.consultation_fee} · Pay at clinic
                    </p>
                  )}
                  {loadingSlots ? (
                    <p>Checking availability…</p>
                  ) : doctor && branch && !hold ? (
                    <>
                      <div className="flex flex-wrap gap-2">
                        {slots.map((s) => (
                          <Button
                            key={s.starts_at + s.ends_at}
                            variant="outline"
                            disabled={!verified || busy}
                            onClick={() =>
                              void act(async () => {
                                setHold(
                                  await request<Hold>(ROOT + "/holds", "POST", {
                                    ...s,
                                    idempotency_key: crypto.randomUUID(),
                                  }),
                                );
                                confirmKey.current = crypto.randomUUID();
                              })
                            }
                          >
                            {pretty(s.starts_at, clinic?.timezone)}
                          </Button>
                        ))}
                      </div>
                      {!slots.length && (
                        <Alert>
                          <AlertTitle>
                            No bookable times on this date
                          </AlertTitle>
                          <AlertDescription>
                            Try another date, join the waitlist after
                            verification, or contact reception. A waitlist
                            request does not reserve a visit.
                          </AlertDescription>
                        </Alert>
                      )}
                      {!verified && (
                        <p className="text-sm text-muted-foreground">
                          Verify your number below to select a time.
                        </p>
                      )}
                    </>
                  ) : null}
                  {hold && (
                    <div className="space-y-4 rounded-xl border p-4">
                      <p className="font-medium">
                        {pretty(hold.starts_at, clinic?.timezone)}
                      </p>
                      <p>
                        {new Date(hold.expires_at).getTime() <= clock
                          ? "Hold expired. Choose a time again."
                          : `Held for ${Math.max(0, Math.ceil((new Date(hold.expires_at).getTime() - clock) / 1000))} seconds.`}
                      </p>
                      {!moving && (
                        <>
                          <Field label="Patient’s full name" id="patient-name">
                            <Input
                              id="patient-name"
                              value={name}
                              maxLength={160}
                              onChange={(e) => setName(e.target.value)}
                            />
                          </Field>
                          <div className="flex items-start gap-3">
                            <Checkbox
                              id="reminders"
                              checked={reminders}
                              onCheckedChange={(v) => setReminders(v === true)}
                            />
                            <Label htmlFor="reminders" className="leading-6">
                              Send optional visit reminders through WhatsApp.
                              This does not opt me into marketing. STOP turns
                              proactive messages off.
                            </Label>
                          </div>
                        </>
                      )}
                      <div className="flex flex-wrap gap-3">
                        <Button
                          disabled={
                            busy ||
                            new Date(hold.expires_at).getTime() <= clock ||
                            (!moving && name.trim().length < 2)
                          }
                          onClick={() =>
                            void act(async () => {
                              const r = moving
                                ? await request<Receipt>(
                                    ROOT +
                                      "/appointments/" +
                                      moving.id +
                                      "/reschedule",
                                    "POST",
                                    {
                                      new_hold_id: hold.id,
                                      idempotency_key: confirmKey.current,
                                    },
                                  )
                                : await request<Receipt>(
                                    ROOT + "/appointments",
                                    "POST",
                                    {
                                      hold_id: hold.id,
                                      patient_name: name,
                                      expected_fee: chosen!.consultation_fee,
                                      consent_to_reminders: reminders,
                                      acquisition_source: source,
                                      idempotency_key: confirmKey.current,
                                    },
                                  );
                              setSaved(r);
                              setHold(null);
                              setMoving(null);
                              await refresh();
                            })
                          }
                        >
                          {busy
                            ? "Saving…"
                            : moving
                              ? "Confirm replacement"
                              : "Confirm appointment"}
                        </Button>
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            void act(async () => {
                              await request(
                                ROOT + "/holds/" + hold.id,
                                "DELETE",
                              );
                              setHold(null);
                              setSlotVersion((v) => v + 1);
                            })
                          }
                        >
                          Choose another time
                        </Button>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
            {!verified && (
              <Card>
                <CardHeader>
                  <CardTitle>2. Verify your WhatsApp number</CardTitle>
                  <CardDescription>
                    Send the prepared message to the clinic bot from this
                    number, then return here. Do not share the verification
                    link.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Field
                    label="WhatsApp number with country code"
                    id="patient-phone"
                    hint="For example, +91 followed by your mobile number."
                  >
                    <Input
                      id="patient-phone"
                      autoComplete="tel"
                      type="tel"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                    />
                  </Field>
                  <div className="flex gap-3 items-start">
                    <Checkbox
                      id="privacy"
                      checked={privacy}
                      onCheckedChange={(v) => setPrivacy(v === true)}
                    />
                    <Label htmlFor="privacy" className="leading-6">
                      Use this number for verification and appointment
                      management. I accept the{" "}
                      <a href="/privacy" className="underline">
                        privacy notice
                      </a>
                      . Marketing consent is separate.
                    </Label>
                  </div>
                  <Button
                    disabled={busy || !privacy || !phone}
                    onClick={() =>
                      void act(async () => {
                        const r = await request<{
                          csrf_token: string;
                          verification_url: string;
                        }>(ROOT + "/session", "POST", {
                          phone: phone.replace(/\s/g, ""),
                          privacy_accepted: privacy,
                        });
                        csrf = r.csrf_token;
                        setVerifyLink(r.verification_url);
                      })
                    }
                  >
                    {verifyLink
                      ? "Start new verification"
                      : "Prepare verification message"}
                  </Button>
                  {verifyLink && (
                    <div className="flex flex-wrap gap-4">
                      <a
                        href={verifyLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium underline"
                      >
                        Open WhatsApp and send verification
                      </a>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => void act(check)}
                      >
                        I sent it · Check verification
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
            {verified && (
              <Card>
                <CardHeader>
                  <CardTitle>Your visits and waitlist</CardTitle>
                  <CardDescription>
                    Access lasts 30 minutes. Shared WhatsApp numbers can access
                    website visits booked with that number.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => void act(refresh)}
                  >
                    Refresh visits and offers
                  </Button>
                  {!visits.length && (
                    <p>No website appointments for this verified number.</p>
                  )}
                  {visits.map((v) => (
                    <div className="space-y-3 rounded-xl border p-4" key={v.id}>
                      <p className="font-medium">
                        {v.doctor_name} · {v.status}
                      </p>
                      <p>
                        {pretty(v.reservation.starts_at, v.timezone)} ·{" "}
                        {v.branch_name}
                      </p>
                      <p className="text-sm">{v.confirmation_code}</p>
                      {v.status === "confirmed" &&
                        new Date(v.reservation.starts_at).getTime() > clock && (
                          <div className="flex gap-3">
                            <Button
                              variant="outline"
                              disabled={busy || !!hold}
                              onClick={() => {
                                setMoving(v);
                                setDoctor(v.reservation.doctor_id);
                                setBranch(v.reservation.branch_id);
                                setKind(v.reservation.consultation_type);
                                setSaved(null);
                                setNote(
                                  "Choose a new time above. Your original visit stays reserved until replacement confirmation.",
                                );
                              }}
                            >
                              Reschedule
                            </Button>
                            <Button
                              variant="outline"
                              disabled={busy}
                              onClick={() =>
                                setConfirmation({
                                  message:
                                    "Cancel this visit and release its time?",
                                  run: () =>
                                    void act(async () => {
                                      await request(
                                        ROOT +
                                          "/appointments/" +
                                          v.id +
                                          "/cancel",
                                        "POST",
                                        {
                                          reason:
                                            "Patient cancelled from website",
                                        },
                                      );
                                      await refresh();
                                      setNote(
                                        "Visit cancelled. Its time is available again.",
                                      );
                                    }),
                                })
                              }
                            >
                              Cancel visit
                            </Button>
                          </div>
                        )}
                    </div>
                  ))}
                  {waitlist.map((w) => (
                    <div key={w.id} className="rounded-xl border p-4 space-y-3">
                      <p>
                        Waitlist ·{" "}
                        {doctors.find((d) => d.id === w.doctor_id)?.name} ·{" "}
                        {w.status}
                      </p>
                      {w.offer && (
                        <>
                          <p>
                            Offer {pretty(w.offer.starts_at)} · expires{" "}
                            {pretty(w.offer.expires_at)}
                          </p>
                          <Button
                            disabled={busy}
                            onClick={() => {
                              const d = doctors.find(
                                (d) => d.id === w.doctor_id,
                              )!;
                              setConfirmation({
                                message: `Accept this visit for ₹${d.consultation_fee}, payable at clinic?`,
                                run: () =>
                                  void act(async () => {
                                    setSaved(
                                      await request<Receipt>(
                                        ROOT + "/waitlist/" + w.id + "/accept",
                                        "POST",
                                        {
                                          expected_fee: d.consultation_fee,
                                          idempotency_key: crypto.randomUUID(),
                                        },
                                      ),
                                    );
                                    await refresh();
                                  }),
                              });
                            }}
                          >
                            Review and accept offer
                          </Button>
                        </>
                      )}
                      {["waiting", "offered"].includes(w.status) && (
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            void act(async () => {
                              await request(
                                ROOT + "/waitlist/" + w.id,
                                "DELETE",
                              );
                              await refresh();
                            })
                          }
                        >
                          Withdraw request
                        </Button>
                      )}
                    </div>
                  ))}
                  {doctor && branch && !moving && (
                    <div className="space-y-3 border-t pt-5">
                      <Field
                        label="Patient name for waitlist"
                        id="waitlist-name"
                      >
                        <Input
                          id="waitlist-name"
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                        />
                      </Field>
                      <div className="flex gap-3 items-start">
                        <Checkbox
                          id="waitlist-consent"
                          checked={waitConsent}
                          onCheckedChange={(v) => setWaitConsent(v === true)}
                        />
                        <Label htmlFor="waitlist-consent" className="leading-6">
                          Request an offer for this doctor, clinic and selected
                          date. No appointment is guaranteed. Reception reviews
                          offers; I can withdraw at any time.
                        </Label>
                      </div>
                      <Button
                        variant="outline"
                        disabled={
                          busy || !waitConsent || name.trim().length < 2
                        }
                        onClick={() =>
                          void act(async () => {
                            await request(ROOT + "/waitlist", "POST", {
                              doctor_id: doctor,
                              branch_id: branch,
                              consultation_type: kind,
                              patient_name: name,
                              start_date: day,
                              end_date: day,
                              consent_to_waitlist: waitConsent,
                            });
                            await refresh();
                            setNote(
                              "Waitlist request saved. It does not reserve a time.",
                            );
                          })
                        }
                      >
                        Join waitlist for selected date
                      </Button>
                    </div>
                  )}
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() =>
                      void act(async () => {
                        await request(ROOT + "/session", "DELETE");
                        setVerified(false);
                        setHold(null);
                        setVisits([]);
                        setWaitlist([]);
                        setSaved(null);
                        setMoving(null);
                        setName("");
                        csrf = "";
                        setNote("Signed out of appointment management.");
                      })
                    }
                  >
                    Sign out of booking
                  </Button>
                </CardContent>
              </Card>
            )}
          </>
        )}
        <p className="text-sm leading-6 text-muted-foreground">
          For urgent medical needs, contact local emergency services. This
          service does not provide medical advice.
        </p>
        <AlertDialog
          open={!!confirmation}
          onOpenChange={(v) => {
            if (!v) setConfirmation(null);
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Confirm visit change</AlertDialogTitle>
              <AlertDialogDescription>
                {confirmation?.message}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep current state</AlertDialogCancel>
              <Button
                onClick={() => {
                  const action = confirmation?.run;
                  setConfirmation(null);
                  action?.();
                }}
              >
                Confirm
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<Booking />);
