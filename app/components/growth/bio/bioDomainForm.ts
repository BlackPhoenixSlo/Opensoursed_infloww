/**
 * The editor's custom domain (ofl.ink v2's Domain screen, ~/oflinkv2/app/editor/screens/domain.js): the domain being
 * typed, the one write in flight (save / check / remove), its refusal, the last check's problems ("Not yet: …") and the
 * line said after a removal. A pure reducer (BioDomainSection only dispatches); the API's sentences mirrored
 * (`bio_pages/admin.py` set_domain, minus this box's own hosts, which only the API knows) so a typo shows before the
 * round trip.
 */
export type DomainOp = "save" | "check" | "remove";

export interface BioDomainForm {
  draft: string;
  busy: DomainOp | null;
  error: string | null;
  /** The last check's problems (null: no check yet, or it passed). */
  problems: string[] | null;
  /** Said after a removal: "<domain> is removed." */
  said: string | null;
}

export type Action =
  | { type: "set"; draft: string }
  | { type: "submit"; username: string }
  | { type: "start"; op: Exclude<DomainOp, "save"> }
  | { type: "saved" }
  | { type: "checked"; problems: string[] }
  | { type: "removed"; domain: string }
  | { type: "failed"; msg: string };

export const INITIAL_DOMAIN: BioDomainForm = { draft: "", busy: null, error: null, problems: null, said: null };

export const DOMAIN_EMPTY_MSG = "Enter a domain.";
// decide.HOSTNAME
const HOSTNAME = /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$/;
const OURS = ["ofl.ink", "inflowwww.com"];

/** v2's exampleOf: the username as a .com (underscores are not allowed in a hostname). */
export const exampleOf = (username: string) => `${username.replace(/_/g, "") || "yourname"}.com`;

/** v2's form: trimmed and lower-cased (domains.normalize). */
export const normalizeDomain = (raw: string) => raw.trim().toLowerCase();

export function domainError(raw: string, username: string): string | null {
  const d = normalizeDomain(raw);
  if (!d) return DOMAIN_EMPTY_MSG;
  if (d.length > 253 || !HOSTNAME.test(d)) {
    return `Enter the domain alone, like ${exampleOf(username)}: no https://, no slash, no spaces.`;
  }
  if (OURS.some((h) => d === h || d.endsWith(`.${h}`))) return `${d} is one of ofl.ink's own addresses. Use a domain you own.`;
  return null;
}

export const canSave = (f: BioDomainForm, username: string) => f.busy === null && domainError(f.draft, username) === null;
export const buildDomainPayload = (f: BioDomainForm) => ({ domain: normalizeDomain(f.draft) });

/** v2's check line: "Not yet: <problems>" (null when there is nothing to say). */
export const notYet = (f: BioDomainForm) => (f.problems?.length ? `Not yet: ${f.problems.join(" ")}` : null);

export const STATUS_LABEL: Record<string, string> = {
  pending: "Waiting for DNS", pending_cert: "Getting certificate", live: "Live",
};
export const statusLabel = (status: string) => STATUS_LABEL[status] ?? status;

export function bioDomainReducer(state: BioDomainForm, action: Action): BioDomainForm {
  switch (action.type) {
    case "set":
      return { ...state, draft: action.draft, error: null, said: null };
    case "submit": {
      if (state.busy) return state;
      const error = domainError(state.draft, action.username);
      return error ? { ...state, error, said: null } : { ...state, busy: "save", error: null, said: null };
    }
    case "start":
      return state.busy ? state : { ...state, busy: action.op, error: null, said: null };
    case "saved":
      return { ...INITIAL_DOMAIN };
    case "checked":
      return { ...state, busy: null, problems: action.problems };
    case "removed":
      return { ...INITIAL_DOMAIN, said: `${action.domain} is removed.` };
    case "failed":
      return { ...state, busy: null, error: action.msg };
  }
}
