"use client";

/** `infloww.tsx`'s pagers (re-exported there): `IfPager`, `HbPager`, and `pageItems`, the page run both draw. */

import { ChevronLeft, ChevronRight } from "lucide-react";

import { HB_DIM, HB_FILL_1, HB_FILL_2, HB_HAIR, HB_TEXT, Listbox } from "@/components/ui/ifSelect";
import { cn } from "@/lib/utils";

// ── Pagers ──────────────────────────────────────────────────────────────────────────────────────────────────────

/** The pagers' page run (not rc-pagination's; antd's exact run is `pagerItems` in setup/ProxiesTable.tsx): every page
 *  up to 7, else the first, the last, and two either side of the current, with "…". */
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

/** The page buttons both pagers share; `item(current)` styles one page box. */
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

/** antd's pagination, left-aligned: "Total: N records" 14px T1, then prev / pages / next, 32px items 8px apart, radius
 *  6; the current page a 1px M1 outline and M1 text; disabled arrows T4. No size changer. */
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

/** HB's pager footer: a 1px #232323 rule above; "Total: N creators" #a3a3a3, prev / next 28px boxes on #232323, the
 *  current page a #1a1a1a box with a white digit; then "Per page" and the size select (#1a1a1a, 10 / 20 / 50). Pin
 *  it to the page foot with the caller's layout. */
export function HbPager({ total, noun, page, size, sizes = [10, 20, 50], onPage, onSize, className }: {
  total: number;
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
        <span className={cn("mr-0.5", HB_DIM)}>Total: {total} {noun}</span>
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
          // The pager sits at the page foot, so its menu opens upward or it runs off the viewport.
          openUp
        />
      </span>
    </div>
  );
}
