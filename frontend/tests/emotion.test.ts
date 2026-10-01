import { describe, expect, it } from "vitest";
import { emotionFromText } from "@/lib/emotion";

describe("character emotion from what the person said", () => {
  it.each([
    ["I fell and my arm is bleeding", "worried"],
    ["I feel so lonely today", "sad"],
    ["thanks, that was great", "happy"],
    ["I love you Nexa", "love"],
    ["wow, really?", "surprised"],
    ["how do I request help?", "thinking"],
    ["book a plumber tomorrow", "neutral"],
  ])("%s -> %s", (text, want) => expect(emotionFromText(text)).toBe(want));

  it("emergencies win over cheerful words and an empty greeting is warm", () => {
    expect(emotionFromText("thanks but I am bleeding")).toBe("worried");
    expect(emotionFromText(undefined)).toBe("happy");
  });
});
