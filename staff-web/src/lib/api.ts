export type StaffUser = {
  id: string;
  username: string;
  name: string;
  role: string;
  active: boolean;
};
export type Session = {
  user: StaffUser;
  csrf_token: string;
  environment?: string;
};
let csrf = "";
export function setSession(value: Session | null) {
  csrf = value?.csrf_token ?? "";
}
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const multipart = options.body instanceof FormData;
  const response = await fetch(path, {
    method: options.method ?? "GET",
    credentials: "same-origin",
    redirect: "error",
    headers: {
      ...(options.body && !multipart
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.method && options.method !== "GET"
        ? { "X-CSRF-Token": csrf }
        : {}),
    },
    body: options.body
      ? multipart
        ? (options.body as FormData)
        : JSON.stringify(options.body)
      : undefined,
  });
  if (!response.ok) {
    let message = "Something went wrong. Please try again.";
    try {
      const result = await response.json();
      if (result.error?.code === "MODULE_DISABLED")
        window.dispatchEvent(new Event("staff-modules-changed"));
      message =
        result.error?.message ??
        (Array.isArray(result.detail)
          ? result.detail.map((e: { msg: string }) => e.msg).join(". ")
          : message);
    } catch {
      /* non-JSON proxy errors */
    }
    if (response.status === 401 && !path.endsWith("/login"))
      window.dispatchEvent(new Event("staff-signout"));
    throw new ApiError(message, response.status);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const wa = "/api/v1/admin/whatsapp";
export const assetUrl = (id: string) =>
  `${wa}/assets/${encodeURIComponent(id)}`;
export const money = (paise: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(
    paise / 100,
  );
export const dateTime = (date: string) =>
  new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(new Date(date));
export const localDate = (date = new Date(Date.now() + 3600000)) =>
  new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
export type Branch = {
  id: string;
  name: string;
  area: string;
  is_active: boolean;
  is_virtual?: boolean;
  address: string;
  directions_url: string;
  arrival_instructions: string;
};
export type Department = {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
};
export type Catalogue = { branches: Branch[]; departments: Department[] };
export type Asset = {
  id: string;
  filename: string;
  kind: string;
  mime_type: string;
  size_bytes: number;
};
export type Inventory = {
  departments: (Department & { guide: Asset | null })[];
  doctors: {
    id: string;
    name: string;
    title: string;
    departments: string[];
    photo: Asset | null;
  }[];
};
export type Template = {
  id: string;
  name: string;
  status: string;
  language: string;
  category: string;
  synced_at: string;
  components: {
    type: string;
    text?: string;
    buttons?: { type: string; text: string; url?: string }[];
  }[];
  spec: { parameters: number; header: string | null } | null;
};
export type Campaign = {
  id: string;
  title: string;
  status: string;
  template_id: string;
  parameters: string[];
  asset_id: string | null;
  scheduled_at: string;
  audience: { branch_id?: string; interest?: string };
  rate_paise: number;
  budget_paise: number;
  counts: Record<string, number>;
  engaged: number;
  bookings: number;
  approved_count: number;
  unsubscribes_from_buttons: number;
};
export type Preview = {
  body: string;
  recipients: number;
  estimated_cost_paise: number;
  within_budget: boolean;
  audience_hash: string;
  header_asset_id: string | null;
};
export type Config = {
  outreach_enabled: boolean;
  test_recipients: string[];
  marketing_contacts: number;
  environment: string;
  reception: { hours: string; phone: string; response: string };
};
export type Conversation = {
  sender_id: string;
  case_id: string;
  status: string;
  assigned_to: string | null;
  can_reply: boolean;
  messages: {
    direction: string;
    text: string;
    actor: string | null;
    created_at: string;
  }[];
};
export type Appointment = {
  id: string;
  confirmation_code: string;
  patient_name: string;
  patient_phone: string;
  starts_at: string;
  status: string;
  origin_channel: string;
  doctor: { id: string; name: string };
  branch: { id: string; name: string };
};
export function usable(t: Template) {
  return (
    t.status === "APPROVED" &&
    !!t.spec &&
    Date.now() - new Date(t.synced_at).getTime() < 7200000
  );
}

export async function recordingBlob(path: string): Promise<Blob> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    redirect: "error",
    cache: "no-store",
    headers: { "X-CSRF-Token": csrf },
  });
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("staff-signout"));
    const data = await response.json().catch(() => null);
    throw new ApiError(
      data?.error?.message ?? "The recording could not be opened.",
      response.status,
    );
  }
  return response.blob();
}
