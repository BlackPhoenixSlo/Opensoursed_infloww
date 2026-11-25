// Literal mirrored in globals.css exit animations and slop/actors/ui.py sheet probe.
export const EXIT_GHOST = "exit-ghost";
export const SWIPED_ATTR = "data-swiped";

export const notInGhost = (sel: string) => `:is(${sel}):not(.${EXIT_GHOST}, .${EXIT_GHOST} *)`;
