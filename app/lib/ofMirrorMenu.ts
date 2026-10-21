"use client";

/**
 * One runtime dropdown for the Mirror's menus no capture holds open: the sort menus (free trial links, tag dialog,
 * ADD LABELS, the vault dialog's folders and media), the format panel's Text Size and Text Color, a tag row's More.
 * It is drawn in OF's own dropdown markup (the captured free trial links Sort menu: `v-menu__content m-dropdown-list`,
 * `m-radio-dropdown-item` rows with OF's radio, `v-divider` between groups; a plain row is a `v-list-item` title), under
 * its anchor, inside the anchor's document. Where it would run past the anchor's dialog or column it is right-aligned to
 * the anchor, as OF's sort menus; radio rows carry OF's radio scoped-style mark (RADIO_SCOPE). A click outside or
 * Escape closes it; a pick closes it and calls `onPick`. Every row is marked data-oi-wired (bindWrites' click fallback leaves it alone). Only one menu is open at a time.
 */

export interface MenuOption {
  value: string;
  label: string;
  /** A row shown in this CSS class (OF's text colour and size rows carry their own class). */
  className?: string;
  /** A plain row's icon (an OF sprite id, `icon-media`), before its text as OF's composer More rows. */
  icon?: string;
  /** A plain row shown disabled with this tooltip (a click on it does nothing and keeps the menu open). */
  disabled?: string;
}

/** A group of radio rows (`value`: the checked one), or plain rows when `radio` is false. */
export interface MenuGroup {
  name: string;
  options: MenuOption[];
  value?: string | null;
  radio?: boolean;
}

const MENU_ID = "oi-menu";
/** OF's radio component's scoped-style attribute (its captured dropdown rows carry it). */
const RADIO_SCOPE = "data-v-af619994";
/** OF's dropdown list's scoped-style attributes (the captured sort menus' `v-list m-dropdown-v-list`). */
const LIST_SCOPE = ["data-v-d2f665f6", "data-v-55f3fe86"];
/** OF's SM width (its breakpoint map: XS 500, SM 768, MD 1004): below it a sort menu is OF's phone dropdown. */
export const SM_QUERY = "(max-width: 767.98px)";
/** OF's sort dropdown's phone class (its scoped CSS lays it out). */
export const MODAL_VIEW = "m-modal-view";
/** Its scoped-style mark, which that CSS needs on the menu. */
const DROPDOWN_SCOPE = "data-v-55f3fe86";

/** The open menu in `doc`, if any. */
export const openMenu = (doc: Document) => doc.getElementById(MENU_ID);

/** Close the open menu (if any). */
export function closeMenu(doc: Document): void {
  const el = openMenu(doc);
  if (!el) return;
  (el as HTMLElement & { _oiClose?: () => void })._oiClose?.();
}

/**
 * Open a menu of `groups` under `anchor` (a second call on the same anchor closes it, as OF's toggle). `onPick(group,
 * value)` runs after the menu closes. Returns the menu element.
 */
export function showMenu(doc: Document, anchor: Element, groups: MenuGroup[], onPick: (group: string, value: string) => void): HTMLElement | null {
  const was = openMenu(doc) as (HTMLElement & { _oiAnchor?: Element }) | null;
  closeMenu(doc);
  if (was?._oiAnchor === anchor) return null;
  const menu = doc.createElement("div") as HTMLElement & { _oiClose?: () => void; _oiAnchor?: Element };
  menu.id = MENU_ID;
  menu.setAttribute("role", "menu");
  menu.setAttribute("data-oi-wired", "");
  menu.className = "v-menu__content theme--light menuable__content__active m-dropdown-list";
  const list = doc.createElement("div");
  list.className = "v-list m-dropdown-v-list v-sheet theme--light shown";
  // A sort menu (radio rows only) takes OF's dropdown list's scoped-style marks, as its captured sort menus: the rows'
  // block layout and paddings, OF's border, radius, shadow and divider colour. Plain-row menus keep their own look.
  const sortMenu = groups.every((g) => g.radio !== false);
  if (sortMenu) for (const a of LIST_SCOPE) list.setAttribute(a, "");
  groups.forEach((g, gi) => {
    if (gi) {
      const hr = doc.createElement("hr");
      hr.setAttribute("role", "separator");
      hr.className = "v-divider theme--light";
      list.append(hr);
    }
    g.options.forEach((o, oi) => {
      const row = doc.createElement("div");
      row.setAttribute("role", "menuitem");
      row.setAttribute("tabindex", "0");
      row.setAttribute("data-oi-wired", "");
      row.dataset.oiGroup = g.name;
      row.dataset.oiValue = o.value;
      if (g.radio === false) {
        row.className = `m-reset-wcag-link-focus m-with-rectangle-hover m-tb-sm v-list-item theme--light${o.disabled ? " v-list-item--disabled" : " v-list-item--link"}${g.value === o.value ? " primary--text v-list-item--active" : ""}`;
        if (o.disabled) {
          row.setAttribute("aria-disabled", "true");
          row.removeAttribute("tabindex");
          row.title = o.disabled;
        }
        if (o.icon) {
          const icon = doc.createElement("div");
          icon.className = "v-list-item__icon m-light-gray-color";
          icon.style.cssText = "margin:0 12px 0 0;align-self:center";
          icon.innerHTML = `<svg class="g-icon" aria-hidden="true"><use href="#${o.icon}" xlink:href="#${o.icon}"></use></svg>`;
          row.append(icon);
        }
        const title = doc.createElement("div");
        title.className = `${o.icon ? "v-list-item__text" : "v-list-item__title"}${o.className ? ` ${o.className}` : ""}`;
        title.textContent = o.label;
        row.append(title);
      } else {
        row.className = "m-reset-wcag-link-focus m-radio-dropdown-item m-with-rectangle-hover m-tb-sm g-radio-container v-list-item v-list-item--link theme--light";
        const box = doc.createElement("span");
        box.className = "b-input-radio__container";
        // OF's radio component's scoped-style mark (app.css `[data-v-af619994]`): its hidden input, the ring with its gap
        // before the text, the blue checked ring; without it the browser's own radio shows, touching the text.
        box.setAttribute(RADIO_SCOPE, "");
        const input = doc.createElement("input");
        input.type = "radio";
        input.className = "b-input-radio";
        input.tabIndex = -1;
        input.name = `oi-menu-${g.name}`;
        input.id = `oi-menu-${g.name}-${oi}`;
        input.value = o.value;
        input.checked = g.value === o.value;
        input.setAttribute("data-oi-wired", "");
        const label = doc.createElement("label");
        label.htmlFor = input.id;
        label.className = `b-input-radio__text m-break-word${o.className ? ` ${o.className}` : ""}`;
        label.textContent = o.label;
        label.setAttribute("data-oi-wired", "");
        const ring = doc.createElement("span");
        ring.className = "b-input-radio__label";
        ring.innerHTML = '<span class="b-input-ripple"></span>';
        for (const el of [input, label, ring]) el.setAttribute(RADIO_SCOPE, "");
        box.append(input, label, ring);
        row.append(box);
      }
      list.append(row);
    });
  });
  menu.append(list);
  const r = anchor.getBoundingClientRect();
  const win = doc.defaultView;
  // A sort menu below OF's SM width: OF's phone dropdown, a full-screen dimmed box with the list in its middle (its scoped
  // CSS lays it out; see ofMirrorPhone); a press on the box outside the list closes it, as OF's.
  const phone = sortMenu && win?.matchMedia?.(SM_QUERY).matches === true;
  if (phone) {
    menu.classList.add(MODAL_VIEW);
    menu.setAttribute(DROPDOWN_SCOPE, "");
    doc.body.append(menu);
  } else {
    const winWidth = win?.innerWidth ?? 1024;
    menu.style.cssText = `position:absolute;top:${r.bottom + (win?.scrollY ?? 0) + 4}px;left:0;min-width:220px;max-width:256px;z-index:1100;display:block`;
    // ...and its content box none of its own (OF's `.v-menu__content.m-dropdown-list[data-v-55f3fe86]`; the list draws it).
    if (sortMenu) menu.style.cssText += ";background:none;border:none;box-shadow:none;border-radius:0";
    doc.body.append(menu);
    // Under the anchor from its left edge; where that would run past the anchor's dialog or page column, OF's right-aligned
    // dropdown instead (its right edge on the anchor's, as OF's sort menus).
    const width = menu.getBoundingClientRect().width || 220;
    const column = anchor.closest(".modal-content") ?? anchor.closest(".g-page__content, .l-wrapper__content, main");
    const edge = column ? column.getBoundingClientRect().right : winWidth;
    const x = r.left + width > edge ? r.right - width : r.left;
    menu.style.left = `${Math.max(8, Math.min(x, winWidth - width - 8)) + (win?.scrollX ?? 0)}px`;
    // As Vuetify's menus: one that would run past the window's foot moves up until it fits (never above the top).
    const height = menu.getBoundingClientRect().height;
    const winHeight = win?.innerHeight ?? 768;
    if (r.bottom + 4 + height > winHeight - 8) menu.style.top = `${Math.max(8, winHeight - 8 - height) + (win?.scrollY ?? 0)}px`;
  }
  // The anchor says its menu is open, as OF's toggles do (a Vuetify select by its own class).
  const expanded = anchor.getAttribute("aria-expanded");
  anchor.setAttribute("aria-expanded", "true");
  const select = anchor.matches(".v-select") && !anchor.classList.contains("v-select--is-menu-active");
  if (select) anchor.classList.add("v-select--is-menu-active");

  const close = () => {
    menu.remove();
    if (expanded === null) anchor.removeAttribute("aria-expanded");
    else anchor.setAttribute("aria-expanded", expanded);
    if (select) anchor.classList.remove("v-select--is-menu-active");
    doc.removeEventListener("click", outside, true);
    doc.removeEventListener("keydown", esc);
  };
  const outside = (ev: MouseEvent) => {
    const t = ev.target as Node | null;
    if (t && !(phone && t === menu) && (menu.contains(t) || anchor.contains(t))) return;
    close();
  };
  const esc = (ev: KeyboardEvent) => {
    if (ev.key === "Escape") close();
  };
  // A press in the menu keeps the editor's selection (Text Size and Text Color format it).
  menu.addEventListener("mousedown", (ev) => ev.preventDefault());
  menu.addEventListener("click", (ev) => {
    const row = (ev.target as Element | null)?.closest?.<HTMLElement>("[data-oi-group]");
    if (!row) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (row.getAttribute("aria-disabled") === "true") return;
    close();
    onPick(row.dataset.oiGroup ?? "", row.dataset.oiValue ?? "");
  });
  menu._oiClose = close;
  menu._oiAnchor = anchor;
  // After this click has finished bubbling: it must not close the menu it opened.
  win?.setTimeout(() => {
    if (menu.isConnected) {
      doc.addEventListener("click", outside, true);
      doc.addEventListener("keydown", esc);
    }
  }, 0);
  return menu;
}

/** OF's Ascending / Descending group (the sort menus' second group). */
export const ORDER_GROUP = (value: string | null | undefined): MenuGroup => ({
  name: "order",
  value: value ?? "desc",
  options: [
    { value: "asc", label: "Ascending" },
    { value: "desc", label: "Descending" },
  ],
});
