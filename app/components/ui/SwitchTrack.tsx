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
