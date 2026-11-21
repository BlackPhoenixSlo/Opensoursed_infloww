/**
 * Settings > Social media's buttons (ofm-not-yet ticket 69, capture record settings--social-media-buttons, measured in
 * OF's JS): the page lists the model's buttons (GET /users/social/buttons); Add button opens a form whose Save sends
 * PUT /users/social/buttons `{socialMedia, label, link, username}` (OF answers the full list), and a button's remove
 * sends DELETE /users/social/buttons/{id}. The form is OF's (67786.js ModalSocialButtonsAdd): a Button select of
 * GET /init's `socialMediaProviders` (`{socialMedia, label, isLink, isShowAt}`, 22 measured live 2026-11-21; the
 * settings `init` source), Label (prefilled with the picked provider's name), then a Link field (`isLink`) or a
 * Username field ("@" shown for `isShowAt`); socialButtonBody builds OF's body (LINK_BODY_MEASURED). OF refuses any
 * other `socialMedia` (measured live 2026-11-21: 400 "SocialMedia contains invalid value"). One config per list
 * (LISTS), so another profile list reuses the form, the rows and the binder. Both lists' add passed its Live proof (D1)
 * and drops the Not-yet title; a row's remove keeps it.
 *
 * Settings > Things I Like (ticket 70, capture record settings--things-i-like-links, measured in OF's JS): GET /users/links
 * lists `{id, sort, url, title, description, image}` (measured live 2026-11-21: the link is `url`, no `link` key; `title`
 * and `description` are OF's scrape of the linked page); Create link's Save sends PUT /users/links `{link}` (OF answers
 * the full list); a link's delete sends DELETE /users/links/{id}. Its form asks the link alone.
 *
 * `inferred`: OF's form markup is not captured (its field captions are i18n keys: the Mirror says "Button", "Label",
 * "Link" / "Username"; a native select stands in for OF's VSelect; OF's per-network label-unique and username-unique
 * checks are left to OF). The filled list's markup is not captured (the captured page has none): each row shows its
 * label and link as text (never a live link out of the Mirror) and OF's close icon as its remove button. Things I Like: OF's form takes Amazon, Goodreads, IMDB,
 * YouTube and OFTV links only (its page says so; the record's whitelist is client-side) — the hosts likedLinkBody accepts
 * are inferred from those names (OFTV as of.tv).
 */

import { markNotYet, markWired } from "@/lib/ofMirrorTooltip";

export interface LinkItem {
  id: number | string;
  label?: unknown;
  link?: unknown;
  /** Things I Like's link (OF's GET /users/links has `url`, no `link`). */
  url?: unknown;
}

/** A profile list: its settings page (under settings/), Relay route, controls and Save body. */
export interface LinkList {
  page: string;
  path: string;
  /** The page's add button (OF's, enabled and Wired here). */
  add: string;
  /** The captured empty list the rows go in. */
  list: string;
  title: string;
  /** The form asks a label too. */
  labelled: boolean;
  /** The form picks one of init's social media providers first (Social media's Button select). */
  providers: boolean;
  /** The listed item's key holding its link: Social media's `link`, Things I Like's `url`. */
  linkKey: "link" | "url";
  /** Save's body for the typed label and link (and the picked provider), or null when Save stays off. */
  body(label: string, link: string, provider: SocialProvider | null): Record<string, string> | null;
  /** The body builder's D29 tag (LINK_BODY_INFERRED / LINK_BODY_MEASURED), as ofMirrorOffers' CLAIMS_TO_LIST `source`. */
  source: typeof LINK_BODY_INFERRED | typeof LINK_BODY_MEASURED;
}

/** Marks a body builder whose keys are measured but whose derived values are not (D29: one builder, tagged). */
export const LINK_BODY_INFERRED = "inferred" as const;
/** Marks a body builder whose keys and values are both read from OF's JS. */
export const LINK_BODY_MEASURED = "measured-in-js" as const;

/** One of OF's social networks: GET /init's `socialMediaProviders` item (measured live 2026-11-21). */
export interface SocialProvider {
  socialMedia: string;
  label: string;
  /** The button takes a link (Amazon, Etsy, BeReal, VSCO today), else a username. */
  isLink: boolean;
  /** The username field shows an "@" prefix. */
  isShowAt: boolean;
}

/** init's providers in OF's order (items without a `socialMedia` name dropped); [] while init is unread. */
export function providersOf(init: unknown): SocialProvider[] {
  const list = init && typeof init === "object" ? (init as { socialMediaProviders?: unknown }).socialMediaProviders : null;
  if (!Array.isArray(list)) return [];
  return list
    .filter((p): p is Record<string, unknown> => !!p && typeof p === "object" && typeof p.socialMedia === "string" && p.socialMedia !== "")
    .map((p) => ({ socialMedia: String(p.socialMedia), label: typeof p.label === "string" ? p.label : "", isLink: p.isLink === true, isShowAt: p.isShowAt === true }));
}

/** OF's URL test (67786.js module 648075 `bK`): an http(s) scheme and a dotted host of letters, digits and dashes. */
const OF_HOST = /^(https?:\/\/)?((?!-)(?!.*--)[a-zA-Z0-9-]{0,62}[a-zA-Z0-9]\.)+[a-zA-Z]{2,63}(\/[^\s]*)?$/;
export const ofUrl = (v: string) => /^https?:\/\//i.test(v) && OF_HOST.test(v);

/** The typed link as OF would store it: `https://` added when no scheme is typed; http(s) only, a dotted host; else null. */
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

/**
 * Social media's Save body, OF's form submit (67786.js, measured-in-js): `{socialMedia, label, link, username}`, the one
 * field typed (trimmed, a leading "@" dropped) in `link` for an `isLink` provider and in `username` otherwise, the other
 * key "". Null (Save off) with no provider, a blank label, an empty field, more than 255 characters, a link OF's URL test
 * refuses, or a username that passes it (OF: "must be a URL" / "should not be a link").
 */
export function socialButtonBody(label: string, value: string, provider: SocialProvider | null): Record<string, string> | null {
  const v = value.trim().replace(/^@/, "");
  const name = label.trim();
  if (!provider || !name || !v || name.length > 255 || v.length > 255 || provider.isLink !== ofUrl(v)) return null;
  return { socialMedia: provider.socialMedia, label: name, link: provider.isLink ? v : "", username: provider.isLink ? "" : v };
}

/** Things I Like's sites (`inferred` hosts, see the header): a host is one of these or a subdomain of one. */
const LIKED_HOST = /(^|\.)(amazon\.(com|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})|amzn\.to|goodreads\.com|imdb\.com|youtube\.com|youtu\.be|of\.tv)$/i;

/**
 * Things I Like's Save body (`inferred`, LINK_BODY_INFERRED: the record's one key is measured, the site check is not):
 * `{link}` normalized, or null (Save off) unless the link's host is one of OF's named sites. The label is unused.
 */
export function likedLinkBody(_label: string, link: string): Record<string, string> | null {
  const href = normalLink(link);
  return href && LIKED_HOST.test(new URL(href).hostname) ? { link: href } : null;
}

export const LISTS: Record<string, LinkList> = {
  // ticket 69
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
    source: LINK_BODY_MEASURED, // Live proof passed 2026-11-21, undone (docs/of-manager/captures/settings--social-media-buttons.json)
  },
  // ticket 70
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
    source: LINK_BODY_INFERRED, // Live proof passed 2026-11-21, undone (docs/of-manager/captures/settings--things-i-like-links.json)
  },
};

/** The list on settings `page` (no State page suffix), or null. */
export const listFor = (page: string): LinkList | null => (Object.hasOwn(LISTS, page) ? LISTS[page] : null);

/** Save's state: on only with a body to send. */
export const canSave = (list: LinkList, label: string, link: string, provider: SocialProvider | null) =>
  list.body(label, link, provider) !== null;

const items = (data: unknown): LinkItem[] =>
  Array.isArray(data) ? data.filter((x): x is LinkItem => !!x && typeof x === "object" && "id" in x) : [];
const text = (v: unknown) => (typeof v === "string" ? v : "");

/** Draw `data` (the list read, or a write's full-list reply) into `list`'s rows; not an array: nothing changes. Idempotent.
 *  `writable` false (OFM_NEW_WRITES_ENABLED off): each row's remove is Not yet. */
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
      label.textContent = list.labelled ? text(item.label) : text(item[list.linkKey]); // a list without labels shows its link
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

/** OF's Button select (a native select for its VSelect): one option per provider, OF's order, its name as text. */
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

/** The form: OF's modal dialog (Collections' dialog markup), the Button select and a Label field when the list asks
 *  them, Link (or Username), Cancel and Save. */
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

/**
 * Wire the profile list of settings `page` in `doc` (nothing on another page): the add button enabled and Wired
 * (aria-expanded while its form is open), each row's remove Wired. `handlers` null (no single model): a click sends
 * nothing and gets `ui.selectModel`. A Save draws the reply's list and gets `ui.saved`; a failure keeps the form open
 * with `ui.fail` (the list as it was). A remove takes out only its row once OF answers. Returns an unbind.
 * `init()`: the settings `init` source (GET /init), read when the form opens, for a list that picks a provider: the
 * form opens on OF's first provider, its name in Label; picking another puts its name in Label (OF's onSocialChange),
 * and empties the field when it switches between Link and Username (OF keeps `link` and `username` apart).
 */
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
  markWired(add, true); // its Live pass (D1); bound only with OFM_NEW_WRITES_ENABLED on
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
  /** The picked provider's name into Label, the field's caption and "@" its kind's; a Link/Username switch empties it. */
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
      ev.stopPropagation(); // Wired: never the click fallback's
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
    // Inside the form: Cancel or its backdrop closes it, Save sends.
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
