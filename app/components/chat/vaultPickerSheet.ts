/**
 * The Vault picker's Messages Pro shell around the Clone's centred `.sheet`
 * (docs/spec/phase-04-composer-ppv-vault.md, Gap rows 25–27). Only the
 * Composer selects it (`VaultPicker`'s `messagesPro` prop), and passes the
 * sheet's own Geometry (`sheet`: the token module's SH1, and its `md:`
 * variants of SH2, SH5 and SH6, so below md the picker stays the full-screen
 * pane it is everywhere else; docs/spec/phase-06-geometry-pass.md, Shared
 * modules). What stays here is the
 * picker's own: the backdrop, the panel's phone base and the duration badge.
 * Kept out of VaultPicker.tsx, which is already over size.
 */
export const VAULT_SHEET = {
  /** The backdrop row centres the sheet instead of docking it right. */
  backdrop: "md:items-center md:justify-center",
  /** Under the sheet's panel: the full-screen pane below md, clipped from md up. */
  panel: "w-full border-l md:overflow-hidden",
  /** `.mgrid .mt .vdur`: the duration badge 6px in from the corner. */
  duration: "md:bottom-[6px] md:right-[6px]",
} as const;

/** A card the Fan already has (bought, or last sent free): the `bg` token at
 *  60% over the media, which the backdrop filter turns grayscale. It sits
 *  under the card's badges, so the status pill keeps its colour. Rendered
 *  whenever a Fan is in scope, not only in Messages Pro. */
export const VAULT_CARD_GREYED = "absolute inset-0 bg-bg/60 backdrop-grayscale pointer-events-none";

/** ⓘ "Media details" on a card, 6px in from the top-right corner (`1.5` is
 *  6px). Rendered whenever a Fan is in scope. */
const CARD_ROUND = "w-5 h-5 rounded-full bg-black/60 text-white grid place-items-center text-[11px] leading-none select-none";
export const VAULT_CARD_INFO = `absolute top-1.5 right-1.5 ${CARD_ROUND} hover:bg-black/85 cursor-pointer`;

/** The selected ✓ on a card, which sits in the top-right corner, and directly
 *  under the ⓘ when a Fan is in scope. */
export const VAULT_CARD_CHECK = "top-1 right-1";
export const VAULT_CARD_CHECK_UNDER_INFO = "top-7 right-1.5";

/** A card's lower-left stack, 4px in like the GIF badge it now holds: with a
 *  Fan in scope, up to three tag chips, the empty notes slot and the unsend
 *  icon (lowest). It stops short of the duration badge on the right. */
export const VAULT_CARD_FOOT = "absolute bottom-1 left-1 max-w-[60%] flex flex-col items-start gap-0.5";
export const VAULT_CARD_TAGS = "flex flex-wrap gap-0.5 max-w-full";
export const VAULT_CARD_TAG = "max-w-full truncate rounded bg-black/60 px-1 text-[9px] leading-4 text-white";
export const VAULT_CARD_GIF = "bg-black/60 text-white text-[10px] px-1.5 py-0.5 rounded";
/** Unsend, Not wired: the ⓘ's 20px round at the standard disabled opacity (spec, Not wired). */
export const VAULT_CARD_UNSEND = `${CARD_ROUND} opacity-40 cursor-not-allowed`;

/** The picker toolbar's folder, sort and length selects. */
export const VAULT_TOOLBAR_SELECT =
  "shrink-0 ml-2 bg-bg border border-border rounded-md px-2 py-1 text-xs focus:outline-none focus:border-accent";
