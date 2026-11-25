import { markNotYet, markWired } from "@/lib/ofMirrorTooltip";

export type ProfileImageKind = "avatar" | "header";
export interface ProfileImage {
  processId: string;
  host?: string;
  name?: string;
  thumbId?: number | string;
  extra?: unknown;
}
export type ProfileImagePatch = Partial<Record<ProfileImageKind, ProfileImage | "">>;
export type StagedImages = Partial<Record<ProfileImageKind, File | "remove">>;

export const PROFILE_IMAGE_TYPES: readonly string[] = ["image/jpeg", "image/png", "image/gif", "image/webp"];
export const PROFILE_IMAGE_MAX = 5 * 1024 * 1024;
export const IMAGE_TYPE_NOTE = "Choose a JPEG, PNG, GIF or WebP image";
export const IMAGE_SIZE_NOTE = "Choose an image of 5 MB or less";

export function profileImageProblem(file: { type: string; size: number }): string | null {
  if (!PROFILE_IMAGE_TYPES.includes(file.type)) return IMAGE_TYPE_NOTE;
  if (file.size > PROFILE_IMAGE_MAX) return IMAGE_SIZE_NOTE;
  return null;
}

export async function profileImagePatch(
  staged: StagedImages,
  upload: (kind: ProfileImageKind, file: File) => Promise<ProfileImage>,
): Promise<ProfileImagePatch> {
  const out: ProfileImagePatch = {};
  for (const kind of ["header", "avatar"] as const) {
    const s = staged[kind];
    // A removal sends "" (measured).
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
export const AVATAR_CAMERA_NAME = "Change avatar";
export const PROFILE_REMOVE: Record<ProfileImageKind, string> = {
  header: `${HEADER_BTNS} > button`,
  avatar: `${AVATAR_BTNS} [data-oi-avatar-remove]`,
};
const COVER = "img.b-profile__header__cover-img";
export const COVER_PLACEHOLDER =
  "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxIDEiPjxyZWN0IHdpZHRoPSIxIiBoZWlnaHQ9IjEiIGZpbGw9IiNlNWU3ZWIiLz48L3N2Zz4=";
const AVATAR = ".b-profile__user .g-avatar .g-avatar__placeholder";

export interface ProfileImages {
  staged(): StagedImages;
  revert(): void;
  commit(): void;
  unbind(): void;
}

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
  let before: Partial<Record<ProfileImageKind, string>> = {};
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
    for (const b of doc.querySelectorAll(PROFILE_CAMERA.header)) b.removeAttribute("title");
    for (const b of doc.querySelectorAll(PROFILE_CAMERA.avatar)) b.setAttribute("aria-label", AVATAR_CAMERA_NAME);
  };
  usable();
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
      ev.stopPropagation();
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
