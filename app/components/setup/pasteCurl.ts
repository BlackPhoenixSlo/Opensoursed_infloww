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
  busy: boolean;
  result: { ok: boolean; text: string } | null;
  pending: { accountId: string; bound: boolean } | null;
}

type Field<K extends keyof PasteCurlForm = keyof PasteCurlForm> = K extends K ? { type: "setField"; field: K; value: PasteCurlForm[K] } : never;

export type PasteCurlAction =
  | Field
  | { type: "submitStart" }
  | { type: "retryStart" }
  | { type: "submitErr"; text: string }
  | { type: "attachErr"; text: string; accountId: string; bound: boolean }
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

const header = (name: string) => new RegExp(String.raw`(?:^|\s)(?:-H|--header)\s+\$?['"]?\s*${name}\s*:`, "i");
const flag = (...names: string[]) => new RegExp(String.raw`(?:^|\s)(?:${names.join("|")})(?:\s|=)`);
const HAS_COOKIES = [flag("-b", "--cookie"), header("cookie")];
const HAS_UA = [flag("-A", "--user-agent"), header("user-agent")];

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

export const extensionBusy = (s: PasteCurlState) => s.busy || !!s.pending;

export const canSubmit = (s: Pick<PasteCurlState, "curl" | "busy">) => !s.busy && !validateCurl(s.curl);

export const continueText = (p: NonNullable<PasteCurlState["pending"]>) => p.bound
  ? `Linked account ${p.accountId}; its proxy is attached, but the session was not reloaded`
  : `Linked account ${p.accountId} without a proxy`;

export const curlHint = (curl: string): string | null => (curl.trim() ? validateCurl(curl) : null);

export function buildBootstrapBody(form: PasteCurlForm, nickname = ""): BootstrapBody {
  const body: BootstrapBody = { mode: "paste-curl", curl: form.curl, make_active: true };
  if (nickname.trim()) body.nickname = nickname.trim();
  if (form.staticOverride.trim()) body.static_param_override = form.staticOverride.trim();
  return body;
}
