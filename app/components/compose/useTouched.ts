import { useCallback, useLayoutEffect, useRef, useState, type Dispatch } from "react";

/**
 * Has the user changed this composer since it opened (its Escape gate)? The first user action touches it and it
 * stays touched until the composer closes (unmounts), a reverted edit included. The automatic seeding (the picker's
 * first account, the standing exclude list) never does, whenever it lands.
 *
 * Returns the user's `dispatch`: an action touches unless `isSeed(action, state)` (the state last rendered), and
 * `edit(set)`: a plain setter that touches.
 */
export function useTouched<S, A>(state: S, dispatch: Dispatch<A>, isSeed: (action: A, state: S) => boolean) {
  const [touched, setTouched] = useState(false);
  const stateRef = useRef(state);
  const seedRef = useRef(isSeed);
  useLayoutEffect(() => {
    stateRef.current = state;
    seedRef.current = isSeed;
  });
  const userDispatch = useCallback<Dispatch<A>>((a) => {
    if (!seedRef.current(a, stateRef.current)) setTouched(true);
    dispatch(a);
  }, [dispatch]);
  const edit = useCallback(<V,>(set: (v: V) => void) => (v: V) => {
    setTouched(true);
    set(v);
  }, []);
  return { touched, dispatch: userDispatch, edit };
}

/** The audience reducer's automatic actions: the standing exclude seed, and the picker's first account (from none). */
export function isAudienceSeed(a: { type: string }, s: { accountId: string | null }): boolean {
  return a.type === "seedExclude" || (a.type === "setAccount" && s.accountId == null);
}
