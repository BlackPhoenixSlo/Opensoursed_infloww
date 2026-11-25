import { markNotYet, markWired } from "@/lib/ofMirrorTooltip";

export interface LinkItem {
  id: number | string;
  label?: unknown;
  link?: unknown;
  url?: unknown;
}

export interface LinkList {
  page: string;
  path: string;
  add: string;
  list: string;
  title: string;
  labelled: boolean;
  providers: boolean;
  linkKey: "link" | "url";
  body(label: string, link: string, provider: SocialProvider | null): Record<string, string> | null;
  source: typeof LINK_BODY_INFERRED | typeof LINK_BODY_MEASURED;
}

export const LINK_BODY_INFERRED = "inferred" as const;
export const LINK_BODY_MEASURED = "measured-in-js" as const;

export interface SocialProvider {
  socialMedia: string;
  label: string;
  isLink: boolean;
  isShowAt: boolean;
}

// OF 400s any socialMedia outside this provider list ("SocialMedia contains invalid value").
export function providersOf(init: unknown): SocialProvider[] {
  const list = init && typeof init === "object" ? (init as { socialMediaProviders?: unknown }).socialMediaProviders : null;
  if (!Array.isArray(list)) return [];
  return list
    .filter((p): p is Record<string, unknown> => !!p && typeof p === "object" && typeof p.socialMedia === "string" && p.socialMedia !== "")
    .map((p) => ({ socialMedia: String(p.socialMedia), label: typeof p.label === "string" ? p.label : "", isLink: p.isLink === true, isShowAt: p.isShowAt === true }));
}

const OF_HOST = /^(https?:\/\/)?((?!-)(?!.*--)[a-zA-Z0-9-]{0,62}[a-zA-Z0-9]\.)+[a-zA-Z]{2,63}(\/[^\s]*)?$/;
export const ofUrl = (v: string) => /^https?:\/\//i.test(v) && OF_HOST.test(v);

export function normalLink(text: string): string | null {
  const s = text.trim();
  if (!s || /\s/.test(s)) return null;
  let u: URL;
  try {
    u = new URL(/^[a-z][a-z0-9+.-]*:/i.test(s) ? s : `https://${s}`);
  } catch {
    return null;
  }
  if (u.protocol !== "https:" && u.protocol !== "http:") return null;
  if (!/^[^.]+(\.[^.]+)+$/.test(u.hostname)) return null;
  return u.href;
}

export function socialButtonBody(label: string, value: string, provider: SocialProvider | null): Record<string, string> | null {
  const v = value.trim().replace(/^@/, "");
  const name = label.trim();
  if (!provider || !name || !v || name.length > 255 || v.length > 255 || provider.isLink !== ofUrl(v)) return null;
  return { socialMedia: provider.socialMedia, label: name, link: provider.isLink ? v : "", username: provider.isLink ? "" : v };
}

const LIKED_HOST = /(^|\.)(amazon\.(com|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})|amzn\.to|goodreads\.com|imdb\.com|youtube\.com|youtu\.be|of\.tv)$/i;

export function likedLinkBody(_label: string, link: string): Record<string, string> | null {
  const href = normalLink(link);
  return href && LIKED_HOST.test(new URL(href).hostname) ? { link: href } : null;
}

export const LISTS: Record<string, LinkList> = {
  "social-media": {
    page: "social-media",
    path: "/api/of/v2/users/social/buttons",
    add: ".b-settings__row.g-btn__wrapper > button.g-btn",
    list: ".b-rows-lists.m-socials-list > div",
    title: "Add button",
    labelled: true,
    providers: true,
    linkKey: "link",
    body: socialButtonBody,
    source: LINK_BODY_MEASURED,
  },
  links: {
    page: "links",
    path: "/api/of/v2/users/links",
    add: ".b-settings__things-like__add > button.g-btn",
    list: ".b-things__group-items",
    title: "Create link",
    labelled: false,
    providers: false,
    linkKey: "url",
    body: likedLinkBody,
    source: LINK_BODY_INFERRED,
  },
};

export const listFor = (page: string): LinkList | null => (Object.hasOwn(LISTS, page) ? LISTS[page] : null);

export const canSave = (list: LinkList, label: string, link: string, provider: SocialProvider | null) =>
  list.body(label, link, provider) !== null;

const items = (data: unknown): LinkItem[] =>
  Array.isArray(data) ? data.filter((x): x is LinkItem => !!x && typeof x === "object" && "id" in x) : [];
const text = (v: unknown) => (typeof v === "string" ? v : "");

export function drawLinks(doc: Document, list: LinkList, data: unknown, writable: boolean): void {
  const box = doc.querySelector(list.list);
  if (!box || !Array.isArray(data)) return;
  box.replaceChildren(
    ...items(data).map((item) => {
      const row = doc.createElement("div");
      row.className = "b-rows-lists__item";
      row.setAttribute("data-oi-link-row", String(item.id));
      row.style.cssText = "display:flex;align-items:center;gap:12px;padding:8px 16px;flex:0 0 auto;max-width:100%;";
      const words = doc.createElement("div");
      words.style.cssText = "flex:1;min-width:0;";
      const label = doc.createElement("div");
      label.className = "g-semibold";
      label.textContent = list.labelled ? text(item.label) : text(item[list.linkKey]);
      words.append(label);
      if (list.labelled) {
        const link = doc.createElement("div");
        link.className = "g-text-ellipsis";
        link.style.color = "#8a96a3";
        link.textContent = text(item[list.linkKey]);
        words.append(link);
      }
      const remove = doc.createElement("button");
      remove.type = "button";
      remove.className = "g-btn m-icon m-icon-only m-gray m-sm-size";
      remove.setAttribute("aria-label", "Remove");
      remove.setAttribute("data-oi-link-remove", String(item.id));
      if (writable) markWired(remove, false);
      else markNotYet(remove);
      remove.innerHTML = '<svg class="g-icon" aria-hidden="true"><use href="#icon-close" xlink:href="#icon-close"></use></svg>';
      row.append(words, remove);
      return row;
    }),
  );
}

const field = (id: string, placeholder: string) =>
  `<div class="g-input__wrapper input-text-field m-reset-bottom-gap" style="margin-bottom:12px"><div class="v-input form-control g-input mb-0 theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined v-text-field--placeholder"><div class="v-input__control"><div class="v-input__slot"><fieldset aria-hidden="true"><legend style="width: 0px;"></legend></fieldset><div class="v-text-field__slot"><input id="${id}" autocomplete="off" type="text" data-oi-wired=""></div></div></div></div></div>`.replace(
    "<input ",
    `<input placeholder="${placeholder}" aria-label="${placeholder}" `,
  );

function providerSelect(doc: Document, providers: SocialProvider[]): HTMLElement {
  const wrap = doc.createElement("div");
  wrap.className = "g-input__wrapper m-gap-lg";
  wrap.style.marginBottom = "12px";
  const select = doc.createElement("select");
  select.id = "oi-link-provider";
  select.className = "form-control g-input";
  select.setAttribute("aria-label", "Button");
  select.setAttribute("data-oi-wired", "");
  select.style.cssText = "width:100%;height:48px;padding:0 12px;";
  for (const p of providers) {
    const option = doc.createElement("option");
    option.value = p.socialMedia;
    option.textContent = p.label;
    select.append(option);
  }
  wrap.append(select);
  return wrap;
}

function dialog(doc: Document, list: LinkList, providers: SocialProvider[]): HTMLElement {
  const wrap = doc.createElement("div");
  wrap.setAttribute("data-oi-link-dialog", "");
  wrap.setAttribute("data-oi-wired", "");
  wrap.style.cssText = "position: absolute; z-index: 1040;";
  wrap.innerHTML =
    '<div role="dialog" class="modal fade show" style="display: block;" aria-modal="true"><div class="modal-dialog modal-sm modal-dialog-centered"><div tabindex="-1" class="modal-content">' +
    '<header class="modal-header"><h4 class="modal-title"></h4></header><form><div class="modal-body">' +
    (list.labelled ? field("oi-link-label", "Label") : "") +
    field("oi-link-url", "Link") +
    '</div><div class="modal-footer"><button type="button" class="g-btn m-flat m-btn-gaps m-reset-width" data-oi-link-cancel="" data-oi-wired=""> Cancel </button>' +
    '<button type="submit" disabled="disabled" class="g-btn m-flat m-btn-gaps m-reset-width" data-oi-link-save="" data-oi-wired=""> Save </button></div></form></div></div></div>' +
    '<div class="modal-backdrop show"></div>';
  wrap.querySelector(".modal-title")!.textContent = list.title;
  if (list.providers) {
    wrap.querySelector(".modal-body")!.prepend(providerSelect(doc, providers));
    const at = doc.createElement("div");
    at.className = "v-text-field__prefix";
    at.setAttribute("data-oi-link-at", "");
    at.textContent = "@";
    at.hidden = true;
    wrap.querySelector("#oi-link-url")!.before(at);
  }
  return wrap;
}

export interface LinkHandlers {
  send(w: { method: "PUT" | "DELETE"; path: string; body?: Record<string, unknown> }): Promise<unknown>;
}

export function bindProfileLinks(
  doc: Document,
  page: string,
  handlers: LinkHandlers | null,
  ui: { saved(): void; fail(anchor: Element, text: string): void; selectModel(anchor: Element): void; message(e: unknown): string },
  init: () => unknown,
): () => void {
  const list = listFor(page);
  const add = list ? doc.querySelector<HTMLButtonElement>(list.add) : null;
  if (!list || !add) return () => {};
  markWired(add, true);
  add.setAttribute("aria-expanded", "false");
  let open: HTMLElement | null = null;
  let shown: SocialProvider[] = [];

  const close = () => {
    open?.remove();
    open = null;
    add.setAttribute("aria-expanded", "false");
  };
  const value = (id: string) => open?.querySelector<HTMLInputElement>(`#${id}`)?.value ?? "";
  const provider = () => (list.providers ? (shown.find((p) => p.socialMedia === value("oi-link-provider")) ?? null) : null);
  const pick = (was: SocialProvider | null) => {
    const p = provider();
    const label = open?.querySelector<HTMLInputElement>("#oi-link-label");
    const field = open?.querySelector<HTMLInputElement>("#oi-link-url");
    if (!p || !label || !field) return;
    label.value = p.label;
    if (was && was.isLink !== p.isLink) field.value = "";
    const caption = p.isLink ? "Link" : "Username";
    field.placeholder = caption;
    field.setAttribute("aria-label", caption);
    const at = open?.querySelector<HTMLElement>("[data-oi-link-at]");
    if (at) at.hidden = !p.isShowAt;
  };
  let picked: SocialProvider | null = null;
  const saveButton = () => open?.querySelector<HTMLButtonElement>("[data-oi-link-save]") ?? null;
  const refresh = () => {
    const save = saveButton();
    if (save) save.disabled = !canSave(list, value("oi-link-label"), value("oi-link-url"), provider());
  };
  const save = () => {
    const btn = saveButton();
    const body = list.body(value("oi-link-label"), value("oi-link-url"), provider());
    if (!btn || btn.disabled || !body || !handlers) return;
    btn.disabled = true;
    handlers.send({ method: "PUT", path: list.path, body }).then(
      (reply) => {
        close();
        drawLinks(doc, list, reply, true);
        ui.saved();
      },
      (e) => {
        refresh();
        ui.fail(btn, `Could not save: ${ui.message(e)}`);
      },
    );
  };
  const remove = (btn: HTMLButtonElement) => {
    if (!handlers) return ui.selectModel(btn);
    const id = btn.getAttribute("data-oi-link-remove");
    btn.disabled = true;
    handlers.send({ method: "DELETE", path: `${list.path}/${id}` }).then(
      () => btn.closest("[data-oi-link-row]")?.remove(),
      (e) => {
        btn.disabled = false;
        ui.fail(btn, `Could not remove: ${ui.message(e)}`);
      },
    );
  };

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    const removeBtn = t.closest<HTMLButtonElement>("[data-oi-link-remove]");
    if (t.closest(list.add) === add) {
      ev.preventDefault();
      ev.stopPropagation();
      if (!handlers) return ui.selectModel(add);
      if (open) return;
      shown = list.providers ? providersOf(init()) : [];
      open = dialog(doc, list, shown);
      doc.body.append(open);
      add.setAttribute("aria-expanded", "true");
      pick(null);
      picked = provider();
      open.querySelector<HTMLInputElement>("input")?.focus();
      return;
    }
    if (removeBtn) {
      ev.preventDefault();
      ev.stopPropagation();
      return remove(removeBtn);
    }
    if (!open?.contains(t)) return;
    if (t.closest("[data-oi-link-cancel]") || t.classList.contains("modal") || t.classList.contains("modal-backdrop")) {
      ev.preventDefault();
      return close();
    }
    if (t.closest("[data-oi-link-save]")) {
      ev.preventDefault();
      save();
    }
  };
  const onInput = (ev: Event) => {
    if (!open?.contains(ev.target as Node)) return;
    if ((ev.target as Element).id === "oi-link-provider") {
      pick(picked);
      picked = provider();
    }
    refresh();
  };
  const onSubmit = (ev: Event) => {
    if (!open?.contains(ev.target as Node)) return;
    ev.preventDefault();
    save();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (open && ev.key === "Escape") close();
  };
  doc.addEventListener("click", onClick, true);
  doc.addEventListener("input", onInput);
  doc.addEventListener("submit", onSubmit, true);
  doc.addEventListener("keydown", onKey);
  return () => {
    doc.removeEventListener("click", onClick, true);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("submit", onSubmit, true);
    doc.removeEventListener("keydown", onKey);
    close();
    add.removeAttribute("aria-expanded");
    markNotYet(add);
  };
}
