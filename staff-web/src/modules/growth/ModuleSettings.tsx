import { useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { GrowthApi } from "./GrowthModule";
export type ModuleRecord = {
  key: string;
  name: string;
  description: string;
  enabled: boolean;
  accessible: boolean;
};
export type ModuleCatalogue = {
  can_manage: boolean;
  scope: string;
  modules: ModuleRecord[];
};
export function ModuleSettings({
  api,
  onChanged,
}: {
  api: GrowthApi;
  onChanged: () => void;
}) {
  const [data, setData] = useState<ModuleCatalogue | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(""),
    [notice, setNotice] = useState(""),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    let live = true;
    api<ModuleCatalogue>("/api/v1/staff/modules")
      .then((d) => {
        if (live) {
          setData(d);
          setError("");
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [api, revision]);
  async function toggle(item: ModuleRecord, enabled: boolean) {
    setBusy(item.key);
    setError("");
    setNotice("");
    try {
      await api("/api/v1/staff/modules/" + item.key, {
        method: "PUT",
        body: { enabled },
      });
      setData((d) =>
        d
          ? {
              ...d,
              modules: d.modules.map((m) =>
                m.key === item.key ? { ...m, enabled } : m,
              ),
            }
          : d,
      );
      setNotice(
        `${item.name} ${enabled ? "enabled" : "disabled"}. Saved data is retained.`,
      );
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to update module.");
    } finally {
      setBusy("");
    }
  }
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-muted-foreground">Clinic configuration</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Modules</h1>
        <p className="mt-2 text-muted-foreground">
          Choose the optional tools your clinic uses. Staff permissions still
          apply.
        </p>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Module settings could not be updated</AlertTitle>
          <AlertDescription>
            {error}
            <Button variant="outline" onClick={() => setRevision((v) => v + 1)}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {notice && (
        <Alert role="status">
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Core clinic workspace</CardTitle>
          <CardDescription>
            Appointments, doctors and schedules remain available as the core
            workspace.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Badge variant="secondary">Included</Badge>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Optional modules</CardTitle>
          <CardDescription>
            Disabling a module blocks access through its APIs. It does not
            delete saved data or grant staff new permissions.
          </CardDescription>
        </CardHeader>
        <CardContent className="divide-y">
          {data?.modules.map((item) => (
            <div
              className="flex items-center justify-between gap-6 py-5 first:pt-0"
              key={item.key}
            >
              <div className="space-y-1">
                <Label
                  htmlFor={"module-" + item.key}
                  className="text-base font-medium"
                >
                  {item.name}
                </Label>
                <p className="text-sm text-muted-foreground">
                  {item.description}
                </p>
              </div>
              <Switch
                id={"module-" + item.key}
                checked={item.enabled}
                disabled={!data.can_manage || !!busy}
                onCheckedChange={(v) => toggle(item, v)}
                aria-label={"Enable " + item.name}
              />
            </div>
          ))}
          {!data && !error && (
            <p className="text-sm text-muted-foreground">Loading modules…</p>
          )}
        </CardContent>
      </Card>
      {data && !data.can_manage && (
        <p className="text-sm text-muted-foreground">
          Only your clinic administrator can enable or disable modules.
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        These settings apply to this clinic deployment. This backend does not
        yet isolate multiple clients within one shared database.
      </p>
    </div>
  );
}
