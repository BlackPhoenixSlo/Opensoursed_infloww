"use client";


import { applyScript, type PickedScript } from "@/lib/ofMirrorChat";
import { FORM_TAGS } from "@/lib/ofMirrorChatShared";
import { countdown, plainText } from "@/lib/ofMirrorThread";
import { note, NOT_YET, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import type { MenuMessage, MessageMenuContext } from "@/lib/ofMirrorMessageMenu";

const EXTRAS = "data-oi-bubble-extras";
const priced = (m: MenuMessage) => !m.isTip && (m.price ?? 0) > 0;

export function bubbleExtras(m: MenuMessage, left: number, mine: boolean): { countdown: string | null; copyDraft: boolean; unsendPpv: boolean } {
  return { countdown: mine && left > 0 ? countdown(left) : null, copyDraft: mine && priced(m), unsendPpv: mine && priced(m) && left > 0 };
}

export function scriptFromMessage(m: MenuMessage): PickedScript {
  const ids = (xs: unknown[]) => xs.map(Number).filter((id) => Number.isFinite(id));
  const forms = (m.releaseForms ?? []).filter((f) => Number.isFinite(Number(f.id)));
  const tags = forms.map((f) => ({ id: Number(f.id), type: f.type ?? "user", name: f.name ?? "" }));
  return {
    text: plainText(m.text),
    displayText: m.text ?? undefined,
    price: priced(m) ? Number(m.price) : 0,
    lockedText: !!m.lockedText,
    media: ids((m.media ?? []).map((x) => x.id)).map((id) => ({ id })),
    previews: ids(m.previews ?? []),
    taggedUsers: tags.filter((t) => !FORM_TAGS.includes(t.type)).map((t) => t.id),
    ...(tags.length ? { tags } : {}),
    gifId: null,
  };
}

export type UnsendAction = (m: MenuMessage, anchor: HTMLElement, live: () => boolean) => { close(): void } | null;

export type BubbleExtrasContext = Pick<MessageMenuContext, "chat" | "message" | "left" | "storage" | "accountId"> & { unsend: UnsendAction };

export function bindBubbleExtras(doc: Document, ctx: BubbleExtrasContext): () => void {
  let bound = true;
  let confirming: { close(): void } | null = null;

  const drawExtras = () => {
    for (const host of doc.querySelectorAll<HTMLElement>(".b-chat__message.m-from-me[data-oi-msg]")) {
      const m = ctx.message(host.dataset.oiMsg!);
      const x = m ? bubbleExtras(m, ctx.left(m), true) : { countdown: null, copyDraft: false, unsendPpv: false };
      let box = host.querySelector<HTMLElement>(`[${EXTRAS}]`);
      if (!x.countdown && !x.copyDraft && !x.unsendPpv) {
        box?.remove();
        continue;
      }
      if (!box) {
        box = doc.createElement("span");
        box.setAttribute(EXTRAS, "");
        box.style.cssText = "display:inline-flex;gap:8px;margin-left:8px;align-items:center";
        (host.querySelector(".b-chat__message__time") ?? host).append(box);
      }
      for (const [key, label, want] of [["countdown", "Countdown", x.countdown], ["copy-draft", "Copy as draft", x.copyDraft], ["unsend-ppv", "Unsend PPV", x.unsendPpv]] as const) {
        let el = box.querySelector<HTMLElement>(`[data-oi-bubble='${key}']`);
        if (!want) {
          el?.remove();
          continue;
        }
        if (!el) {
          el = doc.createElement(key === "countdown" ? "span" : "button");
          el.dataset.oiBubble = key;
          el.setAttribute("data-oi-wired", "");
          el.title = NOT_YET;
          if (key === "countdown") {
            el.setAttribute("role", "timer");
            el.setAttribute("aria-label", label);
          } else {
            (el as HTMLButtonElement).type = "button";
            el.textContent = label;
            el.style.cssText = "background:none;border:0;padding:0;cursor:pointer;font:inherit;color:#00aff0";
          }
          box.append(el);
        }
        if (typeof want === "string" && el.textContent !== want) el.textContent = want;
      }
    }
  };
  const extra = (btn: HTMLElement) => {
    const host = btn.closest<HTMLElement>("[data-oi-msg]");
    const m = host ? ctx.message(host.dataset.oiMsg!) : undefined;
    if (!host || !m) return note(doc, btn, "This message has not loaded yet");
    const x = bubbleExtras(m, ctx.left(m), host.classList.contains("m-from-me"));
    if (btn.dataset.oiBubble === "copy-draft") {
      if (!x.copyDraft) return void btn.remove();
      if (!ctx.storage || !ctx.accountId || !ctx.chat) return note(doc, btn, SELECT_MODEL);
      return applyScript(ctx.storage, ctx.accountId, ctx.chat, scriptFromMessage(m), doc);
    }
    if (!x.unsendPpv) return void btn.remove();
    confirming = ctx.unsend(m, btn, () => bound);
  };
  const onClick = (ev: MouseEvent) => {
    const btn = (ev.target as Element | null)?.closest?.<HTMLElement>(`[${EXTRAS}] button[data-oi-bubble]`);
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    extra(btn);
  };
  const redraws = doc.defaultView ? new doc.defaultView.MutationObserver(() => draw()) : null;
  const draw = () => {
    drawExtras();
    redraws?.takeRecords();
  };
  draw();
  const ticker = doc.defaultView?.setInterval(draw, 1000);
  redraws?.observe(doc.querySelector(".b-chat__messages-wrapper") ?? doc.body, { childList: true, subtree: true });
  doc.addEventListener("click", onClick, true);
  return () => {
    bound = false;
    confirming?.close();
    confirming = null;
    doc.defaultView?.clearInterval(ticker);
    redraws?.disconnect();
    doc.removeEventListener("click", onClick, true);
    doc.querySelectorAll(`[${EXTRAS}]`).forEach((b) => b.remove());
  };
}
