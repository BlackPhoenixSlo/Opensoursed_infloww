export interface RichMode {
  toolbar: boolean;
  rich: boolean;
}

export const PLAIN_MODE: RichMode = { toolbar: false, rich: false };

export type RichModeEvent =
  | { type: "aa"; formatted: boolean }
  | { type: "loaded"; formatted: boolean; allowed: boolean }
  | { type: "edited"; formatted: boolean }
  | { type: "sent" };

export function richMode(m: RichMode, e: RichModeEvent): RichMode {
  // A Fansly account never gets OF markup.
  if (e.type === "loaded" && !e.allowed) return m.toolbar || m.rich ? PLAIN_MODE : m;
  let next: RichMode;
  switch (e.type) {
    case "aa": {
      const toolbar = !m.toolbar;
      next = { toolbar, rich: toolbar || e.formatted };
      break;
    }
    case "loaded":
      next = { toolbar: m.toolbar, rich: m.toolbar || e.formatted };
      break;
    case "edited": // an edit never leaves the rich editor: the box would swap under the caret
      next = { toolbar: m.toolbar, rich: m.rich || e.formatted };
      break;
    case "sent":
      next = { toolbar: m.toolbar, rich: m.toolbar };
      break;
  }
  return next.toolbar === m.toolbar && next.rich === m.rich ? m : next;
}
