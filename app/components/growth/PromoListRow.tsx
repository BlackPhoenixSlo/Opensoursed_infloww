"use client";


import { useState } from "react";

import { useFanLists } from "@/components/audience/fanLists";
import { IfHelp, IfSelect, IfSwitch, type IfOption } from "@/components/ui/infloww";
import { errMsg, useIfConfirm } from "@/components/growth/_bits";
import { LIST_NAME_MAX } from "@/components/growth/LinkMetaFields";
import { usePromoList, useSavePromoList, type PromoListSetting } from "@/hooks/useGrowth";

export const MODIFY_LIST = "Modify list?\n\nEditing the list will not affect already-added fans";
export const DELETE_LIST = "Delete the list?\n\nOnce deleted, new subscribers will not be added to the list";

export const PROMO_LIST_HELP = "Adds every promotion's fans to this OnlyFans list, then new claimers about hourly.";
const PROMO_LIST_DETAIL =
  "Adds every promotion's fans to this OnlyFans list now. Fans who claim later are added when the figures are next " +
  "read from OnlyFans, about every hour. Fans already added stay in it.";

const OFF: PromoListSetting = { enabled: false, list_id: null, list_name: null };

export default function PromoListRow({ accountId }: { accountId: string | null }) {
  const q = usePromoList(accountId);
  const saveM = useSavePromoList(accountId);
  const { customLists, isLoading } = useFanLists(accountId);
  const confirm = useIfConfirm();
  const [err, setErr] = useState<string | null>(null);
  const cur = q.data ?? OFF;

  // OnlyFans' add-to-list takes a custom list's number; the built-ins (named ids) are not offered.
  const lists = customLists
    .filter((l) => /^\d+$/.test(String(l.id)))
    .map((l) => ({ id: String(l.id), name: l.name ?? `List ${l.id}` }));
  if (cur.list_id && !lists.some((l) => l.id === cur.list_id)) {
    lists.unshift({ id: cur.list_id, name: cur.list_name || `List ${cur.list_id}` });
  }

  async function save(next: PromoListSetting) {
    setErr(null);
    try { await saveM.mutateAsync(next); } catch (e) { setErr(errMsg(e, "Save failed")); }
  }

  const ask = (text: string) => {
    const [title, body] = text.split("\n\n");
    return confirm.ask(title, body);
  };

  async function pick(id: string) {
    if (!id) {
      if (cur.list_id && await ask(DELETE_LIST)) void save(OFF);
      return;
    }
    if (id === cur.list_id) return;
    if (cur.list_id && !(await ask(MODIFY_LIST))) return;
    const name = (lists.find((l) => l.id === id)?.name ?? "").slice(0, LIST_NAME_MAX) || null;
    void save({ enabled: cur.list_id ? cur.enabled : true, list_id: id, list_name: name });
  }

  async function toggle() {
    if (!cur.enabled) {
      if (cur.list_id) void save({ ...cur, enabled: true });
      return;
    }
    if (await ask(DELETE_LIST)) void save({ ...cur, enabled: false });
  }

  // A failed settings read disables the row: saving over an unread setting would skip "Modify list?" and overwrite it.
  const busy = !accountId || q.isLoading || q.isError || saveM.isPending;
  const options: IfOption[] = [
    { value: "", label: isLoading ? "Loading lists…" : "None" },
    ...lists.map((l) => ({ value: l.id, label: l.name })),
  ];
  return (
    <section aria-label="Add fans to list" className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span id="promo-list-label" className="text-[16px] font-medium text-fg">Add fans to list</span>
        <div className="flex items-center gap-4">
          <IfSelect
            id="promo-list"
            aria-label="Add fans to list"
            className="w-[240px]"
            value={cur.list_id ?? ""}
            options={options}
            disabled={busy}
            onChange={(v) => void pick(v)}
          />
          <span title={!cur.enabled && !cur.list_id ? "Pick a list first" : undefined}>
            <IfSwitch
              aria-label="Add fans to list"
              checked={cur.enabled}
              disabled={busy || (!cur.enabled && !cur.list_id)}
              onChange={() => void toggle()}
            />
          </span>
        </div>
      </div>
      <IfHelp title={PROMO_LIST_DETAIL}>{PROMO_LIST_HELP}</IfHelp>
      {q.isError && (
        <div role="alert" className="text-err text-xs">Couldn&apos;t read this setting. Reload to try again.</div>
      )}
      {err && <div role="alert" className="text-err text-xs">{err}</div>}
      {confirm.modal}
    </section>
  );
}
