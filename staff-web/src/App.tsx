import {
  lazy,
  Suspense,
  useEffect,
  useState,
  type ComponentProps,
} from "react";
import {
  CalendarDays,
  Check,
  ChevronRight,
  Clock3,
  HeartPulse,
  LockKeyhole,
  LogOut,
  MessageCircle,
  Globe,
  ChartNoAxesCombined,
  Settings2,
  Stethoscope,
  BookOpen,
  LoaderCircle,
  Headphones,
} from "lucide-react";
import { api, setSession, type Session, type StaffUser } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";

function NavigationButton({
  onClick,
  ...props
}: ComponentProps<typeof SidebarMenuButton>) {
  const { setOpenMobile } = useSidebar();
  return (
    <SidebarMenuButton
      {...props}
      onClick={(event) => {
        setOpenMobile(false);
        onClick?.(event);
      }}
    />
  );
}
const GrowthModule = lazy(() =>
  import("@/modules/growth/GrowthModule").then((m) => ({
    default: m.GrowthModule,
  })),
);
import type { ModuleCatalogue } from "@/modules/growth/ModuleSettings";
import { useResource } from "@/components/workspace";
import { Notice } from "@/components/workspace";
const WhatsAppModule = lazy(() =>
  import("@/modules/whatsapp").then((m) => ({ default: m.WhatsAppModule })),
);
const ClinicModule = lazy(() =>
  import("@/modules/clinic").then((m) => ({ default: m.ClinicModule })),
);
const SettingsModule = lazy(() =>
  import("@/modules/settings").then((m) => ({ default: m.SettingsModule })),
);

const VoiceModule = lazy(() =>
  import("@/modules/voice").then((m) => ({ default: m.VoiceModule })),
);

function route() {
  const parts = location.pathname.split("/").filter(Boolean);
  return { module: parts[1] ?? "whatsapp", page: parts[2] ?? "overview" };
}
const clinicNav = [
  { key: "appointments", name: "Appointments", icon: CalendarDays },
  { key: "doctors", name: "Doctors", icon: Stethoscope },
  { key: "schedules", name: "Schedules", icon: Clock3 },
  { key: "whatsapp", name: "WhatsApp", icon: MessageCircle },
  { key: "voice", name: "Voice", icon: Headphones },
];
function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="brand-icon">
        <HeartPulse className="size-5" />
      </div>
      <div>
        <div className="font-semibold tracking-tight text-[15px]">
          Avocado Health
        </div>
        <div className="text-xs text-muted-foreground mt-0.5">
          Clinic workspace
        </div>
      </div>
    </div>
  );
}
function SignIn({ onLogin }: { onLogin: (s: Session) => void }) {
  const [name, setName] = useState(""),
    [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <div className="login-layout">
      <aside className="login-story">
        <Brand />
        <div>
          <Badge
            variant="secondary"
            className="bg-white/10 text-white border-white/10"
          >
            YOUR CLINIC, CONNECTED
          </Badge>
          <h1>
            A clearer day
            <br />
            for your team.
          </h1>
          <p>
            Appointments, patient conversations and clinic content.
            <br className="hidden lg:block" /> One workspace, one sign-in.
          </p>
          <div className="login-points">
            {[
              "Know which patients need attention",
              "Keep every appointment in one place",
              "Review every message before outreach",
            ].map((s) => (
              <div key={s}>
                <Check className="size-4" />
                {s}
              </div>
            ))}
          </div>
        </div>
        <p className="text-xs opacity-60">Avocado Health · Staff workspace</p>
      </aside>
      <main className="login-form">
        <div className="w-full max-w-[360px]">
          <div className="lg:hidden mb-12">
            <Brand />
          </div>
          <div className="mb-8">
            <div className="login-lock">
              <LockKeyhole className="size-5" />
            </div>
            <h2 className="text-2xl font-semibold tracking-tight mt-5">
              Welcome back
            </h2>
            <p className="text-sm text-muted-foreground mt-2">
              Sign in with your clinic staff account.
            </p>
          </div>
          <form
            className="space-y-5"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                const s = await api<Session>("/api/v1/staff/login", {
                  method: "POST",
                  body: { username: name, password },
                });
                setPassword("");
                onLogin(s);
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                name="username"
                autoComplete="username"
                autoFocus
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your staff username"
                maxLength={64}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                maxLength={256}
              />
            </div>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit" className="w-full h-10" disabled={busy}>
              {busy ? <LoaderCircle className="animate-spin" /> : null}Sign in
              <ChevronRight />
            </Button>
          </form>
          <Separator className="my-7" />
          <p className="text-xs leading-relaxed text-muted-foreground">
            Need an account or a password reset?
            <br />
            Ask your clinic administrator. Your password is never shared with
            the WhatsApp bot.
          </p>
        </div>
      </main>
    </div>
  );
}
export default function App() {
  const [user, setUser] = useState<StaffUser | null>(null),
    [boot, setBoot] = useState(true),
    [current, setCurrent] = useState(route),
    [logoutError, setLogoutError] = useState(""),
    [environment, setEnvironment] = useState("");
  useEffect(() => {
    api<Session>("/api/v1/staff/session")
      .then((s) => {
        setSession(s);
        setUser(s.user);
        setEnvironment(s.environment ?? "");
      })
      .catch(() => {})
      .finally(() => setBoot(false));
    const pop = () => setCurrent(route());
    const clear = () => {
      setSession(null);
      setUser(null);
    };
    window.addEventListener("popstate", pop);
    window.addEventListener("staff-signout", clear);
    return () => {
      window.removeEventListener("popstate", pop);
      window.removeEventListener("staff-signout", clear);
    };
  }, []);
  const modules = useResource<ModuleCatalogue>(
    user ? "/api/v1/staff/modules" : null,
  );
  const refreshModules = modules.refresh;
  useEffect(() => {
    if (!user) return;
    const refresh = () => refreshModules();
    window.addEventListener("focus", refresh);
    window.addEventListener("staff-modules-changed", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("staff-modules-changed", refresh);
    };
  }, [user, refreshModules]);
  const go = (module: string, page = "overview") => {
    history.pushState({}, "", `/staff/${module}/${page}`);
    setCurrent({ module, page });
    window.scrollTo({ top: 0 });
  };
  if (boot)
    return (
      <div className="min-h-screen flex items-center justify-center text-muted-foreground">
        <LoaderCircle className="animate-spin size-5" />
        <span className="ml-3 text-sm">Opening workspace…</span>
      </div>
    );
  if (!user)
    return (
      <TooltipProvider>
        <SignIn
          onLogin={(s) => {
            setSession(s);
            setUser(s.user);
            setEnvironment(s.environment ?? "");
          }}
        />
        <Toaster theme="light" />
      </TooltipProvider>
    );
  const available = (key: string) =>
    modules.data?.modules.some((m) => m.key === key && m.accessible) ?? false;
  const navigation = clinicNav.filter(
    (n) =>
      user.role !== "growth_manager" &&
      (!["whatsapp", "voice"].includes(n.key) || available(n.key)),
  );
  const growthNavigation = [
    { key: "google_business", name: "Google Business", icon: Globe },
    {
      key: "growth_analytics",
      name: "Growth analytics",
      icon: ChartNoAxesCombined,
    },
  ].filter((n) => available(n.key));
  const moduleAllowed =
    !["whatsapp", "voice", "google_business", "growth_analytics"].includes(
      current.module,
    ) || available(current.module);
  const title =
    [...clinicNav, ...growthNavigation].find((n) => n.key === current.module)
      ?.name ??
    (current.module === "settings" ? "Workspace settings" : "Workspace");
  return (
    <TooltipProvider>
      <SidebarProvider>
        <Sidebar collapsible="offcanvas">
          <SidebarHeader className="px-5 py-7">
            <Brand />
          </SidebarHeader>
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupLabel className="tracking-wider text-[10px] font-semibold">
                CLINIC OPERATIONS
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {navigation.map((n) => (
                    <SidebarMenuItem key={n.key}>
                      <NavigationButton
                        isActive={current.module === n.key}
                        onClick={() => go(n.key)}
                      >
                        <n.icon />
                        <span>{n.name}</span>
                      </NavigationButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
            {growthNavigation.length > 0 && (
              <SidebarGroup>
                <SidebarGroupLabel className="tracking-wider text-[10px] font-semibold">
                  PATIENT GROWTH
                </SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {growthNavigation.map((n) => (
                      <SidebarMenuItem key={n.key}>
                        <NavigationButton
                          isActive={current.module === n.key}
                          onClick={() => go(n.key)}
                        >
                          <n.icon />
                          <span>{n.name}</span>
                        </NavigationButton>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            )}
            <SidebarGroup className="mt-auto">
              <SidebarGroupLabel className="tracking-wider text-[10px]">
                WORKSPACE
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  <SidebarMenuItem>
                    <NavigationButton
                      isActive={current.module === "settings"}
                      onClick={() => go("settings")}
                    >
                      <Settings2 />
                      Settings
                    </NavigationButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <NavigationButton onClick={() => go("settings", "design")}>
                      <BookOpen />
                      Design & UX guide
                    </NavigationButton>
                  </SidebarMenuItem>
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter className="border-t p-4">
            <div className="flex items-center gap-3">
              <div className="size-9 rounded-full bg-emerald-100 text-emerald-900 flex items-center justify-center font-semibold text-xs">
                {user.name
                  .split(" ")
                  .map((n) => n[0])
                  .slice(0, 2)
                  .join("")}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium truncate">{user.name}</p>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  {user.role === "admin"
                    ? "Clinic administrator"
                    : user.role === "growth_manager"
                      ? "Growth manager"
                      : "Staff member"}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Sign out"
                onClick={async () => {
                  try {
                    await api("/api/v1/staff/logout", { method: "POST" });
                    setSession(null);
                    setUser(null);
                  } catch (e) {
                    setLogoutError((e as Error).message);
                  }
                }}
              >
                <LogOut className="size-4" />
              </Button>
            </div>
          </SidebarFooter>
        </Sidebar>
        <SidebarInset>
          <header className="workspace-header">
            <div className="flex items-center gap-3">
              <SidebarTrigger />
              <Separator orientation="vertical" className="h-4" />
              <span className="text-muted-foreground text-xs hidden sm:inline">
                Clinic workspace
              </span>
              <ChevronRight className="size-3 text-muted-foreground hidden sm:inline" />
              <span className="text-xs font-medium">{title}</span>
            </div>
            <Badge variant="outline" className="font-normal">
              {environment && environment !== "production"
                ? "Development workspace"
                : "Staff workspace"}
            </Badge>
          </header>
          <section className="workspace-content" id="main-content">
            {logoutError && (
              <Notice title="Sign-out failed" text={logoutError} />
            )}{" "}
            <Suspense
              fallback={
                <p className="text-sm text-muted-foreground">
                  Loading workspace…
                </p>
              }
            >
              {modules.loading && !modules.data ? (
                <div className="text-sm text-muted-foreground">
                  Loading clinic modules…
                </div>
              ) : modules.error ? (
                <Notice
                  title="Module settings couldn’t load"
                  text={modules.error}
                  action={
                    <Button variant="outline" onClick={modules.refresh}>
                      Try again
                    </Button>
                  }
                />
              ) : !moduleAllowed ? (
                <Notice
                  title="This module is unavailable"
                  text="It is disabled for your clinic or your account does not have access. Saved data is retained."
                  action={
                    <Button
                      variant="outline"
                      onClick={() => go("settings", "modules")}
                    >
                      View module settings
                    </Button>
                  }
                />
              ) : ["google_business", "growth_analytics"].includes(
                  current.module,
                ) ? (
                <GrowthModule
                  key={current.module}
                  api={api}
                  user={user}
                  page={current.page}
                  onNavigate={(p) => go(current.module, p)}
                  module={
                    current.module as "google_business" | "growth_analytics"
                  }
                />
              ) : current.module === "voice" ? (
                <VoiceModule />
              ) : current.module === "whatsapp" ? (
                <WhatsAppModule
                  user={user}
                  page={current.page}
                  onNavigate={(p) => go("whatsapp", p)}
                  onAppointments={() => go("appointments")}
                />
              ) : current.module === "settings" ? (
                <SettingsModule
                  user={user}
                  page={current.page}
                  onModulesChanged={modules.refresh}
                />
              ) : ["appointments", "doctors", "schedules"].includes(
                  current.module,
                ) && user.role !== "growth_manager" ? (
                <ClinicModule module={current.module} user={user} />
              ) : (
                <Card>
                  <CardContent className="p-6">
                    Page not found.{" "}
                    <Button variant="link" onClick={() => go("whatsapp")}>
                      Open WhatsApp
                    </Button>
                  </CardContent>
                </Card>
              )}
            </Suspense>
          </section>
          <footer className="workspace-footer">
            Avocado Health
            <span>All visit times shown in India Standard Time</span>
          </footer>
        </SidebarInset>
      </SidebarProvider>
      <Toaster theme="light" richColors />
    </TooltipProvider>
  );
}
