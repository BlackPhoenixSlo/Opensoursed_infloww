export function newOpId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export function sendKey(...parts: unknown[]): string {
  return JSON.stringify(parts);
}

export type RetainedOps = Map<string, { opId: string; path: string }>;

export async function withRetainedOp<T>(
  ref: { current: RetainedOps | null }, key: string, fn: (opId: string, path: string) => Promise<T>,
  path = "",
): Promise<T> {
  const ops = ref.current ??= new Map();
  const op = ops.get(key) ?? { opId: newOpId(), path };
  ops.set(key, op);
  const result = await fn(op.opId, op.path);
  if (ops.get(key) === op) ops.delete(key);
  return result;
}
