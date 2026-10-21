"use client";

/**
 * Settings > Streaming > Blocked users (settings/streaming/blocked), read-only, as OF's page draws its list (build
 * 202610091632: SettingsStreamingBlockedUsers): GET /streams/users/blocked?limit=10&offset=<n> ({list, hasMore}), read
 * page after page (OF: as the list scrolls; here up to MAX_PAGES); each user a `b-rows-lists__item` row (50px avatar,
 * name, @username) with OF's remove button, which stays disabled with the house tooltip (unblocking, like blocking by
 * username, is not written here). The form gets OF's bottom border when there are rows. No rows: no list, and no text
 * (OF has none); a failed read is swallowed, as OF's.
 */

import { useEffect, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { proxyImage } from "@/lib/mediaUrl";
import { plain } from "@/lib/ofMirrorData";
import { avatarOf, elOf, iconOf, type AvatarUser } from "@/lib/ofMirrorAvatar";
import { NOT_YET } from "@/lib/ofMirrorWrites";
import { relay } from "@/lib/relay";

export const BLOCKED_PAGE = "settings/streaming/blocked";
export const BLOCKED_PATH = "/api/of/v2/streams/users/blocked";
const LIMIT = 10;
const MAX_PAGES = 10;
/** OF's ListWrapper's scope: its rows' layout (80px avatar column, 72px rows) is styled under it. */
const SCOPE = "data-v-62b39f36";

export interface BlockedUser extends AvatarUser {
  displayName?: string | null;
  isVerified?: boolean;
}
interface Page {
  list?: BlockedUser[];
  hasMore?: boolean;
}

/** Every page of the list (OF's limit 10), up to MAX_PAGES. */
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

function row(doc: Document, u: BlockedUser, img: ((u: string) => string) | undefined): HTMLElement {
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
  // OF's UsernameBlock (size md): m-verified on the name makes room for the badge.
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
  remove.disabled = true;
  remove.title = NOT_YET;
  remove.append(iconOf(doc, "close"));
  item.append(icon, text, remove);
  return item;
}

/** Draw `users` under the block form in `doc` (replacing an earlier list). */
export function applyBlocked(doc: Document, users: BlockedUser[] | null | undefined, img?: (u: string) => string): void {
  const form = doc.querySelector<HTMLFormElement>("#content .b-settings__content form");
  if (!form) return;
  doc.querySelector("[data-oi-blocked-list]")?.remove();
  form.classList.toggle("g-border-bottom", !!users?.length);
  if (!users?.length) return;
  // OF's ListWrapper: its root (`b-rows-lists`, scoped styles data-v-62b39f36) with the page's classes.
  const list = elOf(doc)("div", "b-rows-lists b-menu-list g-border-bottom");
  list.setAttribute(SCOPE, "");
  list.setAttribute("at-attr", "");
  list.setAttribute("data-oi-blocked-list", "");
  list.append(...users.map((u) => row(doc, u, img)));
  form.after(list);
}

/** On Blocked users: the model's list (a selected model, or All's stand-in), drawn on every frame load. */
export function useOfStreamBlocked(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const on = src === `/of-mirror/pages/${BLOCKED_PAGE}.html`;
  const users = useQuery({
    queryKey: ["of-stream-blocked", accountId],
    queryFn: () => readBlocked((path) => relay.get<Page>(path, { accountId })),
    enabled: !!accountId && on,
    staleTime: 60 * 1000,
    retry: false,
  }).data;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    const img = (u: string) => proxyImage(u, accountId);
    const apply = () => {
      const doc = frame.contentDocument;
      if (doc?.body) applyBlocked(doc, users, img);
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => frame.removeEventListener("load", apply);
  }, [frameRef, src, on, users, accountId]);
}
