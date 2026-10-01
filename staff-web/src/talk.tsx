import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ConversationAgent,
  BrowserAudioInterface,
  InteractionType,
  AgentState,
} from "sarvam-conv-ai-sdk/browser";
import { Headphones, Mic, MicOff, PhoneOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import "./index.css";

type Config = {
  org_id: string;
  workspace_id: string;
  app_id: string;
  version: number;
  agent_name: string;
  runtime_base_url: string;
  recording_notice: string;
  notice_version: string;
  session_seconds: number;
  website_booking_url: string;
};
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      data.error?.message ?? "The call could not be started. Please try again.",
    );
  return data;
}
function Talk() {
  const [config, setConfig] = useState<Config | null>(null),
    [error, setError] = useState(""),
    [consent, setConsent] = useState(false);
  const [phase, setPhase] = useState<
      "idle" | "connecting" | "live" | "ending" | "ended"
    >("idle"),
    [state, setState] = useState(AgentState.IDLE),
    [muted, setMuted] = useState(false);
  const agent = useRef<ConversationAgent | null>(null),
    audio = useRef<BrowserAudioInterface | null>(null),
    alive = useRef(true),
    busy = useRef(false),
    cancelled = useRef(false),
    finishing = useRef(false);
  const starting = useRef<Promise<void> | null>(null),
    deadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  async function cleanup() {
    if (finishing.current) return;
    finishing.current = true;
    const current = agent.current,
      input = audio.current;
    agent.current = null;
    audio.current = null;
    if (deadline.current) clearTimeout(deadline.current);
    await current?.stop().catch(() => {});
    await input?.stop().catch(() => {});
    await fetch("/api/v1/web/voice/sessions/end", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
    }).catch(() => {});
    busy.current = false;
    finishing.current = false;
    if (alive.current) {
      setPhase("ended");
      setMuted(false);
      setConsent(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    request<Config>("/api/v1/web/voice/config")
      .then((c) => {
        if (alive.current) setConfig(c);
      })
      .catch((e) => {
        if (alive.current) setError(e.message);
      });
    const leaving = () => {
      cancelled.current = true;
      if (busy.current)
        void (starting.current ?? Promise.resolve()).finally(() => cleanup());
    };
    window.addEventListener("pagehide", leaving);
    return () => {
      alive.current = false;
      window.removeEventListener("pagehide", leaving);
      leaving();
    };
  }, []);
  async function end() {
    cancelled.current = true;
    setPhase("ending");
    await starting.current;
    await cleanup();
  }
  function start() {
    if (!config || !consent || busy.current) return;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError(
        "Microphone access needs HTTPS or localhost. Please use website booking or contact reception.",
      );
      return;
    }
    busy.current = true;
    cancelled.current = false;
    setError("");
    setPhase("connecting");
    starting.current = (async () => {
      try {
        const session = await request<{ runtime_session_id: string }>(
          "/api/v1/web/voice/sessions",
          { recording_consent: true, notice_version: config.notice_version },
        );
        if (cancelled.current || !alive.current) {
          await cleanup();
          return;
        }
        const input = new BrowserAudioInterface(16000);
        audio.current = input;
        const current = new ConversationAgent({
          apiKey: "",
          platform: "browser",
          baseUrl: config.runtime_base_url,
          config: {
            org_id: config.org_id,
            workspace_id: config.workspace_id,
            app_id: config.app_id,
            version: config.version,
            user_identifier_type: "custom",
            user_identifier: session.runtime_session_id,
            interaction_type: InteractionType.CALL,
            input_sample_rate: 16000,
            output_sample_rate: 16000,
            agent_variables: {
              runtime_session_id: session.runtime_session_id,
              agent_version: config.version,
              recording_consent: true,
            },
          },
          audioInterface: input,
          stateCallback: (next) => {
            if (alive.current && !cancelled.current) setState(next);
          },
          endCallback: async () => {
            if (!finishing.current) {
              cancelled.current = true;
              await cleanup();
            }
          },
        });
        agent.current = current;
        await current.start();
        if (cancelled.current || !alive.current) {
          await cleanup();
          return;
        }
        if (!(await current.waitForConnect(10)))
          throw new Error("Connection timed out");
        if (cancelled.current || !alive.current) {
          await cleanup();
          return;
        }
        setPhase("live");
        deadline.current = setTimeout(() => {
          void end();
        }, config.session_seconds * 1000);
      } catch (e) {
        if (alive.current && !cancelled.current)
          setError(
            e instanceof Error && !agent.current
              ? e.message
              : "The call could not connect. Check microphone permission and try again, or contact reception.",
          );
        await cleanup();
      }
    })();
  }
  const active =
    phase === "live" || phase === "connecting" || phase === "ending";
  const status =
    phase === "connecting"
      ? "Connecting…"
      : phase === "ending"
        ? "Ending call…"
        : phase === "ended"
          ? "Call ended"
          : phase === "live"
            ? muted
              ? "Microphone muted"
              : state === AgentState.SPEAKING
                ? "Assistant speaking"
                : state === AgentState.ERROR
                  ? "Connection interrupted"
                  : "Listening"
            : "Ready when you are";
  return (
    <main className="min-h-dvh bg-background px-5 py-10 sm:py-20">
      <div className="mx-auto max-w-xl space-y-6">
        <p className="text-sm font-semibold tracking-tight">Avocado Health</p>
        <Card>
          <CardHeader className="gap-3">
            <Headphones className="size-7 text-primary" />
            <CardTitle className="text-3xl tracking-tight">
              Talk to {config?.agent_name ?? "our booking assistant"}
            </CardTitle>
            <CardDescription className="text-base leading-relaxed">
              Find a doctor, check available appointments and make a booking by
              voice.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Calling unavailable</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <div className="rounded-lg border p-5 space-y-3">
              <Badge variant="secondary" role="status" aria-live="polite">
                {status}
              </Badge>
              <p className="text-sm text-muted-foreground">
                Your microphone is used during the call. A booking is confirmed
                only when the assistant gives you a booking reference.
              </p>
            </div>
            {!active && config && (
              <div className="space-y-4">
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {config.recording_notice}
                </p>
                <div className="flex items-start gap-3">
                  <Checkbox
                    id="recording-consent"
                    checked={consent}
                    onCheckedChange={(checked) => setConsent(checked === true)}
                  />
                  <Label
                    htmlFor="recording-consent"
                    className="text-sm leading-relaxed"
                  >
                    I agree to this call being recorded for clinic administrator
                    review.
                  </Label>
                </div>
              </div>
            )}
            {active ? (
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  disabled={phase !== "live"}
                  onClick={() => {
                    if (muted) agent.current?.unmute();
                    else agent.current?.mute();
                    setMuted(!muted);
                  }}
                >
                  {muted ? <MicOff /> : <Mic />}
                  {muted ? "Unmute" : "Mute"}
                </Button>
                <Button
                  variant="destructive"
                  disabled={phase === "ending"}
                  onClick={() => void end()}
                >
                  <PhoneOff />
                  End call
                </Button>
              </div>
            ) : (
              <Button
                className="w-full"
                size="lg"
                disabled={!config || !consent}
                onClick={start}
              >
                <Mic />
                {phase === "ended" ? "Start another call" : "Start call"}
              </Button>
            )}
            <p className="text-xs text-muted-foreground leading-relaxed">
              For a medical emergency, contact emergency services. This
              assistant helps with appointments and does not provide medical
              advice.
            </p>
          </CardContent>
        </Card>
        <Button
          variant="link"
          render={
            <a href={config?.website_booking_url ?? "/schedule-appointment"} />
          }
        >
          Prefer to book on the website?
        </Button>
      </div>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Talk />
  </StrictMode>,
);
