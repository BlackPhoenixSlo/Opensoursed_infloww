import { persistJSON, readJSON } from "./persist";
import { POPOUT_MODE_ROUTES } from "@/lib/chatSlots";
import type { FanId } from "@/lib/fanId";

export const SETTINGS_KEY = "chatterly:money-rail:settings:v1";
export const SMALL_ROW_CHOICES = [0, 1, 2, 3, 4] as const;
export const BIG_ROW_CHOICES = [5, 6, 7, 8] as const;

export const SURFACE_VALUES = ["inbox", "popup", "group", "other"] as const;

export type Surface = (typeof SURFACE_VALUES)[number];

export function surfaceOf(pathname: string | null): Surface {
  if (pathname?.startsWith("/group")) return "group";
  if (pathname === "/messages-pro" || (pathname !== null && POPOUT_MODE_ROUTES.has(pathname))) return "inbox";
  if (pathname?.startsWith("/messages-pro/")) return "popup";
  return "other";
}

export interface RailSettings {
  smallRows: number;
  bigRows: number;
  accounts: string[] | null;
  surfaces: Surface[] | null;
}

export const DEFAULT_SETTINGS: RailSettings = {
  smallRows: 1,
  bigRows: 6,
  accounts: null,
  surfaces: ["inbox", "popup", "group"],
};

function clampChoice(v: unknown, choices: readonly number[], fallback: number): number {
  return typeof v === "number" && choices.includes(v) ? v : fallback;
}

// Empty and complete picks both mean everywhere: a rail hidden on every surface has its only un-hide control inside itself.
export function parseSurfaces(v: unknown): Surface[] | null {
  if (!Array.isArray(v)) return null;
  const picked = SURFACE_VALUES.filter((s) => v.includes(s));
  return picked.length > 0 && picked.length < SURFACE_VALUES.length ? picked : null;
}

export function railVisibleOn(settings: RailSettings, surface: Surface): boolean {
  return !settings.surfaces || settings.surfaces.includes(surface);
}

export function withRailOn(settings: RailSettings, surface: Surface, on: boolean): RailSettings {
  const current = settings.surfaces ?? SURFACE_VALUES;
  const next = on ? [...current, surface] : current.filter((s) => s !== surface);
  return { ...settings, surfaces: parseSurfaces(next) };
}

function normalizeSettings(p: Partial<RailSettings>): RailSettings {
  return {
    smallRows: clampChoice(p.smallRows, SMALL_ROW_CHOICES, DEFAULT_SETTINGS.smallRows),
    bigRows: clampChoice(p.bigRows, BIG_ROW_CHOICES, DEFAULT_SETTINGS.bigRows),
    accounts:
      // An empty array would be a permanently blank rail; treat as all, same as null.
      Array.isArray(p.accounts) && p.accounts.length > 0
        ? p.accounts.filter((a): a is string => typeof a === "string")
        : null,
    surfaces:
      // null = user chose everywhere; missing = a save from before surfaces existed, so the house default.
      p.surfaces === null
        ? null
        : Array.isArray(p.surfaces)
          ? parseSurfaces(p.surfaces)
          : DEFAULT_SETTINGS.surfaces,
  };
}

// A write that could not land (full origin) is held so the pick still wins in this tab instead of snapping back.
let quotaFallback: RailSettings | null = null;

export function resetSettingsQuotaFallback(): void {
  quotaFallback = null;
}

export function readSettings(): RailSettings {
  if (quotaFallback) return normalizeSettings(quotaFallback);
  const p = readJSON<Partial<RailSettings>>(SETTINGS_KEY);
  return p ? normalizeSettings(p) : DEFAULT_SETTINGS;
}

export const SETTINGS_EVENT = "chatterly:money-rail:settings";

export function writeSettings(s: RailSettings): void {
  quotaFallback = persistJSON(SETTINGS_KEY, s) ? null : s;
  try {
    queueMicrotask(() => {
      try { window.dispatchEvent(new CustomEvent(SETTINGS_EVENT)); } catch { }
    });
  } catch { }
}

export function resolveRailAccounts(
  settings: RailSettings,
  active: readonly { id: string }[],
): string[] {
  const activeIds = active.map((a) => a.id);
  if (!settings.accounts) return activeIds;
  const picked = activeIds.filter((id) => settings.accounts!.includes(id));
  return picked.length > 0 ? picked : activeIds;
}


export interface DockState {
  open: boolean;
  x: number | null;
  y: number | null;
  anchor: "top" | "bottom";
}

export const DEFAULT_DOCK: DockState = { open: false, x: null, y: null, anchor: "bottom" };

function stateKey(surface: Surface): string {
  return `chatterly:money-rail:v2:${surface}`;
}

export function readDock(surface: Surface): DockState {
  const p = readJSON<Partial<DockState>>(stateKey(surface));
  if (!p) return DEFAULT_DOCK;
  return {
    open: p.open === true,
    x: typeof p.x === "number" && Number.isFinite(p.x) ? p.x : null,
    y: typeof p.y === "number" && Number.isFinite(p.y) ? p.y : null,
    anchor: p.anchor === "bottom" ? "bottom" : "top",
  };
}

export function writeDock(surface: Surface, s: DockState): void {
  persistJSON(stateKey(surface), s);
}


const SNAPSHOT_KEY = "chatterly:money-rail:snapshot:v1";
const SNAPSHOT_TTL_MS = 3 * 24 * 60 * 60 * 1000;
export const SNAPSHOT_MAX_ITEMS = 20;

export interface NotificationUser {
  id?: FanId;
  name?: string;
  username?: string;
  avatar?: string;
}
export interface NotificationItem {
  id?: number | string;
  type?: string;
  text?: string;
  description?: string;
  createdAt?: string;
  user?: NotificationUser;
  fromUser?: NotificationUser;
  replacePairs?: Record<string, string>;
  [k: string]: unknown;
}

export interface SnapshotEntry {
  at: number;
  items: NotificationItem[];
}
export type SnapshotMap = Record<string, SnapshotEntry>;

export function snapshotKeyOf(aid: string, type: string): string {
  return `${aid}:${type}`;
}

function slimUser(u?: NotificationUser): NotificationUser | undefined {
  if (!u) return undefined;
  return { id: u.id, name: u.name, username: u.username, avatar: u.avatar };
}

export function slimNotif(n: NotificationItem): NotificationItem {
  return {
    id: n.id,
    type: n.type,
    text: n.text,
    description: n.description,
    createdAt: n.createdAt,
    user: slimUser(n.user),
    fromUser: slimUser(n.fromUser),
    replacePairs: n.replacePairs,
  };
}

export function readMoneySnapshot(): SnapshotMap {
  const parsed = readJSON<SnapshotMap>(SNAPSHOT_KEY);
  if (!parsed || typeof parsed !== "object") return {};
  const cutoff = Date.now() - SNAPSHOT_TTL_MS;
  const out: SnapshotMap = {};
  for (const [k, v] of Object.entries(parsed)) {
    if (!v || typeof v.at !== "number" || !Array.isArray(v.items)) continue;
    if (v.at < cutoff) continue;
    out[k] = { at: v.at, items: v.items.slice(0, SNAPSHOT_MAX_ITEMS) };
  }
  return out;
}

export function writeMoneySnapshot(map: SnapshotMap): void {
  persistJSON(SNAPSHOT_KEY, map);
}


export const SEEN_KEY = "chatterly:money-rail:seen:v1";

export function readSeenTs(): number {
  const v = readJSON<unknown>(SEEN_KEY);
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0;
}

export function writeSeenTs(ts: number): void {
  persistJSON(SEEN_KEY, ts);
}

export function unseenCountOf(items: readonly { ts: number }[], seenTs: number): number {
  let n = 0;
  for (const it of items) if (it.ts > seenTs) n++;
  return n;
}
