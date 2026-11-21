/**
 * Edit profile's cover and avatar (ofm-not-yet ticket 67, capture record settings--profile-cover-avatar): each camera
 * button picks an image, the cover's (and, once there is an avatar, the avatar's) remove button clears it; the change
 * shows at once and goes out with the page's Save. A picked image goes up first through the Relay's
 * POST /api/of/v2/users/me/profile-image (OF's upload steps, its convert claim `inferred`: the record says "params to
 * verify"), then Save's PATCH /users/me carries `{header|avatar: <the Relay's reply>}`; a removal sends `""`
 * (measured). A failed Save puts the pictures back. The buttons keep their Not-yet title until a Live-proof pass (D1): the
 * cover's camera passed (2026-11-21) and drops it; the avatar's camera and the removes keep it.
 */

import { markNotYet, markWired } from "@/lib/ofMirrorTooltip";

export type ProfileImageKind = "avatar" | "header";
/** The Relay's reply for an uploaded image: OF's convert item, sent as is in the profile write. */
export interface ProfileImage {
  processId: string;
  host?: string;
  name?: string;
  thumbId?: number | string;
  extra?: unknown;
}
export type ProfileImagePatch = Partial<Record<ProfileImageKind, ProfileImage | "">>;
/** A staged change: a picked file, or the image removed. */
export type StagedImages = Partial<Record<ProfileImageKind, File | "remove">>;

/** The Relay route's limits (service/server.py PROFILE_IMAGE_TYPES, PROFILE_IMAGE_MAX). */
export const PROFILE_IMAGE_TYPES: readonly string[] = ["image/jpeg", "image/png", "image/gif", "image/webp"];
export const PROFILE_IMAGE_MAX = 5 * 1024 * 1024;
export const IMAGE_TYPE_NOTE = "Choose a JPEG, PNG, GIF or WebP image";
export const IMAGE_SIZE_NOTE = "Choose an image of 5 MB or less";

/** Why a picked file cannot go up (refused before any request), or null. */
export function profileImageProblem(file: { type: string; size: number }): string | null {
  if (!PROFILE_IMAGE_TYPES.includes(file.type)) return IMAGE_TYPE_NOTE;
  if (file.size > PROFILE_IMAGE_MAX) return IMAGE_SIZE_NOTE;
  return null;
}

/** The profile write's image keys: each staged file uploaded (cover first), each removal `""`. */
export async function profileImagePatch(
  staged: StagedImages,
  upload: (kind: ProfileImageKind, file: File) => Promise<ProfileImage>,
): Promise<ProfileImagePatch> {
  const out: ProfileImagePatch = {};
  for (const kind of ["header", "avatar"] as const) {
    const s = staged[kind];
    if (s === "remove") out[kind] = "";
    else if (s) out[kind] = await upload(kind, s);
  }
  return out;
}

const HEADER_BTNS = ".b-profile__header > .b-profile__header__cover__btns";
const AVATAR_BTNS = ".b-profile__user .g-avatar .b-profile__header__cover__btns";
export const PROFILE_CAMERA: Record<ProfileImageKind, string> = {
  header: `${HEADER_BTNS} button.dropdown-toggle`,
  avatar: `${AVATAR_BTNS} button.dropdown-toggle`,
};
/** The avatar's remove button: ofMirrorIdentity's copy of the cover's, drawn once there is an avatar. */
/** The avatar's camera's accessible name while bound (ours): it keeps its Not-yet title, the cover's camera does not (D1). */
export const AVATAR_CAMERA_NAME = "Change avatar";
export const PROFILE_REMOVE: Record<ProfileImageKind, string> = {
  header: `${HEADER_BTNS} > button`,
  avatar: `${AVATAR_BTNS} [data-oi-avatar-remove]`,
};
const COVER = "img.b-profile__header__cover-img";
/** The cover's empty state: OF's grey placeholder, as the captured page draws it. */
export const COVER_PLACEHOLDER =
  "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxIDEiPjxyZWN0IHdpZHRoPSIxIiBoZWlnaHQ9IjEiIGZpbGw9IiNlNWU3ZWIiLz48L3N2Zz4=";
const AVATAR = ".b-profile__user .g-avatar .g-avatar__placeholder";

export interface ProfileImages {
  staged(): StagedImages;
  /** The pictures as they were before anything was staged (a failed Save). */
  revert(): void;
  /** The staged changes saved: what shows is now the saved state. */
  commit(): void;
  unbind(): void;
}

/**
 * Wire the cameras and remove buttons of Edit profile in `doc`: usable and Wired, titles kept but the cover camera's (D1). `canWrite` false (no
 * single model): a click sends nothing and gets `onSelectModel`. A picked file that fails profileImageProblem gets
 * `onRefuse` (nothing staged); a staged change calls `onStage` (Save turns on). Null on a page with neither camera.
 */
export function bindProfileImages(
  doc: Document,
  opts: {
    canWrite: boolean;
    onStage(): void;
    onRefuse(anchor: Element, text: string): void;
    onSelectModel(anchor: Element): void;
  },
): ProfileImages | null {
  if (!doc.querySelector(PROFILE_CAMERA.header) && !doc.querySelector(PROFILE_CAMERA.avatar)) return null;
  let staged: StagedImages = {};
  // Each picture as it was before its first staged change (ofMirrorIdentity may paint it after this bind).
  let before: Partial<Record<ProfileImageKind, string>> = {};
  // OF draws a picture's remove button only while there is a picture: a removal hides it, a pick shows it again.
  let removeShown: Partial<Record<ProfileImageKind, boolean>> = {};
  const showRemove = (kind: ProfileImageKind, on: boolean) => {
    for (const b of doc.querySelectorAll<HTMLElement>(PROFILE_REMOVE[kind])) b.hidden = !on;
  };
  const urls: string[] = [];
  const cover = doc.querySelector<HTMLImageElement>(COVER);
  const avatar = doc.querySelector<HTMLElement>(AVATAR);
  const inputs = {} as Record<ProfileImageKind, HTMLInputElement>;
  for (const kind of ["header", "avatar"] as const) {
    const input = doc.createElement("input");
    input.type = "file";
    input.accept = PROFILE_IMAGE_TYPES.join(",");
    input.hidden = true;
    input.setAttribute("data-oi-profile-file", kind);
    input.setAttribute("data-oi-wired", "");
    doc.body.append(input);
    inputs[kind] = input;
  }
  const usable = () => {
    for (const sel of [...Object.values(PROFILE_CAMERA), ...Object.values(PROFILE_REMOVE)])
      for (const b of doc.querySelectorAll<HTMLButtonElement>(sel)) markWired(b, false);
    // D1: the cover's camera passed Live (docs/of-manager/captures/settings--profile-cover-avatar.json, 2026-11-21) and
    // drops its Not-yet title; the avatar's camera (no proof of its own) keeps it under its own name, so the sweep tells
    // the two "[btn.dropdown-toggle]" apart.
    for (const b of doc.querySelectorAll(PROFILE_CAMERA.header)) b.removeAttribute("title");
    for (const b of doc.querySelectorAll(PROFILE_CAMERA.avatar)) b.setAttribute("aria-label", AVATAR_CAMERA_NAME);
  };
  usable();
  // ofMirrorIdentity draws the avatar's remove button when users/me lands, maybe after this bind.
  const avatarBtns = doc.querySelector(AVATAR_BTNS);
  const Observer = doc.defaultView?.MutationObserver;
  const observer = avatarBtns && Observer ? new Observer(usable) : null;
  if (observer && avatarBtns) observer.observe(avatarBtns, { childList: true });

  const stage = (kind: ProfileImageKind, s: File | "remove", url: string | null) => {
    if (!(kind in before)) {
      before = { ...before, [kind]: kind === "header" ? (cover?.getAttribute("src") ?? "") : (avatar?.innerHTML ?? "") };
      removeShown = { ...removeShown, [kind]: !doc.querySelector<HTMLElement>(PROFILE_REMOVE[kind])?.hidden };
    }
    staged = { ...staged, [kind]: s };
    showRemove(kind, s !== "remove");
    if (kind === "header" && cover) cover.src = url ?? COVER_PLACEHOLDER;
    if (kind === "avatar" && avatar) {
      if (url === null) {
        // OF's text avatar: the display name's first letter.
        const name = doc.querySelector<HTMLInputElement>("#input-name")?.value.trim() ?? "";
        avatar.replaceChildren(doc.createTextNode(` ${(name[0] ?? "").toUpperCase()} `));
      } else {
        const pic = doc.createElement("img");
        pic.setAttribute("data-oi-avatar", "");
        pic.alt = "";
        pic.src = url;
        pic.style.cssText = "width:100%;height:100%;object-fit:cover;border-radius:inherit;";
        avatar.replaceChildren(pic);
      }
    }
    opts.onStage();
  };

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    for (const kind of ["header", "avatar"] as const) {
      const control = t?.closest?.(PROFILE_CAMERA[kind]) ?? t?.closest?.(PROFILE_REMOVE[kind]);
      if (!control) continue;
      ev.preventDefault();
      ev.stopPropagation(); // Wired: never the click fallback's
      if (!opts.canWrite) return opts.onSelectModel(control);
      if (control.matches(PROFILE_CAMERA[kind])) return inputs[kind].click();
      return stage(kind, "remove", null);
    }
  };
  const onChange = (ev: Event) => {
    const input = ev.target as HTMLInputElement;
    const kind = input.getAttribute?.("data-oi-profile-file");
    if (kind !== "header" && kind !== "avatar") return;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    const problem = profileImageProblem(file);
    if (problem) return opts.onRefuse(doc.querySelector(PROFILE_CAMERA[kind]) ?? input, problem);
    const url = URL.createObjectURL(file);
    urls.push(url);
    stage(kind, file, url);
  };
  doc.addEventListener("click", onClick, true);
  doc.addEventListener("change", onChange, true);
  return {
    staged: () => staged,
    revert() {
      if (cover && before.header !== undefined) cover.src = before.header;
      if (avatar && before.avatar !== undefined) avatar.innerHTML = before.avatar;
      for (const [kind, on] of Object.entries(removeShown) as [ProfileImageKind, boolean][]) showRemove(kind, on);
      staged = {};
      before = {};
      removeShown = {};
    },
    commit() {
      staged = {};
      before = {};
      removeShown = {};
    },
    unbind() {
      doc.removeEventListener("click", onClick, true);
      doc.removeEventListener("change", onChange, true);
      observer?.disconnect();
      for (const input of Object.values(inputs)) input.remove();
      for (const url of urls) URL.revokeObjectURL(url);
      for (const sel of [...Object.values(PROFILE_CAMERA), ...Object.values(PROFILE_REMOVE)]) for (const b of doc.querySelectorAll(sel)) markNotYet(b);
      for (const b of doc.querySelectorAll(PROFILE_CAMERA.avatar)) b.removeAttribute("aria-label");
    },
  };
}
