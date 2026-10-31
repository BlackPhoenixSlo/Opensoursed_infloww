/**
 * pasteCurl — PasteCurlCard's form and outcome as a pure reducer, plus the checks run before anything is sent and
 * the POST /admin/session/bootstrap body. The card only dispatches and does the I/O.
 *
 * The only client-side curl check is the `curl` prefix: cookies, user-agent and the signed headers are the relay's to
 * parse (it answers with the reason), so a curl missing them is sent as pasted.
 */

/** Select value for "Paste a new proxy…"; never a real label. */
export const PASTE_PROXY = "__paste__";

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
  /** A proxy label, "" for none, or PASTE_PROXY. */
  proxyLabel: string;
  /** The pasted proxy line (PASTE_PROXY only). */
  pastedProxy: string;
  staticOverride: string;
}

export interface PasteCurlState extends PasteCurlForm {
  result: { ok: boolean; text: string } | null;
  /** An account captured but whose attach failed: Retry re-runs the attach step, Continue goes on without it. */
  pending: { accountId: string; label: string } | null;
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
  | { type: "attachErr"; text: string; accountId: string; label: string }
  /** Captured (and attached, or Continue): the curl is cleared. */
  | { type: "submitOk"; text: string };

/** `nickname` / `proxyLabel`: the flow's (the card's props, which default them). */
export function initialPasteCurl({ nickname, proxyLabel }: { nickname: string; proxyLabel: string }): PasteCurlState {
  return { curl: "", nickname, makeActive: true, proxyLabel, pastedProxy: "", staticOverride: "", result: null, pending: null };
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
      return { ...state, result: { ok: true, text: action.text }, pending: { accountId: action.accountId, label: action.label } };
    case "submitOk":
      return { ...state, curl: "", result: { ok: true, text: action.text }, pending: null };
  }
}

/** Why a pasted curl is refused before sending; null = send it. */
export function validateCurl(text: string): string | null {
  return text.trim().startsWith("curl") ? null : "Must start with `curl ...`";
}

/** Why the form is refused before anything is sent (curl first, then the pasted proxy); null = go on. */
export function submitError(form: PasteCurlForm): string | null {
  const curlErr = validateCurl(form.curl);
  if (curlErr) return curlErr;
  if (form.proxyLabel === PASTE_PROXY && !form.pastedProxy.trim()) return "Paste a proxy line or pick another option.";
  return null;
}

/** The Bootstrap button. */
export const canSubmit = (form: PasteCurlForm) => !!form.curl.trim();

/** POST /admin/session/bootstrap's body: the curl as pasted, optional fields trimmed and left out when blank. */
export function buildBootstrapBody(form: PasteCurlForm): BootstrapBody {
  const body: BootstrapBody = { mode: "paste-curl", curl: form.curl, make_active: form.makeActive };
  if (form.nickname.trim()) body.nickname = form.nickname.trim();
  if (form.staticOverride.trim()) body.static_param_override = form.staticOverride.trim();
  return body;
}
