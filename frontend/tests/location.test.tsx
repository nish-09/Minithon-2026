import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SAMPLE_LOCATION, ToastProvider, useLocation } from "@/lib/hooks";

const refresh = vi.fn(async () => undefined);
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: null, refresh }) }));

const wrapper = ({ children }: { children: ReactNode }) => <ToastProvider>{children}</ToastProvider>;

function mockGeolocation(impl: ((ok: PositionCallback, err: PositionErrorCallback) => void) | null) {
  Object.defineProperty(navigator, "geolocation", { configurable: true, value: impl ? { getCurrentPosition: impl } : undefined });
}
function mockFetchOk() {
  const f = vi.fn(async () => new Response(JSON.stringify({ lat: 1, lng: 2 }), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", f);
  return f;
}

beforeEach(() => {
  window.localStorage.setItem("nexa_token", "t");
  refresh.mockClear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  mockGeolocation(null);
});

describe("useLocation", () => {
  it("reports 'unavailable' when the browser has no geolocation", () => {
    mockGeolocation(null);
    const { result } = renderHook(() => useLocation(), { wrapper });
    act(() => result.current.request());
    expect(result.current.status).toBe("unavailable");
    expect(result.current.coords).toBeNull();
  });

  it("reports 'denied' (not a crash) when permission is refused", () => {
    mockGeolocation((_ok, err) => err({ code: 1, PERMISSION_DENIED: 1 } as GeolocationPositionError));
    const { result } = renderHook(() => useLocation(), { wrapper });
    act(() => result.current.request());
    expect(result.current.status).toBe("denied");
    expect(result.current.coords).toBeNull();
  });

  it("distinguishes other failures (timeout / position unavailable)", () => {
    mockGeolocation((_ok, err) => err({ code: 3, PERMISSION_DENIED: 1 } as GeolocationPositionError));
    const { result } = renderHook(() => useLocation(), { wrapper });
    act(() => result.current.request());
    expect(result.current.status).toBe("error");
  });

  it("stores a granted position on the profile via the API", async () => {
    const f = mockFetchOk();
    mockGeolocation((ok) => ok({ coords: { latitude: 12.9, longitude: 77.6 } } as GeolocationPosition));
    const { result } = renderHook(() => useLocation(), { wrapper });
    act(() => result.current.request());
    await waitFor(() => expect(result.current.coords).toEqual({ lat: 12.9, lng: 77.6 }));
    expect(result.current.status).toBe("granted");
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/users\/me\/location$/);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ lat: 12.9, lng: 77.6 });
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("offers a sample location for desktops without GPS", async () => {
    mockFetchOk();
    const { result } = renderHook(() => useLocation(), { wrapper });
    await act(async () => {
      await result.current.useSample();
    });
    expect(result.current.coords).toEqual({ lat: SAMPLE_LOCATION.lat, lng: SAMPLE_LOCATION.lng });
  });

  it("keeps the local position even if saving to the server fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Location sharing is turned off" }), { status: 403 })));
    const { result } = renderHook(() => useLocation(), { wrapper });
    await act(async () => {
      await result.current.setManual(1, 2);
    });
    expect(result.current.coords).toEqual({ lat: 1, lng: 2 });
    expect(refresh).not.toHaveBeenCalled();
  });
});
