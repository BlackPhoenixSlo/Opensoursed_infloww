"use client";

/**
 * AiKeyNotice — the amber "this automation cannot use its AI key" notice on an
 * automation's page.
 *
 * Background automations cannot toast, so their page asks
 * `GET /admin/ai-key-status` instead: a missing key (live presence) or the
 * key error the automation's LATEST run stopped on (a key the provider
 * rejected). The relay groups them into `notices` and writes every sentence;
 * this only renders them, with the same owner/chatter split as the toaster.
 * Nothing renders while all is well, or for kinds that call no LLM.
 */

import { useQuery } from "@tanstack/react-query";

import { ApiKeyMessage } from "@/components/ApiKeyToaster";
import { relay, type ApiKeyErrorPayload } from "@/lib/relay";

export interface AiKeyStatus {
  account_id: string;
  items: Array<{
    kind: string;
    provider: string;
    available: boolean;
    last_key_error: ApiKeyErrorPayload | null;
  }>;
  notices: ApiKeyErrorPayload[];
}

export function useAiKeyStatus(accountId: string | null | undefined, kinds: string[]) {
  const k = kinds.join(",");
  return useQuery<AiKeyStatus>({
    queryKey: ["ai-key-status", accountId ?? null, k],
    enabled: !!accountId && !!k,
    queryFn: () =>
      relay.get<AiKeyStatus>(
        `/admin/ai-key-status?account_id=${encodeURIComponent(accountId!)}&kinds=${encodeURIComponent(k)}`,
        { accountId: accountId! },
      ),
    // A fixed key should clear the notice on the next look, not in 3 days
    // (the app-wide staleTime) — this is one cheap read.
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
}

export function AiKeyNotice({ accountId, kinds }: { accountId: string | null | undefined; kinds: string[] }) {
  const q = useAiKeyStatus(accountId, kinds);
  const notices = q.data?.notices ?? [];
  if (notices.length === 0) return null;
  return (
    <div className="space-y-2">
      {notices.map((n) => (
        <div
          key={`${n.error}|${n.provider}`}
          role="status"
          className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-fg"
        >
          <ApiKeyMessage payload={n} />
        </div>
      ))}
    </div>
  );
}
