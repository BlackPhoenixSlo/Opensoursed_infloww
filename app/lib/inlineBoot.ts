export type InlineAnswer = { status: number; body: string } | null;
export type InlineData = Record<string, Promise<InlineAnswer>>;

export const BOOT_PATH_HEADER = "x-chatterly-boot-path";
export const BOOTED: ReadonlySet<string> = new Set(["/", "/messages-pro"]);
export const INLINE_KEEP_MS = 10_000;
const IGNORED = ["t", "focus"];

let seeded: number | null = null;
const answers = new Map<string, Promise<InlineAnswer>>();

export function inlineKey(url: string): string {
  const u = new URL(url, "http://x");
  for (const k of IGNORED) u.searchParams.delete(k);
  return u.pathname + u.search;
}

export function seedInline(data: InlineData): void {
  if (seeded != null) return;
  seeded = Date.now();
  for (const [k, p] of Object.entries(data)) answers.set(k, p);
}

export function takeInline(url: string): Promise<Response | null> | null {
  if (seeded == null || answers.size === 0) return null;
  if (Date.now() - seeded > INLINE_KEEP_MS) {
    answers.clear();
    return null;
  }
  const k = inlineKey(url);
  const p = answers.get(k);
  if (!p) return null;
  answers.delete(k);
  return new Promise<InlineAnswer>((res) => {
    try {
      p.then(res, () => res(null));
    } catch {
      res(null);
    }
  }).then((a) => {
    if (!a) return null;
    const empty = a.status === 204 || a.status === 205;
    return new Response(empty ? null : a.body, { status: a.status, headers: { "content-type": "application/json" } });
  });
}

export function clearInline(): void {
  answers.clear();
}

export function resetInline(): void {
  clearInline();
  seeded = null;
}
