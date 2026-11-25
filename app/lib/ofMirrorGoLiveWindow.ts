"use client";


import { useEffect, type RefObject } from "react";
import { useScope } from "@/contexts/ScopeContext";
import { BRAND_NAME } from "@/lib/brand";
import { note, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { useRelaySwitch } from "@/lib/ofMirrorNewWrites";

export const GO_LIVE_PAGE = "streaming/index";
export const LIVE_WINDOW_PATH = "/api/of/live-window";
export const DOWNLOAD_APP = `Download the ${BRAND_NAME} app`;
export const WEB_HINT = `Go live runs in the ${BRAND_NAME} desktop app`;
export const DESKTOP_HINT = "Start opens OnlyFans's own Go live page in a new window";
export const OPENED = "Go live opened in its own window";
export const OPENED_SIGN_IN = "No OnlyFans session for this Creator: sign in to OnlyFans in the Go live window";
const FAILED = "Couldn't open Go live. Try again.";

export interface GoLiveResult {
  ok: boolean;
  signIn?: boolean;
  error?: string;
}

export interface GoLiveEnv {
  desktop: boolean;
  accountId: string | null;
  open?: (creatorId: string) => Promise<GoLiveResult>;
  download: () => void;
}

export function bindGoLiveWindow(doc: Document, env: GoLiveEnv): () => void {
  const b = doc.querySelector<HTMLButtonElement>(".b-streaming__btn-start");
  if (!b) return () => {};
  const value = doc.querySelector(".b-stream-status-connect .b-text-progress__value") ?? doc.querySelector(".b-stream-status-connect");
  const was = { disabled: b.disabled, title: b.getAttribute("title"), text: b.textContent, status: value?.textContent ?? null };
  const viaApp = env.desktop && !!env.open;
  b.disabled = false;
  b.removeAttribute("title");
  b.setAttribute("data-oi-wired", "");
  if (!viaApp) b.textContent = ` ${DOWNLOAD_APP} `;
  if (value) value.textContent = viaApp ? DESKTOP_HINT : WEB_HINT;

  let busy = false;
  const onClick = (e: Event) => {
    e.preventDefault();
    if (!viaApp) return env.download();
    if (!env.accountId) return note(doc, b, SELECT_MODEL, true);
    if (busy) return;
    busy = true;
    env.open!(env.accountId)
      .then((r) => (r?.ok ? note(doc, b, r.signIn ? OPENED_SIGN_IN : OPENED, false, r.signIn ? 8000 : 3000) : note(doc, b, r?.error || FAILED, true)))
      .catch(() => note(doc, b, FAILED, true))
      .finally(() => (busy = false));
  };
  b.addEventListener("click", onClick);
  return () => {
    b.removeEventListener("click", onClick);
    b.disabled = was.disabled;
    if (was.title == null) b.removeAttribute("title");
    else b.setAttribute("title", was.title);
    b.removeAttribute("data-oi-wired");
    b.textContent = was.text;
    if (value) value.textContent = was.status;
    doc.getElementById("oi-note")?.remove();
  };
}

export function useOfGoLiveWindow(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const on = src === `/of-mirror/pages/${GO_LIVE_PAGE}.html`;
  const enabled = useRelaySwitch("of-live-window", LIVE_WINDOW_PATH, "enabled", on);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on || !enabled) return;
    const shell = typeof window !== "undefined" ? window.fasttShell : undefined;
    const env: GoLiveEnv = {
      desktop: shell?.isDesktop === true,
      accountId,
      // Only the creator id crosses; the desktop's main process reads the session from the Relay, so this page never sees it.
      open: shell?.openGoLive,
      download: () => window.open("/download", "_blank", "noopener"),
    };
    let unbind = () => {};
    const apply = () => {
      unbind();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindGoLiveWindow(doc, env) : () => {};
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => {
      frame.removeEventListener("load", apply);
      unbind();
    };
  }, [frameRef, on, enabled, accountId]);
}
