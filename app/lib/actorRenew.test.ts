import { afterEach, expect, it, vi } from "vitest";
import { fetchRenewing, renewActor, resetActorRenewal } from "./actorRenew";

afterEach(() => {
  resetActorRenewal();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it.each([
  ["GET", { detail: { error: "actor_expired" } }, true],
  ["POST", { detail: { error: "actor_missing" } }, true],
  ["GET", { detail: "sign in required" }, false],
  ["POST", { detail: { error: "handler_error" } }, false],
  ["POST", "unauthorized", false],
])("handles %s 401 %j, retry=%s", async (method, body, retry) => {
  const unauthorized = typeof body === "string"
    ? new Response(body, { status: 401 })
    : Response.json(body, { status: 401 });
  const retried = new Response(null, { status: 401 });
  const fetch = vi.fn()
    .mockResolvedValueOnce(unauthorized)
    .mockResolvedValueOnce(new Response())
    .mockResolvedValueOnce(retried);
  vi.stubGlobal("window", undefined);
  vi.stubGlobal("fetch", fetch);

  const init = { method };
  const result = await fetchRenewing("/admin/example", init);
  expect(result).toBe(retry ? retried : unauthorized);
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(
    retry ? ["/admin/example", "/auth/actor", "/admin/example"] : ["/admin/example"],
  );
  if (!retry) expect(result.bodyUsed).toBe(false);
});

it.each(["/auth/cells", "/admin/example"])("continues %s after a stalled renewal", async (url) => {
  vi.useFakeTimers();
  const timeout = vi.fn((ms: number) => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), ms);
    return controller.signal;
  });
  vi.stubGlobal("AbortSignal", { timeout });
  vi.stubGlobal("window", {});
  const response = new Response();
  const fetch = vi.fn((path: string, init: RequestInit) => {
    if (path !== "/auth/actor") return Promise.resolve(response);
    return new Promise<Response>((_, reject) => {
      init.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true });
    });
  });
  vi.stubGlobal("fetch", fetch);

  const request = fetchRenewing(url, {});
  const renewal = renewActor();
  expect(fetch.mock.calls.map(([path]) => path)).toEqual(["/auth/actor"]);
  await vi.advanceTimersByTimeAsync(10_000);
  expect(fetch.mock.calls.map(([path]) => path)).toEqual(["/auth/actor", url]);
  await expect(renewal).resolves.toBe(false);
  await expect(request).resolves.toBe(response);
});
