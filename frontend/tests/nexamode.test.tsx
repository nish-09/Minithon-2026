import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NexaMode } from "@/components/NexaMode";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/NexaAvatar", () => ({ NexaAvatar: () => <canvas data-testid="avatar" /> }));
vi.mock("@/lib/hooks", () => ({
  useLocation: () => ({ coords: null, status: "idle", request: vi.fn(), useSample: vi.fn() }),
}));

describe("NexaMode", () => {
  it("renders nothing when closed", () => {
    const { container } = render(<NexaMode open={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is a full-screen idle dialog with voice primary and typing always available", () => {
    render(<NexaMode open onClose={() => {}} />);
    expect(screen.getByRole("dialog", { name: /nexa ai mode/i })).toBeInTheDocument();
    expect(screen.getByText("How can I help?")).toBeInTheDocument();
    expect(screen.getByText("Your neighborhood, when you need it most.")).toBeInTheDocument();
    expect(screen.getByLabelText("Message to NEXA")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /voice input not supported|tap to talk/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mute NEXA's voice" })).toBeInTheDocument();
  });

  it("exits (after the transition) on Escape", () => {
    vi.useFakeTimers();
    const onClose = vi.fn();
    render(<NexaMode open onClose={onClose} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    vi.advanceTimersByTime(400);
    expect(onClose).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });
});
