import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useState } from "react";
import { Plus } from "lucide-react";
import { api, dateTime, type StaffUser } from "@/lib/api";
import {
  Action,
  Choice,
  Field,
  PageTitle,
  Resource,
  SectionTitle,
  usePermissions,
  useResource,
} from "@/components/workspace";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
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
import { ModuleSettings } from "@/modules/growth/ModuleSettings";

export function SettingsModule({
  user,
  page,
  onModulesChanged,
}: {
  user: StaffUser;
  page: string;
  onModulesChanged?: () => void;
}) {
  const [open, setOpen] = useState(false),
    [name, setName] = useState(""),
    [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [role, setRole] = useState("staff"),
    [current, setCurrent] = useState(""),
    [next, setNext] = useState(""),
    [change, setChange] = useState(false);
  const users = useResource<StaffUser[]>(
    user.role === "admin" ? "/api/v1/staff/users" : null,
  );
  if (page === "modules")
    return (
      <ModuleSettings api={api} onChanged={onModulesChanged ?? (() => {})} />
    );
  if (page === "design") return <DesignBook />;
  if (page === "activity") return <ActivityLog />;

  return (
    <>
      <PageTitle
        title="Workspace settings"
        description="Staff accounts and optional modules are managed in one place."
      />
      <div className="grid md:grid-cols-2 gap-5 mb-7">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Your account</CardTitle>
            <CardDescription>
              {user.name} · @{user.username}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" onClick={() => setChange(true)}>
              Change password
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Optional modules</CardTitle>
            <CardDescription>
              Choose which tools your clinic uses. Saved data is retained when a
              module is disabled.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="outline"
              onClick={() => {
                history.pushState({}, "", "/staff/settings/modules");
                window.dispatchEvent(new PopStateEvent("popstate"));
              }}
            >
              Manage modules
            </Button>
          </CardContent>
        </Card>
      </div>
      {user.role === "admin" && <StaffPermissions />}
      {user.role === "admin" && (
        <>
          <SectionTitle
            title="Staff accounts"
            description="Each staff member uses their own username and password."
            action={
              <Button onClick={() => setOpen(true)}>
                <Plus />
                Add staff member
              </Button>
            }
          />
          <Resource {...users}>
            <Card className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Username</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.data?.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell>{u.name}</TableCell>
                      <TableCell>{u.username}</TableCell>
                      <TableCell>{u.role.replaceAll("_", " ")}</TableCell>
                      <TableCell>{u.active ? "Active" : "Disabled"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          </Resource>
        </>
      )}
      <Dialog
        open={open}
        onOpenChange={(v) => {
          setOpen(v);
          if (!v) setPassword("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add staff member</DialogTitle>
            <DialogDescription>
              Share these credentials privately with the new team member.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Field label="Full name" id="staff-name">
              <Input
                id="staff-name"
                value={name}
                maxLength={40}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field
              label="Username"
              id="staff-username"
              hint="At least 3 characters. Letters, numbers, dots, underscores or hyphens."
            >
              <Input
                id="staff-username"
                value={username}
                autoComplete="off"
                maxLength={64}
                onChange={(e) => setUsername(e.target.value)}
              />
            </Field>
            <Field
              label="Initial password"
              id="staff-password"
              hint="Use at least 12 characters. No shared or default passwords."
            >
              <Input
                id="staff-password"
                type="password"
                value={password}
                autoComplete="new-password"
                maxLength={128}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <Choice
              label="Role"
              value={role}
              onChange={setRole}
              options={["staff", "admin", "growth_manager"].map((r) => [
                r,
                r === "staff"
                  ? "Clinic staff"
                  : r === "admin"
                    ? "Clinic administrator"
                    : "Growth manager",
              ])}
            />
            <p className="text-xs text-muted-foreground">
              Clinic staff manage appointments and WhatsApp. Growth managers
              access enabled growth tools only. Administrators also manage staff
              and module settings.
            </p>
            <Action
              disabled={
                name.trim().length < 2 ||
                username.length < 3 ||
                password.length < 12
              }
              run={async () => {
                await api("/api/v1/staff/users", {
                  method: "POST",
                  body: { name, username, password, role },
                });
                setPassword("");
                setOpen(false);
                users.refresh();
              }}
              success="Staff account created"
            >
              Create staff account
            </Action>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={change}
        onOpenChange={(v) => {
          setChange(v);
          if (!v) {
            setCurrent("");
            setNext("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Change your password</DialogTitle>
            <DialogDescription>
              This signs you out on every device. Sign in again with your new
              password.
            </DialogDescription>
          </DialogHeader>
          <Field label="Current password" id="current-password">
            <Input
              type="password"
              id="current-password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              maxLength={256}
            />
          </Field>
          <Field
            label="New password"
            id="new-password"
            hint="12–128 characters."
          >
            <Input
              type="password"
              id="new-password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              maxLength={128}
            />
          </Field>
          <Action
            disabled={!current || next.length < 12}
            run={async () => {
              await api("/api/v1/staff/password", {
                method: "POST",
                body: { current_password: current, new_password: next },
              });
              setNext("");
              setCurrent("");
              window.dispatchEvent(new Event("staff-signout"));
            }}
            success="Password changed. Sign in again."
          >
            Change password & sign out
          </Action>
        </DialogContent>
      </Dialog>
    </>
  );
}

function DesignBook() {
  const book = useResource<{ title: string; markdown: string }>(
    "/api/v1/staff/design-guide",
  );
  return (
    <Resource {...book}>
      <Card className="max-w-4xl mx-auto">
        <CardContent className="p-6 sm:p-10">
          <article className="decision-book">
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={{
                h2: ({ children, ...props }) => (
                  <h2
                    {...props}
                    id={String(children)
                      .toLowerCase()
                      .replace(/[^\w\s-]/g, "")
                      .trim()
                      .replace(/\s+/g, "-")}
                  >
                    {children}
                  </h2>
                ),
              }}
            >
              {book.data?.markdown ?? ""}
            </Markdown>
          </article>
        </CardContent>
      </Card>
    </Resource>
  );
}

function StaffPermissions() {
  const permissions = usePermissions();
  return (
    <Card className="mb-7">
      <CardHeader>
        <CardTitle className="text-base">
          What clinic staff can change
        </CardTitle>
        <CardDescription>
          Administrators can always change everything. Consultation fees are
          administrator-only. Every change is recorded in the activity log.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Resource {...permissions}>
          {permissions.data?.staff.map((p) => (
            <div
              key={p.key}
              className="flex items-center justify-between gap-4"
            >
              <Label htmlFor={"perm-" + p.key} className="text-sm font-normal">
                {p.label}
              </Label>
              <Switch
                id={"perm-" + p.key}
                checked={p.allowed}
                onCheckedChange={async (allowed) => {
                  try {
                    await api(`/api/v1/staff/permissions/${p.key}`, {
                      method: "PUT",
                      body: { allowed },
                    });
                  } finally {
                    permissions.refresh();
                  }
                }}
              />
            </div>
          ))}
        </Resource>
      </CardContent>
    </Card>
  );
}

type AuditItem = {
  id: string;
  created_at: string;
  actor: string;
  actor_type: string;
  action: string;
  targets: Record<string, string>;
  change: Record<string, unknown>;
  status_code: number;
  outcome: "success" | "rejected";
  request_id: string;
};
const describe = (value: unknown) =>
  value && typeof value === "object" && "from" in value && "to" in value
    ? `${String((value as { from: unknown }).from)} → ${String((value as { to: unknown }).to)}`
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);

function ActivityLog() {
  const [filters, setFilters] = useState({
      actor: "",
      target: "",
      action: "",
      outcome: "",
      start: "",
      end: "",
    }),
    [limit, setLimit] = useState(50);
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => v),
  ).toString();
  const log = useResource<{ items: AuditItem[]; more: boolean }>(
    `/api/v1/staff/audit?${query}&limit=${limit}`,
  );
  const set = (key: keyof typeof filters) => (v: string) => {
    setFilters({ ...filters, [key]: v });
    setLimit(50);
  };
  return (
    <>
      <PageTitle
        title="Activity log"
        description="Every change made in the clinic system: who, what, which record, and whether it worked."
        action={
          <Button
            variant="outline"
            render={<a href={`/api/v1/staff/audit.csv?${query}`} download />}
          >
            Export CSV
          </Button>
        }
      />
      <Card className="mb-5">
        <CardContent className="grid sm:grid-cols-3 lg:grid-cols-6 gap-3 pt-6">
          <Field label="Person" id="audit-actor">
            <Input
              id="audit-actor"
              value={filters.actor}
              onChange={(e) => set("actor")(e.target.value)}
            />
          </Field>
          <Field label="Record (code or id)" id="audit-target">
            <Input
              id="audit-target"
              value={filters.target}
              onChange={(e) => set("target")(e.target.value)}
            />
          </Field>
          <Field label="Action contains" id="audit-action">
            <Input
              id="audit-action"
              value={filters.action}
              onChange={(e) => set("action")(e.target.value)}
            />
          </Field>
          <Choice
            label="Outcome"
            value={filters.outcome}
            onChange={set("outcome")}
            options={[
              ["", "All"],
              ["success", "Succeeded"],
              ["rejected", "Rejected or failed"],
            ]}
          />
          <Field label="From" id="audit-start">
            <Input
              id="audit-start"
              type="date"
              value={filters.start}
              onChange={(e) => set("start")(e.target.value)}
            />
          </Field>
          <Field label="To" id="audit-end">
            <Input
              id="audit-end"
              type="date"
              value={filters.end}
              onChange={(e) => set("end")(e.target.value)}
            />
          </Field>
        </CardContent>
      </Card>
      <Resource {...log}>
        <Card className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Person</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Records</TableHead>
                <TableHead>Change</TableHead>
                <TableHead>Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {log.data?.items.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="whitespace-nowrap">
                    {dateTime(e.created_at)}
                  </TableCell>
                  <TableCell className="whitespace-normal">{e.actor}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {e.action}
                  </TableCell>
                  <TableCell className="whitespace-normal text-xs">
                    {Object.entries(e.targets)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(", ")}
                  </TableCell>
                  <TableCell className="whitespace-normal text-xs">
                    {Object.entries(e.change)
                      .map(([k, v]) => `${k}: ${describe(v)}`)
                      .join("; ")}
                  </TableCell>
                  <TableCell>
                    <span
                      className={
                        e.outcome === "success"
                          ? ""
                          : "text-destructive font-medium"
                      }
                    >
                      {e.status_code}{" "}
                      {e.outcome === "success" ? "OK" : "Rejected"}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {!log.data?.items.length && (
            <p className="p-6 text-sm text-muted-foreground">
              No matching activity.
            </p>
          )}
        </Card>
        {log.data?.more && (
          <Button
            variant="outline"
            className="mt-4"
            onClick={() => setLimit(Math.min(limit + 50, 200))}
            disabled={limit >= 200}
          >
            {limit >= 200
              ? "Narrow the filters or export CSV for more"
              : "Show more"}
          </Button>
        )}
      </Resource>
    </>
  );
}
