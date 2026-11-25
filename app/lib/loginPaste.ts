export const MAX_LOGINS = 50;
export const MAX_LINE = 512;
export const LOGINS_PAGE = "/creators/logins";

const SEP = String.raw`(?:[ \t]*[:|][ \t]*|[ \t]+)(?=\S)`;
const EMAIL = String.raw`[^\s:|@,;/]+@[^\s:|@,;/.]+(?:\.[^\s:|@,;/.]+)+`;
// single-way matches (no ambiguous alternation) so a miss is one pass, no slow backtracking
const LINE = new RegExp(String.raw`^(${EMAIL})${SEP}`);
const G_LINE = new RegExp(String.raw`^\s*[^\s:|@]+@[^\s:|@][^\s:|@.]*\.[^\s:|@]+${SEP}`);
const G_EMAIL = String.raw`(?<![^\s:|@,;/])[^\s:|@,;/]+@[^\s:|@,;/.]+(?:\.[^\s:|@,;/.]+)+\.*`;
const INLINE = new RegExp(String.raw`${G_EMAIL}[ \t]*(?:[:|\t][ \t]*\S|[,;/]\S)`);
const SPACED = new RegExp(String.raw`${G_EMAIL}(?:[ \t]*[,;/][ \t]+|[ \t]+)(?=(\S+))`, "g");
const G_EMAIL_ONLY = new RegExp(String.raw`^${G_EMAIL}$`);
const TRAIL = /[.,;:!?)'"]+$/;
// Python str.splitlines() boundaries; U+2028/9 built from code points because a literal one ends a JS line
const LINES = new RegExp(String.raw`\r\n|[\n\r\v\f\x1c-\x1e\x85` + String.fromCharCode(0x2028, 0x2029) + "]");

const lines = (text: string) => (text || "").split(LINES);

export function loginCount(text: string): number {
  const seen = new Set<string>();
  for (const raw of lines(text)) {
    const line = raw.trim();
    const m = Array.from(line).length <= MAX_LINE ? LINE.exec(line) : null;
    if (m) seen.add(m[1].toLowerCase());
  }
  return Math.min(seen.size, MAX_LOGINS);
}

function passwordLike(word: string): boolean {
  const w = word.replace(TRAIL, "");
  return w.length >= 6 && /[^A-Za-z]/.test(w) && !G_EMAIL_ONLY.test(w);
}

export const holdsLogin = (text: string): boolean =>
  lines(text).some(
    (raw) =>
      G_LINE.test(raw) || INLINE.test(raw) || Array.from(raw.matchAll(SPACED)).some((m) => passwordLike(m[1])),
  );
