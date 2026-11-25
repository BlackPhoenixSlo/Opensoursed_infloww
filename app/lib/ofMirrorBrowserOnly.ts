export const PASSWORD = "settings/account/password";
export const PHONE = "settings/account/phone";
export const SUPPORT_PAGES = ["bank/dac7/edit", "settings/account/delete"];
export const SUPPORT = "support@onlyfans.com";
export const MAILTO = `mailto:${SUPPORT}`;
export const ACCOUNT = "/of-manager/settings/account";

export const revealed = (type: string): "text" | "password" => (type === "password" ? "text" : "password");

const REVEAL = "#content button[aria-label='Reveal password']";
const MARK = "data-oi-browser-only";

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
