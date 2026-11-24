import { QueryClient } from "@tanstack/react-query";
import { expect, it } from "vitest";

import { setVaultHistory, vaultHistoryKey, type FanVaultHistoryResp } from "./useFanVaultHistory";

it("keeps the sync purchase when an older history read finishes late", async () => {
  const qc = new QueryClient();
  const queryKey = vaultHistoryKey("account", 123);
  const sent = { by_media: { "42": {
    send_count: 1, last_sent_at: null, last_price_cents: 800,
    was_purchased: false, last_purchase_at: null, total_paid_cents: 0,
  } } };
  const bought = { by_media: { "42": { ...sent.by_media["42"], was_purchased: true, total_paid_cents: 800 } } };
  let resolveRead!: (value: FanVaultHistoryResp) => void;
  const response = new Promise<FanVaultHistoryResp>((resolve) => { resolveRead = resolve; });
  const read = qc.fetchQuery({ queryKey, queryFn: () => response }).catch(() => {});

  expect(await setVaultHistory(qc, "account", 123, bought)).toBe(true);
  resolveRead(sent);
  await read;
  await response;

  expect(qc.getQueryData(queryKey)).toEqual(bought);
});
