import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return (
    <span aria-hidden data-loading
      className={cn("block rounded bg-bg-elev-2 animate-pulse motion-reduce:animate-none", className)} />
  );
}

export function TableSkeleton({ rows = 8, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("overflow-hidden rounded-[8px] border border-border", className)}>
      <div className="flex h-10 items-center gap-6 bg-bg-elev-1 px-4">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-3 w-16 max-sm:hidden" />
        <Skeleton className="h-3 w-12 max-sm:hidden" />
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex h-12 items-center gap-6 border-t border-border px-4">
          <Skeleton className="size-7 shrink-0 rounded-full" />
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-12 max-sm:hidden" />
          <Skeleton className="ml-auto h-3 w-14" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonRows({ rows = 6, cols, cellClassName }: { rows?: number; cols: number; cellClassName?: string }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r} aria-hidden>
          {Array.from({ length: cols }, (_, c) => (
            <td key={c} className={cn("h-12 px-4", cellClassName)}>
              <Skeleton className={cn("h-3", c === 0 ? "w-24" : "w-14")} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}
