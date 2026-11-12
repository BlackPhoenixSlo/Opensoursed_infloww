"use client";

/**
 * Model info, the account's short note every chat prompt pins (`account_ai_config.model_notes`, through
 * `_persona.compose_persona`: Get to know fans and Auto-reply). One block, shown on both pages, with its own Save
 * ("Save model info"): it PUTs the STORED brain back with only `model_notes` changed (the PUT replaces the brain).
 * The box mounts only once the stored brain is in hand, so a failed read is never saved back; its Save waits while any
 * brain PUT or re-read is out (`useAccountConfigBusy`), so it never lands on a stale copy.
 */

import { useState } from "react";

import { FormBlock } from "@/components/automations/automationPage";
import { Skeleton } from "@/components/ui/Skeleton";
import { IfTextArea, SaveRow, saveVerdict } from "@/components/ui/infloww";
import { useAccountConfig, useAccountConfigBusy, useSaveAccountConfig, type AccountConfigResp } from "@/hooks/useAccountConfig";

/** account_config_api / _persona.MODEL_NOTES_MAX. */
const NOTES_MAX = 1000;

/** A form block's fields while its read runs: a label bar over an input-sized bar, twice. */
export function FormSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="space-y-3">
      <Skeleton className="h-3 w-28" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-3 w-40" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}

export function ModelInfoBlock({ accountId }: { accountId: string }) {
  const cfgQ = useAccountConfig(accountId);
  return (
    <FormBlock title="Model info">
      {cfgQ.data ? <ModelInfoForm accountId={accountId} resp={cfgQ.data} /> : cfgQ.isLoading ? <FormSkeleton /> : (
        <p className="text-[14px] text-err">{(cfgQ.error as Error)?.message || "Could not load Model info."}</p>
      )}
    </FormBlock>
  );
}

function ModelInfoForm({ accountId, resp }: { accountId: string; resp: AccountConfigResp }) {
  const saveM = useSaveAccountConfig(accountId);
  // Any brain PUT or re-read out (this Save's or the page's model Save): `resp` may be stale, a PUT now could undo it.
  const busy = useAccountConfigBusy(accountId);
  // Empty → the prewritten template; its lines left blank never reach a prompt.
  const [text, setText] = useState(resp.config.model_notes || resp.model_notes_template || "");

  return (
    <>
      <p className="text-[12px] text-muted">
        A few short lines about this model. The AI reads them in Get to know fans and Auto-reply chats; a line left
        blank is ignored.
      </p>
      <IfTextArea
        aria-label="Model info"
        value={text}
        onChange={(e) => {
          if (saveM.isSuccess || saveM.isError) saveM.reset();
          setText(e.target.value);
        }}
        rows={7}
        maxLength={NOTES_MAX}
      />
      <SaveRow
        save={saveVerdict(saveM)}
        label="Save model info"
        disabled={busy}
        onSave={() => saveM.mutate({ ...resp.config, model_notes: text })}
      >
        <span className="text-[12px] text-muted tabular-nums">{text.length}/{NOTES_MAX}</span>
      </SaveRow>
    </>
  );
}
