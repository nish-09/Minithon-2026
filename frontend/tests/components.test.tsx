import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TrustCardView, scoreTone } from "@/components/TrustCard";
import { Button, EmptyState, ErrorState, Modal, Toggle } from "@/components/ui";
import { fmtCountdown, fmtDistance, fmtEta, timeAgo } from "@/lib/format";
import type { TrustCardData } from "@/lib/types";

const card: TrustCardData = {
  user_id: 7,
  name: "Aarav Mehta",
  avatar_url: null,
  score: 87,
  confidence: 0.9,
  model_version: "heuristic-v1",
  components: [
    { key: "verification", label: "Verification", score: 100, weight: 0.25 },
    { key: "response_reliability", label: "Response Reliability", score: 91, weight: 0.25 },
  ],
  categories: [{ category: "medical_assistance", label: "Medical / First Aid", score: 94 }],
  factors: [
    { key: "identity", label: "Identity verified", impact: "positive", detail: "Identity was reviewed by an administrator." },
    { key: "cancel", label: "High cancellation rate", impact: "negative", detail: "Cancelled 3 of 5 accepted requests." },
  ],
  badges: ["identity_verified", "certified"],
  stats: { response_rate: 92, acceptance_rate: 80, cancellation_rate: 0, no_show_rate: 0, avg_response_seconds: 55, completed: 23, rating: 4.8, review_count: 23 },
  certifications: ["First Aid Certificate"],
  disclaimer: "Trust scores are indicators based on available evidence, not guarantees of someone's behaviour.",
};

describe("TrustCardView", () => {
  it("shows the score, evidence, contextual trust and the explanation", () => {
    render(<TrustCardView data={card} />);
    expect(screen.getByRole("img", { name: /trust score 87 out of 100/i })).toBeInTheDocument();
    expect(screen.getByText("✓ Identity verified")).toBeInTheDocument();
    expect(screen.getByText("✓ First Aid Certificate")).toBeInTheDocument();
    expect(screen.getByText(/23 helps completed/)).toBeInTheDocument();
    expect(screen.getByText(/92% response rate/)).toBeInTheDocument();
    expect(screen.getByText(/4\.8 community rating/)).toBeInTheDocument();
    expect(screen.getByText("Medical / First Aid")).toBeInTheDocument();
    expect(screen.getByText("High cancellation rate.")).toBeInTheDocument(); // negative factors are shown, not hidden
    expect(screen.getByText(/not guarantees of someone's behaviour/)).toBeInTheDocument();
  });

  it("collapses the explanation in compact mode and toggles it", () => {
    render(<TrustCardView data={card} compact />);
    expect(screen.queryByText("Identity verified.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /why this score/i }));
    expect(screen.getByText("Identity verified.")).toBeInTheDocument();
  });

  it("flags limited history and missing data honestly", () => {
    render(<TrustCardView data={{ ...card, confidence: 0.1, stats: { ...card.stats, rating: null, review_count: 0, response_rate: null, completed: 0, avg_response_seconds: null } }} />);
    expect(screen.getByText("Limited history")).toBeInTheDocument();
    expect(screen.getByText(/No reviews yet/)).toBeInTheDocument();
    expect(screen.getByText(/No response data yet/)).toBeInTheDocument();
  });

  it("classifies score tones", () => {
    expect([scoreTone(90), scoreTone(60), scoreTone(20)]).toEqual(["ok", "warn", "danger"]);
  });
});

describe("ui primitives", () => {
  it("Toggle exposes switch semantics and reports changes", () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} label="Share location" />);
    const sw = screen.getByRole("switch", { name: "Share location" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("Button is disabled and busy while loading", () => {
    const onClick = vi.fn();
    render(<Button loading onClick={onClick}>Save</Button>);
    const b = screen.getByRole("button", { name: /save/i });
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("aria-busy", "true");
    fireEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("Modal is an accessible dialog that closes on Escape", () => {
    const onClose = vi.fn();
    render(<Modal open onClose={onClose} title="Cancel this request?"><p>Sure?</p></Modal>);
    expect(screen.getByRole("dialog", { name: "Cancel this request?" })).toHaveAttribute("aria-modal", "true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("Modal renders nothing when closed", () => {
    render(<Modal open={false} onClose={() => {}} title="Hidden">x</Modal>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("ErrorState announces the problem and offers retry", () => {
    const retry = vi.fn();
    render(<ErrorState message="Can't reach NEXA." onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach NEXA.");
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(retry).toHaveBeenCalled();
  });

  it("EmptyState shows guidance and an action", () => {
    render(<EmptyState title="Your circle is empty" body="Add someone." action={<button>Add</button>} />);
    expect(screen.getByText("Your circle is empty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });
});

describe("format helpers", () => {
  it("formats distance, ETA and countdowns", () => {
    expect(fmtDistance(0.7)).toBe("700 m");
    expect(fmtDistance(1.44)).toBe("1.4 km");
    expect(fmtEta(3.9)).toBe("4 min");
    expect(fmtEta(0.2)).toBe("1 min");
    expect(fmtCountdown(300_000)).toBe("5:00");
    expect(fmtCountdown(-5)).toBe("0:00");
  });
  it("formats relative time", () => {
    const now = Date.parse("2026-10-01T12:00:00Z");
    expect(timeAgo("2026-10-01T11:59:40Z", now)).toBe("just now");
    expect(timeAgo("2026-10-01T11:50:00Z", now)).toBe("10 min ago");
    expect(timeAgo("2026-10-01T09:00:00Z", now)).toBe("3 h ago");
  });
});
