export const isImeComposing = (e: React.KeyboardEvent | KeyboardEvent): boolean =>
  ("nativeEvent" in e ? e.nativeEvent : e).isComposing || e.keyCode === 229;
