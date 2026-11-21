"use client";

/**
 * Go live (streaming/index) with the desktop Go live window (ticket 127, D28). Inflowwww cannot stream, so the mirror's
 * Start Live Video is disabled with the Not-yet title (scripts/of-mirror.mjs streamingPage). With the Relay's
 * OF_LIVE_WINDOW_ENABLED switch on (GET /api/of/live-window answers; its 404 = off):
 * - in the desktop app, Start opens OnlyFans's own Go live page for the selected Creator in a desktop window
 *   (`fasttShell.openGoLive(creatorId)`: only the id crosses; the desktop's main process reads the session from the
 *   Relay, so this page never sees it);
 * - in a browser (or a desktop app too old to have the call), Start becomes "Download the Inflowwww app", opening /download.
 * Switch off, a failed probe or another page: nothing changes, today's disabled Start.
 *
 * ASSUMPTION: the ticket's "Go live and Start" are Go live's page (reached from the "Go live" story tile and nav) and its
 * one action, Start Live Video; the camera's status line says what Start does instead of Not available. Overturned by:
 * another Go live control the owner means.
 */

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
/** The Creator has no Relay session: the desktop opened OF's login page, unfilled, for a person to sign in. */
export const OPENED_SIGN_IN = "No OnlyFans session for this Creator: sign in to OnlyFans in the Go live window";
const FAILED = "Couldn't open Go live. Try again.";

export interface GoLiveResult {
  ok: boolean;
  /** Opened unseeded on OF's login page (the Relay had no session). */
  signIn?: boolean;
  error?: string;
}

export interface GoLiveEnv {
  desktop: boolean;
  accountId: string | null;
  /** The desktop bridge's call (`fasttShell.openGoLive`); absent on the web and in an older desktop app. */
  open?: (creatorId: string) => Promise<GoLiveResult>;
  download: () => void;
}

/** Wire Go live's Start in `doc` for `env`; the returned unbind puts back today's disabled Start and status. */
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

/** On Go live: Start per the switch, the desktop bridge and the selected Creator, bound on every frame load. */
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
