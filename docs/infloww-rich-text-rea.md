# Infloww rich text for OF message text: REA / static extraction (2026-11-05)

How Infloww (desktop 5.7.20) edits, stores, sends and renders formatted OF message text: the "Edit script" modal's
Text field (toolbar: size select "Default", B, I, A, "Aa" clear, x) and everywhere script/message HTML is shown.
Research only. Contrast: `app/lib/ofMirrorFormat.ts` (OF's own format). Conventions as `docs/infloww-of-manager-rea.md`.

Labels: **M** = measured (seen in shipped code/CSS at the offset), **I** = inferred, **G** = guess.

## Sources (read-only, nothing executed, no login, no network)

| tag | artifact | where it came from | sha256 (16) |
|---|---|---|---|
| SPA | `index.b50b8e61.js` (16.9 MB), remote SPA build 38236048582, last-modified 2026-10-12 | gzip body of Chromium cache entry `Partitions/2a0e09df-…/Cache/Cache_Data/94876eb8cf822236_0` | ee4b9139202e6023 |
| CSS | `index.045997ec.css` (6.4 MB), same build | brotli body of `…/b6c25bf65d414a14_0` | 419424b042b4e358 |
| PRE | `preload.asar` (preloads injected into onlyfans.com) | `~/Library/Application Support/infloww/preloads/5.7.20_38192570632_2614339781787656/` | cfe989e457d0f468 |
| OF | OF `app.css` / `app.js` entry, build 202610161317-c4c194673d (served via inflowwcdn proxy) | `Partitions/2612799904677947_/Cache/Cache_Data/5aba32ca43a2ec74_0`, `7dfa537ff6bd91f2_0` | – |

Copies + decoders in `/tmp/rt-rea/` (scripts in `/tmp/rt-scripts/`). REA `analyze_javascript_application` ran on the
preload.asar (graph only); the SPA is remote, not in `app.asar`, so it was recovered from the HTTP cache and grepped.
The earlier `~/Downloads/infloww-remote-web/` copy is gone. Offsets = byte offsets in the decoded files.
Not available: the Messages Pro "lite" main bundle (`index-hbdevs-*.js`, only V8 code cache left), Infloww's backend.

## 1. Editor

**Library: tiptap v2 (ProseMirror) + DOMPurify.** It is a port of OF's own editor: the SPA function is literally
`useOnlyfansEditor$1` (SPA @9138068), and the size/colour config objects are OF's `TEXT_EDITOR` config copied
verbatim (OF app.js @110900), with OF's i18n `textKey`s swapped for hard-coded English labels. **M**

Extensions, in order (`genExtensions$1`, SPA @9137461; same in PRE `o_` @1110477): `SanitizeHTML` (paste filter),
`TextStyle`, `Placeholder("Enter your message...")`, `CharacterCount{limit:6500}`, `FilterTransaction` (rejects input
when `len - n*len(placeholder) + n*100 > 6500`, so each `{name}` tag counts as 100 chars), `ClassName` (custom mark),
`Color` (tiptap color ext: inline `style="color:…"`, never set by the toolbar), `StarterKit`. Editor DOM class
`b-text-editor prosemirror-editor`. **M**

Toolbar (`Toolbar$1`, SPA @9142774; PRE `c_` @1114825), left to right: **M**

| item | tooltip | action |
|---|---|---|
| antd Select, shows active size label ("Default") | Text size | `toggleClass({className, removeClassNamePattern:"m-editor-fs", disableToggleFunctionality:true})` |
| B (`SMarkdownBold`) | Bold | `toggleBold()`; active colour `#4166f6` |
| I (`SMarkdownItalic`) | Italic | `toggleItalic()` |
| A (`SMarkdownColor`, underline bar filled with active colour or theme `T0`) | Text color | click popover of swatches → `toggleClass(…, "m-editor-fc")` |
| 1px divider | – | – |
| Aa (`SMarkdownClear`) | Clear formatting | see below |
| x (`SMarkdownClose`) | none | `onClose` → hides the toolbar only, content unchanged |

The toolbar is hidden by default: `Text$6` (SPA @9155460) keeps `useState(false)` and the `markdown-icon` button in the
"Tags:" row (next to the `{name}` chips) toggles it. Same in the PRE "Message online fans / Message preview" modal. **M**

Sizes (`FONT_SIZE_CONFIG$1.LIST`, SPA @9086849; PRE `Ve` @1069721): **M**

| order | label | class | px |
|---|---|---|---|
| 1 | Largest | `m-editor-fs__lg` | 26 |
| 2 | Large | `m-editor-fs__l` | 20 |
| 3 | Default (isDefault) | `m-editor-fs__default` | 16 (CSS) |
| 4 | Small | `m-editor-fs__s` | 14 |
| 5 | Smallest | `m-editor-fs__sm` | 12 |

Colours (`FONT_COLOR_CONFIG$1.LIST`): popover = 3 round 24px swatches, a divider, then the default swatch. Labels
exist in data but are not rendered (no text in the popover). **M**

| order | label | class | hex |
|---|---|---|---|
| 1 | gray | `m-editor-fc__gray` | #8a96a3 |
| 2 | blue-1 | `m-editor-fc__blue-1` | #00aff0 |
| 3 | blue-2 | `m-editor-fc__blue-2` | #1b98e0 |
| 4 | divider | – | – |
| 5 | default (isDefault) | `m-editor-fc__default` | swatch = theme `T0`; CSS `var(--text-color)` |

OF's labels for the same entries: grey / light_blue / … (OF app.js @111900); ours says "Grey / Light blue / Medium blue". **M**

Combining: **M**
- Size and colour live in ONE `className` mark (SPA @9131680) whose `class` attr holds space-separated classes;
  `removeClassNamePattern` strips the old class of the same family first, so `<span class="m-editor-fs__l m-editor-fc__blue-1">`.
- Picking "Default" size / default colour writes `m-editor-fs__default` / `m-editor-fc__default` explicitly (not a removal).
- Bold/italic are separate StarterKit marks, so all four combine.
- Empty selection: sets the stored mark so the next typed text carries it.
- Nesting: `ClassName` precedes `StarterKit` in the extension list, so tiptap ranks the span mark outside bold/italic:
  `<span class="m-editor-fc__blue-1"><strong>💖REVERSE RIDING POV💖</strong></span>` (**I** from tiptap mark ranking; the
  paste filter `j8` also moves class/style off `<em>/<strong>` onto a wrapping `<span>`, **M**).
- OF's own wire (**M**, owner's HAR of onlyfans.com, 2026-11-06): a chat send `POST /api2/v2/chats/:id/messages` with
  `"text":"<p><span class=\"m-editor-fs__l m-editor-fc__blue-2\"><strong>safgsfg</strong></span></p>"` → 200, echoed
  byte for byte (`isMarkdownDisabled:true`): **OF DMs keep formatting**; span outside strong, size class first. Every
  serializer here writes that shape (`ofMirrorFormat.runsHtml`; the relay's allow-list orders classes the same way). With
  both classes, their order likely follows which was applied last (`removeClassNamePattern` then append, **I**); size
  first is the canonical one we write.

Clear formatting (`clearFormatting`, SPA in `useOnlyfansEditor$1`): **M**
- With a selection: `clearNodes().unsetAllMarks()` (drops bold, italic, size+colour span; lists/headings → paragraph).
- Empty caret: inserts a temp space, selects it, runs `clearNodes().unsetAllMarks().unsetClass().unsetBold().unsetItalic().deleteSelection()`, so typing continues unformatted.

Paste (`SanitizeHTML.transformPastedHTML`, SPA @9128500, PRE `z8` @1103072): inline `font-size` 26/20/14/12px and `color`
#8a96a3/#00aff0/#1b98e0 (rgb/rgba normalised to hex) become the classes; then DOMPurify with
`ALLOWED_TAGS:[strong,span,em,br,p]`, `ALLOWED_ATTR:[class,data-pm-slice]`, no data/aria attrs; empty class/style removed. **M**

Other editor facts: `.prosemirror-editor` 16px/24px, min-height 48px, max-height 215px, scrolls; selection
`#b4d5fe` light, `#043ea8` dark; `p.is-editor-empty:first-child::before` placeholder (CSS @1100022). StarterKit
keyboard/markdown rules are on (Mod-b, Mod-i, `**x**`), and headings/lists/blockquote/code are not disabled (**M**), so typed
`# ` could yield `<h1>` that the paste filter would never allow (**I**, not verified on the running app).

## 2. Stored format and what is sent

Script save (`ScriptEditModal`, title `"Edit"|"Add" + " script"`, width 535, SPA @9314512): **M**
```
scriptContent:     replaceParagraphsWithBreaks$1(editor.getHTML())
scriptTextContent: replaceAllHtml$3(editor.getHTML())
```
- `replaceParagraphsWithBreaks` (SPA @8596536): `/<\/p>(<p><\/p>)+<p>/g` → `"<br>".repeat(emptyParas*2)`. A blank line
  between paragraphs is folded into the paragraph as `<br><br>`; plain `</p><p>` stays. **M**
- `replaceAllHtml` (SPA @8596200; PRE `Jn` @115231): DOMParser, `<br>`→space, append space after each `<p>`, textContent,
  collapse whitespace, trim. Used for the plain copy, search and sensitive-word checks. **M**
- So stored `scriptContent` is tiptap HTML: `<p>`, `<br>`, `<strong>`, `<em>`, `<span class="m-editor-f[cs]__…">`
  (plus anything StarterKit allowed if typed). No sanitize on save. **M**
- On open, `setValue(scriptContent)` → `setContent(html)`; tiptap reparses, so `<br><br>` become hard breaks. **M**

Send (PRE, `Message online fans` / `Message preview` modal @1117516, editor @1122284): **M**
- PPV/mass: `POST /message/single-message/sendV2` body `{text: scriptContent (HTML), lockedText, mediaFiles, price, previews, …}`.
- Chat script send: `scriptsParam:{…script, scriptTextContent: Jn(scriptContent)}`; lite chat: `POST /lite/chats/messages` with `text`.
- Both go to Infloww's backend, never straight to OF from the client. The backend forwarding `text` HTML unchanged to OF's
  `text` field: **I** (backend not visible). `{name}` is replaced server-side before preview (`Ia(...)`, PRE main @196921). **M**
- Picking a script in the OF chat does NOT type into OF's composer (`.b-make-post__textarea-wrapper .ProseMirror`); it opens
  Infloww's own preview modal with the HTML loaded into the same tiptap editor (formatting kept). Emojis are inserted into
  OF's composer as text nodes (`Ba`, PRE chunk-TPQZS2A6 @85763). **M**

## 3. Rendering message HTML

| surface | code | treatment |
|---|---|---|
| OF chat bubbles inside OF Manager | OF's own Vue app in the BrowserView | Infloww does not re-render. OF's text directive: DOMPurify `ALLOWED_TAGS` b,h1-h6,p,br,strong,span,em,mark,small,del,ins,sub,sup,ul,li,ol,table,th,tr,td,a,div,iframe,svg,use,i; `ADD_ATTR` target,class; `FORBID_ATTR` style (OF app.js @138837). **M** that bubbles use it: **I** |
| Script hover popover (in-chat script picker) | SPA @15154163, PRE main @16168 | `DOMPurify.sanitize(scriptContent)` default config → rich **M** |
| Send preview of composed message | SPA @15245641 | `DOMPurify.sanitize(html)` in `editor-content` → rich **M** |
| Message report / all messages `ChatMessageContent` | SPA @13737542 | `DOMPurify.sanitize(postedMessage.text)` default config → rich **M** |
| Fansly / multi-platform scripts | SPA @16639261 | `escapeHtmlString` → literal text **M** |

CSS for the classes (global, not scoped; SPA CSS @1098750, identical in PRE `of/common.css` @313795 and OF app.css @118434): **M**

| class | rule |
|---|---|
| `m-editor-fs__default/lg/l/s/sm` | 16 / 26 / 20 / 14 / 12 px |
| `m-editor-fc__gray/blue-1/blue-2` | #8a96a3 / #00aff0 / #1b98e0, same in light and dark (no dark remap anywhere) |
| `m-editor-fc__default` | `color: var(--text-color)` |
| `.b-text-colour.m-editor-fc__*`, `button[class].m-editor-fc__*` | swatch background (OF also sets `--bg-color`) |
| `.b-text-editor em>strong, strong>em` | `color: inherit`; inline marks `line-height: normal` |

`--text-color`: OF defines `#242529` light, `#f6f7f8` under `:root.m-mode-dark` (OF app.css @119322) **M**. The Infloww SPA
CSS never defines it (**M**), so in Infloww's own surfaces `__default` falls back to the inherited text colour (**I**, CSS
`unset` on an inherited property).
Owner screenshot: the blue bold lines match `m-editor-fc__blue-1` (#00aff0) + `<strong>` (**I**, by eye).

## 4. Plain previews (HTML stripped)

| surface | code |
|---|---|
| Scripts page rows / detail (Tag & Sequence, owner screenshot) | `replaceAllHtml$3(scriptContent)` SPA @9381153, @9416184, @14230562; with search it then highlights and `dangerouslySetInnerHTML`s the stripped text **M** |
| In-chat script list `scriptContentShow` | strip (`Jn` / `replaceAllHtml`) → highlight → DOMPurify, PRE main @10494, SPA @14629070 **M** |
| Auto-message / smart-message tables, fan last message | `replaceAllHtml` / cheerio `load(html).text()` SPA @13622416, @13719260, @16213160, @16302533 **M** |
| OF chat-list style previews | OF `$()` keeps only br/p via DOMPurify then turns them into spaces (OF app.js @132790) **M**; use on chat list **I** |

## 5. Mobile

None. The toolbar CSS module (`_editor-wrap_1atkn_*`, SPA CSS @1100931–1102600) has no `@media` rules: items 36x36px
(4px margins), select `min-width:150px; max-width:calc(100% - 218px)`, close 20x20 `rgba(138,150,163,.75)`, hover
`#0091ea` 6% circle, colour popover `gap:16px; padding:16px`, divider `#e6e6e6`. Infloww desktop has no phone layout for
it **M**; it simply wraps/shrinks in a narrow window **I**.

## Contrast with `app/lib/ofMirrorFormat.ts`

- Same tags, classes, colours, sizes and paste matrix as documented there; confirmed in Infloww's copy and OF's cached build. **M**
- Differences: Infloww's span is a separate `className` mark, not `textStyle` (**M**); nesting span > strong > em, as OF's
  wire (**M**, HAR above) and `ofMirrorFormat` now write; Infloww folds blank paragraphs into `<br><br>` on script save (**M**).

## Where this app keeps the formatting (2026-11-05)

- Kept: the script editor (Scripts page) saves the markup; the main chat composer sends a picked formatted script as
  markup (preview + "formatting dropped" hint once edited; kept per chat beside the draft); the relay sanitizes to the
  allow-list (`service/of_rich_text.py`) on the chat, 1:1 queue and mass bodies; the automation word guard reads the
  plain text of the sanitized markup and, when it masks, sends the masked plain text (formatting dropped).
- Dropped (out of scope): a formatted script picked in the OF-manager mirror chat (`ofMirrorChat.ts`, `html: undefined`),
  the mass-message composer and the post composer: they insert and send the script's plain text.
