"use client";

/** An Ultra plan's numbered step list (plan page + help bot Ultra panel): each server card (PlanStepCard), and the
 *  waiting judge's pick card right under its step. Ticks dispatch to ultraRunReducer. */
import { cn } from "@/lib/utils";
import { PickCard } from "./PickCard";
import { PlanStepCard } from "./PlanStepCard";
import type { Action, UltraRun } from "./ultraRunReducer";

export function PlanSteps({ state, dispatch, className }: {
  state: UltraRun;
  dispatch: (a: Action) => void;
  className?: string;
}) {
  const plan = state.plan;
  if (!plan) return null;
  return (
    <ol className={cn("flex flex-col gap-3", className)}>
      {plan.card.flatMap((card, i) => {
        const step = plan.step_states.find((s) => s.id === card.id);
        const row = <PlanStepCard key={card.id} card={card} index={i} step={step} />;
        if (step?.state !== "needs_you" || state.picked?.step !== step.id) return [row];
        return [row, (
          <li key={`${card.id}:pick`}>
            <PickCard step={step} ticked={state.picked.ids} disabled={state.busy !== null}
              onTick={(id) => dispatch({ type: "tick", id })} />
          </li>
        )];
      })}
    </ol>
  );
}
