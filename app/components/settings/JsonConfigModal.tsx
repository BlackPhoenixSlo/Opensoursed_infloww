"use client";


import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Braces } from "lucide-react";

import { RawJsonModal } from "@/components/automations/RawJsonModal";
import { IfButton } from "@/components/ui/infloww";
import { relay, type RelayContext } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { parseJsonObjectOr } from "@/lib/rawJsonReducer";

const BG_CTX: RelayContext = { priority: "background" };

export type ConfigSurface = "nudge-config";

const SURFACES: Record<
  ConfigSurface,
  { label: string; path: string; queryKey: (accountId: string) => unknown[] }
> = {
  "nudge-config": { label: "Nudge online config", path: "/admin/nudge-config", queryKey: (a) => ["nudge-config", a] },
};

export function EditRawJsonButton({
  surface,
  accountId,
  className,
  label = "Edit raw JSON",
}: {
  surface: ConfigSurface;
  accountId: string | null;
  className?: string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <IfButton
        variant="link"
        icon={Braces}
        disabled={!accountId}
        onClick={() => setOpen(true)}
        className={cn("hidden md:inline-flex", className)}
        title={accountId ? "Edit the raw JSON for this config" : "Pick an account first"}
      >
        {label}
      </IfButton>
      {open && accountId && (
        <JsonConfigModal
          surface={surface}
          accountId={accountId}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function JsonConfigModal({
  surface,
  accountId,
  onClose,
}: {
  surface: ConfigSurface;
  accountId: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { label, path, queryKey } = SURFACES[surface];
  const [text, setText] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  const q = useQuery<{ config: unknown }>({
    queryKey: ["raw-json-config", surface, accountId],
    queryFn: () =>
      relay.get<{ config: unknown }>(
        `${path}?account_id=${encodeURIComponent(accountId)}`,
        BG_CTX,
      ),
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    // Stop seeding once the user edits so a refetch cannot stomp their changes.
    if (q.data && !dirty) {
      setText(JSON.stringify(q.data.config ?? {}, null, 2));
    }
  }, [q.data, dirty]);

  const save = useMutation({
    mutationFn: (config: unknown) =>
      relay.put(path, { account_id: accountId, config }, { cellAccountId: accountId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKey(accountId) });
      qc.invalidateQueries({ queryKey: ["raw-json-config", surface, accountId] });
      onClose();
    },
    onError: (e: Error) => setErr(e.message || "Save failed"),
  });

  const parseOrError = () => parseJsonObjectOr(text, "Config", '{ "enabled": true }', setErr);

  function onSave() {
    setErr(null);
    const parsed = parseOrError();
    if (parsed) save.mutate(parsed);
  }

  function reformat() {
    setErr(null);
    const parsed = parseOrError();
    if (parsed) setText(JSON.stringify(parsed, null, 2));
  }

  return (
    <RawJsonModal
      name={label}
      subtitle={`acct ${accountId}`}
      text={text}
      onText={(t) => {
        setDirty(true);
        setText(t);
        if (err) setErr(null);
      }}
      error={err}
      status={q.isLoading ? "Loading current config…" : q.isError ? <span className="text-err">Couldn&apos;t load this config.</span> : undefined}
      busy={save.isPending}
      onReformat={reformat}
      onSave={onSave}
      onClose={onClose}
    />
  );
}
