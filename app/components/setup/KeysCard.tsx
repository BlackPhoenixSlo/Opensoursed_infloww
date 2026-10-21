"use client";

/**
 * KeysCard — Setup → Keys. Paste API keys and tokens here instead of editing
 * the server's .env. Saved values live on the server only (service/secrets/secrets.json)
 * and take effect immediately — no restart.
 *
 * Each field shows whether the key is currently set and where the live value
 * comes from (this UI vs the server env). The raw value is never sent back to
 * the browser; an empty field means "leave unchanged".
 */

import { useSecrets, useSaveSecrets, type SecretKeyStatus } from "@/hooks/useSecrets";
import { useKeyDraft } from "@/hooks/useKeyDraft";
import { Badge, Button, Card } from "@/components/ui/primitives";
import SecretKeyField from "@/components/setup/SecretKeyField";

export default function KeysCard() {
  const { data, isLoading, error } = useSecrets();
  const save = useSaveSecrets();
  const { draft, dirty, setField, save: onSave, clear: clearKey, note } =
    useKeyDraft(save.mutateAsync, "Saved — takes effect on the next run.");

  const keys = data?.keys ?? {};
  // Preserve backend (registry) order, bucket by group.
  const groups: { name: string; items: [string, SecretKeyStatus][] }[] = [];
  for (const entry of Object.entries(keys)) {
    const g = entry[1].group;
    let bucket = groups.find((b) => b.name === g);
    if (!bucket) {
      bucket = { name: g, items: [] };
      groups.push(bucket);
    }
    bucket.items.push(entry);
  }

  return (
    <Card className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">Server keys</h2>
          <Badge color="muted">founder only</Badge>
        </div>
        <p className="text-sm text-fg-dim">
          This <em>server&apos;s</em> own keys and tokens — not any agency&apos;s.
          Paste them here instead of editing the VPS <code>.env</code>; they&apos;re
          stored on the server only and take effect immediately. Leave a field
          blank to keep its current value.
        </p>
        <p className="text-[11px] text-fg-dim mt-1">
          A model owned by an agency bills that agency&apos;s key from{" "}
          <strong>Settings → AI keys</strong>, never these. These cover models with
          no owner and the relay&apos;s own maintenance calls.
        </p>
      </div>

      {isLoading && <div className="text-sm text-fg-dim">Loading…</div>}
      {error && (
        <div className="text-sm text-err">Couldn&apos;t load key status.</div>
      )}

      {groups.map((g) => (
        <section key={g.name} className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-dim">
            {g.name}
          </h3>
          {g.items.map(([name, k]) => (
            <SecretKeyField
              key={name}
              name={name}
              k={k}
              value={draft[name] ?? ""}
              setField={setField}
              clear={clearKey}
              pending={save.isPending}
            />
          ))}
        </section>
      ))}

      <div className="flex items-center gap-3 pt-1">
        <Button onClick={onSave} disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving…" : "Save changes"}
        </Button>
        {note && <span className="text-sm text-fg-dim">{note}</span>}
      </div>
    </Card>
  );
}
