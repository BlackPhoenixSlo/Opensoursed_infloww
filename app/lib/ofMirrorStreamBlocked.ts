"use client";


import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { proxyImage } from "@/lib/mediaUrl";
import { plain } from "@/lib/ofMirrorData";
import { avatarOf, elOf, iconOf, type AvatarUser } from "@/lib/ofMirrorAvatar";
import { toast } from "@/lib/ofMirrorToast";
import { message, note, NOT_YET, ofConfirm, ofErrorMessage, SAVED_TOAST, type Ask } from "@/lib/ofMirrorWrites";
import { markNotYet, markWired } from "@/lib/ofMirrorTooltip";
import { useOfmNewWrites } from "@/lib/ofMirrorNewWrites";
import { relay } from "@/lib/relay";

export const BLOCKED_PAGE = "settings/streaming/blocked";
export const BLOCKED_PATH = "/api/of/v2/streams/users/blocked";
const LIMIT = 10;
const MAX_PAGES = 10;
const SCOPE = "data-v-62b39f36";

export interface BlockedUser extends AvatarUser {
  displayName?: string | null;
  isVerified?: boolean;
}
interface Page {
  list?: BlockedUser[];
  hasMore?: boolean;
}

export async function readBlocked(get: (path: string) => Promise<Page>): Promise<BlockedUser[]> {
  const users: BlockedUser[] = [];
  for (let i = 0; i < MAX_PAGES; i++) {
    const page = await get(`${BLOCKED_PATH}?limit=${LIMIT}${users.length ? `&offset=${users.length}` : ""}`);
    const list = Array.isArray(page?.list) ? page.list : [];
    users.push(...list);
    if (!page?.hasMore || !list.length) break;
  }
  return users;
}

function row(doc: Document, u: BlockedUser, img: ((u: string) => string) | undefined, writable: boolean): HTMLElement {
  const el = elOf(doc);
  const item = el("div", "b-rows-lists__item m-control-right m-roung-img-left");
  item.setAttribute(SCOPE, "");
  item.setAttribute("data-oi-blocked", String(u.id ?? ""));
  const icon = el("div", "b-rows-lists__item__icon m-size-lg");
  icon.append(avatarOf(doc, u, 50, img, ""));
  const text = el("div", "b-rows-lists__item__text");
  const sub = el("div", "b-rows-lists__item__subline");
  const r1 = el("div", "b-username-row m-gap-lg");
  const name = el("span", "b-username");
  const n = el("div", `g-user-name${u.isVerified ? " m-verified" : ""} m-md-size`, ` ${plain(u.name) || u.username || ""} `);
  if (u.isVerified) n.append(iconOf(doc, "verified", "g-icon m-verified"));
  name.append(n);
  r1.append(name);
  const r2 = el("div", "b-username-row");
  const real = el("span", "g-user-realname__wrapper m-nowrap-text");
  real.append(el("span", "g-user-username", ` @${u.username ?? ""} `));
  r2.append(real);
  sub.append(r1, r2);
  text.append(sub);
  const remove = el("button", "g-btn m-rounded m-reset-width m-thumb-r-center-pos m-btn-remove m-sm-icon-size b-btn-icon-reset") as HTMLButtonElement;
  remove.type = "button";
  remove.title = NOT_YET;
  if (writable) markWired(remove, false);
  else markNotYet(remove);
  remove.append(iconOf(doc, "close"));
  item.append(icon, text, remove);
  return item;
}

export function applyBlocked(doc: Document, users: BlockedUser[] | null | undefined, img: ((u: string) => string) | undefined, writable: boolean): void {
  const form = doc.querySelector<HTMLFormElement>("#content .b-settings__content form");
  if (!form) return;
  doc.querySelector("[data-oi-blocked-list]")?.remove();
  form.classList.toggle("g-border-bottom", !!users?.length);
  if (!users?.length) return;
  const list = elOf(doc)("div", "b-rows-lists b-menu-list g-border-bottom");
  list.setAttribute(SCOPE, "");
  list.setAttribute("at-attr", "");
  list.setAttribute("data-oi-blocked-list", "");
  list.append(...users.map((u) => row(doc, u, img, writable)));
  form.after(list);
}

export const STREAM_USERS = "/api/of/v2/streams/users";
export const blockPath = (username: string) => `${STREAM_USERS}/${encodeURIComponent(username)}/block`;
export const unblockPath = (id: string) => `${STREAM_USERS}/${encodeURIComponent(id)}/block`;
// Assumed OF username shape: 1-24 letters, digits, dot, underscore, hyphen (form maxlength 24; the Relay checks the same).
export const USERNAME = /^[A-Za-z0-9._-]{1,24}$/;
export const usernameOf = (v: string) => v.trim().replace(/^@/, "");
export const ENTER_USERNAME = "Enter a username";
export const UNBLOCK_ASK: Ask = { title: "Unblock user?", text: "They will be able to watch this model's streams again.", ok: "Unblock" };
const failed = (verb: string, e: unknown) => `Could not ${verb}: ${ofErrorMessage(e) ?? message(e)}`;

export interface StreamBlockHandlers {
  block(username: string): Promise<unknown>;
  unblock(id: string): Promise<unknown>;
}

export function bindStreamBlock(doc: Document, handlers: StreamBlockHandlers): () => void {
  const form = doc.querySelector<HTMLFormElement>("#content .b-settings__content form");
  const input = form?.querySelector<HTMLInputElement>("input[name='block-user-by-name']") ?? null;
  const button = form?.querySelector<HTMLButtonElement>("button[type='submit']") ?? null;
  if (!form || !input || !button) return () => {};
  for (const el of [input, button]) markWired(el, false);

  const block = () => {
    if (button.disabled) return;
    const name = usernameOf(input.value);
    if (!USERNAME.test(name)) return note(doc, input, ENTER_USERNAME, true);
    button.disabled = true;
    handlers.block(name).then(
      () => {
        input.value = "";
        toast(doc, SAVED_TOAST);
      },
      (e) => note(doc, input, failed("block", e), true),
    ).finally(() => (button.disabled = false));
  };

  const unblock = async (remove: HTMLButtonElement) => {
    const id = remove.closest("[data-oi-blocked]")?.getAttribute("data-oi-blocked");
    if (!id || remove.disabled || !(await ofConfirm(doc, UNBLOCK_ASK))) return;
    remove.disabled = true;
    handlers.unblock(id).then(
      () => undefined,
      (e) => {
        remove.disabled = false;
        note(doc, remove, failed("unblock", e), true);
      },
    );
  };

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    const remove = t.closest<HTMLButtonElement>("[data-oi-blocked-list] button.m-btn-remove");
    if (button.contains(t)) {
      ev.preventDefault();
      block();
    } else if (remove) {
      ev.preventDefault();
      void unblock(remove);
    }
  };
  const onSubmit = (ev: Event) => {
    if (ev.target !== form) return;
    ev.preventDefault();
    block();
  };
  doc.addEventListener("click", onClick);
  doc.addEventListener("submit", onSubmit);
  return () => {
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("submit", onSubmit);
    for (const el of [input, button]) markNotYet(el);
  };
}

export function useOfStreamBlocked(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const on = src === `/of-mirror/pages/${BLOCKED_PAGE}.html`;
  const users = useQuery({
    queryKey: ["of-stream-blocked", accountId],
    queryFn: () => readBlocked((path) => relay.get<Page>(path, { accountId })),
    enabled: !!accountId && on,
    staleTime: 60 * 1000,
    retry: false,
  }).data;
  const newWrites = useOfmNewWrites(on, accountId);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    const img = (u: string) => proxyImage(u, accountId);
    const reread = (r: unknown) => (qc.invalidateQueries({ queryKey: ["of-stream-blocked", accountId] }), r);
    const handlers: StreamBlockHandlers = {
      block: (username) => relay.post(blockPath(username), undefined, { accountId }).then(reread),
      unblock: (id) => relay.delete(unblockPath(id), { accountId }).then(reread),
    };
    let unbind: (() => void) | undefined;
    const apply = () => {
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      applyBlocked(doc, users, img, !!accountId && newWrites);
      unbind?.();
      unbind = accountId && newWrites ? bindStreamBlock(doc, handlers) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => {
      frame.removeEventListener("load", apply);
      unbind?.();
    };
  }, [frameRef, src, on, users, accountId, qc, newWrites]);
}
