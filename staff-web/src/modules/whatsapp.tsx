import { useRef, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  FileText,
  ImageIcon,
  MessageCircle,
  Search,
  Upload,
  Users,
  CalendarDays,
  Clock3,
  ShieldCheck,
  ChevronRight,
  RefreshCw,
  Download,
} from "lucide-react";
import { toast } from "sonner";
import {
  api,
  wa,
  assetUrl,
  dateTime,
  usable,
  type Asset,
  type Inventory,
  type Config,
  type Campaign,
  type Conversation,
  type Catalogue,
  type Template,
  type StaffUser,
  type Appointment,
  type Branch,
  localDate,
} from "@/lib/api";
import {
  Action,
  Choice,
  Empty,
  Field,
  Notice,
  PageTitle,
  Resource,
  SectionTitle,
  StateBadge,
  TaskLink,
  useResource,
} from "@/components/workspace";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Campaigns } from "@/modules/campaigns";

const pages = [
  ["overview", "Overview"],
  ["conversations", "Conversations"],
  ["content", "Doctor content"],
  ["campaigns", "Campaigns"],
  ["followups", "Follow-ups"],
  ["delivery", "Delivery history"],
  ["clinics", "Clinic details"],
];
export function WhatsAppModule({
  user,
  page,
  onNavigate,
  onAppointments,
}: {
  user: StaffUser;
  page: string;
  onNavigate: (p: string) => void;
  onAppointments: () => void;
}) {
  const config = useResource<Config>(wa + "/operations-config");
  return (
    <>
      <PageTitle
        title="WhatsApp"
        description="Patient conversations and clinic outreach, in one place."
        action={
          <Button variant="outline" onClick={() => onNavigate("conversations")}>
            <MessageCircle />
            Open inbox
          </Button>
        }
      />
      <Tabs
        value={page}
        onValueChange={(v) => onNavigate(String(v))}
        className="module-tabs"
      >
        <TabsList>
          {pages.map(([key, label]) => (
            <TabsTrigger key={key} value={key}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <Resource {...config}>
        {config.data && (
          <>
            {!config.data.outreach_enabled && page !== "overview" && (
              <Notice
                title="Patient outreach is paused"
                text="You can prepare content and drafts. Patient campaigns, follow-ups and staff replies will send only after delivery is enabled by your administrator."
              />
            )}
            {page === "overview" ? (
              <Overview
                config={config.data}
                go={onNavigate}
                onAppointments={onAppointments}
              />
            ) : page === "content" ? (
              <DoctorContent />
            ) : page === "conversations" ? (
              <Conversations
                user={user}
                enabled={config.data.outreach_enabled}
              />
            ) : page === "campaigns" ? (
              <Campaigns user={user} config={config.data} />
            ) : page === "followups" ? (
              <Followups user={user} />
            ) : page === "delivery" ? (
              <Delivery />
            ) : page === "clinics" ? (
              <ClinicDetails />
            ) : (
              <Empty
                title="This page isn’t available"
                description="Choose a WhatsApp section above."
              />
            )}
          </>
        )}
      </Resource>
    </>
  );
}
function Overview({
  config,
  go,
  onAppointments,
}: {
  config: Config;
  go: (p: string) => void;
  onAppointments: () => void;
}) {
  const reception = useResource<Conversation[]>(wa + "/reception"),
    campaigns = useResource<Campaign[]>(wa + "/campaigns"),
    inventory = useResource<Inventory>("/api/v1/admin/whatsapp-assets"),
    templates = useResource<Template[]>(wa + "/templates");
  const loading = [reception, campaigns, inventory, templates].some(
      (r) => r.loading,
    ),
    error =
      [reception, campaigns, inventory, templates].find((r) => r.error)
        ?.error ?? "";
  const guides = inventory.data?.departments.filter((d) => d.guide).length ?? 0,
    photos = inventory.data?.doctors.filter((d) => d.photo).length ?? 0,
    drafts = campaigns.data?.filter((c) => c.status === "draft") ?? [],
    approved = templates.data?.filter(usable) ?? [];
  return (
    <Resource
      loading={loading}
      error={error}
      refresh={() => {
        reception.refresh();
        campaigns.refresh();
        inventory.refresh();
        templates.refresh();
      }}
    >
      <div className="mb-6 flex flex-wrap justify-between items-center gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            Today at your clinic
          </h2>
          <p className="text-sm text-muted-foreground mt-2">
            Start with reception, then keep your booking content up to date.
          </p>
        </div>
        <Badge
          variant="outline"
          className={
            config.outreach_enabled
              ? "text-emerald-800"
              : "text-muted-foreground"
          }
        >
          <span
            className={`size-1.5 rounded-full ${config.outreach_enabled ? "bg-emerald-600" : "bg-slate-400"}`}
          />
          {config.outreach_enabled
            ? "Patient outreach enabled"
            : "Patient outreach paused"}
        </Badge>
      </div>
      <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-7">
        {[
          {
            title: "Open conversations",
            value: reception.data?.length ?? 0,
            note: "Patients with reception",
            icon: MessageCircle,
            page: "conversations",
          },
          {
            title: "Campaign drafts",
            value: drafts.length,
            note: "Not sent to patients",
            icon: FileText,
            page: "campaigns",
          },
          {
            title: "Offer subscribers",
            value: config.marketing_contacts,
            note: "Patients who opted in",
            icon: Users,
            page: "campaigns",
          },
          {
            title: "Specialty guides",
            value: `${guides}/${inventory.data?.departments.length ?? 0}`,
            note: "PDFs ready for the bot",
            icon: Upload,
            page: "content",
          },
        ].map((m) => (
          <Card key={m.title} className="gap-0 p-0">
            <CardContent className="p-5">
              <div className="flex justify-between items-center text-xs text-muted-foreground">
                <span>{m.title}</span>
                <m.icon className="size-4" />
              </div>
              <div className="text-3xl font-semibold tracking-tight mt-5 tabular-nums">
                {m.value}
              </div>
              <div className="flex items-center justify-between mt-2">
                <p className="text-xs text-muted-foreground">{m.note}</p>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Open ${m.title.toLowerCase()}`}
                  onClick={() => go(m.page)}
                >
                  <ChevronRight />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid xl:grid-cols-[1.5fr_1fr] gap-6">
        <div className="space-y-6">
          <Card className="gap-0 p-0">
            <CardHeader className="p-5 border-b">
              <CardTitle className="text-base">Your next steps</CardTitle>
              <CardDescription>
                Small tasks that keep the patient experience working.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <TaskLink
                title={
                  reception.data?.length
                    ? `${reception.data.length} conversation${reception.data.length === 1 ? "" : "s"} need reception`
                    : "Reception is up to date"
                }
                description={
                  reception.data?.length
                    ? "Read the latest message, take ownership and reply."
                    : "New handoffs will appear here when a patient asks for your team."
                }
                onClick={() => go("conversations")}
              />
              <TaskLink
                title="Complete doctor introductions"
                description={`${guides} specialty PDFs and ${photos} doctor portraits uploaded. Add or replace files in Doctor content.`}
                onClick={() => go("content")}
              />
              <TaskLink
                title={
                  approved.length
                    ? "Prepare your next campaign"
                    : "Set up approved messages"
                }
                description={
                  approved.length
                    ? `${approved.length} current, supported templates available. Create a draft and test it before approval.`
                    : "Approved templates must sync from Meta before you can create a campaign."
                }
                onClick={() => go("campaigns")}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Recent campaign drafts
              </CardTitle>
              <CardDescription>
                Preparation only. Nothing sends when you save a draft.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {drafts.length ? (
                <div className="space-y-3">
                  {drafts.slice(0, 3).map((d) => (
                    <div
                      key={d.id}
                      className="flex items-center justify-between gap-3 py-2"
                    >
                      <div>
                        <p className="text-sm font-medium">{d.title}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {dateTime(d.scheduled_at)}
                        </p>
                      </div>
                      <StateBadge value={d.status} />
                    </div>
                  ))}
                  <Button
                    variant="outline"
                    className="mt-4"
                    onClick={() => go("campaigns")}
                  >
                    View campaigns
                    <ArrowRight />
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No drafts yet. Start with an approved template when you’re
                  ready.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
        <div className="space-y-6">
          <Card className="bg-muted/40">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <ShieldCheck className="size-4 text-primary" />
                Before a patient message sends
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              {[
                [
                  "Patient permission",
                  "Offers and visit messages have separate consent.",
                ],
                [
                  "Preview, test, approve",
                  "Campaigns need a checked test and a fixed audience.",
                ],
                [
                  "Respect their time",
                  "Messages wait overnight. Offers have frequency limits.",
                ],
              ].map(([title, desc]) => (
                <div key={title} className="flex gap-3">
                  <CheckCircle2 className="size-4 text-primary mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs font-medium">{title}</p>
                    <p className="text-xs leading-relaxed text-muted-foreground mt-1">
                      {desc}
                    </p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Appointments stay together
              </CardTitle>
              <CardDescription>
                WhatsApp bookings use the same appointment records as the rest
                of your clinic.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                variant="outline"
                className="w-full justify-between"
                onClick={onAppointments}
              >
                <span className="flex items-center gap-2">
                  <CalendarDays className="size-4" />
                  Open appointment management
                </span>
                <ArrowRight />
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </Resource>
  );
}
export function UploadFile({
  label,
  accept,
  onUpload,
  compact = false,
}: {
  label: string;
  accept: string;
  onUpload: (file: File) => Promise<void>;
  compact?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null),
    [busy, setBusy] = useState(false),
    [drag, setDrag] = useState(false);
  const upload = async (file?: File) => {
    if (!file) return;
    const image = accept.includes("image");
    if (file.size > (image ? 5 : 10) * 1024 * 1024) {
      toast.error(`Choose a file smaller than ${image ? 5 : 10} MB.`);
      return;
    }
    setBusy(true);
    try {
      await onUpload(file);
      toast.success("File uploaded. The bot will use this version.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
      if (ref.current) ref.current.value = "";
    }
  };
  return (
    <Card
      className={`${compact ? "border-none bg-transparent" : "border-dashed"} ${drag ? "bg-emerald-50 border-primary" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        if (!busy) void upload(e.dataTransfer.files[0]);
      }}
    >
      <CardContent className={compact ? "p-0" : "p-5 text-center"}>
        {!compact && (
          <>
            <Upload className="size-5 text-muted-foreground mx-auto mb-3" />
            <p className="text-xs text-muted-foreground mb-3">
              Drag and drop a file here, or choose from your computer.
            </p>
          </>
        )}
        <Input
          ref={ref}
          type="file"
          accept={accept}
          aria-label={label}
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => void upload(e.target.files?.[0])}
        />
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => ref.current?.click()}
        >
          <Upload />
          {busy ? "Uploading…" : label}
        </Button>
      </CardContent>
    </Card>
  );
}
async function uploadTo(path: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  return api<Asset>(path, { method: "POST", body });
}
function DoctorContent() {
  const resource = useResource<Inventory>("/api/v1/admin/whatsapp-assets"),
    [tab, setTab] = useState("guides"),
    [search, setSearch] = useState("");
  return (
    <Resource {...resource}>
      <SectionTitle
        title="Doctor content"
        description="The bot sends a specialty PDF before the doctor list, then shows the selected doctor’s portrait."
      />
      <div className="flex flex-wrap gap-4 justify-between mb-5">
        <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
          <TabsList>
            <TabsTrigger value="guides">Specialty PDFs</TabsTrigger>
            <TabsTrigger value="photos">Doctor portraits</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="relative max-w-sm w-full sm:w-64">
          <Search className="absolute left-3 top-3 size-4 text-muted-foreground" />
          <Input
            className="pl-9"
            aria-label="Search doctor content"
            placeholder={
              tab === "guides" ? "Find a specialty…" : "Find a doctor…"
            }
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{tab === "guides" ? "Specialty" : "Doctor"}</TableHead>
              <TableHead>Current file</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tab === "guides"
              ? resource.data?.departments
                  .filter((d) =>
                    d.name.toLowerCase().includes(search.toLowerCase()),
                  )
                  .map((d) => (
                    <TableRow key={d.id}>
                      <TableCell className="font-medium">
                        {d.name}
                        <p className="font-normal text-xs text-muted-foreground mt-1">
                          PDF · up to 10 MB
                        </p>
                      </TableCell>
                      <TableCell>
                        {d.guide ? (
                          <Button
                            variant="link"
                            render={
                              <a
                                href={assetUrl(d.guide.id)}
                                target="_blank"
                                rel="noreferrer"
                              />
                            }
                          >
                            <FileText />
                            {d.guide.filename}
                          </Button>
                        ) : (
                          <span className="text-muted-foreground">
                            No PDF uploaded
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <StateBadge value={d.guide ? "ready" : "missing"} />
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end">
                          <UploadFile
                            compact
                            label={
                              d.guide
                                ? `Replace ${d.name} PDF`
                                : `Upload ${d.name} PDF`
                            }
                            accept="application/pdf"
                            onUpload={async (f) => {
                              await uploadTo(
                                `/api/v1/admin/departments/${d.id}/guide`,
                                f,
                              );
                              resource.refresh();
                            }}
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
              : resource.data?.doctors
                  .filter((d) =>
                    (d.name + " " + d.departments.join(" "))
                      .toLowerCase()
                      .includes(search.toLowerCase()),
                  )
                  .map((d) => (
                    <TableRow key={d.id}>
                      <TableCell>
                        <div className="flex items-center gap-3">
                          {d.photo ? (
                            <img
                              alt={`${d.name} portrait`}
                              className="size-10 rounded-lg object-cover"
                              src={assetUrl(d.photo.id)}
                            />
                          ) : (
                            <div className="size-10 bg-muted rounded-lg flex items-center justify-center">
                              <ImageIcon className="size-4 text-muted-foreground" />
                            </div>
                          )}
                          <div className="font-medium">
                            {d.name}
                            <p className="font-normal text-xs text-muted-foreground mt-1">
                              {d.departments.join(", ")}
                            </p>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {d.photo?.filename ?? "No portrait uploaded"}
                      </TableCell>
                      <TableCell>
                        <StateBadge value={d.photo ? "ready" : "missing"} />
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end">
                          <UploadFile
                            compact
                            label={
                              d.photo
                                ? `Replace ${d.name} portrait`
                                : `Upload ${d.name} portrait`
                            }
                            accept="image/png,image/jpeg"
                            onUpload={async (f) => {
                              await uploadTo(
                                `/api/v1/admin/doctors/${d.id}/photo`,
                                f,
                              );
                              resource.refresh();
                            }}
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
          </TableBody>
        </Table>
      </Card>
      {(tab === "guides"
        ? resource.data?.departments
        : resource.data?.doctors
      )?.filter((d) => d.name.toLowerCase().includes(search.toLowerCase()))
        .length === 0 && (
        <Empty
          title="No matches"
          description="Try a different doctor or specialty name."
        />
      )}
      <p className="text-xs text-muted-foreground mt-4">
        Only use clinic-approved content. Uploading a replacement affects future
        bot messages.
      </p>
    </Resource>
  );
}
type Case = {
  id: string;
  kind: string;
  description: string;
  rating: number | null;
  status: string;
  sender_id: string;
  created_at: string;
  attachments: { id: string; asset: Asset }[];
};
function Conversations({
  user,
  enabled,
}: {
  user: StaffUser;
  enabled: boolean;
}) {
  const reception = useResource<Conversation[]>(wa + "/reception"),
    cases = useResource<Case[]>("/api/v1/admin/whatsapp-cases"),
    [selected, setSelected] = useState(""),
    [text, setText] = useState(""),
    [tab, setTab] = useState("reception"),
    [close, setClose] = useState(false);
  const current =
      reception.data?.find((c) => c.sender_id === selected) ??
      reception.data?.[0],
    support = cases.data?.find((c) => c.id === current?.case_id);
  return (
    <Resource {...reception}>
      <SectionTitle
        title="Conversations"
        description="Patient handoffs pause the bot while your team takes care of the conversation."
        action={
          <Button
            variant="outline"
            onClick={() => {
              reception.refresh();
              cases.refresh();
            }}
          >
            <RefreshCw />
            Refresh
          </Button>
        }
      />
      <Tabs
        value={tab}
        onValueChange={(v) => setTab(String(v))}
        className="mb-5"
      >
        <TabsList>
          <TabsTrigger value="reception">
            Reception inbox{" "}
            <Badge variant="secondary">{reception.data?.length ?? 0}</Badge>
          </TabsTrigger>
          <TabsTrigger value="cases">Issues & feedback</TabsTrigger>
        </TabsList>
      </Tabs>
      {tab === "cases" ? (
        <Resource {...cases}>
          {cases.data?.length ? (
            <Card className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Patient</TableHead>
                    <TableHead>Message</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {cases.data.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        +{c.sender_id}
                        <p className="text-xs text-muted-foreground mt-1">
                          {dateTime(c.created_at)}
                        </p>
                      </TableCell>
                      <TableCell className="max-w-80 whitespace-normal">
                        {c.description}
                        {c.rating !== null && (
                          <p className="text-xs mt-2">Rating: {c.rating}/5</p>
                        )}
                        {c.attachments.map((a) => (
                          <Button
                            key={a.id}
                            variant="link"
                            render={
                              <a
                                href={`/api/v1/admin/whatsapp-case-assets/${a.asset.id}`}
                                target="_blank"
                                rel="noreferrer"
                              />
                            }
                          >
                            <Download />
                            {a.asset.filename}
                          </Button>
                        ))}
                      </TableCell>
                      <TableCell>{c.kind}</TableCell>
                      <TableCell>
                        <StateBadge value={c.status} />
                      </TableCell>
                      <TableCell>
                        {c.status !== "resolved" && (
                          <Action
                            variant="outline"
                            run={async () => {
                              await api(
                                `/api/v1/admin/whatsapp-cases/${c.id}`,
                                {
                                  method: "PATCH",
                                  body: { status: "resolved" },
                                },
                              );
                              cases.refresh();
                            }}
                            success="Issue marked resolved"
                          >
                            Resolve issue
                          </Action>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          ) : (
            <Empty
              title="No issues or feedback yet"
              description="Patient issues, ratings and media attachments appear here."
            />
          )}
        </Resource>
      ) : !current ? (
        <Empty
          title="Your reception inbox is clear"
          description="When a patient chooses Talk to reception, their conversation will appear here."
        />
      ) : (
        <Card className="grid lg:grid-cols-[280px_1fr] p-0 gap-0 overflow-hidden">
          <div className="border-b lg:border-b-0 lg:border-r p-3 bg-muted/30">
            <p className="text-[10px] tracking-wider font-semibold text-muted-foreground p-3">
              OPEN CONVERSATIONS
            </p>
            {reception.data?.map((c) => (
              <Button
                key={c.sender_id}
                variant="ghost"
                className={`w-full h-auto min-h-24 justify-start text-left p-3 gap-3 ${c.sender_id === current.sender_id ? "bg-white ring-1 ring-border" : ""}`}
                onClick={() => {
                  setSelected(c.sender_id);
                  setText("");
                }}
              >
                <div className="size-9 rounded-full bg-emerald-50 text-primary flex items-center justify-center shrink-0">
                  <MessageCircle className="size-4" />
                </div>
                <span className="min-w-0">
                  <span className="block text-xs font-medium">
                    +{c.sender_id}
                  </span>
                  <span className="block text-[11px] text-muted-foreground mt-1 truncate max-w-40">
                    {c.messages.at(-1)?.text ?? "New conversation"}
                  </span>
                  <span className="block text-[10px] text-muted-foreground mt-2">
                    {c.assigned_to ?? "Unassigned"}
                  </span>
                </span>
              </Button>
            ))}
          </div>
          <div>
            <div className="p-5 border-b flex flex-wrap items-center justify-between gap-4">
              <div>
                <h3 className="font-semibold text-sm">+{current.sender_id}</h3>
                <p className="text-xs text-muted-foreground mt-1">
                  Bot paused ·{" "}
                  {current.assigned_to ?? "Waiting for a staff member"}
                </p>
              </div>
              <div className="flex gap-2">
                <Action
                  variant="outline"
                  run={async () => {
                    await api(`${wa}/reception/${current.sender_id}`, {
                      method: "PATCH",
                      body: { status: "active", assigned_to: user.name },
                    });
                    reception.refresh();
                  }}
                  success="Conversation assigned to you"
                >
                  Take conversation
                </Action>
                <Button variant="outline" onClick={() => setClose(true)}>
                  Close & resume bot
                </Button>
              </div>
            </div>
            <div className="p-5 space-y-4 max-h-[420px] overflow-y-auto min-h-64">
              {current.messages.map((m, i) => (
                <div
                  key={i}
                  className={`max-w-[85%] ${m.direction === "outbound" ? "ml-auto" : ""}`}
                >
                  <div
                    className={`rounded-lg p-3 text-sm whitespace-pre-wrap break-words ${m.direction === "outbound" ? "bg-emerald-50" : "bg-muted"}`}
                  >
                    {m.text || "Media message"}
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1">
                    {m.direction === "inbound"
                      ? "Patient"
                      : (m.actor ?? "Staff")}{" "}
                    · {dateTime(m.created_at)}
                  </p>
                </div>
              ))}
              {support?.attachments.map((a) => (
                <Button
                  key={a.id}
                  variant="outline"
                  render={
                    <a
                      href={`/api/v1/admin/whatsapp-case-assets/${a.asset.id}`}
                      target="_blank"
                      rel="noreferrer"
                    />
                  }
                >
                  <Download />
                  {a.asset.filename}
                </Button>
              ))}
            </div>
            <div className="p-5 border-t space-y-3">
              {!current.can_reply && (
                <Notice
                  title="Reply window closed"
                  text="Ask the patient to message again before sending a free-text reply."
                />
              )}
              <Field id="reception-reply" label="Reply to patient">
                <Textarea
                  id="reception-reply"
                  placeholder="Write a helpful reply…"
                  value={text}
                  maxLength={2000}
                  onChange={(e) => setText(e.target.value)}
                  disabled={!current.can_reply || !enabled}
                />
              </Field>
              <div className="flex flex-wrap justify-between items-center gap-3">
                <p className="text-xs text-muted-foreground">
                  Replies are sent as {user.name}.
                </p>
                <Action
                  disabled={!enabled || !current.can_reply || !text.trim()}
                  run={async () => {
                    await api(`${wa}/reception/${current.sender_id}/reply`, {
                      method: "POST",
                      body: {
                        actor: user.name,
                        text: text.trim(),
                        idempotency_key: "staff-ui:" + crypto.randomUUID(),
                      },
                    });
                    setText("");
                    reception.refresh();
                  }}
                  success="Reply queued. Check Delivery history for the result."
                >
                  Queue WhatsApp reply
                  <ArrowRight />
                </Action>
              </div>
            </div>
          </div>
        </Card>
      )}
      <Dialog open={close} onOpenChange={setClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Close this conversation?</DialogTitle>
            <DialogDescription>
              Reception will stop handling +{current?.sender_id}. The patient
              can use the booking bot again.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setClose(false)}>
              Keep open
            </Button>
            <Action
              run={async () => {
                await api(`${wa}/reception/${current!.sender_id}`, {
                  method: "PATCH",
                  body: { status: "closed", assigned_to: user.name },
                });
                setClose(false);
                reception.refresh();
              }}
              success="Conversation closed. Bot resumed."
            >
              Close & resume bot
            </Action>
          </div>
        </DialogContent>
      </Dialog>
    </Resource>
  );
}
type Rule = {
  kind: string;
  enabled: boolean;
  template_id: string;
  delay_hours: number;
};
const ruleNames: Record<string, [string, string]> = {
  feedback: ["Post-visit feedback", "After staff mark a visit completed"],
  no_show: [
    "Missed-visit rebooking",
    "After staff mark a patient as a no-show",
  ],
  followup: [
    "Doctor-requested follow-up",
    "After staff select a follow-up date for a completed visit",
  ],
};
function Followups({ user }: { user: StaffUser }) {
  const rules = useResource<Rule[]>(wa + "/followup-rules"),
    templates = useResource<Template[]>(wa + "/templates"),
    visits = useResource<Appointment[]>(
      "/api/v1/admin/appointments?status=completed",
    ),
    [edit, setEdit] = useState<Rule | null>(null),
    [visit, setVisit] = useState(""),
    [due, setDue] = useState(localDate()),
    [confirm, setConfirm] = useState(false);
  const options =
    templates.data
      ?.filter(
        (t) =>
          usable(t) &&
          t.spec?.parameters === 3 &&
          [null, "TEXT"].includes(t.spec.header) &&
          t.category !== "AUTHENTICATION",
      )
      .map((t) => [t.id, `${t.name} · ${t.language}`] as [string, string]) ??
    [];
  return (
    <Resource {...rules}>
      <SectionTitle
        title="Visit follow-ups"
        description="Care messages follow recorded visit events. Patient consent is checked again before delivery."
      />
      <Card className="p-0 mb-6">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Purpose</TableHead>
              <TableHead>Trigger</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Object.entries(ruleNames).map(([kind, [name, trigger]]) => {
              const rule = rules.data?.find((r) => r.kind === kind);
              return (
                <TableRow key={kind}>
                  <TableCell className="font-medium">{name}</TableCell>
                  <TableCell className="text-muted-foreground whitespace-normal">
                    {trigger}
                  </TableCell>
                  <TableCell>
                    <StateBadge value={rule?.enabled ? "enabled" : "off"} />
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="outline"
                      onClick={() =>
                        setEdit(
                          rule ?? {
                            kind,
                            enabled: false,
                            template_id: options[0]?.[0] ?? "",
                            delay_hours: 24,
                          },
                        )
                      }
                    >
                      Configure
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>
      <div className="grid xl:grid-cols-[1.3fr_1fr] gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Schedule a doctor-requested follow-up
            </CardTitle>
            <CardDescription>
              Choose a completed WhatsApp visit and the requested contact date.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <Resource {...visits}>
              <Choice
                label="Completed visit"
                value={visit}
                onChange={setVisit}
                options={[
                  ["", "Select a completed visit"],
                  ...(visits.data
                    ?.filter((a) => a.origin_channel === "whatsapp")
                    .map(
                      (a) =>
                        [
                          a.id,
                          `${a.patient_name} · ${a.confirmation_code}`,
                        ] as [string, string],
                    ) ?? []),
                ]}
              />
            </Resource>
            <Field
              label="Contact date and time"
              id="followup-date"
              hint="Your computer’s local time. Choose within the next 180 days."
            >
              <Input
                type="datetime-local"
                id="followup-date"
                value={due}
                onChange={(e) => setDue(e.target.value)}
                min={localDate(new Date())}
              />
            </Field>
            <Button
              disabled={
                !visit ||
                !due ||
                !rules.data?.find((r) => r.kind === "followup")?.enabled
              }
              onClick={() => setConfirm(true)}
            >
              <Clock3 />
              Review follow-up
            </Button>
            {!rules.data?.find((r) => r.kind === "followup")?.enabled && (
              <p className="text-xs text-muted-foreground">
                Configure and enable the doctor-requested rule first.
              </p>
            )}
          </CardContent>
        </Card>
        <Card className="bg-muted/30">
          <CardHeader>
            <CardTitle className="text-base">
              A visit message is not medical advice
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-muted-foreground leading-relaxed">
            <p>
              Use clinic-approved administrative wording. The bot does not
              prescribe treatment or decide when a patient needs clinical
              follow-up.
            </p>
            <p>
              Patients must opt in to visit messages. Templates classified as
              marketing also need offer consent.
            </p>
            <p>
              Quiet hours and current appointment status are checked at
              delivery.
            </p>
          </CardContent>
        </Card>
      </div>
      <Dialog
        open={!!edit}
        onOpenChange={(v) => {
          if (!v) setEdit(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{edit && ruleNames[edit.kind][0]}</DialogTitle>
            <DialogDescription>
              Template fields must be booking reference, doctor name and visit
              time, in that order.
            </DialogDescription>
          </DialogHeader>
          {edit && (
            <div className="space-y-5">
              <Resource {...templates}>
                <Choice
                  label="Approved template"
                  value={edit.template_id}
                  onChange={(v) => setEdit({ ...edit, template_id: v })}
                  options={
                    options.length
                      ? options
                      : [["", "No compatible template available"]]
                  }
                />
              </Resource>
              <Field
                label="Delay after the visit event (hours)"
                id="rule-delay"
              >
                <Input
                  id="rule-delay"
                  type="number"
                  min={0}
                  max={720}
                  value={edit.delay_hours}
                  onChange={(e) =>
                    setEdit({ ...edit, delay_hours: Number(e.target.value) })
                  }
                />
              </Field>
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="rule-enabled" className="text-sm">
                  Enable consented messages
                </Label>
                <Switch
                  id="rule-enabled"
                  checked={edit.enabled}
                  onCheckedChange={(v) => setEdit({ ...edit, enabled: v })}
                />
              </div>
              <Action
                disabled={!edit.template_id}
                run={async () => {
                  await api(`${wa}/followup-rules/${edit.kind}`, {
                    method: "PUT",
                    body: {
                      enabled: edit.enabled,
                      template_id: edit.template_id,
                      delay_hours: edit.delay_hours,
                    },
                  });
                  setEdit(null);
                  rules.refresh();
                }}
                success="Follow-up rule saved"
              >
                Save rule
              </Action>
            </div>
          )}
        </DialogContent>
      </Dialog>
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Schedule this follow-up?</DialogTitle>
            <DialogDescription>
              {visits.data?.find((v) => v.id === visit)?.patient_name} ·{" "}
              {visits.data?.find((v) => v.id === visit)?.confirmation_code}
              <br />
              {due ? dateTime(new Date(due).toISOString()) : ""}
            </DialogDescription>
          </DialogHeader>
          <p className="text-xs text-muted-foreground">
            This queues the approved template. It sends only if patient
            permission and delivery settings allow it.
          </p>
          <Action
            run={async () => {
              await api(`${wa}/appointments/${visit}/followup`, {
                method: "POST",
                body: { actor: user.name, due_at: new Date(due).toISOString() },
              });
              setConfirm(false);
              setVisit("");
            }}
            success="Follow-up scheduled"
          >
            Schedule follow-up
          </Action>
        </DialogContent>
      </Dialog>
    </Resource>
  );
}
type Job = {
  id: string;
  sender_id: string;
  purpose: string;
  status: string;
  due_at: string;
  last_error?: string;
  meta_message_id?: string;
};
function Delivery() {
  const r = useResource<Job[]>(wa + "/outbound"),
    issues = useResource<{
      inbound: { message_id: string; status: string; attempts: number }[];
      reminders: { id: string; status: string; attempts: number }[];
    }>("/api/v1/admin/whatsapp-delivery-issues"),
    [filter, setFilter] = useState("all");
  return (
    <Resource {...r}>
      <SectionTitle
        title="Delivery history"
        description="Accepted means Meta accepted the request. Delivered and read require provider updates."
        action={
          <Button
            variant="outline"
            onClick={() => {
              r.refresh();
              issues.refresh();
            }}
          >
            <RefreshCw />
            Refresh
          </Button>
        }
      />
      <div className="mb-5 max-w-xs">
        <Choice
          label="Message status"
          value={filter}
          onChange={setFilter}
          options={[
            "all",
            "pending",
            "accepted",
            "delivered",
            "read",
            "failed",
            "uncertain",
            "cancelled",
          ].map((v) => [
            v,
            v === "all"
              ? "All statuses"
              : v.replace(/^./, (c) => c.toUpperCase()),
          ])}
        />
      </div>
      {r.data?.some((j) => j.status === "uncertain") && (
        <Notice
          title="Some messages need manual review"
          text="An uncertain message may already have been sent. Check the provider record before taking any further action; it is never retried automatically."
        />
      )}
      {r.data?.filter((j) => filter === "all" || j.status === filter).length ? (
        <Card className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Recipient</TableHead>
                <TableHead>Purpose</TableHead>
                <TableHead>Send after</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {r.data
                .filter((j) => filter === "all" || j.status === filter)
                .map((j) => (
                  <TableRow key={j.id}>
                    <TableCell>+{j.sender_id}</TableCell>
                    <TableCell>{j.purpose.replaceAll("_", " ")}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {dateTime(j.due_at)}
                    </TableCell>
                    <TableCell>
                      <StateBadge value={j.status} />
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </Card>
      ) : (
        <Empty
          title="No matching messages"
          description="Queued reception replies, campaigns and follow-ups will appear here."
        />
      )}
      <Resource {...issues}>
        {!!(issues.data?.inbound.length || issues.data?.reminders.length) && (
          <div className="mt-6">
            <SectionTitle
              title="Booking replies & reminder issues"
              description="These use separate queues. Check the provider before resending an uncertain message."
            />
            <Card className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Record</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Attempts</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[
                    ...(issues.data?.inbound ?? []).map((j) => ({
                      ...j,
                      id: j.message_id,
                    })),
                    ...(issues.data?.reminders ?? []),
                  ].map((j) => (
                    <TableRow key={j.id}>
                      <TableCell className="font-mono text-xs">
                        {j.id}
                      </TableCell>
                      <TableCell>
                        <StateBadge value={j.status} />
                      </TableCell>
                      <TableCell>{j.attempts}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          </div>
        )}
      </Resource>
    </Resource>
  );
}
function ClinicDetails() {
  const catalogue = useResource<Catalogue>("/api/v1/admin/catalogue"),
    [edit, setEdit] = useState<Branch | null>(null);
  return (
    <Resource {...catalogue}>
      <SectionTitle
        title="Clinic details"
        description="Booking confirmations include the clinic address, directions and arrival instructions."
      />
      <div className="grid md:grid-cols-2 gap-5">
        {catalogue.data?.branches.map((b) => (
          <Card key={b.id}>
            <CardHeader className="flex-row justify-between items-start">
              <div>
                <CardTitle className="text-base">{b.name}</CardTitle>
                <CardDescription className="mt-1">{b.area}</CardDescription>
              </div>
              <StateBadge value={b.is_active ? "active" : "inactive"} />
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground min-h-10">
                {b.address || "Address not added yet."}
              </p>
              {b.arrival_instructions && (
                <p className="text-xs text-muted-foreground">
                  {b.arrival_instructions}
                </p>
              )}
              <div className="flex justify-between gap-3">
                <Button variant="outline" onClick={() => setEdit(b)}>
                  Edit details
                </Button>
                {b.directions_url && (
                  <Button
                    variant="link"
                    render={
                      <a
                        href={b.directions_url}
                        target="_blank"
                        rel="noreferrer"
                      />
                    }
                  >
                    View directions
                    <ArrowRight />
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <Dialog
        open={!!edit}
        onOpenChange={(v) => {
          if (!v) setEdit(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit clinic details</DialogTitle>
            <DialogDescription>{edit?.name}</DialogDescription>
          </DialogHeader>
          {edit && (
            <div className="space-y-5">
              <Field label="Address" id="clinic-address">
                <Textarea
                  id="clinic-address"
                  value={edit.address}
                  maxLength={500}
                  onChange={(e) =>
                    setEdit({ ...edit, address: e.target.value })
                  }
                />
              </Field>
              <Field label="Google Maps directions link" id="clinic-map">
                <Input
                  id="clinic-map"
                  type="url"
                  value={edit.directions_url}
                  maxLength={500}
                  onChange={(e) =>
                    setEdit({ ...edit, directions_url: e.target.value })
                  }
                />
              </Field>
              <Field
                label="Arrival instructions"
                id="clinic-arrival"
                hint="For example, arrive 10 minutes early and bring prior reports."
              >
                <Textarea
                  id="clinic-arrival"
                  value={edit.arrival_instructions}
                  maxLength={500}
                  onChange={(e) =>
                    setEdit({ ...edit, arrival_instructions: e.target.value })
                  }
                />
              </Field>
              <Action
                run={async () => {
                  await api(`${wa}/branches/${edit.id}`, {
                    method: "PATCH",
                    body: {
                      address: edit.address,
                      directions_url: edit.directions_url,
                      arrival_instructions: edit.arrival_instructions,
                    },
                  });
                  setEdit(null);
                  catalogue.refresh();
                }}
                success="Clinic details saved"
              >
                Save details
              </Action>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Resource>
  );
}
