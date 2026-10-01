import { useEffect, useRef, useState } from "react";
import { Headphones, RefreshCw } from "lucide-react";
import { recordingBlob, dateTime } from "@/lib/api";
import {
  PageTitle,
  Resource,
  Notice,
  useResource,
} from "@/components/workspace";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type Call = {
  id: string;
  runtime_session_id: string;
  status: string;
  channel: string;
  agent_version: number | null;
  started_at: string;
  ended_at: string | null;
  turn_count: number;
  tool_call_count: number;
  last_intent: string | null;
  appointment: { id: string; confirmation_code: string; status: string } | null;
  recording_state: string;
  consented_at: string | null;
  recording_available_until: string | null;
};
type History = {
  calls: Call[];
  total: number;
  summary: {
    calls: number;
    bookings: number;
    errors: number;
    completed: number;
    tool_calls: number;
    period_days: number;
  };
  can_review_recordings: boolean;
  configuration: {
    calls_ready: boolean;
    recordings_ready: boolean;
    access_days: number;
    agent_version: number | null;
  };
};
type Access = {
  id: string;
  session_id: string;
  actor: string;
  outcome: string;
  created_at: string;
};
const recordingLabels: Record<string, string> = {
  eligible: "Review recording",
  pending: "Awaiting call details",
  no_consent: "No recording consent",
  expired: "Access expired",
  not_configured: "Playback needs setup",
};
function RecordingReview({ call }: { call: Call }) {
  const [url, setUrl] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const objectUrl = useRef("");
  useEffect(
    () => () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    },
    [],
  );
  async function load() {
    setBusy(true);
    setError("");
    try {
      const blob = await recordingBlob(
        `/api/v1/staff/voice/sessions/${encodeURIComponent(call.id)}/recording`,
      );
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = URL.createObjectURL(blob);
      setUrl(objectUrl.current);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  // A closed dialog unmounts this component and releases its temporary audio.
  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <dt className="text-muted-foreground">Call started</dt>
          <dd className="mt-1">{dateTime(call.started_at)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Outcome</dt>
          <dd className="mt-1 capitalize">{call.status}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Recording consent</dt>
          <dd className="mt-1">
            {call.consented_at ? dateTime(call.consented_at) : "Not recorded"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Access ends</dt>
          <dd className="mt-1">
            {call.recording_available_until
              ? dateTime(call.recording_available_until)
              : "Pending"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Last action</dt>
          <dd className="mt-1">
            {call.last_intent?.replaceAll("_", " ") ?? "Conversation started"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Turns / tools</dt>
          <dd className="mt-1">
            {call.turn_count} / {call.tool_call_count}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Call ended</dt>
          <dd className="mt-1">
            {call.ended_at ? dateTime(call.ended_at) : "In progress"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Session reference</dt>
          <dd className="mt-1 break-all">{call.runtime_session_id}</dd>
        </div>
      </dl>
      {error && <Notice title="Recording could not be opened" text={error} />}
      {url ? (
        <audio
          controls
          preload="metadata"
          src={url}
          className="w-full"
          aria-label="Call recording"
        />
      ) : (
        <Button
          disabled={busy || call.recording_state !== "eligible"}
          onClick={load}
        >
          <Headphones />
          {busy
            ? "Retrieving recording…"
            : recordingLabels[call.recording_state]}
        </Button>
      )}
      <p className="text-xs leading-relaxed text-muted-foreground">
        Opening a recording is logged against your staff account. The provider
        may still be processing a recently ended call. This workspace’s access
        deadline does not delete the provider’s copy.
      </p>
    </div>
  );
}
function RecordingAudit() {
  const r = useResource<Access[]>("/api/v1/staff/voice/recording-access");
  return (
    <Resource {...r}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            <TableHead>Administrator</TableHead>
            <TableHead>Call</TableHead>
            <TableHead>Result</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {r.data?.map((a) => (
            <TableRow key={a.id}>
              <TableCell>{dateTime(a.created_at)}</TableCell>
              <TableCell>{a.actor}</TableCell>
              <TableCell className="font-mono text-xs">
                {a.session_id.slice(0, 8)}
              </TableCell>
              <TableCell>{a.outcome.replaceAll("_", " ")}</TableCell>
            </TableRow>
          ))}
          {!r.data?.length && (
            <TableRow>
              <TableCell colSpan={4} className="text-muted-foreground py-8">
                No recordings have been requested.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </Resource>
  );
}
export function VoiceModule({ demo = false }: { demo?: boolean }) {
  const [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<Call | null>(null),
    [tab, setTab] = useState("calls");
  const r = useResource<History>(`/api/v1/staff/voice?offset=${offset}`);
  return (
    <div className="space-y-6">
      <PageTitle
        title="Voice"
        description="Review assistant calls and the bookings they created."
        action={
          <Button variant="outline" onClick={r.refresh}>
            <RefreshCw />
            Refresh
          </Button>
        }
      />
      <Resource {...r}>
        {r.data && (
          <>
            {!demo && !r.data.configuration.calls_ready && (
              <Notice
                title="Calling needs setup"
                text="Configure the clinic’s Sarvam agent and approved version before patients can start calls."
              />
            )}
            {r.data.can_review_recordings &&
              !r.data.configuration.recordings_ready && (
                <Notice
                  title="Recording playback needs setup"
                  text="Verify the provider’s recording response and download host. Call history remains available."
                />
              )}
            <Card>
              <CardContent className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 py-6">
                {[
                  ["Calls", r.data.summary.calls],
                  ["Bookings created", r.data.summary.bookings],
                  ["Call errors", r.data.summary.errors],
                  ["Completed calls", r.data.summary.completed],
                  ["Tool activity", r.data.summary.tool_calls],
                ].map(([label, value]) => (
                  <div key={label}>
                    <p className="text-xs text-muted-foreground">
                      {label} · 30 days
                    </p>
                    <p className="mt-2 text-2xl font-semibold tabular-nums">
                      {value}
                    </p>
                  </div>
                ))}
              </CardContent>
            </Card>
            <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
              <TabsList>
                <TabsTrigger value="calls">Call history</TabsTrigger>
                {r.data.can_review_recordings && (
                  <TabsTrigger value="access">Recording access</TabsTrigger>
                )}
              </TabsList>
              <TabsContent value="calls">
                <Card>
                  <CardHeader>
                    <CardTitle>Recent calls</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Started</TableHead>
                          <TableHead>Outcome</TableHead>
                          <TableHead>Booking</TableHead>
                          <TableHead>Agent</TableHead>
                          <TableHead>Recording</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {r.data.calls.map((call) => (
                          <TableRow key={call.id}>
                            <TableCell>
                              <p className="whitespace-nowrap">
                                {dateTime(call.started_at)}
                              </p>
                              <p className="text-xs text-muted-foreground mt-1">
                                {call.channel === "phone" ? "Phone" : "Website"}{" "}
                                · {call.turn_count} turns ·{" "}
                                {call.tool_call_count} tools
                              </p>
                            </TableCell>
                            <TableCell>
                              <Badge
                                variant={
                                  call.status === "error"
                                    ? "destructive"
                                    : "secondary"
                                }
                                className="capitalize"
                              >
                                {call.status === "issued"
                                  ? "Connecting"
                                  : call.status}
                              </Badge>
                              <p className="text-xs text-muted-foreground mt-1">
                                {call.last_intent?.replaceAll("_", " ") ??
                                  "Conversation started"}
                              </p>
                            </TableCell>
                            <TableCell>
                              {call.appointment ? (
                                <span className="font-mono text-xs">
                                  {call.appointment.confirmation_code}
                                </span>
                              ) : (
                                <span className="text-muted-foreground">
                                  No booking
                                </span>
                              )}
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {call.agent_version
                                ? `v${call.agent_version}`
                                : "Legacy"}
                            </TableCell>
                            <TableCell>
                              {r.data!.can_review_recordings ? (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  disabled={call.recording_state !== "eligible"}
                                  onClick={() => setSelected(call)}
                                >
                                  <Headphones className="size-4" />
                                  {recordingLabels[call.recording_state]}
                                </Button>
                              ) : (
                                <span className="text-xs text-muted-foreground">
                                  Admin access only
                                </span>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                        {!r.data.calls.length && (
                          <TableRow>
                            <TableCell
                              colSpan={5}
                              className="py-12 text-center text-muted-foreground"
                            >
                              Calls will appear here when patients use the voice
                              assistant.
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                    <div className="flex items-center justify-between gap-3 pt-5">
                      <p className="text-xs text-muted-foreground">
                        {r.data.total
                          ? `${offset + 1}–${offset + r.data.calls.length} of ${r.data.total} calls`
                          : "No calls yet"}
                      </p>
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!offset}
                          onClick={() => setOffset((o) => o - 25)}
                        >
                          Previous
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={offset + 25 >= r.data.total}
                          onClick={() => setOffset((o) => o + 25)}
                        >
                          Next
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>
              {tab === "access" && r.data.can_review_recordings && (
                <TabsContent value="access">
                  <Card>
                    <CardHeader>
                      <CardTitle>Recent recording requests</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <RecordingAudit />
                    </CardContent>
                  </Card>
                </TabsContent>
              )}
            </Tabs>
            <Dialog
              open={!!selected}
              onOpenChange={(open) => {
                if (!open) setSelected(null);
              }}
            >
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Review call</DialogTitle>
                  <DialogDescription>
                    {selected?.appointment
                      ? `Booking ${selected.appointment.confirmation_code}`
                      : "Call recording and consent details"}
                  </DialogDescription>
                </DialogHeader>
                {selected && (
                  <RecordingReview key={selected.id} call={selected} />
                )}
              </DialogContent>
            </Dialog>
          </>
        )}
      </Resource>
    </div>
  );
}
