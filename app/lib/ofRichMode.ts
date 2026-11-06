/**
 * Whether a composer's text box is OF's rich text editor or its plain textarea, and whether the formatting toolbar
 * shows: the "Aa" button's state machine, shared by the chat Composer, the mass message and the post composers.
 * Pure, so each host's reducer folds it in (repo rule: reducers, not setState chains).
 *
 *   • "Aa" shows the toolbar and puts the text in the rich editor. Pressed again, the toolbar hides (OF's "x": the
 *     content is unchanged); with formatting in the text the editor stays (the fan still gets it), else the plain
 *     textarea is back.
 *   • Text loaded from outside (a picked script, a restored draft): formatted, it opens in the rich editor; else the
 *     box stays as the toolbar has it.
 *   • An edit never leaves the rich editor (the box would swap under the caret); only a send or "Aa" off does.
 *   • A send empties the text: the box is back to what the toolbar says.
 *   • Not allowed (a Fansly account: it never gets OF markup): always the plain textarea, no toolbar.
 */

export interface RichMode {
  /** "Aa" on: the formatting toolbar shows. */
  toolbar: boolean;
  /** The text is in the rich editor (else the plain textarea). */
  rich: boolean;
}

export const PLAIN_MODE: RichMode = { toolbar: false, rich: false };

export type RichModeEvent =
  /** "Aa" pressed; `formatted`: the text holds formatting now. */
  | { type: "aa"; formatted: boolean }
  /** Text put in from outside (a script pick, a restore). */
  | { type: "loaded"; formatted: boolean }
  /** The text was edited in the box. */
  | { type: "edited"; formatted: boolean }
  | { type: "sent" };

export function richMode(m: RichMode, e: RichModeEvent, allowed = true): RichMode {
  if (!allowed) return m.toolbar || m.rich ? PLAIN_MODE : m;
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
    case "edited":
      next = { toolbar: m.toolbar, rich: m.rich || e.formatted };
      break;
    case "sent":
      next = { toolbar: m.toolbar, rich: m.toolbar };
      break;
  }
  return next.toolbar === m.toolbar && next.rich === m.rich ? m : next;
}
