import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/AppShell";

const mockRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/",
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { id: 1, name: "Elena Rostova", role: "member", avatar_url: null },
    loading: false,
    logout: vi.fn(async () => undefined),
    connectionError: null,
    refresh: vi.fn(async () => undefined),
  }),
}));

vi.mock("@/lib/realtime", () => ({
  useRealtime: () => ({ connected: true }),
  useLiveEvents: () => undefined,
}));

vi.mock("@/lib/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/hooks")>();
  return {
    ...actual,
    useToast: () => ({ push: vi.fn() }),
    useQuery: () => ({ data: null, error: null, reload: vi.fn() }),
    useLocation: () => ({ coords: { lat: 12.97, lng: 77.59 }, status: "ready" as const, request: vi.fn() }),
  };
});

describe("AppShell Sidebar", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders desktop sidebar with fixed sticky positioning so it does not scroll off screen", () => {
    render(<AppShell><div>Content</div></AppShell>);
    const aside = screen.getByRole("complementary", { name: "Primary" });
    expect(aside).toHaveClass("lg:sticky");
    expect(aside).toHaveClass("lg:top-3");
    expect(aside).toHaveClass("lg:self-start");
    expect(aside).toHaveClass("lg:h-[calc(100vh-1.5rem)]");
    expect(screen.getByText("Your neighborhood, when you need it most.")).toBeInTheDocument();
  });

  it("can be collapsed and expanded using the collapse button", () => {
    render(<AppShell><div>Content</div></AppShell>);
    // Initially expanded
    expect(screen.getByText("Your neighborhood, when you need it most.")).toBeInTheDocument();

    // Click collapse button
    const collapseBtn = screen.getAllByRole("button", { name: /collapse sidebar/i })[0];
    fireEvent.click(collapseBtn);

    // Now collapsed: tagline is hidden, expand button is shown
    expect(screen.queryByText("Your neighborhood, when you need it most.")).not.toBeInTheDocument();
    expect(window.localStorage.getItem("nexa_sidebar_collapsed")).toBe("true");

    // Click expand button
    const expandBtn = screen.getAllByRole("button", { name: /expand sidebar/i })[0];
    fireEvent.click(expandBtn);

    // Expanded again
    expect(screen.getByText("Your neighborhood, when you need it most.")).toBeInTheDocument();
    expect(window.localStorage.getItem("nexa_sidebar_collapsed")).toBe("false");
  });

  it("toggles collapse state with Ctrl+B shortcut", () => {
    render(<AppShell><div>Content</div></AppShell>);
    expect(screen.getByText("Your neighborhood, when you need it most.")).toBeInTheDocument();

    // Press Ctrl+B
    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(screen.queryByText("Your neighborhood, when you need it most.")).not.toBeInTheDocument();

    // Press Ctrl+B again
    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(screen.getByText("Your neighborhood, when you need it most.")).toBeInTheDocument();
  });

  it("opens and closes mobile navigation drawer", () => {
    render(<AppShell><div>Content</div></AppShell>);
    // Open mobile menu
    const menuBtn = screen.getByRole("button", { name: /open navigation menu/i });
    fireEvent.click(menuBtn);

    const drawer = screen.getByRole("dialog", { name: /navigation drawer/i });
    expect(drawer).toBeInTheDocument();

    // Close via close button
    const closeBtn = screen.getByRole("button", { name: /close navigation menu/i });
    fireEvent.click(closeBtn);
    expect(screen.queryByRole("dialog", { name: /navigation drawer/i })).not.toBeInTheDocument();
  });
});
