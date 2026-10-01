import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import {
  ArrowRight,
  Check,
  LoaderCircle,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [version, setVersion] = useState(0);
  useEffect(() => {
    if (!path) {
      setLoading(false);
      setData(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setError("");
    api<T>(path)
      .then((value) => {
        if (alive) setData(value);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [path, version]);
  return {
    data,
    error,
    loading,
    refresh: useCallback(() => setVersion((v) => v + 1), []),
  };
}
export function Resource({
  loading,
  error,
  refresh,
  children,
}: {
  loading: boolean;
  error: string;
  refresh: () => void;
  children: ReactNode;
}) {
  if (error)
    return (
      <Notice
        title="We couldn’t load this page"
        text={error}
        action={
          <Button variant="outline" onClick={refresh}>
            <RefreshCw />
            Try again
          </Button>
        }
      />
    );
  if (loading)
    return (
      <div aria-label="Loading workspace" className="space-y-4">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-44 w-full" />
        <Skeleton className="h-44 w-full" />
      </div>
    );
  return children;
}
export function PageTitle({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
export function SectionTitle({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        {description && (
          <p className="text-sm text-muted-foreground mt-1">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}
export function Field({
  label,
  hint,
  id,
  children,
}: {
  label: string;
  hint?: string;
  id: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && (
        <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}
export function Choice({
  label,
  value,
  onChange,
  options,
  hint,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
  hint?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <Field label={label} id={id} hint={hint}>
      <Select
        items={options.map(([value, label]) => ({ value, label }))}
        value={value}
        onValueChange={(v) => onChange(String(v ?? ""))}
        disabled={disabled}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map(([key, text]) => (
            <SelectItem key={key} value={key}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
}
export function StateBadge({ value }: { value: string }) {
  const positive = [
    "confirmed",
    "completed",
    "delivered",
    "read",
    "active",
    "approved",
    "enabled",
  ].includes(value.toLowerCase());
  const warning = ["uncertain", "failed", "no_show"].includes(value);
  return (
    <Badge
      variant="secondary"
      className={
        positive
          ? "bg-emerald-50 text-emerald-800"
          : warning
            ? "bg-amber-50 text-amber-900"
            : "text-muted-foreground"
      }
    >
      {value.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase())}
    </Badge>
  );
}
export function Notice({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <Alert className="notice">
      <TriangleAlert className="size-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        {text}
        {action && <div className="mt-3">{action}</div>}
      </AlertDescription>
    </Alert>
  );
}
export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <Card className="shadow-none">
      <CardContent className="empty">
        <div className="rounded-full bg-muted p-3">
          <Check className="size-5 text-muted-foreground" />
        </div>
        <h3 className="font-semibold">{title}</h3>
        <p className="max-w-md text-sm text-muted-foreground">{description}</p>
        {action}
      </CardContent>
    </Card>
  );
}
export function Action({
  children,
  run,
  success,
  disabled = false,
  variant = "default",
}: {
  children: ReactNode;
  run: () => Promise<unknown>;
  success?: string;
  disabled?: boolean;
  variant?: "default" | "outline" | "ghost" | "destructive";
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant={variant}
      disabled={disabled || busy}
      onClick={async () => {
        setBusy(true);
        try {
          await run();
          if (success) toast.success(success);
        } catch (e) {
          toast.error(e instanceof Error ? e.message : "Please try again.");
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? <LoaderCircle className="animate-spin" /> : null}
      {children}
    </Button>
  );
}
export function TaskLink({
  title,
  description,
  onClick,
}: {
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <Button variant="ghost" className="task-link" onClick={onClick}>
      <span className="min-w-0 text-left">
        <span className="block text-sm font-medium">{title}</span>
        <span className="block text-xs text-muted-foreground mt-1 whitespace-normal">
          {description}
        </span>
      </span>
      <ArrowRight className="ml-auto shrink-0" />
    </Button>
  );
}
