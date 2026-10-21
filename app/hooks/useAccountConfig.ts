"use client";

/**
 * useAccountConfig — the data layer for the per-account "Brain" editor
 * (account_ai_config) on /automations. Reads/writes the owner-gated
 * /admin/account-config routes (covered by the /admin/:path* rewrite).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type RelayContext } from "@/lib/relay";

const BG_CTX: RelayContext = { priority: "background" };

export interface BrainConfig {
  persona: string | null;
  location: string | null;
  /**
   * Structured creator canon pinned into every chat prompt — the facts she must
   * never contradict. Keys: age, job, home_city, home_country, born_city,
   * born_country, upbringing, living_situation, relationship, family, pets.
   * Empty {} = never enriched; nothing renders into the prompt.
   */
  persona_facts: Record<string, string>;
  /** ISO 639-1 the creator writes in; "en" default. Gates output language + guard vocab. */
  language: string;
  /**
   * Whose voice this account writes in: "her" (every account that has ever run
   * here) or "him" (the male lane). Set from the Brain panel's Creator dropdown,
   * and it MUST stay on this type and travel with the form, because
   * Save PUTs the whole config object back. A field the type doesn't know about
   * is a field a rebuild silently drops, and dropping this one puts a male
   * creator back in the female lane mid-conversation.
   */
  voice: string;
  /** LEGACY IANA zone (e.g. America/Vancouver). No longer settable from the Brain —
   *  `utc_offset` is the account's one clock, and this is only consulted when that
   *  is unset. Saving the Brain clears it. */
  timezone: string | null;
  utc_offset: number;
  daily_cost_cap_cents: number;
  model: string | null;
  /** How hard the picked model may think. "" / null = use the model's own pin.
   *  The legal values are per PROVIDER, so the editor reads them from
   *  `effort_options[model]` rather than from a hardcoded list. */
  reasoning_effort: string | null;
  model_by_purpose: Record<string, string>;
  time_activities: Record<string, string>;
  time_images: Record<string, number>;
  /**
   * Include-only automation audience. These MUST stay on this type and travel
   * with the form (Save PUTs the whole config object back — a field the type
   * doesn't know about is a field a rebuild silently drops, and dropping the
   * mode would reset an enforced fence to off). Server semantics: absent key =
   * unchanged; "off" | "shadow" | "enforce"; shadow is mandatory before
   * enforce unless `audience_enforce_override` rides the same PUT.
   */
  audience_mode: string;
  /** The picked OF folder id (the server owns the local mirror row). */
  audience_of_list_id: number | null;
  /** Local lists.id of the mirror row — informational, server-owned. */
  audience_list_id?: number | null;
  audience_auto_add: boolean;
  /** Transient: rides one PUT to allow direct-to-enforce (logged server-side). */
  audience_enforce_override?: boolean;
  /**
   * Co-performer tagging (media_cotag). Always served by GET; optional here so
   * mocked partials type-check. `cotag_tag_videos` (default false — most
   * creators are solo) is the collab-account opt-in: true tags EVERY send that
   * attaches a video even when the AI describe read it as solo, because video
   * describes miss the POV partner. Server semantics: absent key = unchanged,
   * so an old client can't clear them while saving something else.
   */
  cotag_tag_videos?: boolean;
  /** Handle to tag, no '@'. null = the global default (see cotag_default_username). */
  cotag_username?: string | null;
  /** Get to know fans' short "Model info" note, pinned into every chat prompt. Server semantics: absent key =
   *  unchanged; null = no note (the box then prefills `model_notes_template`). */
  model_notes?: string | null;
}

/** One creator-canon field, as served by the API — the single source of truth. */
export interface PersonaFactField {
  key: string;
  label: string;
  /** Enrich never proposes these: a business decision, or photographic evidence. */
  operator_only: boolean;
  /** Editor hint. Server-side so the 26 keys are enumerated exactly once. */
  placeholder: string;
}

export interface LanguageOption {
  code: string;
  label: string;
}

export interface AccountConfigResp {
  account_id: string;
  config: BrainConfig;
  defaults: BrainConfig;    // starter brain for the STORED lane (no images) — seeds
                            // a blank account, which has no unsaved dropdown yet
  /** Both lanes' starter brains. "Reset to defaults" reads this by the SELECTED
   *  voice: the dropdown is local form state until Save, so resolving the lane from
   *  the stored column refilled a male account with the female brain. */
  defaults_by_voice: Record<string, BrainConfig>;
  /** The canon field contract per lane. Read by the SELECTED voice for the same
   *  reason as `defaults_by_voice`: the labels are what the operator types AGAINST,
   *  and a female label is an instruction to write female canon. */
  persona_fact_fields_by_voice: Record<string, PersonaFactField[]>;
  slots: string[];          // the 6 time-of-day slot keys, ordered
  model_options: string[];  // LLM model ids the account may pick
  // Per model, the reasoning-effort values it accepts (weakest first).
  // Empty for a model with no reasoning control — the legal set is per
  // provider, so this cannot be a single shared list.
  effort_options: Record<string, string[]>;
  purposes: string[];       // per-purpose override targets
  // What a purpose runs with NOTHING pinned. A purpose listed here does not
  // inherit `model` — the server holds it on one model whatever the brain says.
  // Absent key = inherits, as every purpose used to.
  purpose_defaults?: Record<string, string>;
  languages: LanguageOption[]; // language codes + labels for the dropdown
  /** Creator-canon fields, ordered by how often fans ask. Single source of truth. */
  persona_fact_fields: PersonaFactField[];
  /** What a null cotag_username resolves to (env → built-in "", i.e. nobody) — the
   *  editor's placeholder, so the default the box shows is the default that runs. */
  cotag_default_username?: string;
  /** What the Model info box prefills while `model_notes` is empty (labelled blank lines the prompt skips). */
  model_notes_template?: string;
}

export function useAccountConfig(accountId: string | null) {
  return useQuery<AccountConfigResp>({
    queryKey: ["account-config", accountId],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<AccountConfigResp>(
        `/admin/account-config?account_id=${encodeURIComponent(accountId!)}`,
        BG_CTX,
      ),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

export function useSaveAccountConfig(accountId: string | null) {
  const qc = useQueryClient();
  return useMutation<{ account_id: string; config: BrainConfig }, Error, BrainConfig>({
    mutationFn: (config) =>
      relay.put("/admin/account-config", { account_id: accountId, config }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-config", accountId] });
    },
  });
}
