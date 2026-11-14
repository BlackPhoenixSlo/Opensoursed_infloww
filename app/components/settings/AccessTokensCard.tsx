"use client";

/**
 * Settings → AI keys → Access tokens: the owner's own access tokens, for an AI app (an MCP client) that acts as
 * them. List (hint, expiry, last use), New token (name + expiry; the token shown once, with Copy) and Revoke.
 * The dialog's state is `accessTokensForm` (a reducer); the relay is service/owner_tokens_api.py, which only an
 * owner's browser session reaches — a token cannot list, mint or revoke tokens.
 */

import { useReducer, useState } from "react";

import { useCreateOwnerToken, useOwnerTokens, useRevokeOwnerToken, type OwnerToken } from "@/hooks/useOwnerTokens";
import {
  accessTokensFormReducer, buildPayload, canSubmit, INITIAL_FORM, NAME_MAX, TOKEN_DAYS, toTokenDays,
} from "@/components/settings/accessTokensForm";
import {
  Card, Field, FieldInput, FieldSelect, IF_BTN, IF_BTN_PRIMARY, LoadError, SettingsTable, TABLE_CELL, TABLE_ROW,
} from "@/components/settings/SettingsPanel";
import { IfModal } from "@/components/ui/infloww";
import { ifConfirm } from "@/components/ui/ifConfirm";
import { cn } from "@/lib/utils";

const TIP = "text-[length:var(--if-fs-sm)] leading-5 text-[var(--if-fg-2)]";
const DAY_OPTIONS = TOKEN_DAYS.map((d) => ({ value: String(d), label: d === 365 ? "1 year" : `${d} days` }));
const FORM_ID = "access-token-form";

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : "—");

function state(t: OwnerToken, now: number): "revoked" | "expired" | "active" {
  if (t.revoked_at) return "revoked";
  return Date.parse(t.expires_at) <= now ? "expired" : "active";
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={IF_BTN}
      onClick={() => { void navigator.clipboard?.writeText(text).then(() => setCopied(true), () => {}); }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export default function AccessTokensCard() {
  const q = useOwnerTokens();
  const createM = useCreateOwnerToken();
  const revokeM = useRevokeOwnerToken();
  const [form, dispatch] = useReducer(accessTokensFormReducer, INITIAL_FORM);
  const close = () => { dispatch({ type: "close" }); createM.reset(); };
  const submit = () => {
    if (!canSubmit(form)) return;
    createM.mutate(buildPayload(form), { onSuccess: (r) => dispatch({ type: "created", name: r.name, token: r.token }) });
  };
  const revoke = async (t: OwnerToken) => {
    if (await ifConfirm(`Revoke "${t.name}"? Apps using it stop working at once.`, { confirmLabel: "Revoke", danger: true })) {
      revokeM.mutate(t.id);
    }
  };
  const tokens = q.data?.tokens ?? [];
  const [now] = useState(() => Date.now()); // render stays pure; the card is short-lived

  return (
    <Card
      title="Access tokens"
      control={<button type="button" className={IF_BTN} onClick={() => dispatch({ type: "open" })}>New token</button>}
    >
      <p className={TIP}>
        Lets an AI app (an MCP client such as Claude Desktop) use the MCP tools as you, on your own models
        only, and download the report files they make. Nothing else in the app accepts it. Keep a token secret, like a password.
      </p>
      <LoadError error={q.error} />
      {revokeM.error && <p role="alert" className="mt-2 text-sm text-[var(--if-danger)]">{revokeM.error.message}</p>}
      {tokens.length > 0 && (
        <div className="mt-4">
          <SettingsTable aria-label="Access tokens" columns={["Name", "Token", "Expires", "Last used", ""]}>
            {tokens.map((t) => {
              const st = state(t, now);
              return (
                <tr key={t.id} className={TABLE_ROW}>
                  <td className={TABLE_CELL}>{t.name}</td>
                  <td className={cn(TABLE_CELL, "font-mono text-[var(--if-fg-2)]")}>{t.hint}</td>
                  <td className={TABLE_CELL}>{day(t.expires_at)}</td>
                  <td className={TABLE_CELL}>{t.last_used_at ? day(t.last_used_at) : "Never"}</td>
                  <td className={cn(TABLE_CELL, "text-right")}>
                    {st === "active" ? (
                      <button type="button" className={IF_BTN} disabled={revokeM.isPending} onClick={() => void revoke(t)}>
                        Revoke
                      </button>
                    ) : (
                      <span className="text-[var(--if-fg-3)]">{st === "revoked" ? "Revoked" : "Expired"}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </SettingsTable>
        </div>
      )}
      {form.open && (
        <IfModal
          title={form.created ? "Copy your access token" : "New access token"}
          onClose={close}
          footer={form.created ? (
            <button type="button" className={IF_BTN_PRIMARY} onClick={close}>Done</button>
          ) : (
            <>
              <button type="button" className={IF_BTN} onClick={close}>Cancel</button>
              <button type="submit" form={FORM_ID} className={IF_BTN_PRIMARY} disabled={!canSubmit(form) || createM.isPending}>
                {createM.isPending ? "Creating…" : "Create"}
              </button>
            </>
          )}
        >
          {form.created ? (
            <>
              <p className={`mb-3 ${TIP}`}>
                Copy &quot;{form.created.name}&quot; now and paste it into your AI app. It is not shown again.
              </p>
              <div className="flex items-center gap-2">
                <FieldInput readOnly aria-label="Access token" value={form.created.token} className="font-mono" onFocus={(e) => e.currentTarget.select()} />
                <CopyButton text={form.created.token} />
              </div>
            </>
          ) : (
            <form id={FORM_ID} onSubmit={(e) => { e.preventDefault(); submit(); }}>
              <Field label="Name" htmlFor="access-token-name">
                <FieldInput
                  id="access-token-name"
                  value={form.name}
                  maxLength={NAME_MAX}
                  placeholder="e.g. Claude Desktop"
                  autoFocus
                  onChange={(e) => dispatch({ type: "name", value: e.target.value })}
                />
              </Field>
              <Field label="Expires in" htmlFor="access-token-days">
                <FieldSelect
                  id="access-token-days"
                  value={String(form.days)}
                  options={DAY_OPTIONS}
                  onChange={(v) => dispatch({ type: "days", value: toTokenDays(v) })}
                />
              </Field>
              {createM.error && <p role="alert" className="text-sm text-[var(--if-danger)]">{createM.error.message}</p>}
            </form>
          )}
        </IfModal>
      )}
    </Card>
  );
}
