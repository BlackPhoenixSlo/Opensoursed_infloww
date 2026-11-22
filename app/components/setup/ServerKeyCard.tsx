"use client";

/**
 * ServerKeyCard — one secrets-store key's card in Settings → AI keys (AiKeysTab names
 * which: the fallback TypeSafe key, the vault importer's Google Drive key), set where an
 * operator looks for keys rather than only in the master's System tab. It is the same
 * secrets-store entry the "Server keys" card edits: stored server-side in
 * service/secrets/secrets.json, read masked, never sent back raw, and the relay
 * still falls back to the env var when it is unset here.
 *
 * `/admin/secrets` is master-only, so anyone else sees one line saying who sets
 * it and never fires the read.
 */

import { useUser } from "@/contexts/UserContext";
import { useKeyDraft } from "@/hooks/useKeyDraft";
import { useSaveSecrets, useSecrets } from "@/hooks/useSecrets";
import { Button } from "@/components/ui/primitives";
import SecretKeyField from "@/components/setup/SecretKeyField";
import { Skeleton } from "@/components/ui/Skeleton";

type ServerKeyProps = {
  /** The secrets-store key (service/secrets_store.py KNOWN). */
  name: string;
  intro: React.ReactNode;
  savedNote: string;
};

function ServerKeyEditor({ name, savedNote }: Omit<ServerKeyProps, "intro">) {
  const { data, isLoading, error } = useSecrets();
  const save = useSaveSecrets();
  const { draft, dirty, setField, save: onSave, clear, note } = useKeyDraft(
    save.mutateAsync,
    savedNote,
  );
  const k = data?.keys?.[name];

  if (isLoading) return <div className="space-y-2" aria-busy="true"><Skeleton className="h-4 w-32" /><Skeleton className="h-9 w-full" /></div>;
  if (error || !k) return <div className="text-sm text-err">Couldn&apos;t load the key&apos;s status.</div>;
  return (
    <div className="space-y-2">
      <SecretKeyField
        name={name}
        k={k}
        value={draft[name] ?? ""}
        setField={setField}
        clear={clear}
        pending={save.isPending}
      />
      <div className="flex items-center gap-3 pt-1">
        <Button onClick={onSave} disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {note && <span className="text-sm text-fg-dim">{note}</span>}
      </div>
    </div>
  );
}

/** A section body; AI keys' Panel gives it its Section title. */
export default function ServerKeyCard({ name, intro, savedNote }: ServerKeyProps) {
  const { user } = useUser();
  return (
    <div className="space-y-3">
      <p className="text-sm text-fg-dim">{intro}</p>
      {user?.is_admin === true ? (
        <ServerKeyEditor name={name} savedNote={savedNote} />
      ) : (
        <p className="text-sm text-fg-dim">
          This key belongs to the server, so its owner sets it here.
        </p>
      )}
    </div>
  );
}
