"use client";


import { ChevronLeft, ChevronRight } from "lucide-react";

import { HB_DIM, HB_FILL_1, HB_FILL_2, HB_HAIR, HB_TEXT, Listbox } from "@/components/ui/ifSelect";
import { cn } from "@/lib/utils";


export function pageItems(page: number, pages: number): (number | "…")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const start = Math.max(2, Math.min(page - 2, pages - 5));
  const end = Math.min(pages - 1, Math.max(page + 2, 6));
  const out: (number | "…")[] = [1];
  if (start > 2) out.push("…");
  for (let i = start; i <= end; i++) out.push(i);
  if (end < pages - 1) out.push("…");
  out.push(pages);
  return out;
}

const pageCount = (total: number, size: number) => Math.max(1, Math.ceil(total / Math.max(1, size)));

function PageButtons({ page, pages, onPage, arrow, item }: {
  page: number;
  pages: number;
  onPage: (page: number) => void;
  arrow: string;
  item: (current: boolean) => string;
}) {
  return (
    <>
      <button type="button" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)} className={arrow}>
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
      </button>
      {pageItems(page, pages).map((p, i) => p === "…" ? (
        <span key={`gap-${i}`} aria-hidden className="px-1 text-muted">…</span>
      ) : (
        <button key={p} type="button" aria-label={`Page ${p}`} aria-current={p === page ? "page" : undefined}
          onClick={() => p !== page && onPage(p)} className={item(p === page)}>
          {p}
        </button>
      ))}
      <button type="button" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)} className={arrow}>
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
      </button>
    </>
  );
}

export function IfPager({ total, noun = "records", page, size, onPage, className }: {
  total: number;
  noun?: string;
  page: number;
  size: number;
  onPage: (page: number) => void;
  className?: string;
}) {
  return (
    <nav aria-label="Pagination" className={cn("flex flex-wrap items-center gap-2 text-[14px] text-fg", className)}>
      <span className="mr-1">Total: {total} {noun}</span>
      <PageButtons
        page={page}
        pages={pageCount(total, size)}
        onPage={onPage}
        arrow="grid h-8 w-8 place-items-center rounded-md text-fg hover:bg-bg-elev-2 disabled:bg-transparent disabled:text-border-light disabled:cursor-not-allowed"
        item={(on) => cn("h-8 min-w-8 rounded-md px-1.5", on ? "border border-accent text-accent" : "text-fg hover:bg-bg-elev-2")}
      />
    </nav>
  );
}

export function HbPager({ total, count = total, noun, page, size, sizes = [10, 20, 50], onPage, onSize, className }: {
  total: number;
  count?: number;
  noun: string;
  page: number;
  size: number;
  sizes?: number[];
  onPage: (page: number) => void;
  onSize: (size: number) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-8 gap-y-2 border-t border-[#232323] py-4 text-[14px]",
      "[html[data-theme=light]_&]:border-black/[.09]", className)}>
      <nav aria-label="Pagination" className="flex flex-wrap items-center gap-2">
        <span className={cn("mr-0.5", HB_DIM)}>Total: {count} {noun}</span>
        <PageButtons
          page={page}
          pages={pageCount(total, size)}
          onPage={onPage}
          arrow={cn("grid h-7 w-7 place-items-center rounded-[4px] disabled:cursor-not-allowed disabled:opacity-60", HB_FILL_2, HB_TEXT)}
          item={(on) => cn("h-7 min-w-7 rounded-[4px] px-1.5", on ? cn(HB_FILL_1, HB_TEXT) : cn(HB_DIM, "hover:opacity-80"))}
        />
      </nav>
      <span className={cn("flex items-center gap-2", HB_DIM)}>
        Per page
        <Listbox
          value={String(size)}
          options={sizes.map((s) => ({ value: String(s), label: String(s) }))}
          onChange={(v) => onSize(Number(v))}
          ariaLabel="Per page"
          triggerClassName={cn("h-7 rounded-[4px] px-2 text-[14px]", HB_FILL_1, HB_TEXT)}
          chevronClassName={cn("h-4 w-4", HB_TEXT)}
          menuClassName={cn("border bg-panel", HB_HAIR)}
          // The pager sits at the page foot, so its menu opens upward or runs off the viewport.
          openUp
        />
      </span>
    </div>
  );
}
