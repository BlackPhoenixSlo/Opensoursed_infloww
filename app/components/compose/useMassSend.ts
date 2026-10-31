/**
 * useMassSend — MassMessageComposer's send: one mutation for both shapes.
 *
 *   • All-models: compose/massFanOut `massFanOutRound` (the same text-only
 *     body from each target in turn, its results merged into the form) — the
 *     modal closes only when every target took it. A partial round stays
 *     open, the content locked, for the retry.
 *   • One account: the Smart Lists resolved to fan ids (a segment matching
 *     nobody stops the send), the main send with the first GIF, then each
 *     further GIF as its own send (massMessageReducer `gifOnlyForm`). A GIF
 *     send failing after the main one landed spends the form
 *     (`gifSendsFailed`) instead of re-arming a (paid) re-broadcast.
 *   • Only a refused form (`invalid`, massMessageReducer `validateMass`) or a
 *     one-account failure throws (the footer shows `send.error`).
 *   • It resolves to whether the modal may close (onSuccess closes it).
 *   • Either way the sent-from accounts' queued / broadcast lists refetch.
 */

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
  form, dispatch, online, included, invalid, employeeId, onClose,
}: {
  form: MassForm;
  dispatch: Dispatch<MassAction>;
  online: boolean;
  /** The included models (all-models; chip order). */
  included: string[];
  invalid: string | null;
  employeeId: number | undefined;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { allModels, accountId, schedule, smartInclude, smartExclude, pickedGifs } = form;

  // One POST to the queue; records the schedule pick on success.
  async function post(forAccountId: string, body: Record<string, unknown>) {
    const resp = await relay.post(
      "/api/of/v2/messages/queue",
      body,
      { accountId: forAccountId, employeeId },
    );
    if (schedule) recordSchedule(forAccountId, schedule);
    return resp;
  }

  // The picked Smart Lists as explicit fan ids (one account only).
  async function resolveSegments(): Promise<MassResolved> {
    const [userIds, excludeUserIds] = await Promise.all([
      resolveSmartLists(smartInclude),
      resolveSmartLists(smartExclude),
    ]);
    // A segment that matches nobody must STOP the send. Without this the body
    // is byte-identical to picking no segment at all, so "message my whales"
    // silently became "message everyone" — the worst possible failure for a
    // mass send, and completely invisible to the operator.
    if (smartInclude.size > 0 && userIds.length === 0) {
      throw new Error(
        "The Smart List you picked matches 0 fans right now — nothing was sent. " +
        "Adjust the segment or remove it to message an audience list instead.",
      );
    }
    return { userIds, excludeUserIds };
  }

  return useMutation({
    // Resolves to whether the modal may close.
    mutationFn: async (): Promise<boolean> => {
      if (invalid) throw new Error(invalid);

      if (allModels) {
        // Text-only fan-out — no media until upload-from-computer comes back.
        const round = await massFanOutRound(form, included, online, post, dispatch);
        return round.every((r) => r.ok);
      }

      // One account: mixed payload (vault ids + fresh claims), the first GIF.
      const aid = accountId!;
      const resolved = await resolveSegments();
      await post(aid, buildMassBody(form, online, resolved));
      // OF accepts ONE GIF per send: the rest go out as GIF-only sends to the
      // same audience (gifOnlyForm), after the main one landed. From here the
      // send succeeded: a failure here must not re-arm Broadcast, which would
      // repeat the (paid) broadcast — the form is spent instead.
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
    onSettled: () => {
      // Refresh the queued-send + broadcast lists for the account(s) we sent
      // from — after a partial failure too (something did go out). Scheduled
      // sends live under ["scheduled", accountId] (useScheduledMessages) and
      // immediate broadcasts under ["mass-messages", accountId, …]
      // (useMassMessages).
      const sentFrom = new Set(allModels ? included : accountId ? [accountId] : []);
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
