"use client";

/**
 * A chat composer's own tools (messages/chat and its state-* pages, and New message's: messages/send), OF's MakeFeedPost
 * in a chat (build 202610091632). bindChat (or bindMass) keeps the draft and sends; this wires the tools around the editor:
 * - Format Text (Aa): opens OF's Format text panel the generator put at the top of the sticky panel (New post's capture);
 *   its tools are New post's (bindFormatPanel), so the editor holds OF's markup and Send sends it as the text.
 * - Add GIF: OF's InputGiphy in the composer's `.b-comments__giphy.m-chat-giphy`: a search field over Giphy's trending
 *   or searched GIFs (the Relay's OF Giphy proxy); a pick is the draft's `giphy_id`, shown under the editor with a delete.
 * - Record voice: OF's audio record panel (`.js-chat__audiorecord-panel`): the record button starts and stops the
 *   microphone (MediaRecorder), its timer runs to OF's 30:00 cap; a stopped recording goes up as Add media's upload.
 * - Record video: OF's video-js recorder (`.b-chat__video-message__preview`): camera preview, Record / Stop, OF's 05:00
 *   cap; the clip goes up as Add media's upload. Hidden on a phone or tablet, as OF hides it (`!iOS && !mobile`).
 * - Drop files onto the composer: OF's dropzone (`is-dragover` shows "Drop files to upload"); the files go up as Add
 *   media's.
 * - Send tip: shown only when the fan takes tips (OF: `withUser.tipsEnabled`); it stays disabled (the generator's "Not
 *   available" tooltip): OF's tip is a card payment the Relay's tip route cannot make.
 * OF's rules between them: Add GIF is off with a GIF picked, media other than voice, a price or tagged creators; the
 * price, Record video, Tag creators, Add media and the vault are off with a GIF (a GIF goes with nothing but a voice
 * note; bindChat refuses a drop and collectMessage a body otherwise); Record voice is off once an audio file is attached.
 * A drop takes photos, videos and audio only. The recorders ask for mp4 first, then webm (isTypeSupported), and the
 * File's type has no `;codecs`. Recordings belong to the document, not the bind: a rebind of the same chat keeps them.
 * Opening a tool sends nothing; without a model or an open chat it shows the reason (`ready`).
 */

import type { GiphyItem } from "@/lib/relay";
import type { ChatDraft, ChatHandlers } from "@/lib/ofMirrorChat";
import { bindFormatPanel, lock } from "@/lib/ofMirrorPost";
import { message, note } from "@/lib/ofMirrorWrites";

const FORMAT_BTN = "button[aria-label='Format Text']";
const FORMAT_PANEL = "[data-oi-format-panel]";
const FORMAT_CLOSE = "[aria-label='Close Formatting Panel']";
const GIF_BTN = "button.m-chat-giphy[aria-label='Add GIF']";
const GIF_BOX = "div.b-comments__giphy.m-chat-giphy";
const VOICE_BTN = "button[aria-label='Record voice']";
const VIDEO_BTN = "button.js-chat__video-record-btn";
const TIP_BTN = "button[at-attr='send_tip']";
const PRICE_BTN = "[at-attr='price_btn']";
const ADD_MEDIA_BTN = "button.attach_file[aria-label='Add media']";
const VAULT_BTN = "[at-attr='add_vault_media']";
const TAG_BTN = "[at-attr='release_forms_btn']";
const AUDIO_PANEL = ".js-chat__audiorecord-panel";
const VIDEO_BOX = ".b-chat__video-message__preview";
const DROP = ".b-dropzone__label:not([aria-hidden])";
const PREVIEW = "oi-chat-gif";

/** OF's caps: a voice message's (its panel's " 0:00 / 30:00 ") and a video message's (its player's 05:00). */
export const VOICE_MAX_MS = 30 * 60_000;
export const VIDEO_MAX_MS = 5 * 60_000;
export const NO_MIC = "No microphone was found";
export const MIC_BLOCKED = "Allow microphone access to record a voice message";
export const NO_CAMERA = "No camera was found";
export const CAMERA_BLOCKED = "Allow camera access to record a video message";
export const NO_RECORDER = "This browser cannot record";
export const NO_GIFS = "Nothing found";
export const GIF_SEARCH_MS = 400;
/** A GIF goes alone (OF: with a GIF, no media but a voice note, no price, no tagged creators). */
export const GIF_ALONE = "Remove the GIF to add media or tag creators";
/** What a drop takes: OF's dropzone uploads photos, videos and audio only. */
export const DROP_TYPES = /^(?:image|video|audio)\//;
export const notMedia = (names: string[]) => `Not a photo, video or audio file: ${names.join(", ")}`;

/** OF hides Record video on phones and tablets. */
export const isMobile = (ua: string) => /Mobi|Android|iPhone|iPad|iPod/i.test(ua);

export interface ComposerTools {
  editor: HTMLElement;
  draftOf(): ChatDraft;
  update(patch: Partial<ChatDraft>): void;
  /** The handlers when a write may be made, else null after a note at `anchor`. */
  ready(anchor: Element): ChatHandlers | null;
  /** The note when no write may be made (no model, no chat), else null. */
  blocked(): string | null;
  /** Add media's upload of `files` (an audio file counts as a voice note). */
  take(files: File[]): void;
  /** The draft a recording belongs to (the account and chat): a rebind with the same key keeps a recording going. */
  key?: string;
  tipsEnabled?: boolean;
  mobile: boolean;
}

const clock = (ms: number) => {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/** The containers a recording is asked for, OF's upload's first: mp4 where the browser records it, then webm. */
const RECORD_TYPES = { audio: ["audio/mp4", "audio/webm"], video: ["video/mp4", "video/webm"] } as const;
/** The first of RECORD_TYPES[kind] the browser's MediaRecorder records, or undefined (its own default). */
export function recordType(win: Window, kind: "audio" | "video"): string | undefined {
  const Rec = (win as unknown as { MediaRecorder?: { isTypeSupported?(t: string): boolean } }).MediaRecorder;
  return RECORD_TYPES[kind].find((t) => {
    try {
      return Rec?.isTypeSupported?.(t) === true;
    } catch {
      return false;
    }
  });
}
/** A MIME type without its parameters (`video/webm;codecs=vp8,opus` is `video/webm`). */
export const bareType = (t: string) => t.split(";")[0].trim().toLowerCase();

/** A media stream's recorder: `stop(save)` ends it (save: the recording goes to `done` with its bare type), every track stopped. */
function recorder(win: Window, stream: MediaStream, kind: "audio" | "video", done: (blob: Blob, type: string) => void) {
  const Rec = (win as unknown as { MediaRecorder?: typeof MediaRecorder }).MediaRecorder;
  const mimeType = recordType(win, kind);
  const rec = mimeType ? new Rec!(stream, { mimeType }) : new Rec!(stream);
  const chunks: Blob[] = [];
  let keep = false;
  rec.ondataavailable = (e) => {
    if (e.data?.size) chunks.push(e.data);
  };
  rec.onstop = () => {
    for (const t of stream.getTracks()) t.stop();
    if (!keep) return;
    const type = bareType(rec.mimeType || mimeType || "") || `${kind}/webm`;
    done(new Blob(chunks, { type }), type);
  };
  return {
    start: () => rec.start(),
    stop(save: boolean) {
      keep = save;
      if (rec.state !== "inactive") rec.stop();
      else for (const t of stream.getTracks()) t.stop();
    },
  };
}

/** The media stream for `kind`, or the note for why there is none. */
async function streamFor(win: Window, kind: "audio" | "video"): Promise<MediaStream | string> {
  const devices = win.navigator.mediaDevices;
  if (!devices?.getUserMedia || !(win as unknown as { MediaRecorder?: unknown }).MediaRecorder) return NO_RECORDER;
  try {
    return await devices.getUserMedia(kind === "audio" ? { audio: true } : { audio: true, video: true });
  } catch (e) {
    const name = (e as { name?: string })?.name;
    if (name === "NotFoundError") return kind === "audio" ? NO_MIC : NO_CAMERA;
    if (name === "NotAllowedError") return kind === "audio" ? MIC_BLOCKED : CAMERA_BLOCKED;
    return `Could not record: ${message(e)}`;
  }
}

type Recorder = ReturnType<typeof recorder>;
/**
 * A document's recordings. They outlive a bind: useOfChat rebinds the same frame document when the chat's details
 * change (its name, mute state, tips flag), and a recording (or a permission prompt) must go on through that. Only when
 * no bind of the same draft takes the document back (by the end of the task) is it stopped, nothing kept.
 */
interface Live {
  key: string;
  owners: number;
  dead: boolean;
  take: (files: File[]) => void;
  voice: Recorder | null;
  voiceAt: number;
  voiceTick: number;
  asking: boolean;
  video: Recorder | null;
  videoStream: MediaStream | null;
  videoTimer: number;
  videoAsking: boolean;
}
const LIVE = new WeakMap<Document, Live>();
/** Stop `live`'s recordings, keeping nothing (no DOM work: its document is gone or another draft's). */
function stopLive(win: Window, live: Live) {
  live.dead = true;
  win.clearInterval(live.voiceTick);
  win.clearTimeout(live.videoTimer);
  live.voice?.stop(false);
  if (live.video) live.video.stop(false);
  else for (const t of live.videoStream?.getTracks() ?? []) t.stop();
  live.voice = live.video = null;
  live.videoStream = null;
}

/** Wire the chat composer's tools in `doc`. `sync` re-applies OF's rules (bindChat calls it on every draft change). */
export function bindComposer(doc: Document, tools: ComposerTools): { sync(): void; unbind(): void } {
  const { editor, draftOf, update, ready } = tools;
  const win = doc.defaultView!;
  const q = <T extends Element = HTMLElement>(sel: string) => doc.querySelector<T>(sel);
  const formatBtn = q<HTMLButtonElement>(FORMAT_BTN);
  const panel = q(FORMAT_PANEL);
  const gifBtn = q<HTMLButtonElement>(GIF_BTN);
  const gifBox = q(GIF_BOX);
  const voiceBtn = q<HTMLButtonElement>(VOICE_BTN);
  const videoBtn = q<HTMLButtonElement>(VIDEO_BTN);
  const tipBtn = q<HTMLButtonElement>(TIP_BTN);
  const priceBtn = q(PRICE_BTN);
  const audioPanel = q(AUDIO_PANEL);
  const videoBox = q(VIDEO_BOX);
  const drop = q(DROP);
  const area = drop?.parentElement ?? null;
  for (const el of [formatBtn, gifBtn, voiceBtn, videoBtn]) el?.setAttribute("data-oi-wired", "");
  const addBtn = q<HTMLButtonElement>(ADD_MEDIA_BTN);
  const vaultBtn = q(VAULT_BTN);
  const tagBtn = q(TAG_BTN);
  const cleanups: Array<() => void> = [];
  const key = tools.key ?? "";
  let live = LIVE.get(doc);
  if (live && (live.dead || live.key !== key)) {
    if (!live.dead) stopLive(win, live);
    live = undefined;
  }
  if (!live) {
    live = { key, owners: 0, dead: false, take: tools.take, voice: null, voiceAt: 0, voiceTick: 0, asking: false, video: null, videoStream: null, videoTimer: 0, videoAsking: false };
    LIVE.set(doc, live);
  }
  const L: Live = live;
  L.owners++;
  L.take = tools.take;

  // Send tip: only where OF shows it.
  if (tipBtn) tipBtn.style.display = tools.tipsEnabled === true ? "" : "none";
  // Record video: not on a phone or tablet.
  if (videoBtn && tools.mobile) videoBtn.style.display = "none";

  // ---- Format text
  if (panel) cleanups.push(bindFormatPanel(doc, editor, panel, tools.blocked));
  const showFormat = (on: boolean) => {
    if (!panel) return;
    // OF's toolbar is `d-flex` (display:flex !important): only an important inline display hides it.
    if (on) panel.style.removeProperty("display");
    else panel.style.setProperty("display", "none", "important");
    // OF renders the panel only while open: its `:has(.b-form-editor)` rule makes room for it under the text box.
    panel.classList.toggle("b-form-editor", on);
    formatBtn?.classList.toggle("m-active", on);
  };

  // ---- GIF picker and the picked GIF
  let gifTimer = 0;
  let gifAsk = 0;
  const gifWrap = () => gifBox?.querySelector<HTMLElement>(".b-comments__giphy__wrapper") ?? null;
  const gifField = () => gifBox?.querySelector<HTMLInputElement>(".b-comments__giphy-form input") ?? null;
  const icon = (name: string) => `<svg class="g-icon" aria-hidden="true"><use href="#${name}" xlink:href="#${name}"></use></svg>`;
  const loadGifs = (term: string) => {
    const wrap = gifWrap();
    const h = tools.blocked() ? null : ready(gifBtn ?? editor);
    if (!wrap || !h?.gifs) return;
    const ask = ++gifAsk;
    wrap.classList.remove("m-empty-list");
    h.gifs(term).then(
      (items) => {
        if (ask !== gifAsk) return;
        wrap.replaceChildren(...items.map(gifTile));
        if (!items.length) {
          wrap.classList.add("m-empty-list");
          const none = doc.createElement("div");
          none.className = "b-empty-placeholder";
          none.style.fontSize = "14px"; // OF's wrapper is font-size 0 (its tiles sit edge to edge)
          none.textContent = NO_GIFS;
          wrap.append(none);
        }
      },
      (e) => {
        if (ask !== gifAsk) return;
        const fail = doc.createElement("div");
        fail.className = "b-empty-placeholder";
        fail.style.cssText = "font-size:14px;white-space:normal";
        fail.textContent = `Could not load GIFs: ${message(e)}`;
        wrap.replaceChildren(fail);
      },
    );
  };
  // OF's InputGiphy is a scoped (data-v-*) component: its CSS only reaches elements carrying the box's scope attributes.
  const scope = () => [...(gifBox?.attributes ?? [])].filter((a) => a.name.startsWith("data-v-")).map((a) => a.name);
  const scoped = <T extends Element>(el: T): T => {
    for (const a of scope()) el.setAttribute(a, "");
    return el;
  };
  // A tile as OF draws one: a still frame that sizes the 128px-high tile, and the animated GIF laid over it (OF's
  // `.b-comments__giphy__img img:last-child` is absolute).
  const gifTile = (g: GiphyItem) => {
    const b = scoped(doc.createElement("button"));
    b.type = "button";
    b.className = "b-comments__giphy__img";
    b.setAttribute("aria-label", g.title || "GIF");
    b.setAttribute("data-oi-gif", g.id);
    b.setAttribute("data-oi-wired", "");
    const moving = g.images.fixed_height?.webp || g.images.fixed_height?.url || g.images.original?.url || "";
    const still = g.images.fixed_height_still?.url || moving;
    for (const src of [still, moving]) {
      const img = scoped(doc.createElement("img"));
      img.src = src;
      img.alt = g.title || "";
      b.append(img);
    }
    return b;
  };
  const openGifs = (on: boolean) => {
    if (!gifBox) return;
    gifBox.classList.toggle("m-opened", on);
    if (!on) return gifBox.replaceChildren();
    const v = scope().map((a) => ` ${a}=""`).join("");
    gifBox.innerHTML =
      `<div${v} class="b-comments__giphy-content m-not-absolute"><div${v} class="b-comments__giphy-form d-flex align-items-center">` +
      `<button${v} type="button" data-oi-wired="" class="g-btn m-with-round-hover m-icon m-icon-only m-sm-size b-comments__form__btn-close" aria-label="Close">${icon("icon-close")}</button>` +
      `<input${v} type="text" data-oi-wired="" class="form-control b-field-like m-sm-size" placeholder="Search GIFs" aria-label="Search GIFs">` +
      `<button${v} type="button" data-oi-wired="" class="g-btn m-with-round-hover m-icon m-icon-only m-sm-size" aria-label="Search">${icon("icon-search")}</button>` +
      `</div><div${v} class="b-comments__giphy-scroll-wrapper"><div${v} class="b-dragscroll" style="overflow-x:auto;overflow-y:hidden">` +
      `<div${v} class="b-comments__giphy__wrapper"></div></div></div></div>`;
    gifField()?.focus();
    loadGifs("");
  };
  const showPicked = () => {
    const { giphy_id: id, giphy_thumb: thumb } = draftOf();
    const old = doc.getElementById(PREVIEW);
    if (!id) return old?.remove();
    const el = old ?? doc.createElement("div");
    el.id = PREVIEW;
    el.className = "b-comments__giphy-wrapper";
    const item = doc.createElement("div");
    item.className = "b-comments__giphy-item";
    item.style.cssText = "position:relative;display:inline-block;margin:4px 0";
    const img = doc.createElement("img");
    img.src = thumb ?? "";
    img.alt = "GIF";
    img.style.height = "100px";
    const del = doc.createElement("button");
    del.type = "button";
    del.className = "b-dropzone__preview__delete g-btn m-rounded m-reset-width m-thumb-r-corner-pos m-btn-remove m-sm-icon-size";
    del.setAttribute("aria-label", "Delete");
    del.setAttribute("data-oi-gif-delete", "");
    del.setAttribute("data-oi-wired", "");
    del.innerHTML = icon("icon-close");
    item.append(img, del);
    el.replaceChildren(item);
    if (!old) (gifBox ?? editor).after(el);
  };

  // ---- Voice (its state is the document's, L)
  const voiceParts = () => ({
    idleHead: audioPanel?.querySelector<HTMLElement>(".js-message-header-default"),
    recHead: audioPanel?.querySelector<HTMLElement>(".js-message-header-recording"),
    timer: audioPanel?.querySelector<HTMLElement>(".js-chat__audio-record-timer"),
    rec: audioPanel?.querySelector<HTMLButtonElement>(".b-float-panel__btn-record"),
    stopIcon: audioPanel?.querySelector<HTMLElement>(".js-chat__audio-record-state-stop"),
    recIcon: audioPanel?.querySelector<HTMLElement>(".js-chat__audio-record-state-rec"),
  });
  const voiceState = (recording: boolean) => {
    const p = voiceParts();
    p.idleHead?.classList.toggle("g-hidden", recording);
    p.recHead?.classList.toggle("g-hidden", !recording);
    p.stopIcon?.classList.toggle("g-hidden", !recording);
    p.recIcon?.classList.toggle("g-hidden", recording);
    if (p.timer) p.timer.textContent = ` ${clock(recording ? Date.now() - L.voiceAt : 0)} / ${clock(VOICE_MAX_MS)} `;
  };
  const closeVoice = (save: boolean) => {
    win.clearInterval(L.voiceTick);
    L.voice?.stop(save);
    L.voice = null;
    if (audioPanel) audioPanel.style.display = "none";
    doc.body.classList.remove("open-panel");
  };
  const openVoice = () => {
    if (!audioPanel) return;
    audioPanel.style.display = "";
    doc.body.classList.add("open-panel");
    voiceState(false);
  };
  const startVoice = async () => {
    const anchor = voiceBtn ?? editor;
    L.asking = true;
    const stream = await streamFor(win, "audio").finally(() => (L.asking = false));
    if (L.dead || audioPanel?.style.display === "none") {
      if (typeof stream !== "string") for (const t of stream.getTracks()) t.stop();
      return;
    }
    if (typeof stream === "string") {
      closeVoice(false);
      return note(doc, anchor, stream, true);
    }
    L.voice = recorder(win, stream, "audio", (blob, type) => L.take([new File([blob], `voice-${Date.now()}.${/ogg/.test(type) ? "ogg" : /mp4/.test(type) ? "m4a" : "webm"}`, { type })]));
    L.voice.start();
    L.voiceAt = Date.now();
    voiceState(true);
    L.voiceTick = win.setInterval(() => {
      if (Date.now() - L.voiceAt >= VOICE_MAX_MS) return closeVoice(true);
      voiceState(true);
    }, 250);
  };

  // ---- Video (its state is the document's, L)
  const videoParts = () => ({
    tech: videoBox?.querySelector<HTMLVideoElement>("video.vjs-tech"),
    rec: videoBox?.querySelector<HTMLButtonElement>(".vjs-record-button"),
    indicator: videoBox?.querySelector<HTMLElement>(".vjs-record-indicator"),
    liveIcon: videoBox?.querySelector<HTMLElement>(".b-chat__videorec-live-icon"),
    liveLabel: videoBox?.querySelector<HTMLElement>(".b-chat__videorec-live-label"),
  });
  const videoState = (recording: boolean) => {
    const p = videoParts();
    p.rec?.classList.toggle("vjs-icon-record-start", !recording);
    p.rec?.classList.toggle("vjs-icon-record-stop", recording);
    if (p.rec) {
      p.rec.title = recording ? "Stop" : "Record";
      const t = p.rec.querySelector(".vjs-control-text");
      if (t) t.textContent = recording ? "Stop" : "Record";
    }
    p.indicator?.classList.toggle("vjs-hidden", !recording);
    p.liveIcon?.classList.toggle("g-hidden", !recording);
    p.liveLabel?.classList.toggle("g-hidden", !recording);
  };
  const closeVideo = (save: boolean) => {
    win.clearTimeout(L.videoTimer);
    if (L.video) L.video.stop(save);
    else for (const t of L.videoStream?.getTracks() ?? []) t.stop();
    L.video = null;
    L.videoStream = null;
    const p = videoParts();
    if (p.tech) p.tech.srcObject = null;
    videoState(false);
    p.rec?.classList.add("vjs-hidden");
    videoBox?.classList.add("g-hidden");
  };
  const openVideo = async () => {
    const anchor = videoBtn ?? editor;
    L.videoAsking = true;
    const stream = await streamFor(win, "video").finally(() => (L.videoAsking = false));
    if (L.dead) {
      if (typeof stream !== "string") for (const t of stream.getTracks()) t.stop();
      return;
    }
    if (typeof stream === "string") return note(doc, anchor, stream, true);
    L.videoStream = stream;
    const p = videoParts();
    videoBox?.classList.remove("g-hidden");
    p.rec?.classList.remove("vjs-hidden");
    if (p.rec) p.rec.setAttribute("data-oi-wired", "");
    if (p.tech) {
      p.tech.muted = true;
      p.tech.srcObject = stream;
      void p.tech.play?.()?.catch?.(() => {});
    }
    videoState(false);
  };
  const toggleVideoRec = () => {
    if (!L.videoStream) return;
    if (L.video) return closeVideo(true);
    L.video = recorder(win, L.videoStream, "video", (blob, type) => L.take([new File([blob], `video-${Date.now()}.${/mp4/.test(type) ? "mp4" : "webm"}`, { type })]));
    L.video.start();
    videoState(true);
    L.videoTimer = win.setTimeout(() => closeVideo(true), VIDEO_MAX_MS);
  };

  // ---- OF's rules between the tools
  const sync = () => {
    const d = draftOf();
    const gif = !!d.giphy_id;
    const audio = d.audio ?? 0;
    const others = d.media_files.length - audio > 0;
    if (gifBtn) lock(gifBtn, gif || others || !!d.price || !!d.tags?.length);
    if (priceBtn) lock(priceBtn, gif);
    if (videoBtn) lock(videoBtn, gif);
    if (voiceBtn) lock(voiceBtn, audio > 0);
    // OF: Tag creators is off with a GIF (ledger-rea: "Disabled while a GIF is set"); a GIF goes without other media.
    for (const el of [addBtn, vaultBtn, tagBtn]) if (el) lock(el, gif);
    if (gif && gifBox?.classList.contains("m-opened")) openGifs(false);
    showPicked();
  };

  // ---- Events
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    // A GIF set: Add media, the vault and Tag creators take nothing (a keyboard Enter reaches a locked link too).
    const off = draftOf().giphy_id ? [addBtn, vaultBtn, tagBtn].find((el) => el && t.closest(`${ADD_MEDIA_BTN}, ${VAULT_BTN}, ${TAG_BTN}`) === el) : null;
    if (off) {
      ev.preventDefault();
      ev.stopPropagation();
      return note(doc, off, GIF_ALONE);
    }
    if (formatBtn && t.closest(FORMAT_BTN) === formatBtn) {
      ev.preventDefault();
      return showFormat(panel?.style.display === "none");
    }
    if (panel && t.closest(FORMAT_CLOSE) && panel.contains(t)) {
      ev.preventDefault();
      return showFormat(false);
    }
    if (gifBtn && t.closest(GIF_BTN) === gifBtn) {
      ev.preventDefault();
      if (gifBtn.disabled) return;
      if (gifBox?.classList.contains("m-opened")) return openGifs(false);
      if (!ready(gifBtn)) return;
      return openGifs(true);
    }
    if (gifBox?.contains(t)) {
      if (t.closest(".b-comments__form__btn-close")) {
        ev.preventDefault();
        return openGifs(false);
      }
      if (t.closest("[aria-label='Search']")) {
        ev.preventDefault();
        win.clearTimeout(gifTimer);
        return loadGifs(gifField()?.value.trim() ?? "");
      }
      const tile = t.closest<HTMLElement>("[data-oi-gif]");
      if (tile) {
        ev.preventDefault();
        if (!ready(gifBtn ?? tile)) return;
        update({ giphy_id: tile.getAttribute("data-oi-gif")!, giphy_thumb: tile.querySelector("img")?.getAttribute("src") ?? "" });
        return openGifs(false);
      }
    }
    if (t.closest("[data-oi-gif-delete]")) {
      ev.preventDefault();
      return update({ giphy_id: undefined, giphy_thumb: undefined });
    }
    if (voiceBtn && t.closest(VOICE_BTN) === voiceBtn) {
      ev.preventDefault();
      if (voiceBtn.disabled || !ready(voiceBtn)) return;
      return openVoice();
    }
    if (audioPanel?.contains(t)) {
      const p = voiceParts();
      if (p.rec && t.closest(".b-float-panel__btn-record") === p.rec) {
        ev.preventDefault();
        if (L.voice) return closeVoice(true);
        if (!L.asking) void startVoice();
        return;
      }
      // The default header's Back and the recording header's close: nothing is kept.
      if (t.closest("a[aria-label='Back'], .js-message-header-recording button")) {
        ev.preventDefault();
        ev.stopPropagation();
        return closeVoice(false);
      }
    }
    if (videoBtn && t.closest(VIDEO_BTN) === videoBtn) {
      ev.preventDefault();
      if (videoBtn.disabled || L.videoStream || L.videoAsking || !ready(videoBtn)) return;
      void openVideo();
      return;
    }
    if (videoBox && t.closest(".js-video-message-close") && videoBox.contains(t)) {
      ev.preventDefault();
      return closeVideo(false);
    }
    if (videoBox && t.closest(".vjs-record-button") && videoBox.contains(t)) {
      ev.preventDefault();
      return toggleVideoRec();
    }
  };
  const onInput = (ev: Event) => {
    const field = gifField();
    if (!field || ev.target !== field) return;
    win.clearTimeout(gifTimer);
    gifTimer = win.setTimeout(() => loadGifs(field.value.trim()), GIF_SEARCH_MS);
  };
  const onKey = (ev: KeyboardEvent) => {
    const field = gifField();
    if (!field || ev.target !== field || ev.key !== "Enter") return;
    ev.preventDefault();
    win.clearTimeout(gifTimer);
    loadGifs(field.value.trim());
  };

  // ---- Drop files onto the composer (OF's dragUploadArea)
  let depth = 0;
  const onDrag = (ev: DragEvent) => {
    ev.preventDefault();
    if (!area) return;
    if (ev.type === "dragenter") depth++;
    if (ev.type === "dragleave") depth = Math.max(0, depth - 1);
    if (ev.type === "drop" || ev.type === "dragend") depth = 0;
    area.classList.toggle("is-dragover", depth > 0);
    if (ev.type !== "drop") return;
    const files = [...(ev.dataTransfer?.files ?? [])];
    if (!files.length || !ready(drop!)) return;
    // OF's dropzone takes photos, videos and audio; anything else is named and left out.
    const ok = files.filter((f) => DROP_TYPES.test(f.type));
    const bad = files.filter((f) => !DROP_TYPES.test(f.type));
    if (bad.length) note(doc, drop!, notMedia(bad.map((f) => f.name || "file")), true);
    if (ok.length) tools.take(ok);
  };
  const DRAG = ["dragenter", "dragover", "dragleave", "drop", "dragend"] as const;
  for (const type of DRAG) area?.addEventListener(type, onDrag as EventListener);

  doc.addEventListener("click", onClick, true);
  doc.addEventListener("input", onInput);
  doc.addEventListener("keydown", onKey);
  sync();
  return {
    sync,
    unbind() {
      win.clearTimeout(gifTimer);
      // A rebind of the same draft in this task keeps the recordings; otherwise they stop, nothing kept.
      L.owners--;
      queueMicrotask(() => {
        if (L.owners > 0 || L.dead) return;
        closeVoice(false);
        closeVideo(false);
        stopLive(win, L);
        if (LIVE.get(doc) === L) LIVE.delete(doc);
      });
      for (const type of DRAG) area?.removeEventListener(type, onDrag as EventListener);
      doc.removeEventListener("click", onClick, true);
      doc.removeEventListener("input", onInput);
      doc.removeEventListener("keydown", onKey);
      for (const c of cleanups) c();
      doc.getElementById(PREVIEW)?.remove();
    },
  };
}
