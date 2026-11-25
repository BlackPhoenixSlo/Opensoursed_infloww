import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, post: vi.fn() } };
});

import { relay, RelayError } from "@/lib/relay";
import { fillPlanKey, useFillApply, useFillPlan } from "@/hooks/useSavedReplies";

const post = relay.post as unknown as Mock;
const plan = { status: "no_fit", steps: [] };

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

const metaOf = (client: QueryClient) => client.getQueryCache().find({ queryKey: fillPlanKey("c1", "Seq") })?.meta;

afterEach(() => {
  cleanup();
  post.mockReset();
});

describe("a Fill plan is never persisted", () => {
  it("the dialog's read", async () => {
    post.mockResolvedValue(plan);
    const { client, wrapper } = setup();
    renderHook(() => useFillPlan("c1", "Seq"), { wrapper });
    await waitFor(() => expect(client.getQueryData(fillPlanKey("c1", "Seq"))).toEqual(plan));
    expect(metaOf(client)).toEqual({ persist: false });
  });

  it.each([
    ["non-ok answer", () => post.mockResolvedValue({ status: "no_fit", plan })],
    ["409 stale", () => post.mockRejectedValue(new RelayError(409, { detail: { error: "stale", plan } }))],
  ])("a press's %s seeding it with no dialog open", async (_name, answer) => {
    answer();
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useFillApply(), { wrapper });
    await result.current.mutateAsync({ account: "c1", sequence: "Seq" }).catch(() => undefined);
    expect(client.getQueryData(fillPlanKey("c1", "Seq"))).toEqual(plan);
    expect(metaOf(client)).toEqual({ persist: false });
  });
});
