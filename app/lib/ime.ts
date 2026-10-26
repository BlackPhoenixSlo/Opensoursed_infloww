/** An IME (Japanese, Chinese, Korean…) is composing: its Enter picks the
 *  candidate and is no send. `keyCode` 229 catches Safari, whose keydown for
 *  that Enter comes after `compositionend`, with `isComposing` false. */
export const isImeComposing = (e: React.KeyboardEvent | KeyboardEvent): boolean =>
  ("nativeEvent" in e ? e.nativeEvent : e).isComposing || e.keyCode === 229;
