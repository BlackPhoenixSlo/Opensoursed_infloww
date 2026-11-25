import { cn } from "@/lib/utils";

export const IF_BTN = cn(
  "h-8 px-[15px] rounded-[6px] text-sm border border-[var(--if-line)] text-[var(--if-fg-0)]",
  "hover:border-[var(--if-accent)] hover:text-[var(--if-accent)] disabled:opacity-50 disabled:cursor-not-allowed",
  "disabled:hover:border-[var(--if-line)] disabled:hover:text-[var(--if-fg-0)]",
);
export const IF_BTN_PRIMARY =
  "h-8 px-[15px] rounded-[6px] text-sm bg-[var(--if-accent)] text-white hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed";
