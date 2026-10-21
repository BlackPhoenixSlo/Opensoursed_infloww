"use client";

/**
 * OF's "Post statistics" popup (POST_STAT, chunk 60969 module 228572), opened by a post's "Full stat" and its More menu's
 * "View detailed statistics": "Some statistics may be delayed or approximated", the multi-line chart of the picked
 * figures and a row per figure (MultipleLineChartRadioButton: a check, the title, the count, linked to its list when OF
 * links it, and a sum), then Duration / Average when the post has a view duration. Its numbers are the Relay's
 * `/posts/stats?post_id` (OF's `/posts/{id}/stats?withChart=true`), mapped as OF's store does (app.js `setPostStat`).
 * That route is the phase-1 Relay's (omf-statistics-relay-2): callers enable the buttons only when postStatsProbe finds
 * it (Statistics' Full stat and menus, useOfStats; a post row's Post statistics, useOfPostActions).
 */

import { chartLabels, drawLines, type ValueKind } from "@/lib/ofMirrorChart";
import { usd } from "@/lib/ofMirrorMoney";
import { at, elOf, isObj, num } from "@/lib/ofMirrorStatsDom";
import { openUsers, readsCtx, usersLink, type UserListKind } from "@/lib/ofMirrorStatsKit";
import { NOT_YET, openModal } from "@/lib/ofMirrorWrites";
import { relay, RelayError } from "@/lib/relay";

export const POST_STATS_PROBE = "/api/of/v2/posts/stats";
/**
 * Whether the Relay has the phase-1 per-item reads (omf-statistics-relay-2, `/posts/stats` among them): that route
 * without a post id answers 422 (its own check, no OnlyFans request); an older Relay answers 404, and a role without
 * Statistics 403. The query answers true only for the 422.
 */
export const postStatsProbe = (accountId: string | null | undefined) => ({
  queryKey: ["of-mirror-data", accountId, POST_STATS_PROBE],
  queryFn: () => relay.get<unknown>(POST_STATS_PROBE, { accountId }).then(() => false, (e: unknown) => e instanceof RelayError && e.status === 422),
});

/** The Relay route of a post's stats, or null for a non-numeric id. */
export const postStatsRoute = (id: unknown) => (/^\d+$/.test(String(id ?? "")) ? `/api/of/v2/posts/stats?post_id=${String(id)}` : null);

type Point = { date?: string; count?: unknown };
const pts = (v: unknown): Point[] => (Array.isArray(v) ? (v as Point[]) : []);
const values = (list: Point[]) => list.map((p) => num(p.count) ?? 0);

/** One of OF's figure rows (datasetData): its id, title, colour, row class, count, sum, list, chart and partner line. */
export interface StatRow {
  id: string;
  title: string;
  color: string;
  className: string;
  count: number;
  sum?: number;
  list?: UserListKind;
  tooltip?: string;
  chart: Point[];
  hidden?: boolean;
  relatedTo?: string;
}

/** OF's figure rows for a `/posts/{id}/stats` reply (228572's datasetData over setPostStat's fields), in its order. */
export function postStatRows(stats: unknown, isStream = false): StatRow[] {
  if (!isObj(stats)) return [];
  const n = (k: string) => num(stats[k]) ?? 0;
  return [
    { id: "purchases", title: "Purchases", color: "#7CB342", className: "m-purchases", count: n("purchasedCount"), sum: n("purchasedSumm"), list: "post-buyers", tooltip: isStream ? "This number includes stream purchases" : undefined, chart: pts(stats.purchasesChart) },
    { id: "views", title: "Views", color: "#00AFF0", className: "m-viewers", count: n("lookCount"), chart: pts(stats.lookChart) },
    { id: "uniq-views", title: "Unique viewers", color: "#6b6b6b", className: "m-unique-viewers", count: n("uniqueLookCount"), chart: pts(stats.uniqueLookChart), hidden: true, relatedTo: "views" },
    // OF links Likes to the post's likers (UserList PostLikes: `/posts/{id}/favorites`).
    { id: "likes", title: "Likes", color: "#EC407A", className: "m-likes", count: n("likeCount"), list: "post-likes", chart: pts(stats.likeChart) },
    { id: "comment", title: "Comments", color: "#FFA000", className: "m-comments", count: n("commentCount"), chart: pts(stats.commentChart) },
    { id: "tips", title: "Tips", color: "#9575CD", className: "m-tips", count: n("tipCount"), sum: num(stats.tipSum) ?? 0, list: "post-tips", chart: pts(stats.tipChart) },
  ];
}

/** OF's view duration (moment-duration-format "HH:mm:ss", its leading zero units trimmed). */
export function durationText(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const parts = [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60];
  while (parts.length > 1 && parts[0] === 0) parts.shift();
  return parts.map((p) => String(p).padStart(2, "0")).join(":");
}

/** OF's check (CheckboxOF with `m-pseudo-checkbox`). */
function check(doc: Document, id: string, on: boolean) {
  const el = elOf(doc);
  const box = el("span", "b-input-radio__container m-pseudo-checkbox");
  box.setAttribute("at-attr", "checkbox");
  const input = el("input", "b-input-radio") as HTMLInputElement;
  input.type = "checkbox";
  input.id = id;
  input.name = id;
  input.checked = on;
  input.tabIndex = -1;
  input.setAttribute("data-oi-wired", "");
  box.append(input, el("label", "b-input-radio__text m-break-word m-without-text"), el("span", "b-input-radio__label"));
  return box;
}

/** Fill the popup's `body` with `stats` (the Relay's reply) for post `postId`. */
export function fillPostStats(doc: Document, body: HTMLElement, postId: unknown, stats: unknown, tz: string | null, isStream = false) {
  const el = elOf(doc);
  body.replaceChildren(el("div", "g-sm-text g-gray-text", " Some statistics may be delayed or approximated "));
  const rows = postStatRows(stats, isStream);
  if (!rows.length) return;
  const active = new Set(rows.map((r) => r.id));
  const tab = el("div", "b-tab-stats m-current");
  const wrap = el("div", "b-chart__wrapper b-chart");
  const canvas = el("canvas", "b-chart__multiple-line") as HTMLCanvasElement;
  canvas.height = 200; // OF's chartHeight
  canvas.style.height = "200px";
  wrap.append(canvas);
  const labels = chartLabels(pts(at(stats, "commentChart")).map((p) => p.date), tz);
  const draw = () =>
    drawLines(canvas, {
      labels,
      lines: rows.filter((r) => active.has(r.id)).map((r) => ({ title: r.title, color: r.color, values: values(r.chart), kind: "count" as ValueKind })),
    });
  const list = el("div", "b-stats-row__content");
  for (const r of rows.filter((x) => !x.hidden)) {
    const row = el("div", `b-stats-row__label m-border-line m-checkbox g-radio-container ${r.className} m-current`);
    row.setAttribute("data-oi-stat-row", r.id);
    row.setAttribute("data-oi-wired", "");
    row.append(check(doc, r.title, true));
    row.append(el("span", "b-stats-row__name g-md-text flex-grow-1", ` ${r.title} `));
    if (r.tooltip) {
      const info = el("span", "g-icon-info m-with-round-hover");
      info.title = r.tooltip;
      info.tabIndex = 0;
      row.append(info);
    }
    const val = el("div", "b-stats-row__val");
    const count = r.count.toLocaleString("en-US");
    if (r.list && r.count > 0 && postId !== undefined) {
      const link = usersLink(doc, count, r.list, postId);
      link.addEventListener("click", (ev) => {
        ev.stopPropagation(); // OF's doEmit: the list opens, the line stays
        ev.preventDefault();
        openUsers(doc, link.getAttribute("data-oi-users")!, link);
      });
      val.append(link);
    } else val.append(el("span", "", ` ${count} `));
    if (r.sum !== undefined) val.append(el("span", "d-inline-flex", ` (${usd(r.sum)}) `));
    row.append(val);
    row.addEventListener("click", () => {
      // OF's toggleDatasetHandler: the row's line and the line related to it (Views' Unique viewers).
      const on = !active.has(r.id);
      for (const id of [r.id, ...rows.filter((x) => x.relatedTo === r.id).map((x) => x.id)]) {
        if (on) active.add(id);
        else active.delete(id);
      }
      row.classList.toggle("m-current", on);
      const input = row.querySelector<HTMLInputElement>("input");
      if (input) input.checked = on;
      draw();
    });
    list.append(row);
  }
  tab.append(wrap, list);
  const look = num(at(stats, "lookDuration"));
  if (look) {
    const avg = num(at(stats, "lookDurationAverage"));
    const d = el("div", "b-stats-row__content");
    const label = el("div", "b-stats-row__label m-checkbox m-current m-without-switcher m-border-line m-first-el");
    const name = el("span", "b-stats-row__name g-md-text", " Duration ");
    if (avg) name.append(el("span", "b-stats-row__name g-md-text m-aside", " / Average "));
    const v = el("div", "b-stats-row__val");
    v.append(el("span", "", ` ${durationText(look)} `));
    if (avg) v.append(el("span", "g-gray-text", ` / ${durationText(avg)} `));
    label.append(name, v);
    d.append(label);
    tab.append(d);
  }
  body.append(tab);
  draw();
}

/** Open the popup for post `postId`, read from the Relay. */
export function openPostStats(doc: Document, postId: unknown, tz: string | null, opener?: Element, isStream = false) {
  const route = postStatsRoute(postId);
  if (!route) return;
  const { close, modal } = openModal(doc, "oi-post-stats", "Post statistics", (body) => {
    body.append(elOf(doc)("div", "empty-message", "Loading…"));
  }, [{ text: "Close", className: "g-btn m-flat m-btn-gaps", onClick: () => close() }], opener);
  const body = modal.querySelector<HTMLElement>(".modal-body")!;
  body.classList.add("m-post-stats", "m-reset-body-padding-bottom");
  relay
    .get<unknown>(route, { accountId: readsCtx(doc).accountId })
    .then((stats) => {
      if (modal.isConnected) fillPostStats(doc, body, postId, stats, tz, isStream);
    })
    .catch((e: unknown) => {
      body.replaceChildren(elOf(doc)("div", "empty-message", `Couldn't load the statistics: ${e instanceof Error ? e.message : String(e)}`));
    });
}

/** A post's "Full stat" button: it opens the popup with the phase-1 Relay (`v3`), else disabled with the tooltip. */
export function fullStat(doc: Document, post: { id?: unknown; streamId?: unknown }, v3: boolean, tz: string | null) {
  const b = elOf(doc)("button", "g-btn m-flat m-btn-gaps m-ex-sm", " Full stat ") as HTMLButtonElement;
  b.type = "button";
  if (v3 && postStatsRoute(post.id)) {
    b.setAttribute("data-oi-wired", "");
    b.addEventListener("click", (ev) => {
      ev.preventDefault();
      openPostStats(doc, post.id, tz, b, !!post.streamId);
    });
  } else {
    b.disabled = true;
    b.title = NOT_YET;
  }
  return b;
}
