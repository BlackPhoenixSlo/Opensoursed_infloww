/**
 * Edit profile's About format button (ofm-not-yet ticket 68, capture record settings--profile-about-format,
 * measured-in-js): the Bio's "Aa" opens OF's text editor toolbar over the Bio (TextEditorToolbar, its PROFILE_BIO
 * instance); its tools are New post's (ofMirrorPost bindFormatPanel), so the Bio holds OF's markup. The button and its
 * tools send nothing; Save's PATCH /users/me carries the Bio as `about`: OF's markup (tiptap getHTML: strong, em and the
 * m-editor-fs__* / m-editor-fc__* spans) while it holds formatting, else its plain text as before (`profileAbout`).
 * The toolbar's markup is New post's Format text capture (the chat composer's copy, scripts/of-mirror.mjs
 * formatToolbar), scoped-style attributes dropped (app.css styles it); its icons are that capture's sprite symbols the
 * Edit profile capture lacks. Where OF draws the bio's toolbar is not captured: here it opens above the Bio (inferred).
 * Not sent: OF's POST /users/me/validate-data while typing (the record's read; Save goes without it). The button's
 * Not-yet title dropped on its Live-proof pass (D1, 2026-11-21, the capture record above).
 */
import { markNotYet, markWired } from "@/lib/ofMirrorTooltip";
import { hasFormatting } from "@/lib/ofMirrorFormat";
import { bindFormatPanel } from "@/lib/ofMirrorPost";
import { editorValue } from "@/lib/ofRichTextEditor";

const BIO = "[data-placeholder='Bio']";
/** The Bio's format button: the icon-text button under the Bio editor. */
export const ABOUT_FORMAT = ".b-input-contenteditable .b-icon-text-container > button";
const PANEL = "[data-oi-about-format]";

/** New post's Format text toolbar (OF's TextEditorToolbar), as captured. */
const TOOLBAR = "<div class=\"js-text-editor-toolbar d-flex align-items-center justify-content-start g-sides-l-gap g-separate-border pt-1 pb-1 pr-1\"><div class=\"v-input form-control multiselect__tags m-with-icon-prepend m-sm-height mr-1 m-reset-active-border v-input--hide-details v-input--is-label-active v-input--is-dirty theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined v-select\" data-original-title=\"null\" aria-label=\"Text Size\"><div class=\"v-input__control\"><div role=\"button\" aria-haspopup=\"listbox\" aria-expanded=\"false\" aria-owns=\"oi-about-size-list\" class=\"v-input__slot\"><fieldset aria-hidden=\"true\"><legend style=\"width: 0px;\"><span class=\"notranslate\">\u200b</span></legend></fieldset><div class=\"v-select__slot\"><div class=\"v-select__selections\"><div class=\"v-select__selection v-select__selection--comma\">Default</div><input at-attr=\"dropdown\" autocomplete=\"\" id=\"oi-about-size\" readonly=\"readonly\" type=\"text\" aria-readonly=\"false\"></div><div class=\"v-input__append-inner\"><div class=\"v-input__icon v-input__icon--append\"><i aria-hidden=\"true\" class=\"v-icon notranslate mdi mdi-menu-down theme--light\"></i></div></div><input type=\"hidden\" name=\"\" value=\"m-editor-fs__default\"></div><div class=\"v-menu\"></div></div></div></div><button type=\"button\" class=\"m-icon m-icon-only m-gray m-sm-size g-btn m-with-round-hover m-gaps-around-btn icon-bold has-tooltip\" data-original-title=\"null\" aria-label=\"Bold\"><svg data-icon-name=\"icon-bold\" aria-hidden=\"true\" class=\"g-icon\"><use href=\"#icon-bold\" xlink:href=\"#icon-bold\"></use></svg></button><button type=\"button\" class=\"m-icon m-icon-only m-gray m-sm-size g-btn m-with-round-hover m-gaps-around-btn icon-italic has-tooltip\" data-original-title=\"null\" aria-label=\"Italic\"><svg data-icon-name=\"icon-italic\" aria-hidden=\"true\" class=\"g-icon\"><use href=\"#icon-italic\" xlink:href=\"#icon-italic\"></use></svg></button><div tabindex=\"-1\" class=\"b-dropdown-wrapper m-dropdown-v2\"><button type=\"button\" aria-label=\"Text Color\" role=\"button\" aria-haspopup=\"true\" aria-expanded=\"false\" class=\"btn dropdown-toggle m-text-colour m-with-hover-highlight has-tooltip\" data-original-title=\"null\"><svg data-icon-name=\"icon-text-colour\" aria-hidden=\"true\" class=\"g-icon\"><use href=\"#icon-text-colour\" xlink:href=\"#icon-text-colour\"></use></svg><div class=\"b-text-colour m-editor-fc__default\"></div></button><div class=\"v-menu\"><!----></div></div><div class=\"b-form-editor__vline\"></div><button type=\"button\" class=\"m-icon m-icon-only m-gray m-sm-size g-btn m-with-round-hover m-gaps-around-btn icon-clear-format has-tooltip\" data-original-title=\"null\" aria-label=\"Clear Formatting\"><svg data-icon-name=\"icon-clear-format\" aria-hidden=\"true\" class=\"g-icon\"><use href=\"#icon-clear-format\" xlink:href=\"#icon-clear-format\"></use></svg></button><button type=\"button\" class=\"m-rounded m-reset-width m-btn-remove m-secondary m-sm-icon-size m-colored-btn m-mr-8 m-clickable-area ml-auto g-btn m-with-round-hover m-gaps-around-btn icon-close has-tooltip\" data-original-title=\"null\" aria-label=\"Close Formatting Panel\"><svg data-icon-name=\"icon-close\" aria-hidden=\"true\" class=\"g-icon\"><use href=\"#icon-close\" xlink:href=\"#icon-close\"></use></svg></button></div>";
/** Its icons (OF's sprite symbols) Edit profile's sprite lacks. */
const SYMBOLS = "<symbol id=\"icon-bold\" viewBox=\"0 0 24 24\"><path d=\"M15.4,11.6c1-0.9,1.6-2.2,1.6-3.6c0-2.8-2.2-5-5-5H8C7.4,3,7,3.4,7,4v8v8c0,0.6,0.4,1,1,1h5c2.8,0,5-2.2,5-5C18,14.1,16.9,12.5,15.4,11.6z M9,5h3c1.7,0,3,1.3,3,3s-1.3,3-3,3H9V5z M13,19H9v-6h4c1.7,0,3,1.3,3,3S14.7,19,13,19z\"></path></symbol><symbol id=\"icon-italic\" viewBox=\"0 0 24 24\"><path d=\"M18.5,3H8C7.4,3,7,3.4,7,4s0.4,1,1,1h4.7L9.2,19H5.5c-0.6,0-1,0.4-1,1s0.4,1,1,1H16c0.6,0,1-0.4,1-1s-0.4-1-1-1h-4.7l3.5-14h3.7c0.6,0,1-0.4,1-1S19.1,3,18.5,3z\"></path></symbol><symbol id=\"icon-text-colour\" viewBox=\"0 0 24 24\"><path d=\"M17.9,14.6l-5-12C12.8,2.2,12.4,2,12,2s-0.8,0.2-0.9,0.6l-5,12c-0.2,0.5,0,1.1,0.5,1.3s1.1,0,1.3-0.5L9.3,12h5.3l1.4,3.4c0.2,0.4,0.5,0.6,0.9,0.6c0.1,0,0.3,0,0.4-0.1C17.9,15.7,18.1,15.1,17.9,14.6z M10.2,10L12,5.6l1.8,4.4H10.2z\"></path></symbol><symbol id=\"icon-clear-format\" viewBox=\"0 0 24 24\"><path d=\"M11.2,13.2l1.6-1.5L8.9,2.6C8.8,2.2,8.4,2,8,2S7.2,2.2,7.1,2.6l-5,12c-0.2,0.5,0,1.1,0.5,1.3c0.5,0.2,1.1,0,1.3-0.5L5.3,12\n        h5.3L11.2,13.2z M6.2,10L8,5.6L9.8,10H6.2z M21,20l-3.3,0l3.5-3.5c0.8-0.8,0.8-2,0-2.8l-2.5-2.5c-0.7-0.7-2.1-0.7-2.8,0l-5,5\n        c-0.8,0.8-1,1.7-0.3,2.5l2.8,2.8c0.4,0.4,0.9,0.6,1.4,0.6c0,0,0,0,0,0c0,0,0,0,0,0h6c0.5,0,1-0.4,1-1S21.5,20,21,20z M17.4,12.5\n        l2.5,2.6l-2.8,2.8l-2.6-2.6L17.4,12.5z M12.4,17.5l0.7-0.7l2.6,2.6L15,20c0,0,0,0,0,0L12.4,17.5z\"></path></symbol>";

/** The Bio as Save sends it: OF's markup while it holds formatting (the record's tiptap getHTML), else its plain text,
 *  one line per paragraph (as before ticket 68). */
export function profileAbout(editor: Element): string {
  if (hasFormatting(editor)) {
    // A plain bio shows its lines as newlines in one text node (ofMirrorIdentity bioOf, white-space: break-spaces); in
    // OF's markup a newline is only a space, so each goes out as a <br>.
    const copy = editor.cloneNode(true) as Element;
    const doc = editor.ownerDocument;
    const walker = doc.createTreeWalker(copy, 4 /* NodeFilter.SHOW_TEXT */);
    const broken: Text[] = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) if (n.nodeValue?.includes("\n")) broken.push(n as Text);
    for (const n of broken) {
      const parts = n.nodeValue!.split("\n");
      n.replaceWith(...parts.flatMap((t, i) => (i ? [doc.createElement("br"), t] : [t])).filter((x) => x !== ""));
    }
    return editorValue(copy);
  }
  const ps = [...editor.querySelectorAll("p")];
  return ps.length ? ps.map((p) => p.textContent ?? "").join("\n") : (editor.textContent ?? "");
}

/**
 * Wire the Bio's format button in `doc`: usable and Wired, its Not-yet title dropped (Live pass, D1); a click opens or closes the toolbar over
 * the Bio, its close button closes it. `blocked`: the note a tool shows when no write may be made (no single model).
 * Null on a page without the Bio's button; else the unbind.
 */
export function bindAboutFormat(doc: Document, blocked: () => string | null): (() => void) | null {
  const editor = doc.querySelector<HTMLElement>(BIO);
  const button = doc.querySelector<HTMLButtonElement>(ABOUT_FORMAT);
  const field = editor?.closest(".b-input-contenteditable");
  if (!editor || !button || !field) return null;
  markWired(button, true); // its Live pass (D1); bound only with OFM_NEW_WRITES_ENABLED on (ofMirrorWrites)
  const holder = doc.createElement("div");
  holder.innerHTML = TOOLBAR;
  const panel = holder.firstElementChild as HTMLElement;
  panel.setAttribute("data-oi-about-format", "");
  const show = (on: boolean) => {
    // OF's toolbar is `d-flex` (display:flex !important): only an important inline display hides it.
    if (on) panel.style.removeProperty("display");
    else panel.style.setProperty("display", "none", "important");
    button.setAttribute("aria-expanded", String(on)); // the button says whether its toolbar is open
  };
  show(false);
  field.before(panel);
  const sprite = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
  sprite.setAttribute("display", "none");
  sprite.setAttribute("data-oi-about-format-icons", "");
  sprite.innerHTML = SYMBOLS;
  doc.body.prepend(sprite);
  const unbindPanel = bindFormatPanel(doc, editor, panel, blocked);
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    const open = t?.closest?.(ABOUT_FORMAT) === button;
    const close = !!t?.closest?.(`${PANEL} [aria-label='Close Formatting Panel']`);
    if (!open && !close) return;
    ev.preventDefault();
    ev.stopPropagation(); // Wired: never the click fallback's
    show(open ? panel.style.display === "none" : false);
  };
  doc.addEventListener("click", onClick, true);
  return () => {
    doc.removeEventListener("click", onClick, true);
    button.removeAttribute("aria-expanded");
    markNotYet(button);
    unbindPanel();
    panel.remove();
    sprite.remove();
  };
}
