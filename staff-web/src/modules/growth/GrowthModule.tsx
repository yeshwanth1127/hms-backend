import { useEffect, useState } from "react";
import {
  ArrowRight,
  Building2,
  CalendarDays,
  CheckCircle2,
  Globe,
  MapPin,
  MessageCircle,
  Phone,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";

export type GrowthApi = <T>(
  path: string,
  options?: { method?: string; body?: unknown },
) => Promise<T>;
export type GrowthUser = {
  id: string;
  username: string;
  name: string;
  role: string;
  active: boolean;
};
type Props = {
  api: GrowthApi;
  user: GrowthUser;
  page: string;
  onNavigate: (page: string) => void;
  module?: "google_business" | "growth_analytics";
};
type Branch = {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  is_virtual: boolean;
};
type Link = { branch_id: string; booking_url: string; updated_at: string };
type Capability = {
  title: string;
  state: string;
  description: string;
  reference: string;
};
type Audit = {
  id: string;
  branch_id: string;
  actor: string;
  actor_name: string;
  action: string;
  change: { before: string | null; after: string };
  created_at: string;
};
type Summary = {
  filters: {
    start_date: string;
    end_date: string;
    timezone: string;
    cohort: string;
  };
  summary: Record<string, number | null>;
  by_acquisition_source: Record<string, number>;
  by_channel: Record<string, number>;
  by_status: Record<string, number>;
  sources: Record<string, string>;
};
const prefix = "/api/v1/admin";
const message = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Could not load this page. Try again.";
const times = ["10:00 AM", "11:30 AM", "3:00 PM"];

function Notice({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>Unable to complete this request</AlertTitle>
      <AlertDescription>
        {error}
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </AlertDescription>
    </Alert>
  );
}

export function GrowthModule({
  api,
  user,
  page,
  onNavigate,
  module = "google_business",
}: Props) {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [links, setLinks] = useState<Link[]>([]);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [history, setHistory] = useState<Audit[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [branch, setBranch] = useState("");
  const [url, setUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [cohort, setCohort] = useState("created");
  const [filters, setFilters] = useState("");
  const analytics = module === "growth_analytics";
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    setSaved("");
    const load = async () => {
      const cat = await api<{ branches: Branch[] }>(
        prefix + "/growth/catalogue",
      );
      if (!live) return;
      setBranches(cat.branches);
      if (analytics) {
        const data = await api<Summary>(prefix + "/growth/summary" + filters);
        if (live) setSummary(data);
      } else {
        const [linkData, caps, audit] = await Promise.all([
          api<{ links: Link[] }>(prefix + "/google/booking-links"),
          api<{ capabilities: Capability[] }>(prefix + "/google/capabilities"),
          api<Audit[]>(prefix + "/google/changes"),
        ]);
        if (live) {
          setLinks(linkData.links);
          setCapabilities(caps.capabilities);
          setHistory(audit);
        }
      }
    };
    load()
      .catch((e) => {
        if (live) {
          setError(message(e));
          setSummary(null);
          setLinks([]);
          setCapabilities([]);
          setHistory([]);
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [api, module, revision, filters, analytics]);
  const physical = branches.filter((b) => b.is_active && !b.is_virtual);
  const selected = physical.find((b) => b.id === branch);
  const retry = () => setRevision((v) => v + 1);
  async function saveLink(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSaved("");
    try {
      const item = await api<Link>(prefix + "/google/booking-links/" + branch, {
        method: "PUT",
        body: { booking_url: url },
      });
      setLinks((old) => [...old.filter((l) => l.branch_id !== branch), item]);
      setUrl(item.booking_url);
      setSaved(
        "Booking link saved locally. It has not been published to Google.",
      );
      setHistory(await api<Audit[]>(prefix + "/google/changes"));
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  }
  if (!["admin", "growth_manager"].includes(user.role))
    return (
      <Alert>
        <AlertTitle>Access restricted</AlertTitle>
        <AlertDescription>
          Your clinic administrator can assign a growth manager to this module.
        </AlertDescription>
      </Alert>
    );
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">
            {analytics
              ? "Understand appointment outcomes"
              : "Help patients find and book your clinic"}
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">
            {analytics ? "Growth analytics" : "Google Business"}
          </h1>
        </div>
        <Button variant="outline" onClick={retry} disabled={loading}>
          <RefreshCw className="size-4" />
          Refresh
        </Button>
      </div>
      {error && <Notice error={error} onRetry={retry} />}
      {loading ? (
        <div className="space-y-4" aria-label="Loading module">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : analytics ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Report scope</CardTitle>
              <CardDescription>
                Production records only. Existing records with unverified
                provenance are excluded.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form
                className="flex flex-wrap items-end gap-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  const p = new URLSearchParams({ cohort });
                  if (start) p.set("start_date", start);
                  if (end) p.set("end_date", end);
                  if (branch) p.set("branch_id", branch);
                  setFilters("?" + p.toString());
                }}
              >
                <div className="space-y-2">
                  <Label htmlFor="report-start">From</Label>
                  <Input
                    id="report-start"
                    type="date"
                    value={start}
                    onChange={(e) => setStart(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="report-end">To</Label>
                  <Input
                    id="report-end"
                    type="date"
                    value={end}
                    onChange={(e) => setEnd(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="report-branch">Clinic</Label>
                  <BranchSelect
                    id="report-branch"
                    value={branch}
                    onChange={setBranch}
                    branches={branches}
                    all
                  />
                </div>
                <div className="space-y-2">
                  <Label>Group by</Label>
                  <Tabs value={cohort} onValueChange={setCohort}>
                    <TabsList>
                      <TabsTrigger value="created">Booking date</TabsTrigger>
                      <TabsTrigger value="visit">Visit date</TabsTrigger>
                    </TabsList>
                  </Tabs>
                </div>
                <Button type="submit">Apply filters</Button>
              </form>
            </CardContent>
          </Card>
          {summary && (
            <>
              <p className="text-sm text-muted-foreground">
                {summary.filters.start_date} – {summary.filters.end_date} ·{" "}
                {summary.filters.timezone} ·{" "}
                {summary.filters.cohort === "created"
                  ? "Booking date"
                  : "Visit date"}
              </p>
              <div className="grid gap-4 sm:grid-cols-3">
                {[
                  [
                    "Appointments",
                    summary.summary.appointments_in_cohort,
                    "Persisted bookings in this cohort",
                  ],
                  [
                    "Retained confirmations",
                    summary.summary.retained_confirmation_share,
                    "Confirmed, checked-in or completed / all records",
                  ],
                  [
                    "Attendance",
                    summary.summary.attendance_rate_resolved,
                    "Attended / attended + no-show; ended visits only",
                  ],
                ].map(([label, value, definition], i) => (
                  <Card key={String(label)}>
                    <CardHeader>
                      <CardDescription>{label}</CardDescription>
                      <CardTitle className="text-3xl">
                        {value === null || value === undefined ? "—" : value}
                        {i > 0 && value !== null && value !== undefined
                          ? "%"
                          : ""}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="text-sm text-muted-foreground">
                      {definition}
                    </CardContent>
                  </Card>
                ))}
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <CountTable
                  title="Where bookings started"
                  description="Entry attribution supplied with the booking; independent of message channel."
                  rows={summary.by_acquisition_source}
                />
                <CountTable
                  title="Appointment outcomes"
                  description="Current status of persisted appointments in the chosen cohort."
                  rows={summary.by_status}
                />
              </div>
            </>
          )}
          <Alert>
            <AlertTitle>Visitor conversion is not connected yet</AlertTitle>
            <AlertDescription>
              PostHog visitor funnels and Google impressions are unavailable.
              Booking counts alone cannot tell us what percentage of visitors
              booked. Patient names, phone numbers and clinical details are
              excluded from these reports.
            </AlertDescription>
          </Alert>
        </>
      ) : (
        <Tabs
          value={
            [
              "overview",
              "links",
              "preview",
              "capabilities",
              "history",
            ].includes(page)
              ? page
              : "overview"
          }
          onValueChange={(v) => onNavigate(String(v))}
        >
          <TabsList className="mb-6 flex h-auto flex-wrap justify-start">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="links">Booking links</TabsTrigger>
            <TabsTrigger value="preview">Patient preview</TabsTrigger>
            <TabsTrigger value="capabilities">Options</TabsTrigger>
            <TabsTrigger value="history">Change history</TabsTrigger>
          </TabsList>
          <TabsContent value="overview" className="space-y-6">
            <Card>
              <CardHeader className="flex-row items-start justify-between">
                <div className="space-y-2">
                  <CardTitle>Start with a direct appointment link</CardTitle>
                  <CardDescription>
                    Let patients reach the right clinic's booking page in one
                    step.
                  </CardDescription>
                </div>
                <Badge variant="secondary">Google not connected</Badge>
              </CardHeader>
              <CardContent className="space-y-5">
                <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                  Prepare an approved clinic booking URL here. The owner then
                  adds it to the verified Google profile. Automated profile
                  editing needs separate API approval and OAuth.
                </p>
                <Button onClick={() => onNavigate("links")}>
                  Prepare booking link
                  <ArrowRight className="size-4" />
                </Button>
              </CardContent>
            </Card>
            <div className="grid gap-4 md:grid-cols-3">
              {[
                [
                  "01",
                  "Complete the profile",
                  "Confirm the factual name, category, address, opening hours, website and contact number.",
                ],
                [
                  "02",
                  "Verify with Google",
                  "The clinic owner completes the verification method Google offers.",
                ],
                [
                  "03",
                  "Test the patient journey",
                  "Check availability, confirmation, directions and recovery before publishing a booking link.",
                ],
              ].map(([n, title, body]) => (
                <Card key={n}>
                  <CardHeader>
                    <p className="text-sm text-muted-foreground">{n}</p>
                    <CardTitle>{title}</CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm leading-6 text-muted-foreground">
                    {body}
                  </CardContent>
                </Card>
              ))}
            </div>
            <Card>
              <CardHeader>
                <CardTitle>WhatsApp is a separate module</CardTitle>
                <CardDescription>
                  Google Business can work with website booking even when a
                  client opts out of WhatsApp.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-3">
                <Button variant="outline" onClick={() => onNavigate("preview")}>
                  Explore patient preview
                </Button>
                <Button
                  variant="outline"
                  render={
                    <a
                      href="https://business.google.com/"
                      target="_blank"
                      rel="noreferrer"
                    />
                  }
                >
                  Open Google profile manager
                  <Globe className="size-4" />
                </Button>
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="links" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Prepare a clinic booking link</CardTitle>
                <CardDescription>
                  Saving prepares the link in this backend. It does not publish
                  a change to Google.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={saveLink} className="max-w-xl space-y-5">
                  <div className="space-y-2">
                    <Label htmlFor="link-branch">Physical clinic</Label>
                    <BranchSelect
                      id="link-branch"
                      value={branch}
                      branches={physical}
                      onChange={(id) => {
                        setBranch(id);
                        setUrl(
                          links.find((l) => l.branch_id === id)?.booking_url ||
                            "",
                        );
                        setSaved("");
                      }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="booking-url">Live booking URL</Label>
                    <Input
                      id="booking-url"
                      type="url"
                      required
                      placeholder="https://your-clinic.com/book"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                    />
                    <p className="text-sm text-muted-foreground">
                      Use the approved HTTPS website origin. We add clinic and
                      Google source parameters.
                    </p>
                  </div>
                  <Button type="submit" disabled={!selected || saving}>
                    {saving ? "Saving…" : "Save booking link"}
                  </Button>
                  {saved && (
                    <Alert role="status">
                      <CheckCircle2 className="size-4" />
                      <AlertTitle>Link prepared</AlertTitle>
                      <AlertDescription>{saved}</AlertDescription>
                    </Alert>
                  )}
                </form>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Saved links</CardTitle>
              </CardHeader>
              <CardContent>
                {links.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Clinic</TableHead>
                        <TableHead>Prepared URL</TableHead>
                        <TableHead>State</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {links.map((l) => (
                        <TableRow key={l.branch_id}>
                          <TableCell>
                            {branches.find((b) => b.id === l.branch_id)?.name ||
                              l.branch_id}
                          </TableCell>
                          <TableCell className="max-w-md break-all whitespace-normal">
                            {l.booking_url}
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline">Local draft</Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    No links prepared. Choose a physical clinic above to begin.
                  </p>
                )}
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="preview">
            <PatientPreview name={selected?.name || "Your clinic"} />
          </TabsContent>
          <TabsContent value="capabilities">
            <div className="grid gap-4 lg:grid-cols-2">
              {capabilities.map((c) => (
                <Card key={c.title}>
                  <CardHeader>
                    <CardTitle>{c.title}</CardTitle>
                    <CardDescription>{c.state}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <p className="text-sm leading-6 text-muted-foreground">
                      {c.description}
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      render={
                        <a
                          href={c.reference}
                          target="_blank"
                          rel="noreferrer"
                        />
                      }
                    >
                      Read documentation
                      <ArrowRight className="size-4" />
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>
          <TabsContent value="history">
            <Card>
              <CardHeader>
                <CardTitle>Change history</CardTitle>
                <CardDescription>
                  Recorded backend changes attributed to the signed-in staff
                  account.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {history.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>When</TableHead>
                        <TableHead>Clinic</TableHead>
                        <TableHead>Change</TableHead>
                        <TableHead>Changed by</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {history.map((h) => (
                        <TableRow key={h.id}>
                          <TableCell>
                            {new Date(h.created_at).toLocaleString()}
                          </TableCell>
                          <TableCell>
                            {branches.find((b) => b.id === h.branch_id)?.name ||
                              h.branch_id}
                          </TableCell>
                          <TableCell className="max-w-md whitespace-normal break-all">
                            Booking link prepared: {h.change.after}
                          </TableCell>
                          <TableCell>{h.actor_name}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    No recorded changes yet.
                  </p>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
function BranchSelect({
  id,
  value,
  onChange,
  branches,
  all = false,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  branches: Branch[];
  all?: boolean;
}) {
  return (
    <Select
      items={[
        { value: "none", label: all ? "All clinics" : "Choose a clinic" },
        ...branches.map((b) => ({ value: b.id, label: b.name })),
      ]}
      value={value || "none"}
      onValueChange={(v) => onChange(!v || v === "none" ? "" : v)}
    >
      <SelectTrigger id={id} className="min-w-48">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="none">
          {all ? "All clinics" : "Choose a clinic"}
        </SelectItem>
        {branches.map((b) => (
          <SelectItem key={b.id} value={b.id}>
            {b.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
function CountTable({
  title,
  description,
  rows,
}: {
  title: string;
  description: string;
  rows: Record<string, number>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {Object.keys(rows).length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">Appointments</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(rows).map(([key, count]) => (
                <TableRow key={key}>
                  <TableCell>{key.replaceAll("_", " ")}</TableCell>
                  <TableCell className="text-right">{count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-sm text-muted-foreground">
            No production appointments in this period.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function PatientPreview({ name }: { name: string }) {
  const [journey, setJourney] = useState("");
  const [step, setStep] = useState(0);
  const [time, setTime] = useState("");
  function open(value: string) {
    setJourney(value);
    setStep(0);
    setTime("");
  }
  const book =
    journey === "Book" || journey === "WhatsApp" || journey === "Native slots";
  return (
    <div className="space-y-6">
      <Alert>
        <AlertTitle>Illustrative patient preview</AlertTitle>
        <AlertDescription>
          This is a concept, not a live Google listing. Google controls the
          final appearance and available buttons. All clicks below stay in this
          simulation.
        </AlertDescription>
      </Alert>
      <div className="grid items-start gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardContent className="space-y-5 pt-6">
            <div className="grid grid-cols-2 gap-2">
              <ClinicIllustration reception={false} />
              <ClinicIllustration reception />
            </div>
            <div>
              <h2 className="text-2xl font-semibold">{name}</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Hospital · illustrative profile
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {[
                [Globe, "Website"],
                [MapPin, "Directions"],
                [Phone, "Call"],
                [MessageCircle, "WhatsApp"],
                [CalendarDays, "Book"],
              ].map(([Icon, label]) => {
                const I = Icon as typeof Globe;
                return (
                  <Button
                    key={String(label)}
                    variant={label === "Book" ? "default" : "outline"}
                    onClick={() => open(String(label))}
                  >
                    <I className="size-4" />
                    {String(label)}
                  </Button>
                );
              })}
            </div>
            <p className="text-sm text-muted-foreground">
              Address, hours, services and approved clinic photographs appear
              here after configuration. No rating or patient review is invented.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>What each patient can do</CardTitle>
            <CardDescription>
              Give patients a short route from discovery to a real appointment.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {[
              ["Book", "Open live branch availability and reserve a time."],
              [
                "WhatsApp",
                "Open the bot once a business number and profile eligibility are configured.",
              ],
              ["Directions", "Open the actual clinic location."],
              ["Call", "Dial the clinic’s confirmed contact number."],
            ].map(([title, body]) => (
              <div key={title}>
                <p className="font-medium">{title}</p>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  {body}
                </p>
              </div>
            ))}
            <Button variant="outline" onClick={() => open("Native slots")}>
              Explore native slots concept
            </Button>
            <p className="text-xs leading-5 text-muted-foreground">
              Native slots require separate healthcare partner eligibility. The
              movie-showtime experience does not establish this clinic's
              eligibility.
            </p>
          </CardContent>
        </Card>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {[
          [
            Building2,
            "Discover",
            "Accurate clinic details and real photographs.",
          ],
          [
            MessageCircle,
            "Reserve",
            "One booking backend for website and optional WhatsApp.",
          ],
          [
            CheckCircle2,
            "Attend",
            "Persisted confirmation, directions and consented reminders.",
          ],
        ].map(([Icon, title, body]) => {
          const I = Icon as typeof Globe;
          return (
            <Card key={String(title)}>
              <CardHeader>
                <I className="size-6 text-primary" />
                <CardTitle>{String(title)}</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                {String(body)}
              </CardContent>
            </Card>
          );
        })}
      </div>
      <Dialog
        open={!!journey}
        onOpenChange={(v) => {
          if (!v) setJourney("");
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{journey} walkthrough</DialogTitle>
            <DialogDescription>
              Local simulation · no message, call, hold or booking is sent.
            </DialogDescription>
          </DialogHeader>
          {book ? (
            <div className="space-y-4">
              <Badge variant="outline">
                {journey === "Native slots"
                  ? "Conditional Google integration"
                  : "Sample availability"}
              </Badge>
              {step === 0 ? (
                <>
                  <p>
                    {journey === "WhatsApp"
                      ? `Welcome to ${name}. Choose an example consultation time.`
                      : "Choose a sample appointment time."}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {times.map((t) => (
                      <Button
                        variant="outline"
                        key={t}
                        onClick={() => {
                          setTime(t);
                          setStep(1);
                        }}
                      >
                        {t}
                      </Button>
                    ))}
                  </div>
                </>
              ) : step === 1 ? (
                <>
                  <p className="font-medium">Example consultation · {time}</p>
                  <p className="text-sm text-muted-foreground">
                    Production verifies the contact and places a short backend
                    hold before confirmation. This preview collects no patient
                    information.
                  </p>
                  <Button onClick={() => setStep(2)}>
                    Simulate verified confirmation
                  </Button>
                  <Button variant="outline" onClick={() => setStep(3)}>
                    Simulate unavailable slot
                  </Button>
                </>
              ) : step === 2 ? (
                <Alert>
                  <CheckCircle2 className="size-4" />
                  <AlertTitle>Demo journey complete</AlertTitle>
                  <AlertDescription>
                    No appointment was created. Production shows a confirmation
                    only after the backend commits the reservation.
                  </AlertDescription>
                </Alert>
              ) : (
                <>
                  <Alert>
                    <AlertTitle>That time is no longer available</AlertTitle>
                    <AlertDescription>
                      Keep the patient's context and offer fresh availability.
                    </AlertDescription>
                  </Alert>
                  <Button onClick={() => setStep(0)}>
                    Choose another time
                  </Button>
                </>
              )}
              <p className="text-xs text-muted-foreground">
                {journey === "WhatsApp"
                  ? "Business number not configured."
                  : "Use authoritative availability; never publish sample slots."}
              </p>
            </div>
          ) : (
            <Alert>
              <AlertTitle>
                {journey === "Directions"
                  ? "Clinic location needs confirmation"
                  : journey === "Call"
                    ? "Clinic phone needs configuration"
                    : "Website booking needs a live destination"}
              </AlertTitle>
              <AlertDescription>
                {journey === "Directions"
                  ? "Production opens the verified clinic map pin. This preview does not invent a location."
                  : journey === "Call"
                    ? "Production opens the dialler with your approved clinic number. No call is placed here."
                    : "Production opens your approved website. This preview stays local."}
              </AlertDescription>
            </Alert>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
function ClinicIllustration({ reception }: { reception: boolean }) {
  return (
    <div className="rounded-lg border bg-muted/40 p-3">
      <svg
        viewBox="0 0 240 130"
        role="img"
        aria-label={
          reception
            ? "Concept reception illustration"
            : "Concept clinic exterior illustration"
        }
        className="w-full text-primary"
      >
        <rect x="20" y="25" width="200" height="95" rx="4" fill="#e4eadd" />
        {reception ? (
          <>
            <rect x="40" y="80" width="155" height="40" rx="3" fill="#82a396" />
            <rect x="130" y="43" width="55" height="25" fill="#f8faf6" />
            <circle cx="75" cy="63" r="12" fill="#b8cbb9" />
            <path d="M40 95h155" stroke="currentColor" />
          </>
        ) : (
          <>
            <rect x="100" y="70" width="40" height="50" fill="#a1bbb0" />
            <path d="M45 48h45v25H45zm105 0h45v25h-45" fill="#fbfcf9" />
            <path d="M116 33h8v20h-8zm-6 6h20v8h-20" fill="currentColor" />
          </>
        )}
        <path d="M10 121h220" stroke="currentColor" />
      </svg>
      <p className="text-[11px] text-muted-foreground">
        Concept illustration · replace with clinic photo
      </p>
    </div>
  );
}
