export type AutoClass = "text" | "img" | "price";

export interface ClassSetting { on: boolean; h: number }

export interface AutoUnsendForm {
  enabled: boolean;
  text: ClassSetting;
  img: ClassSetting;
  price: ClassSetting;
  hydrated: boolean;
}

export type AutoUnsendAction =
  | { type: "hydrate"; isEnabled: boolean; policy: Record<string, number> }
  | { type: "enabled"; on: boolean }
  | { type: "classOn"; cls: AutoClass; on: boolean }
  | { type: "hours"; cls: AutoClass; hours: number };

const CLASS_KEY: Record<AutoClass, { key: string; fallback: number }> = {
  text: { key: "mass_text_hours", fallback: 4 },
  img: { key: "mass_media_hours", fallback: 24 },
  price: { key: "mass_price_hours", fallback: 48 },
};
const CLASSES: AutoClass[] = ["text", "img", "price"];

export const initialAutoUnsendForm: AutoUnsendForm = {
  enabled: false,
  text: { on: true, h: CLASS_KEY.text.fallback },
  img: { on: false, h: CLASS_KEY.img.fallback },
  price: { on: false, h: CLASS_KEY.price.fallback },
  hydrated: false,
};

export function autoUnsendReducer(state: AutoUnsendForm, action: AutoUnsendAction): AutoUnsendForm {
  switch (action.type) {
    case "hydrate": {
      if (state.hydrated) return state;
      const next: AutoUnsendForm = { ...state, enabled: action.isEnabled, hydrated: true };
      for (const cls of CLASSES) {
        const h = action.policy[CLASS_KEY[cls].key];
        next[cls] = h != null ? { on: true, h } : { on: false, h: CLASS_KEY[cls].fallback };
      }
      return next;
    }
    case "enabled":
      return { ...state, enabled: action.on };
    case "classOn":
      return { ...state, [action.cls]: { ...state[action.cls], on: action.on } };
    case "hours":
      return { ...state, [action.cls]: { ...state[action.cls], h: Math.max(1, action.hours) } };
  }
}

// An empty policy is never sent: the Relay reads one as the per-chat sweep of outbound DMs.
export const canSave = (s: AutoUnsendForm) => s.text.on || s.img.on || s.price.on;

export type SaveBody =
  | { kind: "create"; is_enabled: boolean; payload: { policy: Record<string, number> } }
  | { kind: "update"; id: number; is_enabled: boolean; payload?: { policy: Record<string, number> } };

export function saveBody(s: AutoUnsendForm, ruleId: number | null): SaveBody | null {
  if (canSave(s)) {
    const payload = buildPayload(s);
    return ruleId == null
      ? { kind: "create", is_enabled: s.enabled, payload }
      : { kind: "update", id: ruleId, is_enabled: s.enabled, payload };
  }
  return ruleId != null && !s.enabled ? { kind: "update", id: ruleId, is_enabled: false } : null;
}

export function buildPayload(s: AutoUnsendForm): { policy: Record<string, number> } {
  const policy: Record<string, number> = {};
  for (const cls of CLASSES) if (s[cls].on) policy[CLASS_KEY[cls].key] = s[cls].h;
  return { policy };
}
