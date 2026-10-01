import { useState } from "react";
import { FlaskConical, RotateCcw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";

export function DemoControls({ canManage }: { canManage: boolean }) {
  const [action, setAction] = useState<"clear" | "reload" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <>
      <Alert className="mb-6">
        <FlaskConical />
        <AlertTitle>Demo clinic · synthetic data</AlertTitle>
        <AlertDescription>
          <div className="flex flex-wrap items-center justify-between gap-3 w-full">
            <p>
              Explore real workflows with sample records. Live calls and
              external messages are disabled. Voice playback uses a sample tone.
            </p>
            {canManage && (
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setAction("reload")}
                >
                  <RotateCcw />
                  Reload demo data
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setAction("clear")}
                >
                  <Trash2 />
                  Clear demo data
                </Button>
              </div>
            )}
          </div>
          {error && (
            <p role="alert" className="text-destructive mt-2">
              {error}
            </p>
          )}
        </AlertDescription>
      </Alert>
      <AlertDialog
        open={!!action}
        onOpenChange={(open) => {
          if (!open && !busy) setAction(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {action === "clear"
                ? "Clear all demo records?"
                : "Reload the demo clinic?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              This removes appointments, patients, conversations, calls,
              recording access logs, campaigns, reports and sample clinic
              content from this isolated demo database. Staff accounts, sign-in
              and module settings are preserved.
              {action === "reload"
                ? " A fresh set of sample records will then be loaded."
                : " Data stays empty until you choose Reload demo data, including after a server restart."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              variant={action === "clear" ? "destructive" : "default"}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await api("/api/v1/staff/demo/" + action, { method: "POST" });
                  window.location.reload();
                } catch (e) {
                  setError((e as Error).message);
                  setAction(null);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy
                ? "Working…"
                : action === "clear"
                  ? "Clear all demo records"
                  : "Reload sample records"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
