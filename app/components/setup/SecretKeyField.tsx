"use client";

/**
 * One server key's row: its label, whether it is set and from where, a clear
 * button when the server would accept one, and the masked field. Shared by
 * the "Server keys" card and the Drive key card, which edit the same
 * /admin/secrets store — two copies of this row had already drifted.
 */

import { useId } from "react";

import type { SecretKeyStatus } from "@/hooks/useSecrets";
import { Badge, Input, Textarea } from "@/components/ui/primitives";

export default function SecretKeyField({
  name,
  k,
  value,
  setField,
  clear,
  pending,
}: {
  name: string;
  k: SecretKeyStatus;
  value: string;
  setField: (name: string, value: string) => void;
  clear: (name: string) => void;
  pending: boolean;
}) {
  const id = useId();
  const placeholder = k.set ? (k.secret ? `${k.hint} — leave blank to keep` : k.hint) : "not set";
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {k.label}
        </label>
        {k.set ? (
          <Badge color="ok">set{k.source === "env" ? " · via env" : " · via UI"}</Badge>
        ) : (
          <Badge color="muted">not set</Badge>
        )}
        {/* The SERVER says whether a clear would be accepted. Deriving it here
            from `source` got it exactly backwards for the founder password:
            offered in the one state set_many refuses, hidden in the one state
            it permits. */}
        {k.clearable && (
          <button
            type="button"
            disabled={pending}
            onClick={() => clear(name)}
            className="text-[11px] text-err hover:underline disabled:opacity-40"
          >
            clear
          </button>
        )}
      </div>
      {k.multiline ? (
        <Textarea
          id={id}
          rows={3}
          value={value}
          placeholder={placeholder}
          onChange={(e) => setField(name, e.target.value)}
          className="font-mono text-xs"
        />
      ) : (
        <Input
          id={id}
          type={k.secret ? "password" : "text"}
          value={value}
          placeholder={placeholder}
          autoComplete="off"
          onChange={(e) => setField(name, e.target.value)}
        />
      )}
      {k.help && <p className="text-[11px] text-fg-dim">{k.help}</p>}
    </div>
  );
}
