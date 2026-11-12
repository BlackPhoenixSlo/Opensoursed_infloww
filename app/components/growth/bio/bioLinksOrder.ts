/** The Links card's ↑ / ↓: the order a move asks for. A move off either end, or of an id not in the list, is no move
 *  (the same array back, so the caller can skip the write). */
export function moveLink(ids: readonly string[], id: string, dir: -1 | 1): readonly string[] {
  const i = ids.indexOf(id);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= ids.length) return ids;
  const out = [...ids];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}
