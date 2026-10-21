/**
 * Infloww's top-bar tile: the `HBButton size="generous"` its header items are
 * (index.9f50f370.js `UTCRender`, `HeaderNotification`, `HeaderSignButton`),
 * from `.hb-button--size-generous` and `.hb-button--color-default`
 * (index.9fc9db54.css): borderless, 36px min height and width, 8px radius,
 * 8px 12px padding, 500 16px/1.25, the 9% white fill
 * (`--surface-level-02-emphasis-00`, our `nav-surface`), white text dimming to
 * 62% on hover. Icons are 20px with an 8px gap (`HBIconWrapper
 * size="intermediate"`, `--sizing-named-micro`). An icon-only tile pads 8px
 * all round (`--inner-onlyIconContent`), so 36×36.
 */
export const HEADER_TILE =
  "h-9 min-w-9 px-3 inline-flex items-center justify-center gap-2 rounded-lg bg-nav-surface text-nav-fg-active hover:text-nav-fg text-[16px] leading-5 font-medium whitespace-nowrap shrink-0 disabled:opacity-50";
/** The tile's icon: 20px. */
export const HEADER_TILE_ICON = "size-5 shrink-0";
