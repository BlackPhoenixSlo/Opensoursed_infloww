const CAPTURED = "openinflowwww:account-session-captured";

export function accountSessionCaptured(accountId: string) {
  window.dispatchEvent(new CustomEvent(CAPTURED, { detail: accountId }));
}

export function onAccountSessionCaptured(accountId: string, reset: () => void) {
  const listener = (event: Event) => {
    if ((event as CustomEvent<string>).detail === accountId) reset();
  };
  window.addEventListener(CAPTURED, listener);
  return () => window.removeEventListener(CAPTURED, listener);
}
