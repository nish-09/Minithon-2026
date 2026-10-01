import { afterEach, describe, expect, it, vi } from "vitest";
import { listen, speak, setSpeechOutputEnabled, speechErrorMessage, speechRecognitionSupported } from "@/lib/speech";

afterEach(() => {
  vi.unstubAllGlobals();
  delete (window as any).SpeechRecognition; // eslint-disable-line @typescript-eslint/no-explicit-any
  setSpeechOutputEnabled(true);
});

describe("speech input", () => {
  it("reports unsupported browsers instead of throwing", () => {
    expect(speechRecognitionSupported()).toBe(false);
    const onError = vi.fn();
    const onEnd = vi.fn();
    const l = listen({ onFinal: vi.fn(), onError, onEnd });
    expect(l).toBeNull();
    expect(onError).toHaveBeenCalledWith("unsupported");
    expect(onEnd).toHaveBeenCalled();
  });

  it("delivers interim and final transcripts", () => {
    const made: any[] = []; // eslint-disable-line @typescript-eslint/no-explicit-any
    (window as any).SpeechRecognition = class { // eslint-disable-line @typescript-eslint/no-explicit-any
      start = vi.fn();
      stop = vi.fn();
      constructor() {
        made.push(this);
      }
    };
    const onFinal = vi.fn();
    const onInterim = vi.fn();
    listen({ onFinal, onInterim, onError: vi.fn(), onEnd: vi.fn() });
    made[0].onresult({ resultIndex: 0, results: [Object.assign([{ transcript: "I need", confidence: 0.5 }], { isFinal: false })] });
    made[0].onresult({ resultIndex: 0, results: [Object.assign([{ transcript: " I need help ", confidence: 0.9 }], { isFinal: true })] });
    expect(onInterim).toHaveBeenCalledWith("I need");
    expect(onFinal).not.toHaveBeenCalled(); // still waiting in case the person keeps talking
    made[0].onend();
    expect(onFinal).toHaveBeenCalledWith("I need help", 0.9);
  });

  it("joins speech across a pause and finishes after a stretch of silence", () => {
    vi.useFakeTimers();
    const made: any[] = []; // eslint-disable-line @typescript-eslint/no-explicit-any
    (window as any).SpeechRecognition = class { // eslint-disable-line @typescript-eslint/no-explicit-any
      start = vi.fn();
      stop = vi.fn();
      constructor() {
        made.push(this);
      }
    };
    const onFinal = vi.fn();
    listen({ onFinal, onError: vi.fn(), onEnd: vi.fn() });
    const say = (i: number, t: string) => made[0].onresult({ resultIndex: i, results: [...Array(i), Object.assign([{ transcript: t, confidence: 1 }], { isFinal: true })] });
    say(0, "my father fell");
    vi.advanceTimersByTime(1500); // a normal pause: must not end the session
    expect(onFinal).not.toHaveBeenCalled();
    say(1, "and he can't move");
    vi.advanceTimersByTime(3000);
    expect(onFinal).toHaveBeenCalledWith("my father fell and he can't move", 1);
    expect(made[0].stop).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("surfaces permission errors from the recogniser", () => {
    const made: any[] = []; // eslint-disable-line @typescript-eslint/no-explicit-any
    (window as any).SpeechRecognition = class { // eslint-disable-line @typescript-eslint/no-explicit-any
      start = vi.fn();
      stop = vi.fn();
      constructor() {
        made.push(this);
      }
    };
    const onError = vi.fn();
    listen({ onFinal: vi.fn(), onError, onEnd: vi.fn() });
    made[0].onerror({ error: "not-allowed" });
    expect(onError).toHaveBeenCalledWith("not-allowed");
  });

  it("maps every error code to a helpful sentence that keeps typing available", () => {
    for (const c of ["not-allowed", "no-speech", "audio-capture", "network", "unsupported", "something-else"]) {
      expect(speechErrorMessage(c)).toMatch(/type|Tap|hear/i);
    }
    expect(speechErrorMessage("aborted")).toBe("");
  });
});

describe("speech output", () => {
  it("calls onEnd immediately when synthesis is unavailable or muted", () => {
    const end = vi.fn();
    speak("hello", { onEnd: end });
    expect(end).toHaveBeenCalledTimes(1);
    vi.stubGlobal("speechSynthesis", { cancel: vi.fn(), speak: vi.fn() });
    setSpeechOutputEnabled(false);
    const end2 = vi.fn();
    speak("hello", { onEnd: end2 });
    expect(end2).toHaveBeenCalledTimes(1);
  });
});
