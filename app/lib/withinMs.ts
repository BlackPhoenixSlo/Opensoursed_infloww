/** `f` with a signal that aborts on `outer` or after `ms`. Past `ms` it rejects with a TimeoutError, on `outer` with
 *  its reason, even when `f` ignores the signal (a hung write can't be cancelled, only left behind). */
export function withinMs<T>(ms: number, outer: AbortSignal, f: (s: AbortSignal) => Promise<T>): Promise<T> {
  const ac = new AbortController();
  return new Promise<T>((ok, no) => {
    const end = (e: unknown) => {
      clearTimeout(t);
      outer.removeEventListener("abort", onOuter);
      ac.abort(e);
      no(e);
    };
    const onOuter = () => end(outer.reason);
    const t = setTimeout(() => end(new DOMException(`no answer for ${ms / 1000} s`, "TimeoutError")), ms);
    if (outer.aborted) onOuter();
    else outer.addEventListener("abort", onOuter, { once: true });
    f(ac.signal).then(ok, no).finally(() => {
      clearTimeout(t);
      outer.removeEventListener("abort", onOuter);
    });
  });
}
