import { describe, expect, it } from "vitest";

import { appendMsg, dropMsg, failMsg, insertByCreatedAt, insertMsg, reconcileMsg } from "@/lib/threadCache";
import type { OFMessage } from "@/lib/relay";

const msg = (id: number, extra: Partial<OFMessage> = {}): OFMessage =>
  ({ id, text: `m${id}`, createdAt: `2026-10-01T00:00:0${Math.abs(id) % 10}Z`, media: [], ...extra }) as OFMessage;
const opt = (tempId: number, extra: Partial<OFMessage> = {}) => msg(tempId, { _tempId: tempId, _pending: true, ...extra });
const idsOf = (l: OFMessage[]) => l.map((m) => m.id);

describe("appendMsg", () => {
  it.each([
    ["new id appended", [msg(1)], msg(2), [1, 2], false],
    ["id already there → same ref", [msg(1), msg(2)], msg(2), [1, 2], true],
    ["string id '2' vs 2 → same ref", [msg(2)], { ...msg(2), id: "2" as unknown as number }, [2], true],
    ["empty", [], msg(1), [1], false],
  ] as const)("%s", (_n, prev, m, want, same) => {
    const p = [...prev];
    const out = appendMsg(p, m);
    expect(idsOf(out)).toEqual(want);
    expect(out === p).toBe(same);
  });
});

describe("reconcileMsg", () => {
  const media = [{ id: 7, files: { thumb: { url: "blob:t" } } }] as unknown as OFMessage["media"];
  const bare = [{ id: 7, files: {} }] as unknown as OFMessage["media"];
  it.each([
    // name, prev, tempId, server, want ids
    ["optimistic row takes the server id", [msg(1), opt(-5)], -5, msg(9), [1, 9]],
    ["SSE echo first: optimistic dropped, echo kept once", [msg(1), msg(9), opt(-5)], -5, msg(9), [1, 9]],
    ["unknown tempId: nothing replaced", [msg(1)], -5, msg(9), [1]],
  ] as const)("%s", (_n, prev, tempId, server, want) => {
    expect(idsOf(reconcileMsg([...prev], tempId, server))).toEqual(want);
  });
  it("keeps the optimistic media urls while the CDN has none, stamped with its tempId", () => {
    const out = reconcileMsg([opt(-5, { media })], -5, msg(9, { media: bare }));
    expect(out[0]).toMatchObject({ id: 9, _pending: false, _tempId: -5 });
    expect(out[0].media[0].files).toEqual(media[0].files);
  });
  it("SSE echo first: the echo row gets the optimistic media fallback", () => {
    const out = reconcileMsg([msg(9, { media: bare }), opt(-5, { media })], -5, msg(9));
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ id: 9, _tempId: -5 });
    expect(out[0].media[0].files).toEqual(media[0].files);
  });
});

describe("failMsg / dropMsg", () => {
  it("fail marks only its row", () => {
    const prev = [msg(1), opt(-5), opt(-6)];
    const out = failMsg(prev, -5, { reason: "nope", refusedMediaIds: [3] } as never);
    expect(out[1]).toMatchObject({ _failed: true, _pending: false, _failedReason: "nope", _failedMediaIds: [3] });
    expect(out[0]).toBe(prev[0]);
    expect(out[2]).toBe(prev[2]);
  });
  it("fail without a failure leaves reason/ids undefined", () => {
    const out = failMsg([opt(-5)], -5);
    expect(out[0]).toMatchObject({ _failed: true, _failedReason: undefined, _failedMediaIds: undefined });
  });
  it.each([
    ["drops its row", [msg(1), opt(-5)], -5, [1]],
    ["unknown tempId keeps every row", [msg(1), opt(-5)], -6, [1, -5]],
  ] as const)("drop: %s", (_n, prev, tempId, want) => {
    expect(idsOf(dropMsg([...prev], tempId))).toEqual(want);
  });
});

describe("insertByCreatedAt", () => {
  it.each([
    ["newest goes last", [msg(1), msg(2)], msg(3), [1, 2, 3]],
    ["older slots in by time", [msg(1), msg(3)], msg(2), [1, 2, 3]],
    ["tie keeps arrival order", [msg(1), msg(2)], { ...msg(12), createdAt: msg(2).createdAt }, [1, 2, 12]],
    ["zone-less live row sorts as UTC", [msg(1), msg(3)], { ...msg(2), createdAt: "2026-10-01 00:00:02" }, [1, 2, 3]],
  ] as const)("%s", (_n, prev, row, want) => {
    expect(idsOf(insertByCreatedAt([...prev], row))).toEqual(want);
  });
});

describe("insertMsg", () => {
  it.each([
    ["new id slots in by time", [msg(1), msg(3)], msg(2), [1, 2, 3], false],
    ["newest goes last", [msg(1)], msg(2), [1, 2], false],
    ["id already there → same ref", [msg(1), msg(2)], msg(2), [1, 2], true],
    ["string id '2' vs 2 → same ref", [msg(2)], { ...msg(2), id: "2" as unknown as number }, [2], true],
    ["empty", [], msg(1), [1], false],
  ] as const)("%s", (_n, prev, m, want, same) => {
    const p = [...prev];
    const out = insertMsg(p, m);
    expect(idsOf(out)).toEqual(want);
    expect(out === p).toBe(same);
  });
});
