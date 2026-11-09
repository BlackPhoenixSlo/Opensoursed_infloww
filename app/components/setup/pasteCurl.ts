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
  make_active?: boolean;
  static_param_override?: string;
}

export interface PasteCurlForm {
  curl: string;
  nickname: string;
  makeActive: boolean;
  staticOverride: string;
}

export interface PasteCurlState extends PasteCurlForm {
  result: { ok: boolean; text: string } | null;
  /** An account captured but whose attach failed: Retry re-runs the attach step, Continue goes on without it. */
  pending: { accountId: string } | null;
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
  | { type: "attachErr"; text: string; accountId: string }
  /** Captured (and attached, or Continue): the curl is cleared. */
  | { type: "submitOk"; text: string };

/** `nickname`: the flow's (the card's prop, which defaults it). */
export function initialPasteCurl({ nickname }: { nickname: string }): PasteCurlState {
  return { curl: "", nickname, makeActive: true, staticOverride: "", result: null, pending: null };
}

export function pasteCurlReducer(state: PasteCurlState, action: PasteCurlAction): PasteCurlState {
  switch (action.type) {
    case "setField":
      return { ...state, [action.field]: action.value };
    case "submitStart":
      return { ...state, result: null, pending: null };
    case "retryStart":
      return state.pending ? { ...state, pending: null } : state;
    case "submitErr":
      return { ...state, result: { ok: false, text: action.text }, pending: null };
    case "attachErr":
      return { ...state, result: { ok: true, text: action.text }, pending: { accountId: action.accountId } };
    case "submitOk":
      return { ...state, curl: "", result: { ok: true, text: action.text }, pending: null };
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

/** Why the form is refused before anything is sent; null = go on. */
export const submitError = (form: PasteCurlForm): string | null => validateCurl(form.curl);

/** The Bootstrap button: off while the curl is blank or refused (its hint shows under the textarea). */
export const canSubmit = (form: PasteCurlForm) => !validateCurl(form.curl);

/** The hint under the textarea: why the pasted curl would be refused; none while blank. */
export const curlHint = (curl: string): string | null => (curl.trim() ? validateCurl(curl) : null);

/** POST /admin/session/bootstrap's body: the curl as pasted, optional fields trimmed and left out when blank. */
export function buildBootstrapBody(form: PasteCurlForm): BootstrapBody {
  const body: BootstrapBody = { mode: "paste-curl", curl: form.curl, make_active: form.makeActive };
  if (form.nickname.trim()) body.nickname = form.nickname.trim();
  if (form.staticOverride.trim()) body.static_param_override = form.staticOverride.trim();
  return body;
}
