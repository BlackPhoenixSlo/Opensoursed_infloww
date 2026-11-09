/**
 * AutoUnsendPanel's form as a pure reducer: the rule's on/off and the three message classes (free text, image /
 * video, PPV), each on or off with its hours. The saved rule seeds it once (`hydrate`, ignored after the first);
 * `canSave` and `buildPayload` read it for the Save.
 */

export type AutoClass = "text" | "img" | "price";

export interface ClassSetting { on: boolean; h: number }

export interface AutoUnsendForm {
  enabled: boolean;
  text: ClassSetting;
  img: ClassSetting;
  price: ClassSetting;
  /** The saved rule has seeded the form; later loads leave it alone. */
  hydrated: boolean;
}

export type AutoUnsendAction =
  /** The saved rule landed: its on/off and `payload.policy`. */
  | { type: "hydrate"; isEnabled: boolean; policy: Record<string, number> }
  | { type: "enabled"; on: boolean }
  | { type: "classOn"; cls: AutoClass; on: boolean }
  | { type: "hours"; cls: AutoClass; hours: number };

/** Each class's policy key (the Relay's sweep reads these) and its hours when off in the saved rule. */
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

/** Save guard: an empty policy is never sent. The Relay reads one as the per-chat sweep of outbound DMs
 *  (`not wants_mass`, unsend_messages.py). */
export const canSave = (s: AutoUnsendForm) => s.text.on || s.img.on || s.price.on;

/** The rule's payload: the hours of each class that is on. */
export function buildPayload(s: AutoUnsendForm): { policy: Record<string, number> } {
  const policy: Record<string, number> = {};
  for (const cls of CLASSES) if (s[cls].on) policy[CLASS_KEY[cls].key] = s[cls].h;
  return { policy };
}
