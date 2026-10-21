/**
 * SwitchTrack — the drawing of an on/off switch: the Clone's 26×14 track
 * with its 10px knob (`.switch`, mh:73-74), in our colours (ADR-0001). It is
 * only the picture; the caller's button owns the role, the name and the flip.
 * Shared by the Messages Pro Window header's SFW and the Fan List's rail switch (the
 * app top bar draws Infloww's smaller switch itself, TopBar `SfwSwitch`).
 */

import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

const G = MP.windowHeader;

export function SwitchTrack({ on }: { on: boolean }) {
  return (
    <span aria-hidden className={cn(G.switch, "relative block transition-colors", on ? "bg-accent" : "bg-bg-elev-2")}>
      <span className={cn(G.switchKnob, on && G.switchKnobOn, "absolute bg-fg transition-all")} />
    </span>
  );
}
