export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const WS_URL = API_URL.replace(/^http/, "ws");
export const TOKEN_KEY = "nexa_token";
const TIMEOUT_MS = 15000;

export class ApiError extends Error {
  status: number;
  fieldErrors: { field: string; message: string }[];
  constructor(status: number, message: string, fieldErrors: { field: string; message: string }[] = []) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
  get isNetwork() {
    return this.status === 0;
  }
}

export function getToken(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // storage can be blocked (private mode)
  }
}

export function setToken(token: string | null) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session lasts until reload */
  }
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export async function api<T = unknown>(path: string, opts: { method?: Method; body?: unknown; token?: string | null; signal?: AbortSignal; timeoutMs?: number } = {}): Promise<T> {
  const token = opts.token === undefined ? getToken() : opts.token;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? TIMEOUT_MS);
  opts.signal?.addEventListener("abort", () => controller.abort());
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: opts.method ?? "GET",
      headers: {
        ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
    });
  } catch (e) {
    if (opts.signal?.aborted) throw e;
    const timedOut = controller.signal.aborted;
    throw new ApiError(0, timedOut ? "NEXA took too long to respond. Please try again." : "Can't reach NEXA. Check your internet connection and try again.");
  } finally {
    clearTimeout(timer);
  }

  if (res.status === 204) return undefined as T;
  let data: any = null; // eslint-disable-line @typescript-eslint/no-explicit-any
  try {
    data = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    if (res.status === 401 && token && onUnauthorized) onUnauthorized();
    const fieldErrors = Array.isArray(data?.errors) ? data.errors : [];
    const msg =
      fieldErrors.length > 0
        ? fieldErrors.map((e: { field: string; message: string }) => `${e.field}: ${e.message}`).join(". ")
        : typeof data?.detail === "string"
          ? data.detail
          : res.status >= 500
            ? "Something went wrong on our side. Please try again."
            : `Request failed (${res.status})`;
    throw new ApiError(res.status, msg, fieldErrors);
  }
  return data as T;
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong";
}
