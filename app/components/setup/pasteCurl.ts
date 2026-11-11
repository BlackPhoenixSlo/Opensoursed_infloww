/**
 * pasteCurl — PasteCurlCard's form and outcome as a pure reducer, plus the checks run before anything is sent and
 * the POST /admin/session/bootstrap body. The card only dispatches and does the I/O.
 *
 * Client-side curl checks (instant, before any POST): the `curl` prefix, a bash copy (a Windows cmd copy's `^"` quoting
 * is refused), cookies (`-b`/`--cookie` or a `cookie:` header) and a user-agent (`-A`/`--user-agent` or a `user-agent:`
 * header). The signed headers (sign, time, x-bc, …) stay the relay's to parse: it answers 422 with the reason.
 */

export interface BootstrapBody {
  mode: "paste-curl";
  curl: string;
  nickname?: string;
  make_active: true;
  static_param_override?: string;
}

export interface PasteCurlForm {
  curl: string;
  staticOverride: string;
}

export interface PasteCurlState extends PasteCurlForm {
  /** A capture (and its attach step) or a Retry is running. */
  busy: boolean;
  result: { ok: boolean; text: string } | null;
  /** An account captured but whose attach failed: Retry re-runs the attach step (only the reload once `bound`),
   *  Continue goes on without it. */
  pending: { accountId: string; bound: boolean } | null;
}

type Field<K extends keyof PasteCurlForm = keyof PasteCurlForm> = K extends K ? { type: "setField"; field: K; value: PasteCurlForm[K] } : never;

export type PasteCurlAction =
  | Field
  /** Submit pressed: the last outcome goes. */
  | { type: "submitStart" }
  /** Retry pressed: its buttons go, the error stays readable. */
  | { type: "retryStart" }
  | { type: "submitErr"; text: string }
  /** Captured, but the attach step failed. */
  | { type: "attachErr"; text: string; accountId: string; bound: boolean }
  /** Captured (and attached, or Continue): the curl is cleared. */
  | { type: "submitOk"; text: string };

export function initialPasteCurl(): PasteCurlState {
  return { curl: "", staticOverride: "", busy: false, result: null, pending: null };
}

export function pasteCurlReducer(state: PasteCurlState, action: PasteCurlAction): PasteCurlState {
  switch (action.type) {
    case "setField":
      return { ...state, [action.field]: action.value };
    case "submitStart":
      return { ...state, busy: true, result: null, pending: null };
    case "retryStart":
      return state.pending ? { ...state, busy: true, pending: null } : state;
    case "submitErr":
      return { ...state, busy: false, result: { ok: false, text: action.text }, pending: null };
    case "attachErr":
      return { ...state, busy: false, result: { ok: true, text: action.text }, pending: { accountId: action.accountId, bound: action.bound } };
    case "submitOk":
      return { ...state, busy: false, curl: "", result: { ok: true, text: action.text }, pending: null };
  }
}

const HOW_TO_COPY = "Open the extension, click Copy cURL again and paste the whole copy.";

/** A `-H`/`--header` whose name is `name` (case-insensitive), in any quoting Chrome uses ('…', "…", $'…'). */
const header = (name: string) => new RegExp(String.raw`(?:^|\s)(?:-H|--header)\s+\$?['"]?\s*${name}\s*:`, "i");
/** A flag taking a value (`-b '…'`, `--cookie=…`); case-sensitive like curl's own flags. */
const flag = (...names: string[]) => new RegExp(String.raw`(?:^|\s)(?:${names.join("|")})(?:\s|=)`);
const HAS_COOKIES = [flag("-b", "--cookie"), header("cookie")];
const HAS_UA = [flag("-A", "--user-agent"), header("user-agent")];

/** Why a pasted curl is refused before sending; null = send it. Pure; Chrome's multi-line `\` copy passes. */
export function validateCurl(text: string): string | null {
  const t = text.trim();
  if (!t.startsWith("curl")) return "Must start with `curl ...`";
  if (t.includes('^"')) return `That is a Windows (cmd) copy. ${HOW_TO_COPY}`;
  const missing = [
    !HAS_COOKIES.some((re) => re.test(t)) && "cookies (-b '…')",
    !HAS_UA.some((re) => re.test(t)) && "user-agent (-H 'user-agent: …')",
  ].filter(Boolean);
  return missing.length ? `No ${missing.join(" and no ")} in this curl. ${HOW_TO_COPY}` : null;
}

/** Is the card under way (a capture, its attach, or a Retry running, or an account waiting on Retry / Continue)? The
 *  modal hides Back then. */
export const extensionBusy = (s: PasteCurlState) => s.busy || !!s.pending;

/** The Link account button: off while a capture, its attach or a Retry runs, and while the curl is blank or refused
 *  (its hint shows under the textarea). */
export const canSubmit = (s: Pick<PasteCurlState, "curl" | "busy">) => !s.busy && !validateCurl(s.curl);

/** Continue past a failed attach step: the account goes on as it is, which the line says (its proxy attached, only
 *  the session reload missing; or no proxy attached). */
export const continueText = (p: NonNullable<PasteCurlState["pending"]>) => p.bound
  ? `Linked account ${p.accountId}; its proxy is attached, but the session was not reloaded`
  : `Linked account ${p.accountId} without a proxy`;

/** The hint under the textarea: why the pasted curl would be refused; none while blank. */
export const curlHint = (curl: string): string | null => (curl.trim() ? validateCurl(curl) : null);

/** POST /admin/session/bootstrap's body: the curl as pasted, the flow's `nickname` and the override trimmed and left
 *  out when blank; the new account is always made active. */
export function buildBootstrapBody(form: PasteCurlForm, nickname = ""): BootstrapBody {
  const body: BootstrapBody = { mode: "paste-curl", curl: form.curl, make_active: true };
  if (nickname.trim()) body.nickname = nickname.trim();
  if (form.staticOverride.trim()) body.static_param_override = form.staticOverride.trim();
  return body;
}
