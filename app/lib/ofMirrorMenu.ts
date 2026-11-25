"use client";


import { OF_INSIGHTS_ATTR, OF_INSIGHTS_PX } from "@/lib/ofMirrorChrome";

export interface MenuOption {
  value: string;
  label: string;
  className?: string;
  icon?: string;
  disabled?: string;
}

export interface MenuGroup {
  name: string;
  options: MenuOption[];
  value?: string | null;
  radio?: boolean;
}

const MENU_ID = "oi-menu";
const RADIO_SCOPE = "data-v-af619994";
const LIST_SCOPE = ["data-v-d2f665f6", "data-v-55f3fe86"];
export const SM_QUERY = "(max-width: 767.98px)";
export const MODAL_VIEW = "m-modal-view";
const DROPDOWN_SCOPE = "data-v-55f3fe86";

export const openMenu = (doc: Document) => doc.getElementById(MENU_ID);

export function closeMenu(doc: Document): void {
  const el = openMenu(doc);
  if (!el) return;
  (el as HTMLElement & { _oiClose?: () => void })._oiClose?.();
}

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
  const phone = sortMenu && win?.matchMedia?.(SM_QUERY).matches === true;
  if (phone) {
    menu.classList.add(MODAL_VIEW);
    menu.setAttribute(DROPDOWN_SCOPE, "");
    doc.body.append(menu);
  } else {
    const winWidth = (win?.innerWidth ?? 1024) - (doc.documentElement.hasAttribute(OF_INSIGHTS_ATTR) ? OF_INSIGHTS_PX : 0);
    menu.style.cssText = `position:absolute;top:${r.bottom + (win?.scrollY ?? 0) + 4}px;left:0;min-width:220px;max-width:256px;z-index:1100;display:block`;
    if (sortMenu) menu.style.cssText += ";background:none;border:none;box-shadow:none;border-radius:0";
    doc.body.append(menu);
    const width = menu.getBoundingClientRect().width || 220;
    const column = anchor.closest(".modal-content") ?? anchor.closest(".g-page__content, .l-wrapper__content, main");
    const edge = Math.min(column ? column.getBoundingClientRect().right : winWidth, winWidth);
    const x = r.left + width > edge ? r.right - width : r.left;
    menu.style.left = `${Math.max(8, Math.min(x, winWidth - width - 8)) + (win?.scrollX ?? 0)}px`;
    const height = menu.getBoundingClientRect().height;
    const winHeight = win?.innerHeight ?? 768;
    if (r.bottom + 4 + height > winHeight - 8) menu.style.top = `${Math.max(8, winHeight - 8 - height) + (win?.scrollY ?? 0)}px`;
  }
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

export const ORDER_GROUP = (value: string | null | undefined): MenuGroup => ({
  name: "order",
  value: value ?? "desc",
  options: [
    { value: "asc", label: "Ascending" },
    { value: "desc", label: "Descending" },
  ],
});
