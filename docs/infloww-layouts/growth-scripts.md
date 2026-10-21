# Layout capture — growth-scripts

Bundle: ~/Downloads/infloww-remote-web/, entry `index.9f50f370.js`
Captured: 2026-10-17 at repo `8acc5028`
Method: static — REA's web tools (inspect_web_page, capture_web_screenshot, analyze_web_bundle) watch the page passively and cannot abort a request, and `index.html` asks off-host for fonts and the Cookiebot script, so the page was not rendered; REA's JavaScript application map plus `grep -boF` and byte-offset reads stand in
Reproduce:
```sh
R=$(git rev-parse --show-toplevel); B=$HOME/Downloads/infloww-remote-web; S=/tmp/infloww-serve; J=$B/index.9f50f370.js; C=$B/index.9fc9db54.css
# Serve tree (read-only symlinks, outside the bundle; reused when present), started from /tmp, checked for a 200, then stopped:
mkdir -p $S/35676908170/assets && ln -sf $B/index.html $S/index.html
for f in $B/*; do ln -sf "$f" $S/35676908170/assets/; done
(cd /tmp && exec python3 -I -m http.server --bind 127.0.0.1 3401 --directory $S) & P=$!
sleep 1; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3401/35676908170/assets/index.9f50f370.js   # prints 200
kill $P
# REA (MCP): mcp__rea__analyze_javascript_application input_path=$B format=directory detail=summary
#   integrity_policy=record-and-continue max_heap_mb=4096 (21 JS files parsed; the entry's semantic pass was not started, static facts kept)
# Anchors, each printed as <offset>:<match>:
grep -boF -e 'path:"/admin/growth/pro-written"' -e 'function Scripts(' -e 'const Scripts$1=React$C.memo(Scripts)' $J
grep -boF -e 'function Header(' -e 'function TabsBar(' -e 'const tabList$1=' -e 'function ManageScripts(' -e 'const ScriptList=' $J
grep -boF -e 'const ScriptsExpand=' -e 'const ScriptItem=' -e 'function ScriptDetail$1(' -e 'function ScriptControl(' -e 'function MultipleSelection(' $J
grep -boF -e 'function TagItem(' -e 'function SequenceItem(' -e 'function Sidebar(' -e 'const SequencesHeader=' -e 'const RenderSequenceEmpty' $J
grep -boF -e 'ScriptEditModal=' -e 'function Media$2(' -e 'function TagOtherBlock' -e 'const TagModal=' -e 'function AddSequence(' -e 'AddTemplateModal=' $J
grep -boF -e '._page-header-container_odlcr_15' -e '._scripts-toolbar_odlcr_62{' -e '._scripts-toolbar-manage_odlcr_136{' -e '._sequence-empty_odlcr_525{' -e '._scripts-list-item_j02cy_80{' $C
grep -boF -e '--tc-T1:' -e '--tc-T2:' -e '--tc-T3:' -e '--tc-B1:' -e '--tc-B-nav:' -e '--tc-L1:' -e '--tc-M1:' -e '--tc-M-B:' $C
# Labels, e.g.: grep -boF '"Manage scripts"' $J prints 14399853 and 14400710; the capture cites the match offset + 1 (the first byte inside the quote).
# Any cited offset reads back with: dd if=$J bs=1 skip=14400711 count=80 2>/dev/null
# Welcome-message search inside the page's modules and its editor, each prints nothing:
grep -boF -i 'welcome' $J | awk -F: '$1>14190000 && $1<14420000'
grep -boF -i 'welcome' $J | awk -F: '$1>9300000 && $1<9420000'
# Every Items offset, checked at once (exit 0, 0 misses):
cd /tmp && python3 -I "$R/.scratch/infloww-parity-round-2/verify-offsets.py" "$R/docs/infloww-layouts/growth-scripts.md"
```
Clone: ui-redesign/infloww-exact/growth-scripts.html
Phase: 2 · Matrix row: 3.5.5

## Component tree
- Route `/admin/growth/pro-written` renders `Scripts$1` (index.9f50f370.js @16915417)
  - Nav entry and page title "Scripts" (index.9f50f370.js @10713968; index.9f50f370.js @10714023)
  - `Scripts$1` is `React$C.memo(Scripts)`; `Scripts` mounts the header, the toolbar, the current list and the modals (index.9f50f370.js @14419195; index.9f50f370.js @14413971)
    - `Header`: title, creator selector, Learn, Share, More menu (index.9f50f370.js @14276681)
    - `TabsBar`: Tag and Sequence tabs, search, Manage scripts (index.9f50f370.js @14397795; index.9f50f370.js @14397371)
      - Manage scripts view: back arrow, title, sort popover (index.9f50f370.js @14399854)
    - List by tab: `ManageScripts` (all scripts), `TagsList`, `SequenceList` (index.9f50f370.js @14400732; index.9f50f370.js @14264347)
      - `ScriptsExpand`: select-all and the Expand scripts switch (index.9f50f370.js @14228812)
      - `ScriptList` of `ScriptItem` rows; empty state (index.9f50f370.js @14231049; index.9f50f370.js @14229836)
        - `ScriptDetail$1`: text, media, price and stats, notes; `ScriptTags`; `ScriptControl` (index.9f50f370.js @14224156; index.9f50f370.js @14222203; index.9f50f370.js @14227486)
      - Tag and Sequence views: `Sidebar` of `TagItem` / `SequenceItem` rows beside the list (index.9f50f370.js @14216150; index.9f50f370.js @14208297; index.9f50f370.js @14209942)
        - `SequencesHeader` above a sequence's steps (index.9f50f370.js @14234007)
      - Empty Tag or Sequence view: `RenderSequenceEmpty` (index.9f50f370.js @14235791; index.9f50f370.js @14265707)
    - `MultipleSelection`: the selection bar (index.9f50f370.js @14394509)
    - Script editor `ScriptEditModal` with `Media$2` and `TagOtherBlock` (index.9f50f370.js @9311016; index.9f50f370.js @9258718; index.9f50f370.js @5175343)
    - Tag name and sequence name modals (index.9f50f370.js @14241023; index.9f50f370.js @14242808)
    - Choose a template modal (index.9f50f370.js @14246377)
    - Import from Excel, Import from other creators, Share modals (index.9f50f370.js @14392932; index.9f50f370.js @14413537; index.9f50f370.js @14418856)
  - Sequence editor `AddSequence`, which replaces the page while open (index.9f50f370.js @14269898)
    - Steps: Normal script, Conditional script (index.9f50f370.js @14257318; index.9f50f370.js @14257669)

## Items
| ID | Kind | Element | Value | Source |
|---|---|---|---|---|
| growth-scripts#1 | layout | Route | `/admin/growth/pro-written` renders `Scripts$1` | index.9f50f370.js @16915417 |
| growth-scripts#2 | label | Nav entry | Scripts | index.9f50f370.js @10713968 |
| growth-scripts#3 | label | Page title | "Scripts", the menu title the header shows as `pageTitle` | index.9f50f370.js @10714023; index.9f50f370.js @14276681 |
| growth-scripts#4 | spacing | Page title | 16px, weight 600, 24px right margin | index.9fc9db54.css @2822020 |
| growth-scripts#5 | colour | Page title text | #151515 (`--tc-T1`) | index.9fc9db54.css @2822001; index.9fc9db54.css @457616 |
| growth-scripts#6 | filter | Header creator selector | `CreatorSelect$4` right of the title, with `showScriptCount` | index.9f50f370.js @14279306 |
| growth-scripts#7 | spacing | Header tools | 24px tall, 16px gap, pushed right (`margin-left:auto`) | index.9fc9db54.css @2822545; index.9fc9db54.css @2822450 |
| growth-scripts#8 | button | Header tool 1 | Learn | index.9f50f370.js @14279692 |
| growth-scripts#9 | spacing | Learn and Share boxes | 75px wide, 0 8px padding, 14px weight 500 | index.9fc9db54.css @2822255; index.9fc9db54.css @2822209 |
| growth-scripts#10 | spacing | Learn and Share icon | 4px right margin, 18px icon | index.9fc9db54.css @2822334; index.9f50f370.js @14279625 |
| growth-scripts#11 | button | Header tool 2 | Share | index.9f50f370.js @14279946 |
| growth-scripts#12 | button | Header tool 3 | More menu, a 24px `SMoremenu` icon | index.9f50f370.js @14280107 |
| growth-scripts#13 | label | More menu item 1 | Add script | index.9f50f370.js @14277023 |
| growth-scripts#14 | label | More menu item 2 | "Add sequence", opening "Create new" / "Use template" / "Import from tag" | index.9f50f370.js @14277190; index.9f50f370.js @14277430; index.9f50f370.js @14277477; index.9f50f370.js @14277521 |
| growth-scripts#15 | label | More menu item 3 | Add tag | index.9f50f370.js @14277559 |
| growth-scripts#16 | label | More menu item 4 | "Import", opening "From Excel" / "From other creators" | index.9f50f370.js @14277802; index.9f50f370.js @14278064; index.9f50f370.js @14278137 |
| growth-scripts#17 | layout | More menu dividers | `type:"divider"` after Add script and before Import | index.9f50f370.js @14277151; index.9f50f370.js @14277736 |
| growth-scripts#18 | spacing | Toolbar | 56px tall, 0 24px padding, 1px bottom border | index.9fc9db54.css @2822918 |
| growth-scripts#19 | colour | Toolbar background | #FFFFFF (`--tc-B-nav`) | index.9fc9db54.css @2822918; index.9fc9db54.css @457914 |
| growth-scripts#20 | colour | Toolbar border | #e6e6e6 (`--tc-L1`) | index.9fc9db54.css @2822972; index.9fc9db54.css @458232 |
| growth-scripts#21 | tab | Tab 1 | "Tag", key `ScriptType.Tags` | index.9f50f370.js @14397558; index.9f50f370.js @14397371 |
| growth-scripts#22 | tab | Tab 2 | "Sequence", key `ScriptType.Sequence` | index.9f50f370.js @14397778; index.9f50f370.js @14397570 |
| growth-scripts#23 | tab | Default tab | `selectedTab:ScriptType.Tags` (Tag) | index.9f50f370.js @13899996 |
| growth-scripts#24 | spacing | Tab label | 14px, weight 700, 8px between icon and text | index.9fc9db54.css @2823279; index.9fc9db54.css @2823361 |
| growth-scripts#25 | spacing | Tab icon | 24px (`SListline,{size:24`) | index.9f50f370.js @14397490 |
| growth-scripts#26 | button | Toolbar search | a 24px `SVaultSearch` icon in #666666 that opens the script search | index.9f50f370.js @14400584 |
| growth-scripts#27 | spacing | Toolbar search | 16px right margin, then a 1px by 18px divider 16px to its right | index.9fc9db54.css @2823461; index.9fc9db54.css @2823535 |
| growth-scripts#28 | button | Toolbar right | Manage scripts | index.9f50f370.js @14400711 |
| growth-scripts#29 | spacing | Manage scripts pill | 28px tall, 0 8px padding, 4px radius, 14px weight 400 | index.9fc9db54.css @2824303; index.9fc9db54.css @2824369 |
| growth-scripts#30 | colour | Manage scripts pill | #3467ff (`--tc-M1`) text on #eff4ff (`--tc-M-B`) | index.9fc9db54.css @2824332; index.9fc9db54.css @2824432; index.9fc9db54.css @458249; index.9fc9db54.css @458310 |
| growth-scripts#31 | label | Manage view header | back arrow, then "Manage scripts" in place of the tabs | index.9f50f370.js @14399854 |
| growth-scripts#32 | spacing | Manage view header | 16px, weight 600, 16px gap | index.9fc9db54.css @2824163; index.9fc9db54.css @2824072 |
| growth-scripts#33 | filter | Manage view sort | "Recent" / "Name", "Ascending" / "Descending"; starts on "Recent" and "Descending" | index.9f50f370.js @14399033; index.9f50f370.js @14399042; index.9f50f370.js @14399075; index.9f50f370.js @14399087; index.9f50f370.js @14398286; index.9f50f370.js @14398379 |
| growth-scripts#34 | label | List control | "Expand scripts" switch, with a select-all checkbox on its left | index.9f50f370.js @14229720 |
| growth-scripts#35 | spacing | List control bar | 32px tall, 0 16px padding | index.9fc9db54.css @2841826 |
| growth-scripts#36 | spacing | Expand scripts label | 12px | index.9fc9db54.css @2842051 |
| growth-scripts#37 | colour | Expand scripts label | #999999 (`--tc-T3`) | index.9fc9db54.css @2842090; index.9fc9db54.css @457650 |
| growth-scripts#38 | layout | Script row name cell | 118px, 72px in a sequence (`"72px":"118px"`) | index.9f50f370.js @14230806 |
| growth-scripts#39 | spacing | Script row | 8px 24px 8px 16px padding, at least 40px tall | index.9fc9db54.css @2842516; index.9fc9db54.css @2842602 |
| growth-scripts#40 | spacing | Script row name | 8px 16px padding, at most 68px (3 lines) | index.9fc9db54.css @2843061; index.9fc9db54.css @2843295 |
| growth-scripts#41 | layout | Script row tags | 172px column of tags and sequences, `defaultMaxCount=3` shown, the rest behind a count chip | index.9fc9db54.css @2843311; index.9f50f370.js @14222203 |
| growth-scripts#42 | layout | Script row text | two lines, then expandable (`ellipsis:{rows:2`) | index.9f50f370.js @14225548 |
| growth-scripts#43 | label | Conditional script prefix | "Condition: " before the option's condition | index.9f50f370.js @14225364 |
| growth-scripts#44 | label | Script row price | "$ " and the price, when the media is priced | index.9f50f370.js @14226047 |
| growth-scripts#45 | label | Script row stats | sent count (`SMessageSendStatus` icon, #FFA15F), purchases (`SBag`) and sales (`SAmount`) when priced, "--" without statistics | index.9f50f370.js @14226236; index.9f50f370.js @14226449; index.9f50f370.js @14226632; index.9f50f370.js @14224526 |
| growth-scripts#46 | label | Script row notes | the internal notes on one line behind a `SNotes` icon | index.9f50f370.js @14226904 |
| growth-scripts#47 | button | Script row actions | edit (`SEdit`), share (`SScriptShareLine`), delete (`SShiftDelete` inside a tag or sequence, `SCardDelete` in all scripts) | index.9f50f370.js @14228527; index.9f50f370.js @14228643; index.9f50f370.js @14228736; index.9f50f370.js @14228780 |
| growth-scripts#48 | spacing | Script row actions | 16px left padding, 24px gap | index.9fc9db54.css @2843687 |
| growth-scripts#49 | colour | Remove-from-tag icon | #FC584D | index.9f50f370.js @14228765 |
| growth-scripts#50 | empty state | Script list empty | No data | index.9f50f370.js @14233631 |
| growth-scripts#51 | label | Selection bar | "Selected" and the count, in a 40px bar with an 8px radius | index.9f50f370.js @14396347; index.9fc9db54.css @2824514 |
| growth-scripts#52 | layout | Disabled selection action | `opacity:0.6` | index.9fc9db54.css @2825604 |
| growth-scripts#53 | layout | Tag and Sequence views | a 248px sidebar, 8px 16px padding, beside the selected entry's scripts | index.9fc9db54.css @2826410; index.9fc9db54.css @2826465 |
| growth-scripts#54 | filter | Sidebar search | Search | index.9f50f370.js @14214161 |
| growth-scripts#55 | filter | Sidebar sort | "Recent" / "Name" / "Custom", "Ascending" / "Descending", then "Customize order" | index.9f50f370.js @14212783; index.9f50f370.js @14212792; index.9f50f370.js @14212799; index.9f50f370.js @14212834; index.9f50f370.js @14212846; index.9f50f370.js @14213373 |
| growth-scripts#56 | empty state | Sidebar empty | No data | index.9f50f370.js @14215306 |
| growth-scripts#57 | label | Sidebar row stats | script count, then `purchaseRate` and `revenueAmount` | index.9f50f370.js @14209776; index.9f50f370.js @14209906 |
| growth-scripts#58 | label | Sidebar row menu | Rename / Share / Delete | index.9f50f370.js @14208060; index.9f50f370.js @14208105; index.9f50f370.js @14208251 |
| growth-scripts#59 | label | Sequence row badges | Draft / AI | index.9f50f370.js @14210720; index.9f50f370.js @14210809 |
| growth-scripts#60 | label | Sequence header | name with "Draft" and "AI" badges, "Edit", and a menu of "Share" / "Delete" | index.9f50f370.js @14234833; index.9f50f370.js @14234920; index.9f50f370.js @14235141; index.9f50f370.js @14234166; index.9f50f370.js @14234270 |
| growth-scripts#61 | label | Sequence header meta | Created by / Created on / Last modified on | index.9f50f370.js @14235600; index.9f50f370.js @14235671; index.9f50f370.js @14235737 |
| growth-scripts#62 | empty state | Tag or Sequence view empty | "Try out our new sequence feature", the same panel for both views (`return RenderSequenceEmpty()`) | index.9f50f370.js @14236295; index.9f50f370.js @14265707 |
| growth-scripts#63 | label | Empty panel description | Use sequences to arrange scripts into storylines and conversations to engage fans. | index.9f50f370.js @14236395 |
| growth-scripts#64 | button | Empty panel cards | Create new sequence / Use a template / Import from tag | index.9f50f370.js @14236758; index.9f50f370.js @14237033; index.9f50f370.js @14237300 |
| growth-scripts#65 | spacing | Empty panel | 98px top padding | index.9fc9db54.css @2832819 |
| growth-scripts#66 | spacing | Empty panel title | 32px, weight 500 | index.9fc9db54.css @2832888 |
| growth-scripts#67 | spacing | Empty panel description | 14px, weight 500, 150% line height, 24px above, 0 16px padding | index.9fc9db54.css @2832951 |
| growth-scripts#68 | spacing | Empty panel card row | 48px above, 60px between cards | index.9fc9db54.css @2833137 |
| growth-scripts#69 | spacing | Empty panel card | 276px by 234px, 12px inner gap | index.9fc9db54.css @2833276 |
| growth-scripts#70 | colour | Empty panel background | #f5f5f5 (`--tc-B1`) | index.9fc9db54.css @2832754; index.9fc9db54.css @457765 |
| growth-scripts#71 | colour | Empty panel description | #666666 (`--tc-T2`) | index.9fc9db54.css @2832951; index.9fc9db54.css @457633 |
| growth-scripts#72 | label | Script editor title | `"Edit":"Add"," script"` (Add script or Edit script), 535px wide | index.9f50f370.js @9318781; index.9f50f370.js @9318571 |
| growth-scripts#73 | label | Script editor field 1 | "Name", required, `maxLength:64`, placeholder "Enter name" | index.9f50f370.js @9319002; index.9f50f370.js @9319089; index.9f50f370.js @9319156 |
| growth-scripts#74 | label | Script editor field 2 | "Tags", several, placeholder "Select or create a tag" | index.9f50f370.js @9319196; index.9f50f370.js @9319317 |
| growth-scripts#75 | label | Script editor field 3 | "Text", required, at most `Yn=6500` characters, placeholder "Enter your message..." | index.9f50f370.js @9319644; index.9f50f370.js @9311836; index.9f50f370.js @9313308 |
| growth-scripts#76 | label | Script editor field 4 | "Media", with "Message price" (an input of `width:"60px"`) and the "Select" tile | index.9f50f370.js @9319985; index.9f50f370.js @9258718; index.9f50f370.js @9258769; index.9f50f370.js @9259790 |
| growth-scripts#77 | label | Script editor price rules | "Minimum $3 USD"; "Please set price" when paid media has no price | index.9f50f370.js @9254799; index.9f50f370.js @9314064 |
| growth-scripts#78 | label | Script editor field 5 | Tag other Creator(s) | index.9f50f370.js @5175343 |
| growth-scripts#79 | label | Script editor field 6 | "Internal notes", `maxLength:256` | index.9f50f370.js @9320365; index.9f50f370.js @9320403 |
| growth-scripts#80 | label | Script editor field 7 | "Share script with other Creators", placeholder "Select Creator(s)" | index.9f50f370.js @9320561; index.9f50f370.js @9320686 |
| growth-scripts#81 | label | Tag modal | title "Add" or "Modify" and "tag name"; field "Tag name", placeholder "Enter name", `maxLength:32` | index.9f50f370.js @14241622; index.9f50f370.js @14241613; index.9f50f370.js @14241628; index.9f50f370.js @14241904; index.9f50f370.js @14242061; index.9f50f370.js @14242073 |
| growth-scripts#82 | spacing | Tag and sequence name modal body | 24px 16px 4px padding | index.9f50f370.js @14241776 |
| growth-scripts#83 | label | Sequence name modal | "Modify sequence name"; field "Sequence name", placeholder "Enter name", `maxLength:32` | index.9f50f370.js @14242815; index.9f50f370.js @14243124; index.9f50f370.js @14243283; index.9f50f370.js @14243295 |
| growth-scripts#84 | label | Sequence editor header | back arrow and "Add sequence"; buttons "Save as draft" (when allowed) and "Publish" | index.9f50f370.js @14274105; index.9f50f370.js @14274309; index.9f50f370.js @14274384 |
| growth-scripts#85 | label | Sequence editor card | "Sequence" heading with a "Draft" badge | index.9f50f370.js @14274719; index.9f50f370.js @14274803 |
| growth-scripts#86 | layout | Sequence editor form | labels on the left, `labelCol:{span:3}` | index.9f50f370.js @14274901 |
| growth-scripts#87 | label | Sequence field 1 | "Name", required with "Enter a name", `maxLength:64` | index.9f50f370.js @14274971; index.9f50f370.js @14275041; index.9f50f370.js @14275109 |
| growth-scripts#88 | label | Sequence field 2 | "Description", `maxLength:128`, placeholder "E.g. Please use this only for VIPs" | index.9f50f370.js @14275235; index.9f50f370.js @14275380; index.9f50f370.js @14275422 |
| growth-scripts#89 | label | Sequence steps | "Steps", with an "Expand scripts" switch that starts on | index.9f50f370.js @14275716; index.9f50f370.js @14275817 |
| growth-scripts#90 | button | Empty step | "Normal script" (then "Select" or "Create") or "Conditional script" | index.9f50f370.js @14257318; index.9f50f370.js @14257451; index.9f50f370.js @14257514; index.9f50f370.js @14257669 |
| growth-scripts#91 | label | Conditional step notice | Add different script options that users can choose from depending on the response or behavior of the fan. A minimum of 2 options must be added. | index.9f50f370.js @14257993 |
| growth-scripts#92 | label | Conditional option | "Condition:" input, `maxLength:150`, placeholder "Click here to edit" | index.9f50f370.js @14258950; index.9f50f370.js @14259043; index.9f50f370.js @14259081 |
| growth-scripts#93 | label | Choose a template modal | "Choose a template", `width:800`; card "New Sub" with "Use this template" | index.9f50f370.js @14246384; index.9f50f370.js @14246415; index.9f50f370.js @14246926; index.9f50f370.js @14247074 |
| growth-scripts#94 | label | Import from Excel modal | "Import scripts from Excel", confirm "Import" | index.9f50f370.js @14392939; index.9f50f370.js @14393115 |
| growth-scripts#95 | label | Import from Excel steps | "Step1: Download the script template and fill in the data:" / "Step2: Upload the Excel file below (.xls or .xlsx only):" | index.9f50f370.js @14390458; index.9f50f370.js @14390810 |
| growth-scripts#96 | label | Import from Excel limit | Exceeded maximum allowed rows (1000). | index.9f50f370.js @14389790 |
| growth-scripts#97 | label | Import from other creators modal | "Import scripts from other creators"; "Up to 5 creators can be selected" | index.9f50f370.js @14413544; index.9f50f370.js @14411599 |
| growth-scripts#98 | label | Share modal | 480px; "Confirm" / "Cancel" | index.9f50f370.js @9351645; index.9f50f370.js @14418864; index.9f50f370.js @14418885 |

## Clone fixes
| Item | Clone had | Bundle has | Clone edit |
|---|---|---|---|
| growth-scripts#4 | title 21px, 16px to the selector | 16px, 24px right margin | `.gtitle` 16px with `margin-right:24px`; `.ghead` column gap 0 (row gap 16px kept for the phone wrap) |
| growth-scripts#7 | header actions 22px apart | 16px gap | `.hact{gap:16px}` |
| growth-scripts#8 | no Learn | Learn | Learn box, disabled and titled not wired (the help article is off-host) |
| growth-scripts#9 | 15px links, no padding, no width | 75px wide, 0 8px padding, 14px weight 500 | `.hlink` 14px, `padding:0 8px`, `min-width:75px` |
| growth-scripts#10 | 8px icon gap | 4px, 18px icon | `.hlink` gap 4px; Learn and Share icons 18px |
| growth-scripts#11 | Export link in its place | Share | Share box, disabled and titled not wired; Export moves into the More menu under "Inflowwww extra" |
| growth-scripts#12 | Add single / New script ladder primary button | More menu, 24px icon | primary button removed; a 24px More button opens the menu |
| growth-scripts#13 | none | Add script | menu item, adds a single (the Clone's script) |
| growth-scripts#14 | none | Add sequence: Create new / Use template / Import from tag | Create new adds a script ladder; Use template and Import from tag disabled, titled not wired |
| growth-scripts#15 | none | Add tag | menu item, disabled, titled not wired |
| growth-scripts#16 | none | Import: From Excel / From other creators | both disabled, titled not wired |
| growth-scripts#17 | none | dividers after Add script and before Import | `.hm-sep` lines at those two places |
| growth-scripts#18 | tab strip 50px tall from tab padding | 56px | `.sbtabs{height:56px}`; `.sbtab` stretches to it (`padding:0 4px`) |
| growth-scripts#21 | tabs Singles, Script ladders, Simulate, Live offers, Canned lines | Tag, Sequence | first tab "Tag", disabled and titled not wired; second tab "Sequence" shows the script ladders; Simulate, Live offers and Canned lines follow under an "Inflowwww extra" label; the Singles and Script ladders counts go |
| growth-scripts#24 | 15.5px weight 500, 9px gap | 14px, weight 700, 8px | `.sbtab` 14px, weight 700, gap 8px |
| growth-scripts#25 | 17px and 19px icons | 24px | Tag and Sequence icons 24px |
| growth-scripts#26 | none | search icon | 24px search icon at the right, disabled, titled not wired |
| growth-scripts#27 | none | 16px, then a 1px by 18px divider, then 16px | `.sb-search` with that divider; `.sbtab-right` keeps its 16px gap |
| growth-scripts#28 | Singles tab | Manage scripts at the right of the toolbar | "Manage scripts" pill at the right shows the singles list, the Clone's default view |
| growth-scripts#29 | none | 28px, 0 8px, 4px radius, 14px weight 400 | `.sb-manage` with those values, Clone palette |
| growth-scripts#50 | No singles yet, with a paragraph | No data | singles empty state reads "No data" |
| growth-scripts#62 | No script ladders yet, a paragraph, New script ladder button | the sequence empty panel | Sequence empty panel: title, description and the three cards; Create new sequence adds a ladder, the other two disabled, titled not wired |
| growth-scripts#65 | 56px 20px padding, 14px gap | 98px top, 32px title, 14px weight 500 text 24px below, cards 48px below and 60px apart, 276px by 234px with a 12px gap | `.seq-empty` rules with those values (items #65 to #69); the card row wraps so the page fits at 390px |
| growth-scripts#52 | none | disabled at 0.6 | `opacity:.6` on the disabled header boxes, More menu items and empty-panel cards |

## Notes
- ASSUMPTION: colours are recorded but not applied, as in the Smart Messages capture. The bundle ships a light palette (index.9fc9db54.css @457616) and the Clone is dark on every page, so a recolour is a site-wide theme change (rung 4). Overturned if the owner wants the Clone in the bundle's light palette.
- ASSUMPTION: the Clone opens on Manage scripts (its singles list), not on the bundle's default Tag tab (#23), because Tag is Not wired and opening on a disabled tab would show nothing (rung 5). Overturned when a Tag view is wired.
- ASSUMPTION: the Clone's Sequence tab shows its script ladders. Both are named, ordered runs of scripts (the bundle's tour calls a sequence "Order multiple scripts into a sequence", index.9f50f370.js @14401364). Overturned if Phase 2 decides ladders are not Sequences (the round-2 Phase 2 spec reads them as Sequences, Not wired in the app).
- ASSUMPTION: "Manage scripts" stays a pill beside the tabs in the Clone. The bundle swaps the tabs for a back arrow and the "Manage scripts" title (#31, #32) and shows its own sort (#33); the Clone keeps its singles toolbar (search, filter, sort, AI tools, Save catalog) and editable singles table, which are Inflowwww extras with no bundle counterpart, and Phase 2 rebuilds the list in the app (rung 5). Overturned if the Clone is to copy the Manage view itself.
- ASSUMPTION: the KPI row above the tabs and the extra tabs are kept, each under an "Inflowwww extra" label; the bundle has neither, and both are wired to the relay (rung 4).
- Welcome-message entry point: none on this page. `grep -boF -i 'welcome'` prints no offset inside the page's modules (14190000 to 14420000) or the editor modal's module (9300000 to 9420000); the commands are in `Reproduce:`.
- Inventory (`docs/infloww-screens.md` §3.5.5) disagreements, the bundle values above stand:
  - It names the sections "Tags", "Sequences" and "Manage Scripts"; the bundle labels are "Tag", "Sequence" and "Manage scripts" (#21, #22, #28).
  - It calls the menu a "+" menu with Add Sequence and Import only; the bundle's is a More (`SMoremenu`) menu that also holds "Add script" and "Add tag", and Add sequence offers "Use template" too (#12 to #16).
  - Its limits (name 64, tag 32, text 1000, note 246) are the Excel import's; the editor allows text up to 6500 and notes up to 256 (#75, #79), names up to 64 (#73) and tag names up to 32 (#81). The 1000-row limit is the import's (#96).
  - Sequence names allow 64 characters in the editor (#87) but 32 in the rename modal (#83).
- Share's condition (#11, recorded by ticket 56): the header renders Share only when `Mt` is true, `Mt=react$1.exports.useMemo(()=>{return!localStorageGetShowJoyRide()?true:S.ShareScript}` (index.9f50f370.js @14279038; the render `Mt&&jsxs("div",{onClick:Pt` at index.9f50f370.js @14279704). `localStorageGetShowJoyRide` is `localStorage.getItem("ScriptTour")==="true"` (index.9f50f370.js @14262994). So Share shows before the script tour has run, and after it only to a role with the `ShareScript` permission; the bundle shot shows none. The More trigger likewise renders only when the role grants at least one menu item (`!!bt.length`, index.9f50f370.js @14279958), and in the shot `SMoremenu` draws a filled accent circle with a white plus.
- Each script row has its own expand arrow, `mn&&jsx("div",{className:classNames$1("scripts-expand"` with a 12px `SUparrow` (index.9f50f370.js @14227264), shown once the text overflows its two lines (#42).
- The Text field's 6500 is the editor constant `var Yn=6500` (index.9f50f370.js @9311832); #75 cites the `Yn=6500` byte.
- The "Message price" label is followed by a full-width colon and a no-break space, written as escapes in the bundle (index.9f50f370.js @9258718); #76 quotes the words only.
- Version drift: none; every offset reads in the one entry chunk `index.9f50f370.js` and its stylesheet `index.9fc9db54.css`.
- Rendered-only values: none, the capture is static.
