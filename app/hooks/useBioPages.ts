"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { errText } from "@/lib/errText";
import { relay, RelayError } from "@/lib/relay";

export const BIO_KEY = "bio-pages";
const BASE = "/admin/bio-pages";

export type BioMode = "direct" | "escape_ig";
export const BIO_MODES: readonly BioMode[] = ["direct", "escape_ig"];
export const STOCK_ICONS = ["onlyicon", "linkicon", "twitchicon", "igicon"] as const;
export type StockIcon = (typeof STOCK_ICONS)[number];
export const isBioMode = (mode: string): mode is BioMode => BIO_MODES.some((m) => m === mode);
export const isStockIcon = (icon: string | null): icon is StockIcon => STOCK_ICONS.some((s) => s === icon);

export interface BioDomainRecord { type: string; name: string; fqdn?: string; value: string }
export interface BioDomain { domain: string; status: string; records?: BioDomainRecord[]; checked?: string | null }

export interface BioListRow {
  id: string;
  username: string;
  display_name: string;
  avatar_url: string;
  account_id: string | null;
  mode: string;
  verified: boolean;
  link_count: number;
  custom_domain: BioDomain | null;
  public_url: string | null;
  views_30d: number;
  clicks_30d: number;
  updated_at: string;
}

export interface BioList { serving: boolean; public_base: string | null; profiles: BioListRow[] }

export interface BioProfile {
  id: string;
  username: string;
  display_name: string;
  bio: string;
  avatar: string;
  avatar_url: string;
  background_url: string;
  account_id: string | null;
  mode: string;
  verified: boolean;
  custom_domain: BioDomain | null;
  public_url: string | null;
  short_url?: string | null;
  domain_server_ip?: string | null;
  home_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BioLink {
  id: string;
  link_id: string;
  title: string;
  destination: string;
  icon: string;
  icon_stock: StockIcon | null;
  icon_url: string;
  background_image: string;
  background_url: string;
  is_adult: boolean;
  mode: string;
  tracking: boolean;
  default_tracking_code: string;
  geo: Record<string, unknown> | null;
  sort_order: number;
  updated_at: string;
}

export interface BioPage { profile: BioProfile; links: BioLink[] }

export type ProfileCreate = { username: string; display_name: string; account_id?: string };
export type ProfilePatch = Partial<{ display_name: string; bio: string; mode: BioMode; verified: boolean; account_id: string | null }>;
export type LinkBody = Partial<{
  title: string; destination: string; icon: StockIcon | null; is_adult: boolean; mode: "" | BioMode;
  tracking: boolean; default_tracking_code: string; geo: Record<string, unknown> | null;
}>;

export const bioPageHref = (pid: string) => `/growth/bio-pages/${encodeURIComponent(pid)}`;
export const BIO_LIST_HREF = "/growth/bio-pages";
export const stockIconUrl = (stem: StockIcon) => `${BASE}/stock/${stem}.webp`;
const pagePath = (pid: string) => `${BASE}/${encodeURIComponent(pid)}`;
const linkPath = (pid: string, lid: string) => `${pagePath(pid)}/links/${encodeURIComponent(lid)}`;

export function bioFailure(e: unknown, fallback: string): { msg: string; fields: string[] } {
  const detail = e instanceof RelayError && e.body && typeof e.body === "object"
    ? (e.body as { detail?: unknown }).detail : undefined;
  if (detail && typeof detail === "object" && typeof (detail as { msg?: unknown }).msg === "string") {
    const d = detail as { field?: unknown; msg: string };
    return { msg: d.msg, fields: typeof d.field === "string" ? [d.field] : [] };
  }
  return { msg: errText(e, fallback), fields: [] };
}

export const isNotFound = (e: unknown) => e instanceof RelayError && e.status === 404;

export function useBioPages(enabled = true) {
  return useQuery<BioList>({
    queryKey: [BIO_KEY],
    enabled,
    queryFn: () => relay.get<BioList>(BASE),
    refetchOnMount: "always",
  });
}

export function useBioPage(pid: string, enabled = true) {
  return useQuery<BioPage>({
    queryKey: [BIO_KEY, pid],
    enabled,
    queryFn: () => relay.get<BioPage>(pagePath(pid)),
    refetchOnMount: "always",
    retry: (n, e) => !isNotFound(e) && n < 2,
  });
}

export function useCreateBioPage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProfileCreate) => relay.post<BioPage>(BASE, body),
    onSuccess: (P) => {
      qc.setQueryData([BIO_KEY, P.profile.id], P);
      qc.invalidateQueries({ queryKey: [BIO_KEY], exact: true });
    },
  });
}

export function useDeleteBioPage(pid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => relay.delete(pagePath(pid)),
    onSuccess: () => qc.invalidateQueries({ queryKey: [BIO_KEY], exact: true }),
  });
}

function usePageWrite<V, P extends BioPage = BioPage>(pid: string, call: (v: V) => Promise<P>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (P) => {
      qc.setQueryData([BIO_KEY, pid], P);
      qc.invalidateQueries({ queryKey: [BIO_KEY], exact: true });
    },
    onError: () => qc.invalidateQueries({ queryKey: [BIO_KEY, pid], exact: true }),
  });
}

export const usePatchBioPage = (pid: string) =>
  usePageWrite(pid, (body: ProfilePatch) => relay.patch<BioPage>(pagePath(pid), body));

export const useBioAvatar = (pid: string) =>
  usePageWrite(pid, (file: File | null) => file
    ? relay.uploadFile<BioPage>(`${pagePath(pid)}/avatar`, file)
    : relay.delete<BioPage>(`${pagePath(pid)}/avatar`));

export const useBioAvatarFromVault = (pid: string) =>
  usePageWrite(pid, (m: { id: number; type: string }) =>
    relay.post<BioPage>(`${pagePath(pid)}/avatar/vault`, { media_id: m.id, type: m.type }));

export const useBioBackground = (pid: string) =>
  usePageWrite(pid, (file: File | null) => file
    ? relay.uploadFile<BioPage>(`${pagePath(pid)}/background`, file)
    : relay.delete<BioPage>(`${pagePath(pid)}/background`));

export const useBioBackgroundFromVault = (pid: string) =>
  usePageWrite(pid, (m: { id: number; type: string }) =>
    relay.post<BioPage>(`${pagePath(pid)}/background/vault`, { media_id: m.id, type: m.type }));

export const useCreateBioLink = (pid: string) =>
  usePageWrite(pid, (body: LinkBody) => relay.post<BioPage & { link: BioLink }>(`${pagePath(pid)}/links`, body));

export const usePatchBioLink = (pid: string) =>
  usePageWrite(pid, ({ lid, body }: { lid: string; body: LinkBody }) => relay.patch<BioPage>(linkPath(pid, lid), body));

export const useDeleteBioLink = (pid: string) =>
  usePageWrite(pid, (lid: string) => relay.delete<BioPage>(linkPath(pid, lid)));

export const useReorderBioLinks = (pid: string) =>
  usePageWrite(pid, (ids: string[]) => relay.put<BioPage>(`${pagePath(pid)}/links/order`, { ids }));

export const useBioLinkBackgroundFromVault = (pid: string) =>
  usePageWrite(pid, ({ lid, m }: { lid: string; m: { id: number; type: string } }) =>
    relay.post<BioPage>(`${linkPath(pid, lid)}/background/vault`, { media_id: m.id, type: m.type }));

export const useBioLinkBackground = (pid: string) =>
  usePageWrite(pid, ({ lid, file }: { lid: string; file: File | null }) => file
    ? relay.uploadFile<BioPage>(`${linkPath(pid, lid)}/background`, file)
    : relay.delete<BioPage>(`${linkPath(pid, lid)}/background`));

export const useSetBioDomain = (pid: string) =>
  usePageWrite(pid, (domain: string) => relay.put<BioPage>(`${pagePath(pid)}/domain`, { domain }));

export const useRemoveBioDomain = (pid: string) =>
  usePageWrite(pid, () => relay.delete<BioPage>(`${pagePath(pid)}/domain`));

export function useCheckBioDomain(pid: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => relay.post<BioPage & { check: { status: string; problems: string[] } }>(`${pagePath(pid)}/domain/check`, {}),
    onSuccess: ({ check: _check, ...P }) => {
      qc.setQueryData([BIO_KEY, pid], P);
      qc.invalidateQueries({ queryKey: [BIO_KEY], exact: true });
    },
    onError: () => qc.invalidateQueries({ queryKey: [BIO_KEY, pid], exact: true }),
  });
}
