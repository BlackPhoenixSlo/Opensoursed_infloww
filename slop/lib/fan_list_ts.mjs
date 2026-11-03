// The Fan List's ranking and chip counts in node (scenarios/2026-10-26-fan-list-chips.py, via
// lib/app_ts.py): the app's own sortFanRows + chipCounts (app/components/chat/fanListSort.ts) over
// the relay's view, with FanList's own owe-reply test (lastMessageFromFan). Date.now is
// pinned to `input.now` while it runs, so hybrid's decayed score is the one the scenario recomputes.
//
// input:  {now: epoch ms, spend: {"<account>:<fan>": cents}, groups: [{name, rows: [OF /chats row]}]}
// output: {<name>: {orders: {<mode>: ["<account>:<fan>", ...]}, same_recent: bool, counts: {...}}}
const MODES = ["recent", "spend", "spend-unread", "hybrid"];

export async function run(load, input) {
  const { sortFanRows, chipCounts } = await load("/components/chat/fanListSort.ts");
  const { lastMessageFromFan } = await load("/lib/fanId.ts");
  const key = (c) => `${c.__accountId ?? ""}:${c.withUser.id}`;
  const deps = {
    spendOf: (c) => input.spend[key(c)] ?? 0,
    isOwed: (c) => lastMessageFromFan(c, c.__accountId ?? ""),
  };
  const realNow = Date.now;
  Date.now = () => input.now;
  try {
    const out = {};
    for (const g of input.groups) {
      const orders = {};
      let sameRecent = false;
      for (const m of MODES) {
        const sorted = sortFanRows(g.rows, m, deps);
        if (m === "recent") sameRecent = sorted === g.rows;
        orders[m] = sorted.map(key);
      }
      const counts = chipCounts(g.rows, deps);
      out[g.name] = { orders, same_recent: sameRecent, counts };
    }
    return out;
  } finally {
    Date.now = realNow;
  }
}
