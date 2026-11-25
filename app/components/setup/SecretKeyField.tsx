"use client";


import { useId } from "react";

import type { SecretKeyStatus } from "@/hooks/useSecrets";
import { Badge, Input, Textarea } from "@/components/ui/primitives";
import KeyLink from "@/components/setup/KeyLink";

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
        {/* The server says whether a clear is accepted; deriving it from `source` got the founder password backwards. */}
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
      <KeyLink name={name} />
    </div>
  );
}
