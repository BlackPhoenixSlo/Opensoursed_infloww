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
 * A drop takes photos, videos and audio only. Record video asks for mp4 first, then webm (isTypeSupported); Record voice
 * asks for OF's own recorder's types (VOICE_TYPES: mp3, then ogg) and re-encodes anything else to WAV, as OF's does. The
 * File's type has no `;codecs`. Recordings belong to the document, not the bind: a rebind of the same chat keeps them.
 * Opening a tool sends nothing; without a model or an open chat it shows the reason (`ready`).
 */

import type { GiphyItem } from "@/lib/relay";
import type { ChatDraft, ChatHandlers } from "@/lib/ofMirrorChatShared";
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

/**
 * The voice note types OF's upload takes, with their extensions, in the order OF's own audio record panel picks them
 * (bundle 24014.js `V()`, constants MakeFeedPost 800378 `xJ`/`ni`): `audio/mpeg` .mp3 where MediaRecorder records it,
 * else `audio/ogg` .ogg, else `audio/wav` .wav from RecordRTC's StereoAudioRecorder, one channel (always WAV on iOS and
 * Safari); OF names it `audiorecord_<id>_<time>.<ext>`. OF refused `audio/mp4` .m4a (signed/create 400 "Invalid file
 * type", live 2026-11-21). Any other audio (Chrome's webm recording, a picked or dropped .m4a) is re-encoded to WAV
 * on its way to the upload (`voiceFile`, called by ofMirrorPost's mediaTaker).
 * ASSUMPTION: OF takes these three for a voice note (rung 3: its own recorder uploads them; only the m4a refusal was
 * measured); overturned by a Live Record voice run refusing the type sent, which then changes this one constant.
 */
export const VOICE_TYPES: Readonly<Record<string, string>> = { "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/wav": "wav" };
const WAV = "audio/wav";
/**
 * The rate a re-encoded voice note is resampled to: OF's recorder asks RecordRTC for 16 kHz (`desiredSampRate`, bundle
 * constant `o4`), on Android only; elsewhere it leaves the input's rate. ASSUMPTION: 16 kHz everywhere (rung 3 + 5:
 * OF's own lowest; a third of a 48 kHz WAV's size under OF's 350 MB cap); overturned by a Live run refusing it.
 */
export const VOICE_WAV_RATE = 16_000;
/** The containers a recording is asked for: video mp4 where the browser records it, then webm; voice OF's mp3, then ogg. */
const RECORD_TYPES = { audio: ["audio/mpeg", "audio/ogg"], video: ["video/mp4", "video/webm"] } as const;
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

/**
 * A media stream's recorder: `stop(save)` ends it (save: the recording goes to `done` with its bare type), every track
 * stopped. `stop` returns whether `done` is still to come (it was recording and `save`).
 */
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
    stop(save: boolean): boolean {
      keep = save;
      if (rec.state !== "inactive") {
        rec.stop();
        return save;
      }
      for (const t of stream.getTracks()) t.stop();
      return false;
    },
  };
}

/** 16-bit PCM WAV bytes of one channel of `samples` (-1..1) at `rate` Hz (OF's voice fallback: one channel). */
export function wavBytes(samples: Float32Array, rate: number): ArrayBuffer {
  const out = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const ascii = (at: number, s: string) => [...s].forEach((c, i) => out.setUint8(at + i, c.charCodeAt(0)));
  ascii(0, "RIFF");
  out.setUint32(4, 36 + samples.length * 2, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  out.setUint32(16, 16, true); // fmt chunk size
  out.setUint16(20, 1, true); // PCM
  out.setUint16(22, 1, true); // channels
  out.setUint32(24, rate, true);
  out.setUint32(28, rate * 2, true); // bytes per second
  out.setUint16(32, 2, true); // block align
  out.setUint16(34, 16, true); // bits per sample
  ascii(36, "data");
  out.setUint32(40, samples.length * 2, true);
  samples.forEach((v, i) => {
    const c = Math.max(-1, Math.min(1, v));
    out.setInt16(44 + i * 2, c < 0 ? c * 0x8000 : c * 0x7fff, true);
  });
  return out.buffer;
}

/** Whether `file` is audio of a type OF's upload refuses (one VOICE_TYPES lacks): `voiceFile` re-encodes it. */
export function refusedAudio(file: File): boolean {
  const type = bareType(file.type);
  return type.startsWith("audio/") && !Object.hasOwn(VOICE_TYPES, type);
}
/** Why an audio file cannot be re-encoded: the browser has no Web Audio decoder. */
export const NO_DECODER = "this browser cannot convert audio";
/**
 * `file` as OF's upload takes it: as is unless it is audio of a type VOICE_TYPES lacks, which is decoded (Web Audio, in
 * the app's window, resampled to VOICE_WAV_RATE), mixed to one channel and re-encoded to WAV, same name, `.wav`.
 * Rejects when it cannot be decoded.
 */
export async function voiceFile(file: File): Promise<File> {
  if (!refusedAudio(file)) return file;
  const w = globalThis as unknown as { OfflineAudioContext?: typeof OfflineAudioContext; webkitOfflineAudioContext?: typeof OfflineAudioContext };
  const Ctx = w.OfflineAudioContext ?? w.webkitOfflineAudioContext;
  if (!Ctx) throw new Error(NO_DECODER);
  const audio = await new Ctx(1, 1, VOICE_WAV_RATE).decodeAudioData(await file.arrayBuffer());
  const n = audio.numberOfChannels;
  let mono = audio.getChannelData(0);
  if (n > 1) {
    mono = new Float32Array(audio.length);
    for (let c = 0; c < n; c++) audio.getChannelData(c).forEach((v, i) => (mono[i] += v / n));
  }
  return new File([wavBytes(mono, audio.sampleRate)], `${file.name.replace(/\.[^.]*$/, "")}.${VOICE_TYPES[WAV]}`, { type: WAV });
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

const stopTracks = (stream: MediaStream | string | null | undefined) => {
  if (stream && typeof stream !== "string") for (const t of stream.getTracks()) t.stop();
};

/** Where a recording's note goes (the button that opened it); `signal` stops it, nothing kept. */
interface RecordOptions {
  anchor: Element;
  signal?: AbortSignal;
}

/**
 * Record a voice message in OF's audio record panel (`.js-chat__audiorecord-panel`, in `doc`): the panel opens asking
 * nothing; its record button asks for the microphone and starts, and again stops and keeps; the timer runs to OF's 30:00
 * cap, which stops and keeps. Back (the default header's) and the recording header's close keep nothing. Resolves the
 * recorded File (OF's mp3 or ogg where MediaRecorder records them, else the browser's own, which the upload re-encodes:
 * `voiceFile`), or null: cancelled, aborted, no panel, or the microphone refused (a red note at `anchor` names why).
 */
function startVoiceRecorder(doc: Document, { anchor, signal }: RecordOptions): Promise<File | null> {
  const win = doc.defaultView!;
  const panel = doc.querySelector<HTMLElement>(AUDIO_PANEL);
  if (!panel || signal?.aborted) return Promise.resolve(null);
  return new Promise<File | null>((resolve) => {
    let rec: Recorder | null = null;
    let at = 0;
    let tick = 0;
    let asking = false;
    let over = false;
    const parts = () => ({
      idleHead: panel.querySelector<HTMLElement>(".js-message-header-default"),
      recHead: panel.querySelector<HTMLElement>(".js-message-header-recording"),
      timer: panel.querySelector<HTMLElement>(".js-chat__audio-record-timer"),
      button: panel.querySelector<HTMLButtonElement>(".b-float-panel__btn-record"),
      stopIcon: panel.querySelector<HTMLElement>(".js-chat__audio-record-state-stop"),
      recIcon: panel.querySelector<HTMLElement>(".js-chat__audio-record-state-rec"),
    });
    const show = (recording: boolean) => {
      const p = parts();
      p.idleHead?.classList.toggle("g-hidden", recording);
      p.recHead?.classList.toggle("g-hidden", !recording);
      p.stopIcon?.classList.toggle("g-hidden", !recording);
      p.recIcon?.classList.toggle("g-hidden", recording);
      if (p.timer) p.timer.textContent = ` ${clock(recording ? Date.now() - at : 0)} / ${clock(VOICE_MAX_MS)} `;
    };
    const finish = (file: File | null) => {
      if (over) return;
      over = true;
      resolve(file);
    };
    const close = (save: boolean) => {
      win.clearInterval(tick);
      const r = rec;
      rec = null;
      panel.style.display = "none";
      doc.body.classList.remove("open-panel");
      doc.removeEventListener("click", onClick, true);
      signal?.removeEventListener("abort", onAbort);
      if (!r?.stop(save)) finish(null);
    };
    const start = async () => {
      asking = true;
      const stream = await streamFor(win, "audio").finally(() => (asking = false));
      if (over || panel.style.display === "none") return stopTracks(stream);
      if (typeof stream === "string") {
        close(false);
        return note(doc, anchor, stream, true);
      }
      rec = recorder(win, stream, "audio", (blob, type) => finish(new File([blob], `voice-${Date.now()}.${VOICE_TYPES[type] ?? (/mp4/.test(type) ? "m4a" : "webm")}`, { type })));
      rec.start();
      at = Date.now();
      show(true);
      tick = win.setInterval(() => {
        if (Date.now() - at >= VOICE_MAX_MS) return close(true);
        show(true);
      }, 250);
    };
    const onClick = (ev: MouseEvent) => {
      const t = ev.target as Element | null;
      if (!t?.closest || !panel.contains(t)) return;
      const button = parts().button;
      if (button && t.closest(".b-float-panel__btn-record") === button) {
        ev.preventDefault();
        if (rec) return close(true);
        if (!asking) void start();
        return;
      }
      // The default header's Back and the recording header's close: nothing is kept.
      if (t.closest("a[aria-label='Back'], .js-message-header-recording button")) {
        ev.preventDefault();
        ev.stopPropagation();
        close(false);
      }
    };
    const onAbort = () => close(false);
    panel.style.display = "";
    doc.body.classList.add("open-panel");
    // Its record and close buttons are this recorder's: Wired, so bindWrites' fallback never notes them Read-only (a
    // trusted click runs this capture listener's microtasks first, so a later Read-only note would hide its own).
    for (const b of panel.querySelectorAll(".b-float-panel__btn-record, .js-message-header-recording button")) b.setAttribute("data-oi-wired", "");
    show(false);
    doc.addEventListener("click", onClick, true);
    signal?.addEventListener("abort", onAbort);
  });
}

/**
 * Record a video message in OF's video-js recorder (`.b-chat__video-message__preview`, in `doc`): asks for the camera at
 * once and previews it; its Record button starts, and again stops and keeps; OF's 05:00 cap stops and keeps; its close
 * keeps nothing. Resolves the recorded File (mp4 where MediaRecorder records it, else webm), or null: closed, aborted,
 * no recorder, or the camera refused (a red note at `anchor` names why).
 */
function startVideoRecorder(doc: Document, { anchor, signal }: RecordOptions): Promise<File | null> {
  const win = doc.defaultView!;
  const box = doc.querySelector<HTMLElement>(VIDEO_BOX);
  if (!box || signal?.aborted) return Promise.resolve(null);
  return new Promise<File | null>((resolve) => {
    let stream: MediaStream | null = null;
    let rec: Recorder | null = null;
    let timer = 0;
    let over = false;
    const parts = () => ({
      tech: box.querySelector<HTMLVideoElement>("video.vjs-tech"),
      button: box.querySelector<HTMLButtonElement>(".vjs-record-button"),
      indicator: box.querySelector<HTMLElement>(".vjs-record-indicator"),
      liveIcon: box.querySelector<HTMLElement>(".b-chat__videorec-live-icon"),
      liveLabel: box.querySelector<HTMLElement>(".b-chat__videorec-live-label"),
    });
    const show = (recording: boolean) => {
      const p = parts();
      p.button?.classList.toggle("vjs-icon-record-start", !recording);
      p.button?.classList.toggle("vjs-icon-record-stop", recording);
      if (p.button) {
        p.button.title = recording ? "Stop" : "Record";
        const t = p.button.querySelector(".vjs-control-text");
        if (t) t.textContent = recording ? "Stop" : "Record";
      }
      p.indicator?.classList.toggle("vjs-hidden", !recording);
      p.liveIcon?.classList.toggle("g-hidden", !recording);
      p.liveLabel?.classList.toggle("g-hidden", !recording);
    };
    const finish = (file: File | null) => {
      if (over) return;
      over = true;
      resolve(file);
    };
    const close = (save: boolean) => {
      win.clearTimeout(timer);
      doc.removeEventListener("click", onClick, true);
      signal?.removeEventListener("abort", onAbort);
      const r = rec;
      rec = null;
      const pending = r ? r.stop(save) : (stopTracks(stream), false);
      stream = null;
      const p = parts();
      if (p.tech) p.tech.srcObject = null;
      show(false);
      p.button?.classList.add("vjs-hidden");
      box.classList.add("g-hidden");
      if (!pending) finish(null);
    };
    const toggle = () => {
      if (!stream) return;
      if (rec) return close(true);
      rec = recorder(win, stream, "video", (blob, type) => finish(new File([blob], `video-${Date.now()}.${/mp4/.test(type) ? "mp4" : "webm"}`, { type })));
      rec.start();
      show(true);
      timer = win.setTimeout(() => close(true), VIDEO_MAX_MS);
    };
    const onClick = (ev: MouseEvent) => {
      const t = ev.target as Element | null;
      if (!t?.closest || !box.contains(t)) return;
      if (t.closest(".js-video-message-close")) {
        ev.preventDefault();
        return close(false);
      }
      if (t.closest(".vjs-record-button")) {
        ev.preventDefault();
        toggle();
      }
    };
    const onAbort = () => {
      if (stream || rec) return close(false);
      // Still asking: the stream granted later is stopped at once.
      signal?.removeEventListener("abort", onAbort);
      finish(null);
    };
    signal?.addEventListener("abort", onAbort);
    void streamFor(win, "video").then((got) => {
      if (over) return stopTracks(got);
      if (typeof got === "string") {
        signal?.removeEventListener("abort", onAbort);
        note(doc, anchor, got, true);
        return finish(null);
      }
      stream = got;
      const p = parts();
      box.classList.remove("g-hidden");
      p.button?.classList.remove("vjs-hidden");
      p.button?.setAttribute("data-oi-wired", "");
      if (p.tech) {
        p.tech.muted = true;
        p.tech.srcObject = got;
        void p.tech.play?.()?.catch?.(() => {});
      }
      show(false);
      doc.addEventListener("click", onClick, true);
    });
  });
}

type Recorder = ReturnType<typeof recorder>;

/** The capture whose recorder markup (OF's audio record panel, the video-js recorder) a page without it borrows. */
const RECORDER_PAGE = "/of-mirror/pages/new-post/index.html";

/**
 * `doc`'s copy of New post's capture (fetched same-origin, never the Relay, parsed inertly), once per page load: keyed
 * by the page's body, so markup put in anew fetches again. A failed fetch is dropped, so the next Record asks again.
 */
const RECORDER_SRC = new WeakMap<HTMLElement, Promise<Document>>();
function recorderSource(doc: Document): Promise<Document> {
  const page = doc.body;
  let src = RECORDER_SRC.get(page);
  if (!src) {
    src = doc.defaultView!.fetch(RECORDER_PAGE).then(async (res) => {
      if (!res.ok) throw new Error(`recorder markup: ${res.status}`);
      return new DOMParser().parseFromString(await res.text(), "text/html");
    });
    const mine = src;
    RECORDER_SRC.set(page, mine);
    mine.catch(() => RECORDER_SRC.get(page) === mine && RECORDER_SRC.delete(page));
  }
  return src;
}

/**
 * Fetch the recorder markup a page without it borrows (Home) ahead of a Record click, so the click draws OF's recorder
 * at once, as OF (which renders it with the composer) does, not one round trip later. A failure here is silent: the
 * click asks again and notes it.
 */
export function prefetchRecorder(doc: Document): void {
  if (doc.querySelector(AUDIO_PANEL) && doc.querySelector(VIDEO_BOX)) return;
  recorderSource(doc).catch(() => {});
}

/**
 * Put OF's recorder markup into `doc` when it has none (Home's captures: OF renders it with the composer, the capture did
 * not keep it): the audio record panel and the video-js recorder from New post's capture (recorderSource), after the
 * composer's form as there, with the stylesheets and icons they use that `doc` lacks.
 */
async function ensureRecorder(doc: Document): Promise<void> {
  if (doc.querySelector(AUDIO_PANEL) && doc.querySelector(VIDEO_BOX)) return;
  const from = await recorderSource(doc);
  if (doc.querySelector(AUDIO_PANEL) && doc.querySelector(VIDEO_BOX)) return;
  const form = doc.querySelector("form.b-create-post-form");
  const audio = from.querySelector(AUDIO_PANEL);
  const video = from.querySelector(VIDEO_BOX)?.parentElement;
  if (!form || !audio || !video) throw new Error("no recorder markup");
  const nodes = [audio, video].map((n) => doc.importNode(n, true) as HTMLElement);
  form.after(...nodes);
  const head = doc.head;
  const have = new Set([...doc.querySelectorAll("link[rel='stylesheet']")].map((l) => l.getAttribute("href")));
  for (const link of from.querySelectorAll("link[rel='stylesheet']")) if (!have.has(link.getAttribute("href"))) head.append(doc.importNode(link, true));
  const sprite = doc.querySelector("svg symbol")?.parentElement;
  for (const use of nodes.flatMap((n) => [...n.querySelectorAll("use")])) {
    const id = (use.getAttribute("href") ?? use.getAttribute("xlink:href") ?? "").replace(/^#/, "");
    const symbol = id && !doc.getElementById(id) ? from.getElementById(id) : null;
    if (symbol && sprite) sprite.append(doc.importNode(symbol, true));
  }
}

/** Where a kept recording goes: its File, and the button that started it (for an upload's note). */
export type TakeRecording = (files: File[], anchor: Element) => void;

/**
 * A document's recordings (the voice and video recorders' sessions). They outlive a bind: useOfChat rebinds the same
 * frame document when the chat's details change (its name, mute state, tips flag), useOfPost when the model's details
 * load, and a recording (or a permission prompt) must go on through that, its File going to the latest bind's `take`.
 * Only when no bind of the same draft takes the document back (by the end of the task) is it aborted, nothing kept.
 */
interface Live {
  key: string;
  owners: number;
  dead: boolean;
  take: TakeRecording;
  stop: AbortController;
  voice: boolean;
  video: boolean;
}
const LIVE = new WeakMap<Document, Live>();
/** Stop `live`'s recordings, keeping nothing. */
function stopLive(live: Live) {
  live.dead = true;
  live.stop.abort();
}

/** A bind's handle on its document's recordings (recordSession). */
export interface RecordSession {
  /** Whether a `kind` recording is going (no `kind`: either). */
  busy(kind?: "voice" | "video"): boolean;
  /**
   * Record a `kind` message in OF's recorder (its note at `anchor`); a kept File goes to the latest bind's take. `borrow`:
   * first put OF's recorder markup into the document when it has none (Home); a failure there is a red note at `anchor`.
   */
  record(kind: "voice" | "video", anchor: Element, borrow?: boolean): void;
  /** This bind is over: unless a bind of the same draft takes the document back in this task, its recordings stop. */
  release(): void;
}

/** Join `doc`'s recordings for draft `key` (another draft's stop, nothing kept); this bind's `take` gets what is kept. */
export function recordSession(doc: Document, key: string, take: TakeRecording): RecordSession {
  let live = LIVE.get(doc);
  if (live && (live.dead || live.key !== key)) {
    if (!live.dead) stopLive(live);
    live = undefined;
  }
  if (!live) {
    live = { key, owners: 0, dead: false, take, stop: new AbortController(), voice: false, video: false };
    LIVE.set(doc, live);
  }
  const L: Live = live;
  L.owners++;
  L.take = take;
  return {
    busy: (kind) => (kind ? L[kind] : L.voice || L.video),
    record(kind, anchor, borrow = false) {
      L[kind] = true;
      const opts = { anchor, signal: L.stop.signal };
      const start = () => (kind === "voice" ? startVoiceRecorder(doc, opts) : startVideoRecorder(doc, opts));
      void (borrow ? ensureRecorder(doc).then(start) : start()).then(
        (file) => {
          L[kind] = false;
          if (file && !L.dead) L.take([file], anchor);
        },
        (e) => {
          L[kind] = false;
          note(doc, anchor, `Could not record: ${message(e)}`, true);
        },
      );
    },
    release() {
      L.owners--;
      queueMicrotask(() => {
        if (L.owners > 0 || L.dead) return;
        stopLive(L);
        if (LIVE.get(doc) === L) LIVE.delete(doc);
      });
    },
  };
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
  const rec = recordSession(doc, tools.key ?? "", tools.take);

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
      if (voiceBtn.disabled || rec.busy("voice") || !audioPanel || !ready(voiceBtn)) return;
      return rec.record("voice", voiceBtn);
    }
    if (videoBtn && t.closest(VIDEO_BTN) === videoBtn) {
      ev.preventDefault();
      if (videoBtn.disabled || rec.busy("video") || !videoBox || !ready(videoBtn)) return;
      return rec.record("video", videoBtn);
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
      rec.release();
      for (const type of DRAG) area?.removeEventListener(type, onDrag as EventListener);
      doc.removeEventListener("click", onClick, true);
      doc.removeEventListener("input", onInput);
      doc.removeEventListener("keydown", onKey);
      for (const c of cleanups) c();
      doc.getElementById(PREVIEW)?.remove();
    },
  };
}
