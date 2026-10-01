import { useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import type { GrowthApi } from "./GrowthModule";
type Activity = {
  synthetic?: boolean;
  status:
    | "disabled"
    | "not_configured"
    | "invalid_host"
    | "unavailable"
    | "available";
  traffic: string;
  rows: { event: string; label: string; events: number; visitors: number }[];
  filters: { start_date: string; end_date: string; timezone: string };
  retrieved_at: string | null;
};
export function WebsiteActivity({ api, demo = false }: { api: GrowthApi; demo?: boolean }) {
  const [traffic, setTraffic] = useState(demo ? "demo" : "production"),
    [revision, setRevision] = useState(0),
    [data, setData] = useState<Activity | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setLoading(true);
    setData(null);
    setError("");
    api<Activity>("/api/v1/admin/growth/website-activity?traffic=" + traffic)
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live)
          setError(
            e instanceof Error ? e.message : "Unable to load website activity.",
          );
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [api, traffic, revision]);
  const configured = data?.status === "available";
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>Website activity · PostHog</CardTitle>
          <Badge variant="outline">
            {configured
              ? data?.synthetic ? "Synthetic sample activity" : "Aggregate data available"
              : loading
                ? "Checking connection"
                : "Not connected"}
          </Badge>
        </div>
        <CardDescription>
          Website engagement is separate from the persisted appointment reports
          above.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs value={traffic} onValueChange={setTraffic}>
            <TabsList>
              <TabsTrigger value="production">Production activity</TabsTrigger>
              <TabsTrigger value="demo">Demo activity</TabsTrigger>
            </TabsList>
          </Tabs>
          <Button
            variant="outline"
            size="sm"
            disabled={loading}
            onClick={() => setRevision((v) => v + 1)}
          >
            Refresh website activity
          </Button>
        </div>
        {loading ? (
          <Skeleton className="h-28 w-full" />
        ) : error ? (
          <Alert variant="destructive">
            <AlertTitle>Website activity could not load</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : !configured ? (
          <Alert>
            <AlertTitle>
              {data?.status === "unavailable"
                ? "PostHog could not be reached"
                : data?.status === "invalid_host"
                  ? "PostHog host needs configuration"
                  : "PostHog setup is pending"}
            </AlertTitle>
            <AlertDescription>
              {data?.status === "unavailable"
                ? "Appointment reports remain available. Check the read-key permissions and retry."
                : "Frontend tracking is implemented. An operator still needs to configure the PostHog project, app host and restricted server read key, then enable aggregate reads. No sample counts are substituted."}
            </AlertDescription>
          </Alert>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              {data.filters.start_date} – {data.filters.end_date} ·{" "}
              {data.filters.timezone} · whole website · independent of clinic
              and appointment report filters
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Activity</TableHead>
                  <TableHead className="text-right">Events</TableHead>
                  <TableHead className="text-right">
                    Anonymous visitors
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.rows.map((row) => (
                  <TableRow key={row.event}>
                    <TableCell>{row.label}</TableCell>
                    <TableCell className="text-right">{row.events}</TableCell>
                    <TableCell className="text-right">{row.visitors}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="text-xs text-muted-foreground">
              Retrieved{" "}
              {data.retrieved_at
                ? new Date(data.retrieved_at).toLocaleString()
                : "—"}
              . Visitors are counted per event and must not be added across
              rows.
            </p>
          </>
        )}
        <div className="space-y-2 text-sm leading-6 text-muted-foreground">
          <p>
            Consented visitors only. These event counts are not an ordered
            funnel or a visitor-to-appointment conversion rate.
          </p>
          <p>
            The current website marks every event as demo. “Booking preview
            completed” means a local preview was reached; it does not mean the
            backend created an appointment. Production activity stays separate
            until real booking integration is wired.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
