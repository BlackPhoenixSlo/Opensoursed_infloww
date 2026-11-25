export const VAULT_SHEET = {
  backdrop: "md:items-center md:justify-center",
  panel: "w-full border-l md:overflow-hidden",
  duration: "md:bottom-[6px] md:right-[6px]",
} as const;

export const VAULT_CARD_GREYED = "absolute inset-0 bg-bg/60 backdrop-grayscale pointer-events-none";

const CARD_ROUND = "w-5 h-5 rounded-full bg-black/60 text-white grid place-items-center text-[11px] leading-none select-none";
export const VAULT_CARD_INFO = `absolute top-1.5 right-1.5 ${CARD_ROUND} hover:bg-black/85 cursor-pointer`;

export const VAULT_CARD_CHECK = "top-1 right-1";
export const VAULT_CARD_CHECK_UNDER_INFO = "top-7 right-1.5";

export const VAULT_CARD_FOOT = "absolute bottom-1 left-1 max-w-[60%] flex flex-col items-start gap-0.5";
export const VAULT_CARD_TAGS = "flex flex-wrap gap-0.5 max-w-full";
export const VAULT_CARD_TAG = "max-w-full truncate rounded bg-black/60 px-1 text-[9px] leading-4 text-white";
export const VAULT_CARD_GIF = "bg-black/60 text-white text-[10px] px-1.5 py-0.5 rounded";
export const VAULT_CARD_UNSEND = `${CARD_ROUND} opacity-40 cursor-not-allowed`;
