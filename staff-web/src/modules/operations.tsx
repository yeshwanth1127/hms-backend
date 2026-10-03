import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
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
  PageTitle,
  Resource,
  StateBadge,
  Empty,
  useResource,
} from "@/components/workspace";
import { dateTime, type Appointment, type Catalogue } from "@/lib/api";

type Analytics = {
  summary: Record<string, number>;
  daily_bookings: { date: string; bookings: number }[];
  by_status: { label: string; value: number }[];
  by_channel: { label: string; value: number }[];
  recent_appointments: Appointment[];
};
type Event = {
  id: string;
  event_type: string;
  aggregate_id: string;
  created_at: string;
  processed_at: string | null;
  status: string;
};
type Doctor = { id: string; name: string; departments: { id: string }[] };

export function OperationsModule({ page }: { page: string }) {
  return page === "catalogue" ? (
    <CataloguePage />
  ) : (
    <ActivityPage overview={page === "overview"} />
  );
}
function ActivityPage({ overview }: { overview: boolean }) {
  const r = useResource<Analytics>("/api/v1/admin/analytics");
  const events = useResource<Event[]>(
    overview ? null : "/api/v1/admin/operations",
  );
  const health = useResource<{ ready: boolean }>(
    overview ? null : "/api/health/ready",
  );
  const refresh = () => {
    r.refresh();
    events.refresh();
    health.refresh();
  };
  const s = r.data?.summary ?? {};
  const metrics = overview
    ? [
        [
          "Total appointments",
          s.appointments_total,
          `${s.appointments_upcoming ?? 0} upcoming`,
        ],
        [
          "Retained confirmations",
          `${s.conversion_rate ?? 0}%`,
          `${s.appointments_confirmed ?? 0} confirmed, checked in or completed`,
        ],
        [
          "Active doctors",
          s.active_doctors,
          `${s.schedule_rules ?? 0} schedule rules`,
        ],
        [
          "Pending messages",
          s.pending_notifications,
          `${s.active_holds ?? 0} active slot holds`,
        ],
        [
          "Voice bookings",
          s.voice_bookings,
          `${s.voice_sessions_total ?? 0} call sessions`,
        ],
      ]
    : [
        ["Pending messages", s.pending_notifications, "WhatsApp messages waiting to send"],
        ["Active holds", s.active_holds, "Temporary reservations"],
        [
          "API readiness",
          health.loading
            ? "Checking…"
            : health.data?.ready
              ? "Ready"
              : "Unavailable",
          "Database connectivity check",
        ],
      ];
  return (
    <>
      <PageTitle
        title={overview ? "Overview" : "Operations"}
        description={
          overview
            ? "Appointment activity across the clinic’s booking channels."
            : "Notification outbox, temporary reservations and database readiness."
        }
        action={
          <Button variant="outline" onClick={refresh}>
            <RefreshCw />
            Refresh
          </Button>
        }
      />
      <Resource
        loading={r.loading || (!overview && events.loading)}
        error={r.error || (!overview ? events.error || health.error : "")}
        refresh={refresh}
      >
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4 mb-6">
          {metrics.map(([label, value, detail]) => (
            <Card key={String(label)}>
              <CardHeader>
                <CardDescription>{label}</CardDescription>
                <CardTitle className="text-3xl tabular-nums">
                  {value ?? 0}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-xs text-muted-foreground">
                {detail}
              </CardContent>
            </Card>
          ))}
        </div>
        {overview ? (
          <div className="space-y-6">
            <div className="grid lg:grid-cols-2 gap-6">
              <Card>
                <CardHeader>
                  <CardTitle>Daily bookings</CardTitle>
                  <CardDescription>
                    Last 14 days · records created, using UTC dates.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <ChartContainer
                    className="h-52 w-full mb-5"
                    config={{
                      bookings: { label: "Bookings", color: "var(--primary)" },
                    }}
                  >
                    <BarChart
                      accessibilityLayer
                      data={r.data?.daily_bookings ?? []}
                    >
                      <CartesianGrid vertical={false} />
                      <XAxis
                        dataKey="date"
                        tickLine={false}
                        axisLine={false}
                        tickFormatter={(value) => String(value).slice(5)}
                      />
                      <YAxis
                        allowDecimals={false}
                        tickLine={false}
                        axisLine={false}
                        width={30}
                      />
                      <ChartTooltip content={<ChartTooltipContent />} />
                      <Bar
                        dataKey="bookings"
                        fill="var(--color-bookings)"
                        radius={[3, 3, 0, 0]}
                        isAnimationActive={false}
                      />
                    </BarChart>
                  </ChartContainer>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Date</TableHead>
                        <TableHead>Bookings</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(r.data?.daily_bookings ?? []).map((d) => (
                        <TableRow key={d.date}>
                          <TableCell>{d.date}</TableCell>
                          <TableCell>{d.bookings}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Appointment health</CardTitle>
                  <CardDescription>
                    Current statuses and booking channels.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <ChartContainer
                    className="h-52 w-full mb-5"
                    config={{
                      value: { label: "Appointments", color: "var(--primary)" },
                    }}
                  >
                    <BarChart
                      accessibilityLayer
                      layout="vertical"
                      data={r.data?.by_status ?? []}
                    >
                      <CartesianGrid horizontal={false} />
                      <XAxis
                        type="number"
                        allowDecimals={false}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        type="category"
                        dataKey="label"
                        tickLine={false}
                        axisLine={false}
                        width={90}
                        tickFormatter={(value) =>
                          String(value).replaceAll("_", " ")
                        }
                      />
                      <ChartTooltip content={<ChartTooltipContent />} />
                      <Bar
                        dataKey="value"
                        fill="var(--color-value)"
                        radius={[0, 3, 3, 0]}
                        isAnimationActive={false}
                      />
                    </BarChart>
                  </ChartContainer>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Status</TableHead>
                        <TableHead>Appointments</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(r.data?.by_status ?? []).map((d) => (
                        <TableRow key={d.label}>
                          <TableCell>
                            <StateBadge value={d.label} />
                          </TableCell>
                          <TableCell>{d.value}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <Table className="mt-6">
                    <TableHeader>
                      <TableRow>
                        <TableHead>Channel</TableHead>
                        <TableHead>Appointments</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(r.data?.by_channel ?? []).map((d) => (
                        <TableRow key={d.label}>
                          <TableCell>
                            <StateBadge value={d.label} />
                          </TableCell>
                          <TableCell>{d.value}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </div>
            <Card>
              <CardHeader>
                <CardTitle>Recent appointments</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Patient</TableHead>
                      <TableHead>Doctor & clinic</TableHead>
                      <TableHead>Visit</TableHead>
                      <TableHead>Channel</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Reference</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(r.data?.recent_appointments ?? []).map((a) => (
                      <TableRow key={a.id}>
                        <TableCell>
                          {a.patient_name}
                          <p className="text-xs text-muted-foreground">
                            {a.patient_phone}
                          </p>
                        </TableCell>
                        <TableCell>
                          {a.doctor?.name}
                          <p className="text-xs text-muted-foreground">
                            {a.branch?.name}
                          </p>
                        </TableCell>
                        <TableCell>{dateTime(a.starts_at)}</TableCell>
                        <TableCell>
                          <StateBadge value={a.origin_channel} />
                        </TableCell>
                        <TableCell>
                          <StateBadge value={a.status} />
                        </TableCell>
                        <TableCell>{a.confirmation_code}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {!r.data?.recent_appointments.length && (
                  <Empty
                    title="No appointments yet"
                    description="New clinic bookings will appear here."
                  />
                )}
              </CardContent>
            </Card>
          </div>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>Event outbox</CardTitle>
              <CardDescription>
                Most recent 100 booking events. A processed event is separate
                from a patient delivery receipt.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Event</TableHead>
                    <TableHead>Record</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Processed</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(events.data ?? []).map((e) => (
                    <TableRow key={e.id}>
                      <TableCell>{e.event_type}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {e.aggregate_id}
                      </TableCell>
                      <TableCell>{dateTime(e.created_at)}</TableCell>
                      <TableCell>
                        {e.processed_at ? dateTime(e.processed_at) : "Pending"}
                      </TableCell>
                      <TableCell>
                        <StateBadge
                          value={e.processed_at ? "processed" : "pending"}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {!events.data?.length && (
                <Empty
                  title="No operational events"
                  description="Booking changes appear here."
                />
              )}
            </CardContent>
          </Card>
        )}
      </Resource>
    </>
  );
}
function CataloguePage() {
  const r = useResource<Catalogue>("/api/v1/admin/catalogue");
  const doctors = useResource<Doctor[]>("/api/v1/admin/doctors");
  const refresh = () => {
    r.refresh();
    doctors.refresh();
  };
  return (
    <>
      <PageTitle
        title="Hospital catalogue"
        description="Clinic locations, specialties and doctor coverage available to patients and agents."
        action={
          <Button variant="outline" onClick={refresh}>
            <RefreshCw />
            Refresh
          </Button>
        }
      />
      <Resource
        loading={r.loading || doctors.loading}
        error={r.error || doctors.error}
        refresh={refresh}
      >
        <div className="grid lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Clinic branches</CardTitle>
              <CardDescription>
                {r.data?.branches.length ?? 0} locations
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Clinic</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(r.data?.branches ?? []).map((b) => (
                    <TableRow key={b.id}>
                      <TableCell>
                        {b.name}
                        <p className="text-xs text-muted-foreground">
                          {b.area}
                        </p>
                      </TableCell>
                      <TableCell>
                        <StateBadge
                          value={b.is_active ? "active" : "inactive"}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Departments</CardTitle>
              <CardDescription>
                {r.data?.departments.length ?? 0} clinical services
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Specialty</TableHead>
                    <TableHead>Doctors</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(r.data?.departments ?? []).map((d) => (
                    <TableRow key={d.id}>
                      <TableCell>{d.name}</TableCell>
                      <TableCell>
                        {
                          (doctors.data ?? []).filter((doctor) =>
                            doctor.departments.some((dept) => dept.id === d.id),
                          ).length
                        }
                      </TableCell>
                      <TableCell>
                        <StateBadge
                          value={d.is_active ? "active" : "inactive"}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      </Resource>
    </>
  );
}
