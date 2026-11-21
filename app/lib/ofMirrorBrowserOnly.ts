/**
 * Phase 5's browser-only controls (ticket 110, docs/spec/ofm-not-yet/phase-05-money-account-critical.md; D21: Phase 5
 * is skipped except this): each works in the frame alone and sends nothing, in either scope, and keeps its Not-yet
 * title (D1: no Live proof is planned for them while Phase 5 is skipped).
 * - Change password's three "Reveal password" switches show and hide their field's text (its `type`, password <-> text).
 * - The `support@onlyfans.com` links on DAC7 and Delete account open a mail to that address.
 * - Phone number's Cancel goes back to Account (none while the connected-phone view replaces the form).
 * Every other control on those pages stays as captured (disabled, Not-yet, nothing sent). Mounted by useOfWrites.
 *
 * Not here (D29): the card and wallet hand-offs stay Not-yet: capture-checklist row 10 `settings--handoff-pages`
 * measured 2026-11-21 did not record Add card / Add a payment card / Add funds; parked — needs capture (re-sitting of
 * row 10). Once captured they are entries of ofMirrorHandoffs' HANDOFFS.
 */

export const PASSWORD = "settings/account/password";
export const PHONE = "settings/account/phone";
export const SUPPORT_PAGES = ["bank/dac7/edit", "settings/account/delete"];
export const SUPPORT = "support@onlyfans.com";
export const MAILTO = `mailto:${SUPPORT}`;
export const ACCOUNT = "/of-manager/settings/account";

/** The Reveal password switch's next field type. */
export const revealed = (type: string): "text" | "password" => (type === "password" ? "text" : "password");

const REVEAL = "#content button[aria-label='Reveal password']";
const MARK = "data-oi-browser-only";

/**
 * The browser-only controls of the Mirror page at `path` in `doc` enabled and Wired (`data-oi-browser-only` names each),
 * title kept; `navigate` takes Cancel to Account. Returns an unbind that restores them as captured.
 */
export function bindBrowserOnly(doc: Document, path: string, navigate: (href: string) => void): () => void {
  const buttons: [HTMLButtonElement, string][] = [];
  if (path === PASSWORD) for (const b of doc.querySelectorAll<HTMLButtonElement>(REVEAL)) buttons.push([b, "reveal"]);
  if (path === PHONE) {
    const cancel = [...doc.querySelectorAll<HTMLButtonElement>("#content form button")].find((b) => b.textContent?.trim() === "Cancel");
    if (cancel) buttons.push([cancel, "cancel"]);
  }
  for (const [b, kind] of buttons) {
    b.disabled = false;
    b.setAttribute("data-oi-wired", "");
    b.setAttribute(MARK, kind);
    if (kind === "reveal") b.setAttribute("aria-checked", "false");
  }
  const links = SUPPORT_PAGES.includes(path)
    ? [...doc.querySelectorAll<HTMLAnchorElement>("#content a[href='#']")].filter((a) => a.textContent?.trim() === SUPPORT)
    : [];
  for (const a of links) {
    a.href = MAILTO;
    a.removeAttribute("aria-disabled");
    a.setAttribute("data-oi-wired", "");
  }
  const onClick = (ev: MouseEvent) => {
    const b = (ev.target as Element | null)?.closest?.<HTMLButtonElement>(`button[${MARK}]`);
    if (!b) return;
    ev.preventDefault();
    if (b.getAttribute(MARK) === "cancel") return navigate(ACCOUNT);
    const field = b.closest(".v-input")?.querySelector<HTMLInputElement>("input");
    if (!field) return;
    field.type = revealed(field.type);
    b.setAttribute("aria-checked", String(field.type === "text"));
  };
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("click", onClick);
    for (const [b, kind] of buttons) {
      b.disabled = true;
      b.removeAttribute("data-oi-wired");
      b.removeAttribute(MARK);
      b.removeAttribute("aria-checked");
      const field = kind === "reveal" ? b.closest(".v-input")?.querySelector<HTMLInputElement>("input") : null;
      if (field) field.type = "password";
    }
    for (const a of links) {
      a.setAttribute("href", "#");
      a.setAttribute("aria-disabled", "true");
      a.removeAttribute("data-oi-wired");
    }
  };
}
