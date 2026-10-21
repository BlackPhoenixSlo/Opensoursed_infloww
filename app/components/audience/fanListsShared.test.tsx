/**
 * The `["fan-lists", account]` cache is shared: the Mass premade composer and the funnel launch panel read it too.
 * Whichever screen loads first fills it, so every reader must read every list (readAllFanLists), or a link's List
 * select opened after the composer would offer only the first 50.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";

const get = vi.fn(async (path: string) => {
  const rows = Array.from({ length: 60 }, (_, i) => ({ id: 710001 + i, name: `Fan list ${i + 1}`, type: "custom" }));
  const off = Number(new URL(path, "http://x").searchParams.get("offset") ?? 0);
  return { list: rows.slice(off, off + 50), hasMore: off + 50 < rows.length };
});
vi.mock("@/lib/relay", () => ({ relay: { get: (p: string) => get(p), post: vi.fn(), put: vi.fn() } }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: { id: 1 } }) }));
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => [{ id: "acct1", nickname: "A", color: "#fff" }],
  usePlatformAccounts: () => [{ id: "acct1", nickname: "A", color: "#fff" }],
}));
vi.mock("@/hooks/useAllModelsInclude", () => ({ useAllModelsInclude: () => ({ isIncluded: () => true, toggle: vi.fn() }) }));
vi.mock("@/hooks/useVaultMedia", () => ({ useVaultLists: () => ({ data: { list: [] }, isLoading: false }) }));
vi.mock("@/components/chat/VaultPicker", () => ({ VaultPicker: () => null }));

import LinkMetaFields, { useLinkMetaFields } from "@/components/growth/LinkMetaFields";
import { FunnelLaunchPanel } from "@/components/automations/FunnelLaunchPanel";
import { PremadeForm } from "@/components/compose/PremadeComposer";
import { makeTestQueryClient } from "@/test-utils";

function ListSelect() {
  const f = useLinkMetaFields();
  return <LinkMetaFields f={f} id="shared" accountId="acct1" sources={[]} tags={[]} />;
}

afterEach(() => { cleanup(); get.mockClear(); });

const options = () => (document.getElementById("shared-list") as HTMLSelectElement).options.length - 1;

describe("the shared fan-lists cache", () => {
  it.each([
    ["the Mass premade composer", <PremadeForm key="c" kind="mass_premade" forcedAccountId="acct1" onComposePayload={() => {}} />],
    ["the funnel launch panel", <FunnelLaunchPanel key="f" funnel={{ id: 1, name: "F", description: null, opening_message: "hi", step_count: 1 }}
      accountId="acct1" onClose={() => {}} />],
  ])("holds every list when %s fills it first", async (_name, first) => {
    const client = makeTestQueryClient();
    render(<QueryClientProvider client={client}>{first}</QueryClientProvider>);
    await waitFor(() => expect(client.getQueryState(["fan-lists", "acct1"])?.status).toBe("success"));
    render(<QueryClientProvider client={client}><ListSelect /></QueryClientProvider>);
    await waitFor(() => expect(options()).toBe(60));
    expect(get.mock.calls.map((c) => c[0])).toEqual(["/api/of/v2/lists?limit=50", "/api/of/v2/lists?limit=50&offset=50"]);
  });
});
