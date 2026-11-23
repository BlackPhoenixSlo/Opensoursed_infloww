export async function run(load, input) {
  if (input.op === "circles") {
    const rc = await load("/components/chat/redCircle.ts");
    return { circles: (input.slots ?? []).map((s) => rc.redCircle(s, true, undefined, true)) };
  }
  const cf = await load("/lib/creatorFreshness.ts");
  let state = input.state ?? cf.EMPTY_FRESHNESS;
  for (const a of input.actions ?? []) state = cf.creatorFreshnessReducer(state, a);
  return { state, behind: cf.badgeBehind(state, input.badge) };
}
