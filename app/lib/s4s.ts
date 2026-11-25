"use client";


import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { resolveShareToken } from "@/lib/shareToken";

export const S4S_MAX_POSTS = 20;
export const S4S_MAX_CAPTION = 5000;
export const S4S_DAILY_LIMITS = [1, 2, 3] as const;
export const S4S_MAX_MEDIA = 5;

export interface S4SMedia {
  id: number;
  media_type: "photo" | "gif" | "video";
}

export interface S4SPost {
  id: number;
  caption: string;
  is_primary: boolean;
  media: (S4SMedia & { vault_media_id: number })[];
}

export interface S4SProfile {
  account_id: string;
  profile_id: number | null;
  opted_in: boolean;
  discovery_visible: boolean;
  daily_limit: number;
  display_name: string;
  username: string;
  avatar_url: string | null;
  posts: S4SPost[];
}

export interface S4SProfiles {
  live_posting: boolean;
  profiles: S4SProfile[];
}

export type S4SProfileUpdate = Partial<Pick<S4SProfile, "opted_in" | "discovery_visible" | "daily_limit">>;

export const S4S_PROFILES_KEY = ["s4s", "profiles"] as const;

export function useS4SProfiles() {
  return useQuery<S4SProfiles>({
    queryKey: S4S_PROFILES_KEY,
    queryFn: () => relay.get<S4SProfiles>("/admin/s4s/profiles"),
    refetchOnWindowFocus: false,
  });
}

const profilePath = (accountId: string) => `/admin/s4s/profiles/${encodeURIComponent(accountId)}`;
const postPath = (accountId: string, postId: number) => `${profilePath(accountId)}/posts/${postId}`;

export const updateS4SProfile = (accountId: string, body: S4SProfileUpdate) =>
  relay.put<S4SProfile>(profilePath(accountId), body);
export const createS4SPost = (accountId: string, caption: string) =>
  relay.post<S4SPost>(`${profilePath(accountId)}/posts`, { caption });
export const editS4SPost = (accountId: string, postId: number, caption: string) =>
  relay.patch<S4SPost>(postPath(accountId, postId), { caption });
export const deleteS4SPost = (accountId: string, postId: number) =>
  relay.delete<{ deleted: number }>(postPath(accountId, postId));
export const setPrimaryS4SPost = (accountId: string, postId: number) =>
  relay.post<S4SPost>(`${postPath(accountId, postId)}/primary`);
export const putS4SPostMedia = (accountId: string, postId: number, vaultMediaIds: number[]) =>
  relay.put<S4SPost["media"]>(`${postPath(accountId, postId)}/media`, { vault_media_ids: vaultMediaIds });
export function s4sMediaUrl(id: number): string {
  const tok = resolveShareToken();
  return `/admin/s4s/media/${id}${tok ? `?${new URLSearchParams({ t: tok })}` : ""}`;
}

export interface S4SDiscoveryItem {
  profile_id: number;
  display_name: string;
  username: string;
  avatar_url: string | null;
  primary_caption: string;
  primary_media: S4SMedia[];
  daily_limit: number;
  opted_in: boolean;
  own_agency: boolean;
}

export function useS4SDiscover(q: string) {
  const query = q.trim();
  return useQuery<S4SDiscoveryItem[]>({
    queryKey: ["s4s", "discover", query],
    queryFn: () =>
      relay.get<S4SDiscoveryItem[]>(
        query ? `/admin/s4s/discover?${new URLSearchParams({ q: query })}` : "/admin/s4s/discover",
      ),
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
  });
}

export type S4SProjection = Omit<S4SDiscoveryItem, "own_agency" | "primary_media">;

export type S4SRequestBox = "received" | "sent";
export type S4SRequestStatus = "pending" | "accepted" | "declined" | "cancelled" | "expired";

export interface S4SRequest {
  id: number;
  box: S4SRequestBox;
  status: S4SRequestStatus;
  slot_at: string;
  from: S4SProjection;
  to: S4SProjection;
  from_media: S4SMedia[];
  to_media: S4SMedia[];
  created_at: string;
  answered_at: string | null;
}

export const S4S_REQUESTS_KEY = ["s4s", "requests"] as const;

export function useS4SRequests(box: S4SRequestBox) {
  return useQuery<S4SRequest[]>({
    queryKey: [...S4S_REQUESTS_KEY, box],
    queryFn: () => relay.get<S4SRequest[]>(`/admin/s4s/requests?box=${box}`),
    refetchOnWindowFocus: false,
  });
}

export type S4SBlock = S4SProjection & { blocked_at: string };

export const S4S_BLOCKS_KEY = ["s4s", "blocks"] as const;

export function useS4SBlocks() {
  return useQuery<S4SBlock[]>({
    queryKey: S4S_BLOCKS_KEY,
    queryFn: () => relay.get<S4SBlock[]>("/admin/s4s/blocks"),
    refetchOnWindowFocus: false,
  });
}

export const blockS4SCreator = (profileId: number) =>
  relay.post<S4SBlock>("/admin/s4s/blocks", { profile_id: profileId });
export const unblockS4SCreator = (profileId: number) =>
  relay.delete<{ unblocked: number }>(`/admin/s4s/blocks/${profileId}`);

export const sendS4SRequest = (body: { from_account_id: string; to_profile_id: number; slot_at: string }) =>
  relay.post<S4SRequest>("/admin/s4s/requests", body);

export const proposeS4SSlot = (fromAccountId: string, toProfileId: number) =>
  relay.get<{ slot_at: string | null }>(`/admin/s4s/requests/proposal?${new URLSearchParams({
    from_account_id: fromAccountId, to_profile_id: String(toProfileId),
  })}`);

export type S4SRequestAction = "accept" | "skip" | "decline" | "cancel";

export const actOnS4SRequest = (id: number, action: S4SRequestAction) =>
  relay.post<S4SRequest>(`/admin/s4s/requests/${id}/${action}`);

export type S4SDisplayStatus = "Will be posted shortly" | "In progress" | "Completed" | "Canceled" | "Failed";

export interface S4SSlot {
  id: number;
  slot_at: string;
  status: "scheduled" | "posting" | "posted" | "canceled" | "failed";
  display_status: S4SDisplayStatus;
  reason: string | null;
  partner: S4SProjection;
  own: S4SProjection;
  remove_at: string | null;
  partner_issue: "post_deleted" | "post_archived" | "post_edited" | null;
}

export const S4S_SCHEDULE_KEY = ["s4s", "schedule"] as const;

export function s4sSchedulePath(monthStart: Date): string {
  const qs = new URLSearchParams({
    from: monthStart.toISOString(),
    to: new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth() + 1, 1)).toISOString(),
  });
  return `/admin/s4s/schedule?${qs}`;
}

export function useS4SSchedule(monthStart: Date) {
  const path = s4sSchedulePath(monthStart);
  return useQuery<S4SSlot[]>({
    queryKey: [...S4S_SCHEDULE_KEY, path],
    queryFn: () => relay.get<S4SSlot[]>(path),
    refetchOnWindowFocus: false,
  });
}

export const cancelS4SSlot = (id: number) => relay.post<S4SSlot>(`/admin/s4s/slots/${id}/cancel`);
