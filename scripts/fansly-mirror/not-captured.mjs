const NOT_CAPTURED = new Map([
  ["creator/coperformers/detail", "the rig fills only {username}, not a co-performer id"],
  ["creator/vault/album", "the rig fills only {username}, not an album id"],
  ["lists/list", "the rig fills only {username}, not a list id"],
  ["creator/followers", "Fansly redirects it to /creator"],
]);

export function dropNotCaptured(all, parentOf, landsOwn, fail) {
  const listed = new Set(all.filter((e) => NOT_CAPTURED.has(e.id)).map((e) => e.id));
  for (const e of all) if (listed.has(e.id) && landsOwn(e)) fail(`entry ${e.id} is in NOT_CAPTURED but lands on its own page; remove it from the list`);
  const gone = (e) => listed.has(e.id) || listed.has(parentOf(e.id));
  const dropped = all.filter(gone).map((e) => `${e.id} (${NOT_CAPTURED.get(e.id) || `a State of ${parentOf(e.id)}`})`);
  return { entries: all.filter((e) => !gone(e)), dropped };
}
