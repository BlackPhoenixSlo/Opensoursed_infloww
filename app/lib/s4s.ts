"use client";

/**
 * Share for Share's client: the wire types of `/admin/s4s` (service/s4s_api.py,
 * docs/spec/phase-03-share-for-share.md, Contracts) and the calls the S4S
 * Setting panel and Discover creators send. Owner sessions only; the Relay
 * 403s a chatter.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import { resolveShareToken } from "@/lib/shareToken";

/** The Relay's limits (help-center confirmed, spec user story 38). */
export const S4S_MAX_POSTS = 20;
export const S4S_MAX_CAPTION = 5000;
export const S4S_DAILY_LIMITS = [1, 2, 3] as const;
/** Media per S4S post (Infloww's own limit). */
export const S4S_MAX_MEDIA = 5;

/** A vault item on an S4S post, kept as a reference to its Creator's vault (ADR-0015); its still is `s4sMediaUrl(id)`. */
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

/** One of the owner's own Creators. `profile_id` is null until the first
 *  save; such a Creator reads as opted out with the defaults. `display_name`, `username` and `avatar_url` are the
 *  Creator's own OnlyFans name, @username and avatar, re-read by the Relay on every list; nobody types them. */
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
  /** The Deployment's S4S_LIVE_POSTING flag; off by default. */
  live_posting: boolean;
  profiles: S4SProfile[];
}

/** The fields a profile save may send; only the changed ones are sent. */
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
/** The Relay makes the new post Primary when the Creator has none. */
export const createS4SPost = (accountId: string, caption: string) =>
  relay.post<S4SPost>(`${profilePath(accountId)}/posts`, { caption });
export const editS4SPost = (accountId: string, postId: number, caption: string) =>
  relay.patch<S4SPost>(postPath(accountId, postId), { caption });
export const deleteS4SPost = (accountId: string, postId: number) =>
  relay.delete<{ deleted: number }>(postPath(accountId, postId));
export const setPrimaryS4SPost = (accountId: string, postId: number) =>
  relay.post<S4SPost>(`${postPath(accountId, postId)}/primary`);
/** Set the post's media to these vault items, in order; the Relay checks new ones with the Creator's own session. */
export const putS4SPostMedia = (accountId: string, postId: number, vaultMediaIds: number[]) =>
  relay.put<S4SPost["media"]>(`${postPath(accountId, postId)}/media`, { vault_media_ids: vaultMediaIds });
/** Same-origin and cookie-authenticated, so usable as an <img> or <video> src (with the share token, as
 *  `proxyImage` adds it). */
export function s4sMediaUrl(id: number): string {
  const tok = resolveShareToken();
  return `/admin/s4s/media/${id}${tok ? `?${new URLSearchParams({ t: tok })}` : ""}`;
}

/** One Discovery card: the S4S projection (ADR-0011) plus `own_agency` and the Primary post's media (whose stills
 *  `s4sMediaUrl` serves while the Creator stays listed). A Creator is named by its S4S profile id only; no account id
 *  is ever sent. */
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

/** A Creator as a request stored it at send time: the S4S projection less `own_agency`. Requests only ever show
 *  these snapshots, never a live read of the other Agency (ADR-0011). */
export type S4SProjection = Omit<S4SDiscoveryItem, "own_agency" | "primary_media">;

export type S4SRequestBox = "received" | "sent";
/** `skipped` never reaches the app: the receiver no longer lists it and the sender reads it as `pending`. */
export type S4SRequestStatus = "pending" | "accepted" | "declined" | "cancelled" | "expired";

export interface S4SRequest {
  id: number;
  box: S4SRequestBox;
  status: S4SRequestStatus;
  /** ISO-8601 UTC. */
  slot_at: string;
  from: S4SProjection;
  to: S4SProjection;
  /** The media on each side's Primary post at send: what the other side will post. */
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

/** A Creator this Agency blocked: its projection stored at block time. */
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

/** 06:00 UTC on the first day from tomorrow on which both Creators' Daily limits have room, or null. The Relay
 *  answers only the instant, nothing of the partner's schedule. */
export const proposeS4SSlot = (fromAccountId: string, toProfileId: number) =>
  relay.get<{ slot_at: string | null }>(`/admin/s4s/requests/proposal?${new URLSearchParams({
    from_account_id: fromAccountId, to_profile_id: String(toProfileId),
  })}`);

/** Accept, Skip and Decline are the receiver's; Cancel is the sender's. */
export type S4SRequestAction = "accept" | "skip" | "decline" | "cancel";

export const actOnS4SRequest = (id: number, action: S4SRequestAction) =>
  relay.post<S4SRequest>(`/admin/s4s/requests/${id}/${action}`);

/** The S4S schedule's display statuses: Infloww's four plus "Failed", an Inflowwww extra (spec, Display status). */
export type S4SDisplayStatus = "Will be posted shortly" | "In progress" | "Completed" | "Canceled" | "Failed";

/** One of the owner's own S4S slots. `partner` and `own` are the request's snapshots stored at send, never a live
 *  read of the other Agency (ADR-0011). `status` is the stored state; `display_status` and `reason` are what it
 *  reads as (a partner who opted out reads "Canceled" / `partner_opted_out` while the stored slot stays scheduled). */
export interface S4SSlot {
  id: number;
  /** ISO-8601 UTC. */
  slot_at: string;
  status: "scheduled" | "posting" | "posted" | "canceled" | "failed";
  display_status: S4SDisplayStatus;
  reason: string | null;
  partner: S4SProjection;
  own: S4SProjection;
  remove_at: string | null;
  /** The partner's own post of this pair was found deleted, archived or edited before its removal. */
  partner_issue: "post_deleted" | "post_archived" | "post_edited" | null;
}

export const S4S_SCHEDULE_KEY = ["s4s", "schedule"] as const;

/** The schedule query for one UTC month (Infloww's S4S pages are in UTC): its first UTC midnight to the next
 *  month's. */
export function s4sSchedulePath(monthStart: Date): string {
  const qs = new URLSearchParams({
    from: monthStart.toISOString(),
    to: new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth() + 1, 1)).toISOString(),
  });
  return `/admin/s4s/schedule?${qs}`;
}

/** `monthStart` is the month's first UTC midnight. */
export function useS4SSchedule(monthStart: Date) {
  const path = s4sSchedulePath(monthStart);
  return useQuery<S4SSlot[]>({
    queryKey: [...S4S_SCHEDULE_KEY, path],
    queryFn: () => relay.get<S4SSlot[]>(path),
    refetchOnWindowFocus: false,
  });
}

export const cancelS4SSlot = (id: number) => relay.post<S4SSlot>(`/admin/s4s/slots/${id}/cancel`);
