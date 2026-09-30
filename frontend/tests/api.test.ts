import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, setToken, setUnauthorizedHandler } from "@/lib/api";

const fail = (p: Promise<unknown>) =>
  p.then(
    () => {
      throw new Error("expected the request to fail");
    },
    (e) => e as ApiError,
  );

function mockFetch(impl: (url: string, init: RequestInit) => Promise<Response> | Response) {
  const f = vi.fn(async (url: string, init: RequestInit) => impl(url, init));
  vi.stubGlobal("fetch", f);
  return f;
}
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
  vi.useRealTimers();
});

describe("api()", () => {
  it("sends JSON and the bearer token", async () => {
    setToken("tok123");
    const f = mockFetch(() => json(200, { ok: true }));
    const r = await api<{ ok: boolean }>("/api/x", { method: "POST", body: { a: 1 } });
    expect(r.ok).toBe(true);
    const [url, init] = f.mock.calls[0];
    expect(url).toMatch(/\/api\/x$/);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok123");
    expect(init.body).toBe('{"a":1}');
  });

  it("turns a network failure into a friendly ApiError(0)", async () => {
    mockFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const e = await fail(api("/api/x"));
    expect(e).toBeInstanceOf(ApiError);
    expect(e.isNetwork).toBe(true);
    expect(e.message).toMatch(/Can't reach NEXA/);
  });

  it("times out slow requests with a clear message", async () => {
    vi.useFakeTimers();
    mockFetch((_u, init) => new Promise((_res, rej) => init.signal!.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")))));
    const p = fail(api("/api/slow"));
    await vi.advanceTimersByTimeAsync(15_100);
    const e = await p;
    expect(e.isNetwork).toBe(true);
    expect(e.message).toMatch(/took too long/);
  });

  it("surfaces field-level validation errors", async () => {
    mockFetch(() => json(422, { detail: "Validation failed", errors: [{ field: "email", message: "value is not a valid email address" }] }));
    const e = await fail(api("/api/auth/register", { method: "POST", body: {} }));
    expect(e.status).toBe(422);
    expect(e.fieldErrors).toEqual([{ field: "email", message: "value is not a valid email address" }]);
    expect(e.message).toContain("email:");
  });

  it("calls the unauthorized handler on 401 only when a token was sent", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(() => json(401, { detail: "Invalid or expired token" }));
    await api("/api/me", { token: null }).catch(() => undefined);
    expect(handler).not.toHaveBeenCalled(); // e.g. a failed login must not log you out of nothing
    setToken("expired");
    await api("/api/me").catch(() => undefined);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("hides server internals on 5xx", async () => {
    mockFetch(() => new Response("<html>stack trace</html>", { status: 500 }));
    const e = await fail(api("/api/x"));
    expect(e.message).toBe("Something went wrong on our side. Please try again.");
  });

  it("handles 204 responses", async () => {
    mockFetch(() => new Response(null, { status: 204 }));
    await expect(api("/api/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("survives blocked localStorage", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => setToken("x")).not.toThrow();
    spy.mockRestore();
  });
});
