import type { Dispatch } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { resolveSmartLists } from "@/hooks/useSmartLists";
import { relay } from "@/lib/relay";
import { recordSchedule } from "@/lib/scheduleHistory";

import { massFanOutRound } from "./massFanOut";
import {
  buildMassBody, gifOnlyForm, type GifFailure, type MassAction, type MassForm, type MassResolved,
} from "./massMessageReducer";

export function useMassSend({
  form, dispatch, online, invalid, employeeId, onClose, isEligible,
}: {
  form: MassForm;
  dispatch: Dispatch<MassAction>;
  online: boolean;
  invalid: string | null;
  employeeId: number | undefined;
  onClose: () => void;
  isEligible: (id: string) => boolean;
}) {
  const qc = useQueryClient();
  const { allModels, schedule, smartInclude, smartExclude, pickedGifs } = form;

  async function post(forAccountId: string, body: Record<string, unknown>) {
    if (!isEligible(forAccountId)) throw new Error("Creator is no longer eligible to broadcast");
    const resp = await relay.post(
      "/api/of/v2/messages/queue",
      body,
      { accountId: forAccountId, employeeId },
    );
    if (schedule) recordSchedule(forAccountId, schedule);
    return resp;
  }

  async function resolveSegments(): Promise<MassResolved> {
    const [userIds, excludeUserIds] = await Promise.all([
      resolveSmartLists(smartInclude),
      resolveSmartLists(smartExclude),
    ]);
    // A segment matching nobody must stop the send: the body would equal no segment at all and "message my whales" would reach everyone.
    if (smartInclude.size > 0 && userIds.length === 0) {
      throw new Error(
        "The Smart List you picked matches 0 fans right now — nothing was sent. " +
        "Adjust the segment or remove it to message an audience list instead.",
      );
    }
    return { userIds, excludeUserIds };
  }

  return useMutation({
    mutationFn: async (targets: string[]): Promise<boolean> => {
      if (invalid) throw new Error(invalid);

      if (allModels) {
        const round = await massFanOutRound(form, targets, online, post, dispatch);
        return round.every((r) => r.ok);
      }

      const aid = targets[0];
      const resolved = await resolveSegments();
      await post(aid, buildMassBody(form, online, resolved));
      // The main send landed: a GIF failure must spend the form, not re-arm Broadcast and repeat the paid broadcast.
      const failed: GifFailure[] = [];
      for (const g of pickedGifs.slice(1)) {
        try {
          await post(aid, buildMassBody(gifOnlyForm(form, g), online, resolved));
        } catch (e) {
          failed.push({ id: g.id, title: g.title, error: (e as Error).message });
        }
      }
      if (failed.length === 0) return true;
      dispatch({ type: "gifSendsFailed", failed });
      return false;
    },
    onSettled: (_data, _error, targets) => {
      const sentFrom = new Set(targets);
      qc.invalidateQueries({
        predicate: (q) => {
          const key = q.queryKey;
          if (!Array.isArray(key) || key.length < 2) return false;
          if (key[0] !== "scheduled" && key[0] !== "mass-messages") return false;
          return sentFrom.has(String(key[1]));
        },
      });
    },
    onSuccess: (mayClose) => {
      if (mayClose) onClose();
    },
  });
}
