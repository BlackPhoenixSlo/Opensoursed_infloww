import { useCallback, useLayoutEffect, useRef, useState, type Dispatch } from "react";

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
  return { touched, dispatch: userDispatch };
}

export function isAudienceSeed(a: { type: string }, s: { accountId: string | null }): boolean {
  return a.type === "seedExclude" || (a.type === "setAccount" && s.accountId == null);
}
