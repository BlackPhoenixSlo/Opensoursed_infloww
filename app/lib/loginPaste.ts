/**
 * The relay's pasted-logins parser and credential guard (service/login_paste.py), kept in step by one shared
 * table (service/tests/fixtures/login_paste_cases.json, checked by both test suites): one `email<sep>password`
 * per line, the separator `:`, `|`, a tab or a space; the email holds no `,` `;` `/` and its domain has non-empty
 * dot-separated labels; a line over MAX_LINE characters (trimmed) is skipped. The relay's parse is the one that
 * counts; this one gates the paste card's Start (some line to log in) and the Ultra composer (`holdsLogin`: a login
 * never goes to the planner).
 */

export const MAX_LOGINS = 50;
export const MAX_LINE = 512;
/** service/login_paste.LOGINS_PAGE: the app page with the paste card (LoginQueueCard). */
export const LOGINS_PAGE = "/creators/logins";

/** Email, then `:` / `|` (blanks around it) or blanks, then a character: one way to match, so a miss is one pass. */
const SEP = String.raw`(?:[ \t]*[:|][ \t]*|[ \t]+)(?=\S)`;
const EMAIL = String.raw`[^\s:|@,;/]+@[^\s:|@,;/.]+(?:\.[^\s:|@,;/.]+)+`;
/** Matched on a trimmed line. */
const LINE = new RegExp(String.raw`^(${EMAIL})${SEP}`);
/** The guard's line: a looser email than LINE's (`,` `;` `/` and any dots allowed, one dot inside the domain). */
const G_LINE = new RegExp(String.raw`^\s*[^\s:|@]+@[^\s:|@][^\s:|@.]*\.[^\s:|@]+${SEP}`);
/** The guard's email stops at `,` `;` `/` too, so "a@x.com,pw" reads as an email then a separator. */
/** Starts only at a word start, domain labels hold no dot: one way to match, so no slow backtracking. */
const G_EMAIL = String.raw`(?<![^\s:|@,;/])[^\s:|@,;/]+@[^\s:|@,;/.]+(?:\.[^\s:|@,;/.]+)+\.*`;
const INLINE = new RegExp(String.raw`${G_EMAIL}[ \t]*(?:[:|\t][ \t]*\S|[,;/]\S)`);
/** Lookahead: the word after one email may start the next match. */
const SPACED = new RegExp(String.raw`${G_EMAIL}(?:[ \t]*[,;/][ \t]+|[ \t]+)(?=(\S+))`, "g");
const G_EMAIL_ONLY = new RegExp(String.raw`^${G_EMAIL}$`);
const TRAIL = /[.,;:!?)'"]+$/;
/** Python's str.splitlines() boundaries (U+2028/9 built from code points: a literal one ends a JS line). */
const LINES = new RegExp(String.raw`\r\n|[\n\r\v\f\x1c-\x1e\x85` + String.fromCharCode(0x2028, 0x2029) + "]");

const lines = (text: string) => (text || "").split(LINES);

/** How many distinct emails the paste would log in (at most MAX_LOGINS). */
export function loginCount(text: string): number {
  const seen = new Set<string>();
  for (const raw of lines(text)) {
    const line = raw.trim();
    // Code points, as Python's len() counts them.
    const m = Array.from(line).length <= MAX_LINE ? LINE.exec(line) : null;
    if (m) seen.add(m[1].toLowerCase());
  }
  return Math.min(seen.size, MAX_LOGINS);
}

/** 6+ characters once trailing punctuation is trimmed, not an email, holding a digit or a symbol. */
function passwordLike(word: string): boolean {
  const w = word.replace(TRAIL, "");
  return w.length >= 6 && /[^A-Za-z]/.test(w) && !G_EMAIL_ONLY.test(w);
}

/**
 * A line that starts like a login (G_LINE, no length bound), or an email followed by `:` / `|` / a tab and text,
 * by `,` / `;` / `/` and text with no space, or by a space and a password-looking word, anywhere
 * (service/login_paste.holds_login).
 */
export const holdsLogin = (text: string): boolean =>
  lines(text).some(
    (raw) =>
      G_LINE.test(raw) || INLINE.test(raw) || Array.from(raw.matchAll(SPACED)).some((m) => passwordLike(m[1])),
  );
