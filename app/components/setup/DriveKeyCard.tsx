"use client";

/**
 * DriveKeyCard — Settings → AI keys → Google Drive. The one server key the vault
 * importer's Drive section needs (GOOGLE_DRIVE_API_KEY), set where an operator
 * looks for keys rather than only in the master's System tab. It is the same
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
import { Badge, Button, Card } from "@/components/ui/primitives";
import SecretKeyField from "@/components/setup/SecretKeyField";
import { Skeleton } from "@/components/ui/Skeleton";

const DRIVE_KEY = "GOOGLE_DRIVE_API_KEY";

function Intro() {
  return (
    <p className="text-sm text-fg-dim">
      Lets Vault Pro import from a Google Drive folder link. A plain Google API key with the
      Drive API enabled — the folder itself must be shared as &quot;Anyone with the link can
      view&quot;.
    </p>
  );
}

function DriveKeyEditor() {
  const { data, isLoading, error } = useSecrets();
  const save = useSaveSecrets();
  const { draft, dirty, setField, save: onSave, clear, note } = useKeyDraft(
    save.mutateAsync,
    "Saved — Drive import works on the next upload.",
  );
  const k = data?.keys?.[DRIVE_KEY];

  if (isLoading) return <div className="space-y-2" aria-busy="true"><Skeleton className="h-4 w-32" /><Skeleton className="h-9 w-full" /></div>;
  if (error || !k) return <div className="text-sm text-err">Couldn&apos;t load the key&apos;s status.</div>;
  return (
    <div className="space-y-2">
      <SecretKeyField
        name={DRIVE_KEY}
        k={k}
        value={draft[DRIVE_KEY] ?? ""}
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

export default function DriveKeyCard() {
  const { user } = useUser();
  return (
    <Card className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold">Google Drive</h2>
        <Badge color="muted">server key</Badge>
      </div>
      <Intro />
      {user?.is_admin === true ? (
        <DriveKeyEditor />
      ) : (
        <p className="text-sm text-fg-dim">
          This key belongs to the server, so its owner sets it here.
        </p>
      )}
    </Card>
  );
}
