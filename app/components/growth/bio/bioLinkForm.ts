/**
 * The bio editor's link dialog: closed or open with a nullable saved `base`, the Creator's edits,
 * the background picked or marked for removal, the "Tracking and Geo Rule" disclosure, the save in flight and its
 * refusal. A pure reducer (BioEditor holds it, BioLinkDialog only dispatches), the API's link rules mirrored
 * (`decide.check_link`) and the body a save sends: the whole link on create, only what changed on edit.
 *
 * `saved` sets the open form's base: a background upload that fails after
 * the create leaves the dialog on the saved link, so a retry patches it and never creates a second one (v2
 * `links.js:109`).
 */
import { isBioMode, isStockIcon, type BioLink, type BioMode, type LinkBody, type StockIcon } from "@/hooks/useBioPages";
import { chars, CODE, CODE_MSG, DESTINATION, DEST_EMPTY_MSG, DEST_MSG, GEO_MSG, GEO_SIZE_MSG, MAX_DESTINATION, MAX_GEO, MAX_TITLE, TITLE_MSG, type FormError } from "@/components/growth/bio/bioRules";
export { CODE_MSG, DEST_EMPTY_MSG, DEST_MSG, GEO_MSG, GEO_SIZE_MSG, TITLE_MSG } from "@/components/growth/bio/bioRules";

/** The fields inside the "Tracking and Geo Rule" disclosure: a refusal naming one opens it. */
const ADVANCED_FIELDS = ["tracking", "default_tracking_code", "geo"];

/** "none" = no icon, "current" = the link's own non-stock icon kept as is, else a stock icon. */
export type IconChoice = "none" | "current" | StockIcon;
export type LinkMode = "" | BioMode;

export interface LinkDraft {
  title: string;
  destination: string;
  icon: IconChoice;
  isAdult: boolean;
  mode: LinkMode;
  tracking: boolean;
  code: string;
  geoText: string;
}

interface LinkFormFields {
  draft: LinkDraft;
  bgFile: File | null;
  bgRemove: boolean;
  advanced: boolean;
  busy: boolean;
  error: FormError | null;
}
export type BioLinkForm = LinkFormFields & ({ open: false } | { open: true; base: BioLink | null });

export type Action =
  | { type: "open_new" }
  | { type: "open_edit"; link: BioLink }
  | { type: "set"; patch: Partial<LinkDraft> }
  | { type: "pick_bg"; file: File | null }
  | { type: "remove_bg"; on: boolean }
  | { type: "toggle_advanced" }
  | { type: "submit" }
  | { type: "saved"; link: BioLink }
  | { type: "failed"; msg: string; fields?: string[] }
  | { type: "close" };

const NEW_DRAFT: LinkDraft = {
  title: "", destination: "https://", icon: "none", isAdult: false, mode: "", tracking: false, code: "", geoText: "",
};

export const INITIAL_LINK: BioLinkForm = {
  open: false, draft: NEW_DRAFT, bgFile: null, bgRemove: false, advanced: false, busy: false, error: null,
};

const asLinkMode = (m: string): LinkMode => isBioMode(m) ? m : "";

export const draftOfLink = (l: BioLink): LinkDraft => ({
  title: l.title,
  destination: l.destination,
  icon: isStockIcon(l.icon_stock) ? l.icon_stock : l.icon ? "current" : "none",
  isAdult: l.is_adult,
  mode: asLinkMode(l.mode),
  tracking: l.tracking,
  code: l.default_tracking_code ?? "",
  geoText: l.geo == null ? "" : JSON.stringify(l.geo, null, 2),
});

/** v2's disclosure rule (`links.js:100`): open when any of its values is set. */
const hasAdvanced = (d: LinkDraft) => d.tracking || d.code !== "" || d.geoText.trim() !== "";

/** The Geo Rule textarea: blank is no rule (null), a JSON object is the rule, anything else is refused. */
export function parseGeo(text: string): { ok: true; value: Record<string, unknown> | null } | { ok: false; msg: string } {
  if (!text.trim()) return { ok: true, value: null };
  let v: unknown;
  try { v = JSON.parse(text); } catch { return { ok: false, msg: GEO_MSG }; }
  if (!v || typeof v !== "object" || Array.isArray(v)) return { ok: false, msg: GEO_MSG };
  if (new TextEncoder().encode(JSON.stringify(v)).length > MAX_GEO) return { ok: false, msg: GEO_SIZE_MSG };
  return { ok: true, value: v as Record<string, unknown> };
}

/** The first refusal the API would answer for this draft, or null. */
export function linkFormError(d: LinkDraft, base: BioLink | null = null): FormError | null {
  const was = base ? draftOfLink(base) : null;
  const changed = (field: keyof LinkDraft) => !was || d[field] !== was[field];
  const title = d.title.trim();
  if (changed("title") && !title) return { msg: TITLE_MSG, fields: ["title"] };
  if (changed("title") && chars(title) > MAX_TITLE) return { msg: `Title: at most ${MAX_TITLE} characters.`, fields: ["title"] };
  const dest = d.destination.trim();
  if (changed("destination") && dest === "https://") return { msg: DEST_EMPTY_MSG, fields: ["destination"] };
  if (changed("destination") && chars(dest) > MAX_DESTINATION) {
    return { msg: `Destination: at most ${MAX_DESTINATION} characters.`, fields: ["destination"] };
  }
  if (changed("destination") && !DESTINATION.test(dest)) return { msg: DEST_MSG, fields: ["destination"] };
  if (changed("code") && !CODE.test(d.code)) return { msg: CODE_MSG, fields: ["default_tracking_code"] };
  if (changed("geoText")) {
    const geo = parseGeo(d.geoText);
    if (!geo.ok) return { msg: geo.msg, fields: ["geo"] };
  }
  return null;
}

/** The icon field a save sends: a stock stem, null to remove, or nothing (keep the current one). */
const iconBody = (icon: IconChoice): { icon?: StockIcon | null } =>
  icon === "current" ? {} : { icon: icon === "none" ? null : icon };

/**
 * The body a save sends: with no `base` (create) the whole link; with one (edit) only the fields that differ from it,
 * or null when nothing does. Call it on a draft `linkFormError` passed.
 */
export function buildLinkPayload(base: BioLink | null, draft: LinkDraft): LinkBody | null {
  const geo = parseGeo(draft.geoText);
  const geoValue = geo.ok ? geo.value : null;
  if (!base) {
    return {
      title: draft.title.trim(), destination: draft.destination.trim(), ...iconBody(draft.icon),
      is_adult: draft.isAdult, mode: draft.mode, tracking: draft.tracking, default_tracking_code: draft.code,
      geo: geoValue,
    };
  }
  const was = draftOfLink(base);
  const out: LinkBody = {};
  if (draft.title !== was.title) out.title = draft.title.trim();
  if (draft.destination !== was.destination) out.destination = draft.destination.trim();
  if (draft.icon !== was.icon) Object.assign(out, iconBody(draft.icon));
  if (draft.isAdult !== was.isAdult) out.is_adult = draft.isAdult;
  if (draft.mode !== was.mode) out.mode = draft.mode;
  if (draft.tracking !== was.tracking) out.tracking = draft.tracking;
  if (draft.code !== was.code) out.default_tracking_code = draft.code;
  if (draft.geoText !== was.geoText) out.geo = geoValue;
  return Object.keys(out).length ? out : null;
}

export const canSubmit = (f: BioLinkForm) => f.open && !f.busy && linkFormError(f.draft, f.base) === null;
export const isDirty = (f: BioLinkForm) => f.open && (
  f.bgFile !== null || f.bgRemove || (f.base ? buildLinkPayload(f.base, f.draft) !== null
    : f.draft.title !== "" || f.draft.destination !== "https://" || f.draft.icon !== "none"
      || f.draft.isAdult || f.draft.mode !== "" || f.draft.tracking || f.draft.code !== "" || f.draft.geoText !== "")
);

const opensAdvanced = (fields: string[]) => fields.some((x) => ADVANCED_FIELDS.includes(x));

export function bioLinkReducer(state: BioLinkForm, action: Action): BioLinkForm {
  switch (action.type) {
    case "open_new":
      return { ...INITIAL_LINK, open: true, base: null };
    case "open_edit": {
      const draft = draftOfLink(action.link);
      return { ...INITIAL_LINK, open: true, base: action.link, draft, advanced: hasAdvanced(draft) };
    }
    case "set":
      return { ...state, draft: { ...state.draft, ...action.patch }, error: null };
    case "pick_bg":
      return { ...state, bgFile: action.file, bgRemove: action.file ? false : state.bgRemove, error: null };
    case "remove_bg":
      return { ...state, bgRemove: action.on, bgFile: action.on ? null : state.bgFile, error: null };
    case "toggle_advanced":
      return { ...state, advanced: !state.advanced };
    case "submit": {
      if (state.busy || !state.open) return state;
      const error = linkFormError(state.draft, state.base);
      if (error) return { ...state, error, advanced: state.advanced || opensAdvanced(error.fields) };
      return { ...state, busy: true, error: null };
    }
    case "saved":
      // The link is saved; a background step may still run (busy stays as the thunk set it).
      return { ...state, open: true, base: action.link, draft: draftOfLink(action.link) };
    case "failed": {
      const fields = action.fields ?? [];
      return { ...state, busy: false, error: { msg: action.msg, fields }, advanced: state.advanced || opensAdvanced(fields) };
    }
    case "close":
      return INITIAL_LINK;
  }
}
