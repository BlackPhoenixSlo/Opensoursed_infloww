/**
 * What `useExitGhost` (every modal and menu) and `useSwipe` share, kept apart so
 * neither pulls the other into its chunks.
 */

/** The class on a closed layer's leaving copy (`useExitGhost`). The literal is
 *  mirrored in globals.css (its exit animations) and slop/actors/ui.py (the sheet probe). */
export const EXIT_GHOST = "exit-ghost";
/** Set on a panel and backdrop a swipe dismissed: `useExitGhost` makes no copy of them. */
export const SWIPED_ATTR = "data-swiped";

/** `sel` (a selector list) minus anything in a leaving copy, which keeps the role
 *  it showed but is no open layer. */
export const notInGhost = (sel: string) => `:is(${sel}):not(.${EXIT_GHOST}, .${EXIT_GHOST} *)`;
