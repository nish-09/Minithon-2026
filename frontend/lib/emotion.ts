/* Which feeling NEXA's character shows, chosen from what the person said. Purely expressive: it never changes
   what NEXA does or says, and anything unrecognised stays calm and friendly. */
export type Emotion = "neutral" | "happy" | "love" | "worried" | "sad" | "surprised" | "thinking";

const RULES: [Emotion, RegExp][] = [
  // emergencies and pain first: the character should look concerned, never cheerful
  ["worried", /\b(emergency|bleed\w*|blood|unconscious|unresponsive|collapsed|can'?t breathe|breathing|chest|accident|fell|fall|hurt|injur\w*|pain|burn\w*|faint\w*|dizzy|seizure|choking|help me|sos|urgent|scared|afraid|panic\w*|danger\w*)\b/i],
  ["sad", /\b(sad|lonely|alone|depress\w*|crying|cry|miss (him|her|them)|lost|grief|died|passed away|upset|awful|terrible|worst|tired of|give up|hopeless)\b/i],
  ["love", /\b(love (you|it|this)|you'?re (the best|amazing|awesome|wonderful|so kind)|so sweet|adorable|cute)\b/i],
  ["happy", /\b(thanks?|thank you|great|awesome|amazing|wonderful|perfect|good (morning|evening|news)|yay|nice|glad|happy|hello|hi|hey|welcome|congrat\w*|it worked|resolved|arrived|safe now|i'?m (ok|okay|fine|good))\b/i],
  ["surprised", /\b(wow|really|seriously|no way|whoa|oh my|what\?|unbelievable|suddenly)\b/i],
  ["thinking", /\b(how|why|what|which|can you|could you|explain|where|when|is there|do you know)\b/i],
];

export function emotionFromText(text: string | undefined): Emotion {
  if (!text) return "happy";
  for (const [e, re] of RULES) if (re.test(text)) return e;
  return "neutral";
}
