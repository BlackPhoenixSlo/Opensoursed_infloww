// The Mass composer's all-models fan-out in node, through lib/app_ts.py: `users` operators, each
// with its own form in the app's real reducer (compose/massMessageReducer.ts, its fan-out slice
// compose/fanOut.ts), each round the app's own `massFanOutRound` (compose/massFanOut.ts: targets,
// body, runFanOut, progress + results dispatched), as useMassSend's all-models branch calls it.
// Only `post` and `dispatch` are node's: one fetch per target to the relay's real POST
// /api/of/v2/messages/queue (the operator's cookie, X-Account-Id), as useMassSend's `post`
// (app/lib/relay.ts) makes it, a non-2xx throwing as relay.post does; dispatch runs the reducer.
//
// Input: {base, cookie, accounts: [included ids, chip order], users, text, edit, rounds: [per user
//         {text, results}] | null}
//   rounds null: a first Broadcast (blank form, all models on, `text` typed).
//   rounds given: a retry. Each operator's form is rebuilt through the reducer (all models on, its
//   text, the earlier round's results merged by the `results` action), then Broadcast again.
// Mid-round (its first progress, the first send not yet answered) each operator types `edit` and
// clicks Start over (`discardResults`): the in-flight lock must refuse both (`mid`: the text and
// results then). After its round it types `edit` again: the content lock (fanOut `fanOutLocked`)
// must refuse it when any model took the broadcast.
// Output: {users: [{text (after the edit try), locked, mid: {text, results}, targets, results,
//          sends: [{account, status, t0, t1}], t0, t1}], body (operator 0's, round's)}; times epoch ms.
export async function run(load, input) {
  const fo = await load("/components/compose/fanOut.ts");
  const mm = await load("/components/compose/massMessageReducer.ts");
  const mf = await load("/components/compose/massFanOut.ts");
  const { base, cookie, accounts, text, edit } = input;
  const red = mm.massMessageReducer;

  function form(i) {
    let f = mm.initMassForm(null);
    f = red(f, { type: "setAllModels", on: true });
    const prior = input.rounds?.[i];
    f = red(f, mm.fieldAction("text", prior ? prior.text : text));
    if (prior) f = red(f, { type: "results", v: prior.results });
    return f;
  }

  async function operator(i) {
    let f = form(i);
    let body = null;
    let mid = null;
    const dispatch = (a) => {
      f = red(f, a);
      if (a.type === "progress" && a.done === 0) {
        f = red(red(f, mm.fieldAction("text", edit)), { type: "discardResults" });
        mid = { text: f.text, results: f.results };
      }
    };
    const sends = [];
    const send = async (accountId, b) => {
      body ??= b;
      const s = { account: accountId, status: 0, t0: Date.now(), t1: 0 };
      sends.push(s);
      try {
        const r = await fetch(`${base}/api/of/v2/messages/queue`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Cookie: cookie, "X-Account-Id": accountId },
          body: JSON.stringify(b),
        });
        s.status = r.status;
        await r.text();
        if (!r.ok) throw new Error(`relay ${r.status}`);
      } finally {
        s.t1 = Date.now();
      }
    };
    const t0 = Date.now();
    const round = await mf.massFanOutRound(f, accounts, false, send, dispatch);
    const t1 = Date.now();
    f = red(f, mm.fieldAction("text", edit));
    const targets = round.map((r) => r.accountId);
    return { text: f.text, locked: fo.fanOutLocked(f), mid, targets, results: f.results, sends, t0, t1, body };
  }

  const users = await Promise.all(Array.from({ length: input.users }, (_, i) => operator(i)));
  return { body: users[0]?.body ?? null, users: users.map(({ body, ...u }) => u) };
}
