// The send path's chat-list bump on the relay's answers, through lib/app_ts.py (the app's own
// TypeScript in node): what a manual send leaves in every chats cache the owner's tabs hold,
// from the head pages `GET /admin/chats/recent` served and the relay's answer to
// `POST /api/of/v2/chats/{fan}/messages`.
//
// Input: {limit, page, models: {aid: rows}, sends: [{accountId, fanId, echo}]}. Every model's
// rows become its model-scope cache (useChatList `normalizeChats`, `page` rows a page) and all
// of them one all-scope cache, keyed as useChatList keys them. Each send runs three ways, each
// on fresh caches: `number` (the rows as served, the fan id a number), `string` (the fan id as
// the string a route param or Fansly sends) and `row-string` (the sending model's rows with
// string ids, the Fansly shape, the fan id a number). Every cache goes through lib/chatsCache
// `bumpAfterSend` as useSendMessage's patchChatListAfterSend does. Returns {ways, cases}; a case
// per send and way:
//   own, all: the sending model's cache and the all-scope cache: head [aid, fan], the head row's
//           preview text, copies of the fan, rows before/after, and `untouched`: every other row
//           still the same object, in the same order;
//   others: the other models whose cache came back as a NEW object (must be none).
// Fan ids must be safe integers (`Number(fanId)`): fine for OF; a Fansly snowflake would truncate.
const WAYS = ["number", "string", "row-string"];

export async function run(load, input) {
  const cache = await load("/lib/chatsCache.ts");
  const chats = await load("/hooks/useChatList.ts");
  const models = Object.keys(input.models).sort();
  const pair = (c) => [c.__accountId, String(c.withUser.id)];
  const paged = (rows) => {
    const pages = [];
    for (let i = 0; i < rows.length; i += input.page) pages.push({ rows: rows.slice(i, i + input.page), hasMore: true });
    return { pages: pages.length ? pages : [{ rows: [], hasMore: false }], pageParams: pages.map((_, i) => i) };
  };
  const key = (kind, ak) => ["chats", kind, ak, null, null, null, input.limit];
  const out = [];
  for (const s of input.sends) {
    const isFan = (c) => c.__accountId === s.accountId && String(c.withUser.id) === String(s.fanId);
    const view = (data, next) => {
      const before = data.pages.flatMap((p) => p.rows);
      const after = next.pages.flatMap((p) => p.rows);
      const keptB = before.filter((c) => !isFan(c));
      const keptA = after.filter((c) => !isFan(c));
      const head = next.pages[0].rows[0];
      return {
        head: head ? pair(head) : null, text: head?.lastMessage?.text ?? null,
        copies: after.filter(isFan).length, before: before.length, after: after.length,
        untouched: keptA.length === keptB.length && keptA.every((c, i) => c === keptB[i]),
      };
    };
    for (const way of WAYS) {
      const rowsOf = (aid) => {
        const rows = chats.normalizeChats({ list: input.models[aid] }, aid);
        return way === "row-string" && aid === s.accountId
          ? rows.map((c) => ({ ...c, withUser: { ...c.withUser, id: String(c.withUser.id) } }))
          : rows;
      };
      const caches = models.map((aid) => [aid, key("model", aid), paged(rowsOf(aid))]);
      caches.push(["all", key("all", models.join(",")), paged(models.flatMap(rowsOf))]);
      const fanId = way === "string" ? String(s.fanId) : Number(s.fanId);
      const msg = {
        fromUserId: s.echo?.fromUser?.id ?? s.accountId, fromUserName: s.echo?.fromUser?.name ?? "you",
        text: s.echo?.text ?? "", mediaCount: (s.echo?.media ?? []).length, price: s.echo?.price ?? 0,
      };
      const r = { accountId: s.accountId, fanId: String(s.fanId), way, others: [] };
      for (const [name, k, data] of caches) {
        const next = cache.bumpAfterSend(k, data, s.accountId, fanId, msg, new Date().toISOString());
        if (name === "all") {
          r.all = view(data, next);
        } else if (name === s.accountId) {
          r.own = view(data, next);
        } else if (next !== data) {
          r.others.push(name);
        }
      }
      out.push(r);
    }
  }
  return { ways: WAYS, cases: out };
}
