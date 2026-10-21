# Layout capture — growth-vault-pro

Bundle: ~/Downloads/infloww-remote-web/, entry `index.9f50f370.js`
Captured: 2026-10-17 at repo `c2a22cf0`
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
grep -boF -e 'path:"/admin/growth/vault"' -e 'const VaultIndex=' -e 'const VaultUpload=' $J
grep -boF -e 'function VaultPage$1(' -e 'function VaultClassifyLists(' -e 'function SearchHeader$1(' -e 'function VaultListItem(' $J
grep -boF -e 'function VaultList$1(' -e 'function Tabs(' -e 'function Medias(' -e 'function MediaTable$1(' $J
grep -boF -e 'useCurrentSelectFileList=' -e 'function CategoryWrap' -e 'const tags$3=' -e 'function EditInfoModal(' -e 'DefaultAudioVideoMaxSize=4' $J
grep -boF -e '._page-header-container_u2ztj_1501{' -e '._select-content-wrap_1096w_270{' -e '._vault-search-media-wrap_6g756_275{' -e '._tabs-list_6g756_371{' -e '._vault-upload-pop-box_1ckt2_1535{' $C
grep -boF -e '--tc-T1:' -e '--tc-T2:' -e '--tc-T3:' -e '--tc-B1:' -e '--tc-B-nav:' -e '--tc-L1:' -e '--tc-M1:' -e '--tc-M-B:' $C
# Labels, e.g.: grep -boF '"Select media"' $J prints 13096768; the capture cites the match offset + 1 (the first byte inside the quote).
# Any cited offset reads back with: dd if=$J bs=1 skip=13096769 count=80 2>/dev/null
# Link-import search inside the upload view's modules (12858000 to 13110000), each prints 0:
grep -boF -i 'drive' $J | awk -F: '$1>12858000 && $1<13110000' | wc -l
grep -boF -i -e 'Put into' -e 'import from' -e 'paste' $J | awk -F: '$1>12858000 && $1<13110000' | wc -l
# Every Items offset, checked at once (exit 0, 0 misses):
cd /tmp && python3 -I "$R/.scratch/infloww-parity-round-2/verify-offsets.py" "$R/docs/infloww-layouts/growth-vault-pro.md"
```
Clone: ui-redesign/infloww-exact/growth-vault-pro.html
Phase: 2; 5 reads its import card items · Matrix row: 3.5.4

## Component tree
- Route `/admin/growth/vault` renders `VaultIndex` (index.9f50f370.js @16915320)
  - Nav entry and page title "Vault Pro" (index.9f50f370.js @10714225; index.9f50f370.js @10714282)
  - `VaultIndex`: header (title, creator selector, Learn, Add media), then `ErrorStatus` around the body, then `VaultUpload` while Add media is open (index.9f50f370.js @13102071; index.9f50f370.js @13107936; index.9f50f370.js @13108840)
    - Body: loading `Spin`, the not-a-creator text, or `VaultPage$1` (index.9f50f370.js @13105222; index.9f50f370.js @13105486)
    - `VaultPage$1`: `modal-wrap` row of the rail and the content, the selection bar, the delete and move modals (index.9f50f370.js @7024654; index.9f50f370.js @7027982)
      - Rail `VaultClassifyLists` (index.9f50f370.js @6831469)
        - `SearchHeader$1`: sort label and popover, search, add category (index.9f50f370.js @6817513)
        - "All media" row, then `VaultListItem` rows (index.9f50f370.js @5081661; index.9f50f370.js @6800302)
        - Rename/New category and Delete category modals (index.9f50f370.js @6836484; index.9f50f370.js @6835405)
      - Content `VaultList$1`: search, sort box, `Tabs`, then `Medias` (grid) or `MediaTable$1` (table) (index.9f50f370.js @6990152; index.9f50f370.js @6982936; index.9f50f370.js @6946970; index.9f50f370.js @6964320)
  - `VaultUpload`: the upload and import card, a full overlay over the page (index.9f50f370.js @13086707; index.9f50f370.js @13093823)
    - Back arrow (index.9f50f370.js @13094062)
    - Step 1 "Link a fan account (required)": OnlyFans account select (index.9f50f370.js @13094906)
    - Step 2 "Select media": the drop area (`Upload.Dragger`), its tip and its three rules (index.9f50f370.js @13096769; index.9f50f370.js @13096987)
    - Step 3 "Edit media": table of picked files from `useCurrentSelectFileList` (index.9f50f370.js @13099197; index.9f50f370.js @12932667)
    - Selection bar with "Bulk upload"; `EditInfoModal` (Batch edit media) (index.9f50f370.js @13099592; index.9f50f370.js @12956926)
    - Upload guide (tour) steps (index.9f50f370.js @12944789)

## Items
| ID | Kind | Element | Value | Source |
|---|---|---|---|---|
| growth-vault-pro#1 | layout | Route | `/admin/growth/vault` renders `VaultIndex` | index.9f50f370.js @16915320 |
| growth-vault-pro#2 | label | Nav entry | Vault Pro | index.9f50f370.js @10714225 |
| growth-vault-pro#3 | label | Page title | "Vault Pro", the menu title the header shows as `pageTitle` | index.9f50f370.js @10714282; index.9f50f370.js @13102183 |
| growth-vault-pro#4 | spacing | Page title | 16px, weight 600, 24px right margin | index.9fc9db54.css @2456814 |
| growth-vault-pro#5 | colour | Page title text | #151515 (`--tc-T1`) | index.9fc9db54.css @2456814; index.9fc9db54.css @457616 |
| growth-vault-pro#6 | filter | Header creator selector | `CreatorSelect$4` right of the title | index.9f50f370.js @13107967 |
| growth-vault-pro#7 | button | Header tool 1 | "Learn" behind an 18px `SVaultLearn,{size:18` icon; opens Infloww's help site through `openExternalUrl` | index.9f50f370.js @13108303; index.9f50f370.js @13108236; index.9f50f370.js @13108064 |
| growth-vault-pro#8 | spacing | Learn | 14px weight 500, pushed right (`margin-left:auto`); icon 4px right margin | index.9fc9db54.css @2456959; index.9fc9db54.css @2457175 |
| growth-vault-pro#9 | colour | Learn text | #3467ff (`--tc-M1`) | index.9fc9db54.css @2456959; index.9fc9db54.css @458249 |
| growth-vault-pro#10 | button | Header tool 2 | "Add media", a primary button with the `SAddMaterial` icon, shown only with the `GrowthVault_AddMedia` permission | index.9f50f370.js @13108623; index.9f50f370.js @13108561; index.9f50f370.js @13102754 |
| growth-vault-pro#11 | spacing | Add media | 24px left margin; 135px by 36px | index.9fc9db54.css @2457318; index.9fc9db54.css @2457400 |
| growth-vault-pro#12 | label | Add media tour | "Click “+ Add media” to upload one or more media files to the vault" | index.9f50f370.js @13104412 |
| growth-vault-pro#13 | empty state | Body while loading or not a creator | `Spin`; "The fan account doesn’t have a vault. Unable to view." | index.9f50f370.js @13105222; index.9f50f370.js @13105486 |
| growth-vault-pro#14 | spacing | Not-a-creator text | 16px | index.9fc9db54.css @2456614 |
| growth-vault-pro#15 | layout | Page body | `modal-wrap` flex row: the rail `VaultClassifyLists`, then `vault-content-wrap` holding `VaultList$1` | index.9f50f370.js @7027982; index.9fc9db54.css @558069 |
| growth-vault-pro#16 | layout | Rail | 208px wide, 1px right border | index.9fc9db54.css @568725 |
| growth-vault-pro#17 | colour | Rail border | #e6e6e6 (`--tc-L1`) | index.9fc9db54.css @568725; index.9fc9db54.css @458232 |
| growth-vault-pro#18 | label | Rail title | "Vault Pro", only off the vault page (`!St&&`) | index.9f50f370.js @6834619; index.9f50f370.js @6834558 |
| growth-vault-pro#19 | spacing | Rail sort row | 48px tall, 0 16px padding, label left and icons right | index.9fc9db54.css @569076 |
| growth-vault-pro#20 | filter | Rail sort label | the current sort's name, "Default" at first (`classifySort:"default"`) | index.9f50f370.js @6817952; index.9f50f370.js @5082168 |
| growth-vault-pro#21 | spacing | Rail sort label | 13px, weight 500; sort icon 24px with 8px left margin | index.9fc9db54.css @570514; index.9fc9db54.css @571164 |
| growth-vault-pro#22 | filter | Rail sort popover | "Default" / "Name" / "Recent" / "Media" / "Custom", "Ascending" / "Descending", then "Customize order" | index.9f50f370.js @6817952; index.9f50f370.js @6817986; index.9f50f370.js @6818014; index.9f50f370.js @6818046; index.9f50f370.js @6818076; index.9f50f370.js @6818117; index.9f50f370.js @6818163; index.9f50f370.js @6819551 |
| growth-vault-pro#23 | filter | Rail search | a 20px `SVaultSearch,{size:20` icon that opens a "Search" input, `maxLength:100` | index.9f50f370.js @6821810; index.9f50f370.js @6820317; index.9f50f370.js @6820350 |
| growth-vault-pro#24 | button | Rail add category | a 16px `SAdd,{size:16` icon, with the `createCategory` permission | index.9f50f370.js @6822024; index.9f50f370.js @6821932 |
| growth-vault-pro#25 | spacing | Rail icons | 30px boxes, 20px radius | index.9fc9db54.css @569846 |
| growth-vault-pro#26 | label | Rail first row | "All media" (`AllClassListItem`) | index.9f50f370.js @5081694; index.9f50f370.js @5081661 |
| growth-vault-pro#27 | spacing | Rail row | 10px outer padding left and right; 14px 4px 14px 10px inner padding (`padding:14px 10px` then `padding-right:4px`), 6px gap, 1px bottom border | index.9fc9db54.css @572165; index.9fc9db54.css @572435 |
| growth-vault-pro#28 | colour | Rail row selected | #eff4ff (`--tc-M-B`) | index.9fc9db54.css @572358; index.9fc9db54.css @458310 |
| growth-vault-pro#29 | spacing | Rail row name | 14px, weight 500, at most 145px with an ellipsis | index.9fc9db54.css @572733 |
| growth-vault-pro#30 | label | Rail row counts | photo, video and GIF counts behind 20px icons (`SFImage,{size:20}`, `SFVideo,{size:20}`, `SFGif,{size:20}`), audio behind a 16px one (`SFAudio,{size:16}`), in a `Space$1,{split:"\xB7",size:2` (a 2px gap); "empty" when all are 0 | index.9f50f370.js @6803129; index.9f50f370.js @6803302; index.9f50f370.js @6803646; index.9f50f370.js @6803475; index.9f50f370.js @6802956; index.9f50f370.js @6803705 |
| growth-vault-pro#31 | spacing | Rail row counts | 12px | index.9fc9db54.css @573751 |
| growth-vault-pro#32 | colour | Rail row counts | #999999 (`--tc-T3`) | index.9fc9db54.css @573751; index.9fc9db54.css @457650 |
| growth-vault-pro#33 | label | Rail row stats | send count (`totalSendCount`), unlock rate (`*100)+"%"`) and revenue (`return"$"+formatAmount$1`), with statistics on | index.9f50f370.js @6800771; index.9f50f370.js @6800959; index.9f50f370.js @6801021 |
| growth-vault-pro#34 | label | Rail row menu | Rename / Delete | index.9f50f370.js @6801359; index.9f50f370.js @6801611 |
| growth-vault-pro#35 | empty state | Rail error | "An error occurred when retrieving media. Please try refreshing." with "Refresh" | index.9f50f370.js @6835123; index.9f50f370.js @6835277 |
| growth-vault-pro#36 | label | Category name modal | "Rename category" or "New category"; field "Category", placeholder "Enter category name", `maxLength:64`; "Save" | index.9f50f370.js @6836484; index.9f50f370.js @6836502; index.9f50f370.js @6836989; index.9f50f370.js @6837109; index.9f50f370.js @6837192; index.9f50f370.js @6836788 |
| growth-vault-pro#37 | label | Delete category modal | "Delete category"; "This will permanently remove the category from the vault. This action cannot be undone."; option "Permanently remove all media from the vault" | index.9f50f370.js @6835405; index.9f50f370.js @6835946; index.9f50f370.js @6836380 |
| growth-vault-pro#38 | spacing | Toolbar | 16px 24px margin, search left and sort box right | index.9fc9db54.css @582815 |
| growth-vault-pro#39 | spacing | Search box | 1px border, 8px radius | index.9fc9db54.css @583012 |
| growth-vault-pro#40 | colour | Search box | #e6e6e6 (`--tc-L1`) border on #FFFFFF (`--tc-B-nav`) | index.9fc9db54.css @583012; index.9fc9db54.css @458232; index.9fc9db54.css @457914 |
| growth-vault-pro#41 | filter | Search type | "Caption" / "Note" / "Hashtag", a select of `style:{width:110}` | index.9f50f370.js @6995688; index.9f50f370.js @6995752; index.9f50f370.js @6995812; index.9f50f370.js @6995576 |
| growth-vault-pro#42 | spacing | Search type | 111px, 1px right border | index.9fc9db54.css @583535 |
| growth-vault-pro#43 | filter | Search input | "Search media by " and "PPV caption" (Caption) or "note" (Note); "Search media by hashtags" (Hashtag); `maxLength:100` | index.9f50f370.js @6996706; index.9f50f370.js @6996755; index.9f50f370.js @6996769; index.9f50f370.js @6995933; index.9f50f370.js @6996800 |
| growth-vault-pro#44 | filter | Search trigger | runs at 3 characters or more, or when cleared (`>=3`) | index.9f50f370.js @6997015 |
| growth-vault-pro#45 | spacing | Search input | 16px placeholder; text inset 11px (`.ant-input-lg` 8px 11px) | index.9fc9db54.css @584007; index.9fc9db54.css @3700412 |
| growth-vault-pro#46 | spacing | Search icon | 20px `SVaultSearch,{size:20` icon in a 24px box with an 8px right margin | index.9f50f370.js @6998395; index.9fc9db54.css @584228 |
| growth-vault-pro#47 | spacing | Sort box | 40px tall, 8px 16px padding, 8px radius, 1px border, 16px left margin | index.9fc9db54.css @584459 |
| growth-vault-pro#48 | filter | Sort box text | the field's name, "Recent" at first (`field:OfVaultFieldType.Recent,sort:OfVaultSortType.Desc`), then ", Hide selected content" when the hide switch is on | index.9f50f370.js @6991230; index.9f50f370.js @5082545; index.9f50f370.js @6999148 |
| growth-vault-pro#49 | spacing | Sort box text | 13px, weight 500 | index.9fc9db54.css @584867 |
| growth-vault-pro#50 | filter | Sort popover dates | "All time" / "Go to date" (a "Select date" modal) | index.9f50f370.js @6993571; index.9f50f370.js @6993970; index.9f50f370.js @6999701 |
| growth-vault-pro#51 | filter | Sort popover fields | "Recent" / "Most liked" / "Highest tips", and with statistics "Send count" / "Unlock count" / "Revenue" | index.9f50f370.js @6991230; index.9f50f370.js @6991277; index.9f50f370.js @6991331; index.9f50f370.js @6991488; index.9f50f370.js @6991547; index.9f50f370.js @6991605 |
| growth-vault-pro#52 | filter | Sort popover direction | Ascending / Descending | index.9f50f370.js @6994833; index.9f50f370.js @6995182 |
| growth-vault-pro#53 | filter | Sort popover switch | "Hide content viewed or unlocked by fan, or posted on Creator's feed", its text `width:188` | index.9f50f370.js @6995410; index.9f50f370.js @6995389 |
| growth-vault-pro#54 | spacing | Media tabs row | 0px 24px 16px padding, tabs left and tools right; the tabs scroll sideways (`overflow-x:auto`) | index.9fc9db54.css @585810; index.9fc9db54.css @585916 |
| growth-vault-pro#55 | label | Media tabs label | Media: | index.9f50f370.js @6984872 |
| growth-vault-pro#56 | spacing | Media tabs label | 14px, 8px right margin | index.9fc9db54.css @586142 |
| growth-vault-pro#57 | tab | Media tabs | "All", then "Photo" / "Video" / "GIF" / "Audio" (`defaultViewTypes`) | index.9f50f370.js @6985108; index.9f50f370.js @5081494; index.9f50f370.js @5081541; index.9f50f370.js @5081578; index.9f50f370.js @5081613; index.9f50f370.js @5081648 |
| growth-vault-pro#58 | tab | Media tab disabled | a type with no files is disabled (`photosCount)===0`) | index.9f50f370.js @5088139 |
| growth-vault-pro#59 | spacing | Media tab pill | 12px apart (`margin-right:0` on the last), 3px 16px padding, 20px radius, 14px, 20px line height, 1px border | index.9fc9db54.css @586269; index.9fc9db54.css @586553 |
| growth-vault-pro#60 | colour | Media tab active | #3467ff (`--tc-M1`) border and text | index.9fc9db54.css @586756; index.9fc9db54.css @458249 |
| growth-vault-pro#61 | colour | Media tab disabled | #f5f5f5 (`--tc-B1`) background, #999999 (`--tc-T3`) text, `no-drop` cursor | index.9fc9db54.css @586868; index.9fc9db54.css @457765; index.9fc9db54.css @457650 |
| growth-vault-pro#62 | filter | Video length | "Video length:" with "All" / "< 1 min" / "1 - 5 mins" / "5 - 10 mins" / "> 10 mins", on the Video tab only | index.9f50f370.js @6985672; index.9f50f370.js @6983237; index.9f50f370.js @6983260; index.9f50f370.js @6983290; index.9f50f370.js @6983326; index.9f50f370.js @6983364 |
| growth-vault-pro#63 | spacing | Media tools | 32px tall | index.9fc9db54.css @587107 |
| growth-vault-pro#64 | button | Media tool 1 | Refresh | index.9f50f370.js @6985882 |
| growth-vault-pro#65 | button | Media tool 2 | "Select all", shown while at most 40 files are loaded (`fn<=40`) | index.9f50f370.js @6986202; index.9f50f370.js @6986166 |
| growth-vault-pro#66 | spacing | Media tool icons | 28px boxes, 6px side margins, 20px radius | index.9fc9db54.css @587406 |
| growth-vault-pro#67 | button | View switch | Grid view / Table view | index.9f50f370.js @6986469; index.9f50f370.js @6986795 |
| growth-vault-pro#68 | spacing | View switch | 2px 6px padding, 1px border each, 4px outer radius | index.9fc9db54.css @587869; index.9fc9db54.css @588233 |
| growth-vault-pro#69 | colour | View switch active | #666 background, #fff text | index.9fc9db54.css @588469 |
| growth-vault-pro#70 | layout | Media grid | four per row, each 25% with 5px padding (`padding:5,width:"25%"`) | index.9f50f370.js @6946809 |
| growth-vault-pro#71 | empty state | Media grid empty | No data | index.9f50f370.js @6950005 |
| growth-vault-pro#72 | empty state | Media grid error | "Connectivity" / "Please try refreshing." | index.9f50f370.js @6948855; index.9f50f370.js @6948892 |
| growth-vault-pro#73 | column | Table view columns | "Media" / "Category" / "Tagged Creators" / "Hashtags" / "Notes" / "Suggested price" / "Uploaded by" / "Upload time" / "Actions" | index.9f50f370.js @6966064; index.9f50f370.js @6968555; index.9f50f370.js @6970144; index.9f50f370.js @6972718; index.9f50f370.js @6973903; index.9f50f370.js @6974342; index.9f50f370.js @6974840; index.9f50f370.js @6975073; index.9f50f370.js @6975334 |
| growth-vault-pro#74 | label | Selection bar | "Selected" and the count; move (`SVaultMove`) and delete (`STrash`) icons | index.9f50f370.js @7028556; index.9f50f370.js @7028933; index.9f50f370.js @7029092 |
| growth-vault-pro#75 | spacing | Selection bar | 38px tall, 16px above the bottom, 20px left and 24px right, 0 24px padding, 8px radius; actions 24px apart | index.9fc9db54.css @558309; index.9fc9db54.css @559572 |
| growth-vault-pro#76 | label | Delete media modal | "Delete media file?", `width:480`, "Delete"; "This action is permanent and cannot be undone." and "When deleted:" | index.9f50f370.js @7029167; index.9f50f370.js @7029282; index.9f50f370.js @7029374; index.9f50f370.js @7029625; index.9f50f370.js @7029766 |
| growth-vault-pro#77 | label | Move modal | Add to category | index.9f50f370.js @7030139 |
| growth-vault-pro#78 | layout | Upload card | `vault-upload-pop-box`, over the whole page (`position:absolute`, 100% by 100%, `z-index:1000`) | index.9f50f370.js @13093823; index.9fc9db54.css @2507496 |
| growth-vault-pro#79 | button | Upload card back | a 20px `SBackOutlink,{size:20` arrow; with files picked it asks first | index.9f50f370.js @13094062 |
| growth-vault-pro#80 | spacing | Upload card body | 24px padding, scrolls (`overflow-y:auto`) | index.9fc9db54.css @2507962 |
| growth-vault-pro#81 | spacing | Upload step marker | 15px circle with a 9px dot; a 3px line joins the steps | index.9fc9db54.css @2508271; index.9fc9db54.css @2508491; index.9fc9db54.css @2508687 |
| growth-vault-pro#82 | colour | Upload step marker | #cce6ff circle, #79befd dot, #eff4ff (`--tc-M-B`) line | index.9fc9db54.css @2508271; index.9fc9db54.css @2508491; index.9fc9db54.css @2508687; index.9fc9db54.css @458310 |
| growth-vault-pro#83 | spacing | Upload step body | 65px bottom and 16px left padding (0 0 65px 16px); a 1px rule 32px above its bottom, 16px in | index.9fc9db54.css @2509158; index.9fc9db54.css @2508904 |
| growth-vault-pro#84 | spacing | Upload step title | 16px, weight 500, 18px below | index.9fc9db54.css @2509327 |
| growth-vault-pro#85 | label | Upload step 1 title | "Link a fan account (required)", `marginRight:"6px"` before an info icon (`SInfo`) | index.9f50f370.js @13094906; index.9f50f370.js @13094877; index.9f50f370.js @13095376 |
| growth-vault-pro#86 | label | Upload step 1 info | "Infloww will automatically send media to this account so that it appears in your Creator’s vault" / "NOTE: You must be subscribed to this fan account, or the account must be subscribed to you" | index.9f50f370.js @13095108; index.9f50f370.js @13095266 |
| growth-vault-pro#87 | label | Upload step 1 field | "OnlyFans account"; a searchable select, placeholder "Enter OnlyFans username", "No search results" | index.9f50f370.js @13095512; index.9f50f370.js @13095777; index.9f50f370.js @13096069 |
| growth-vault-pro#88 | spacing | Upload step 1 field | 14px label, weight 500, 20px line height, 8px below; select 240px by 40px | index.9fc9db54.css @2509580; index.9fc9db54.css @2511705 |
| growth-vault-pro#89 | label | Upload step 1 checks | "Authenticating"; "Account successfully linked to Vault Pro"; "This account doesn"; "subscription has expired," and "please subscribe"; "This fan account can't send messages"; "Please provide an OnlyFans account for uploading material" | index.9f50f370.js @13089064; index.9f50f370.js @13089251; index.9f50f370.js @13089423; index.9f50f370.js @13089654; index.9f50f370.js @13089772; index.9f50f370.js @13090026; index.9f50f370.js @13090177 |
| growth-vault-pro#90 | label | Upload step 2 title | Select media | index.9f50f370.js @13096769 |
| growth-vault-pro#91 | layout | Upload drop area | full width, 344px tall, a centred column | index.9fc9db54.css @2515271 |
| growth-vault-pro#92 | colour | Upload drop area | #fafbff (`---B-echart-bg` fallback) | index.9fc9db54.css @2515271 |
| growth-vault-pro#93 | layout | Upload drop target | an `Upload.Dragger` that takes dropped files or a click, `multiple:true`, `beforeUpload:()=>false`, accepting `DefaultVaultMediaAccept` (images, GIF, PDF, video, audio) | index.9f50f370.js @13096987; index.9f50f370.js @13097103; index.9f50f370.js @13097080; index.9f50f370.js @8432460 |
| growth-vault-pro#94 | spacing | Upload drop target | 120px by 120px | index.9fc9db54.css @2516056 |
| growth-vault-pro#95 | label | Upload drop target content | a 24px plus (`SAdd,{size:24}`) over "Add media" | index.9f50f370.js @13097176; index.9f50f370.js @13097251 |
| growth-vault-pro#96 | spacing | Upload drop target text | 8px above, 14px weight 400 | index.9fc9db54.css @2516081 |
| growth-vault-pro#97 | label | Upload drop tip | Drag and drop media file(s) here or select them from your computer | index.9f50f370.js @13097326 |
| growth-vault-pro#98 | spacing | Upload drop tip | 14px, weight 400, 20px line height, 16px above | index.9fc9db54.css @2516367 |
| growth-vault-pro#99 | spacing | Upload rules row | 16px above, centred, 12px, 20px line height | index.9fc9db54.css @2516640 |
| growth-vault-pro#100 | colour | Upload rules row | #999 (`---T3` fallback) | index.9fc9db54.css @2516640 |
| growth-vault-pro#101 | label | Upload rule 1 | "1", "Video/audio size limit: " and the limit (`DefaultAudioVideoMaxSize=4`) and "GB" | index.9f50f370.js @13097603; index.9f50f370.js @13097663; index.9f50f370.js @12924881; index.9f50f370.js @13097693 |
| growth-vault-pro#102 | label | Upload rule 2 | "2", "Image size limit: " and the limit (`DefaultImageMaxSize=100`) and "MB" | index.9f50f370.js @13097849; index.9f50f370.js @13097909; index.9f50f370.js @12924914; index.9f50f370.js @13097933 |
| growth-vault-pro#103 | label | Upload rule 3 | "3", "Image dimensions: " and `minWidth:16`, "px to ", `maxWidth:1e4` (shown as 10,000 through `formatThousands$1`), "px" | index.9f50f370.js @13098089; index.9f50f370.js @13098149; index.9f50f370.js @12924965; index.9f50f370.js @13098192; index.9f50f370.js @12924990; index.9f50f370.js @13098169; index.9f50f370.js @13098223 |
| growth-vault-pro#104 | spacing | Upload rule markers | 16px circles, 4px right margin; rule 2 `margin:0 24px` | index.9fc9db54.css @2517398; index.9fc9db54.css @2517788 |
| growth-vault-pro#105 | colour | Upload rule markers | #f5f5f5 (`---B-btn-bc` fallback) | index.9fc9db54.css @2517398 |
| growth-vault-pro#106 | layout | Upload link import | none: after the drop area the card's next control is step 3, "Edit media" | index.9f50f370.js @13099197 |
| growth-vault-pro#107 | label | Upload drop area with files | a 16px plus (`SAdd,{size:16`), "Add media" and the same tip, "Drag and drop media file(s) here or select them from your computer", in a 106px box | index.9f50f370.js @13098568; index.9f50f370.js @13098643; index.9f50f370.js @13098725; index.9fc9db54.css @2518533 |
| growth-vault-pro#108 | label | Upload step 3 title | Edit media | index.9f50f370.js @13099197 |
| growth-vault-pro#109 | column | Upload step 3 columns | "Media" / "Category" / "Tag Creators" / "Hashtags" / "Notes" / "Suggested price" / "Action" | index.9f50f370.js @12932892; index.9f50f370.js @12934545; index.9f50f370.js @12935090; index.9f50f370.js @12936583; index.9f50f370.js @12937152; index.9f50f370.js @12937470; index.9f50f370.js @12937614 |
| growth-vault-pro#110 | layout | Upload step 3 widths | Tag Creators `width:170`, Hashtags `width:134` | index.9f50f370.js @12935146; index.9f50f370.js @12936629 |
| growth-vault-pro#111 | label | Upload folder control | each file's "Category" cell, and the Batch edit "Category" criterion; no single folder control | index.9f50f370.js @12934545; index.9f50f370.js @12956708 |
| growth-vault-pro#112 | label | Upload selection bar | "Selected" and the count; edit (`SVaultEditIcon`) and delete (`SVaultDeleteIcon`) icons; primary button "Bulk upload" | index.9f50f370.js @13099745; index.9f50f370.js @13100463; index.9f50f370.js @13100618; index.9f50f370.js @13100813 |
| growth-vault-pro#113 | label | Batch edit modal | "Batch edit media"; "Cancel" / "Save" | index.9f50f370.js @12958130; index.9f50f370.js @12958268; index.9f50f370.js @12958328 |
| growth-vault-pro#114 | label | Batch edit criteria | "Select criteria", tooltip "Select the criteria you want to batch-edit"; "All"; "Edit" | index.9f50f370.js @12958702; index.9f50f370.js @12958743; index.9f50f370.js @12959068; index.9f50f370.js @12959787 |
| growth-vault-pro#115 | filter | Batch edit criteria list | "Tag other Creator(s)" / "Category" / "Hashtags" / "Notes" / "Price"; Hashtags and Notes start ticked (`defaultSelectTags=["hashtags","notes"]`) | index.9f50f370.js @12956653; index.9f50f370.js @12956708; index.9f50f370.js @12956756; index.9f50f370.js @12956804; index.9f50f370.js @12956846; index.9f50f370.js @12956887 |
| growth-vault-pro#116 | label | Batch edit fields | "Category"; Notes placeholder "Briefly describe the media content"; "Suggested price" | index.9f50f370.js @12954040; index.9f50f370.js @12955097; index.9f50f370.js @12955507 |
| growth-vault-pro#117 | label | Batch edit note | Saving will update the details for all selected media | index.9f50f370.js @12956373 |
| growth-vault-pro#118 | label | Upload guide steps | "First, you’ll need to link a fan account" / "Next, choose the media you want to upload" / "Then, add your media details" | index.9f50f370.js @12944789; index.9f50f370.js @12944994; index.9f50f370.js @12945133 |
| growth-vault-pro#119 | label | Upload guide step 2 text | You can drag and drop media file(s) here or select them from your computer | index.9f50f370.js @12945046 |

## Clone fixes
| Item | Clone had | Bundle has | Clone edit |
|---|---|---|---|
| growth-vault-pro#4 | title 21px, 16px to the selector | 16px, 24px right margin | `.gtitle` 16px with `margin-right:24px`; `.ghead` column gap 0 (row gap 16px kept for the phone wrap: `_shared/infloww-rea.js` lines 835-836 set `.ghead{flex-wrap:wrap}` at 760px and below); the dead `.gtitle .utc` and `.gtitle .info` rules go |
| growth-vault-pro#7 | Learn as a clickable box with a 19px icon | Learn, 18px icon, opens the help site | Learn is a button, disabled and titled not wired (the help article is off-host), icon 18px |
| growth-vault-pro#8 | 15px, 8px icon gap, actions 22px apart | 14px weight 500, 4px icon margin | `.learn` 14px weight 500, gap 4px; `.hact` gap 24px (#11's left margin) |
| growth-vault-pro#10 | Add media button with no action | opens the upload card | `#vp-add` opens the upload card (#78) |
| growth-vault-pro#11 | Add media 44px tall, padded to its text | 135px by 36px, 24px to Learn | `class="btn-blue add-media"`: the Clone's blue button, `.add-media` sets 135px by 36px, no padding, centred |
| growth-vault-pro#16 | rail 264px with 16px 14px padding (inline 14px 12px) | 208px | `.cpanel` 208px, no padding; the inline style goes |
| growth-vault-pro#19 | rail header 4px 6px 10px padding | 48px tall, 0 16px padding | `.vcustom` 48px tall, `padding:0 16px` |
| growth-vault-pro#20 | header label "Custom" | "Default" | label reads "Default" |
| growth-vault-pro#21 | 16px weight 600, 10px to the sort icon | 13px weight 500, 8px | `.vcustom .l` 13px weight 500, gap 8px |
| growth-vault-pro#25 | 18px icons 14px apart | 20px search and 16px add icons in 30px boxes, 20px radius | `.vcustom .ri` 30px boxes; icons 20px and 16px |
| growth-vault-pro#27 | row 14px 12px padding, 8px radius, counts 8px below the name | 14px top and bottom, 20px left (10px + 10px) and 14px right (10px + 4px), 6px gap | `.vcat` `padding:14px 14px 14px 20px`, column with `gap:6px`, no radius; `.vc` margin goes |
| growth-vault-pro#29 | name 15px | 14px, at most 145px, ellipsis | `.vcat .vn` 14px with `max-width:145px` and an ellipsis |
| growth-vault-pro#30 | 14px and 12px count icons, 14px gap | 20px icons, 16px audio, a `Space` of size 2 | count icons 20px (audio 16px), `.vc` gap 2px |
| growth-vault-pro#31 | counts 13px | 12px | `.vcat .vc` 12px |
| growth-vault-pro#38 | toolbar 18px 22px padding, 14px gap | 16px 24px, sort box 16px left margin (#47) | `.vtoprow` `padding:16px 24px`, gap 16px |
| growth-vault-pro#39 | search 10px radius | 8px | `.vsearch` radius 8px |
| growth-vault-pro#41 | Caption label outside the search box, badged STATIC | the type select inside the search box | "Caption" moves inside `.vsearch` as a disabled button, titled not wired (the type stays Caption) |
| growth-vault-pro#42 | no width, no divider | 111px, 1px right border | `.capsel` 111px with a right border |
| growth-vault-pro#45 | placeholder 15px, no inset | 16px, 11px inset | `.vsearch input` 16px, `padding:0 11px` |
| growth-vault-pro#46 | 20px icon flush right | 24px box, 8px right margin | `.vsearch .si` 24px wide, `margin-right:8px` |
| growth-vault-pro#47 | 44px tall, 0 16px padding, 9px radius | 40px, 8px 16px, 8px | `.recent` 40px, `padding:8px 16px`, radius 8px |
| growth-vault-pro#48 | label flipped between "Recent" and "Oldest" | the field name stays; direction is Ascending / Descending | label stays "Recent"; a click flips the direction, named in its title "Descending" or "Ascending" |
| growth-vault-pro#49 | 14.5px | 13px weight 500 | `.recent` 13px weight 500 |
| growth-vault-pro#54 | 0 22px 18px padding, one flex row | 0px 24px 16px, tabs scroll sideways | `.mrow` `padding:0 24px 16px`, space-between; tabs in `.mtabs` (`overflow-x:auto`) |
| growth-vault-pro#56 | "Media:" 15px, 12px gap | 14px, 8px right margin | `.ml2` 14px, `margin-right:8px` |
| growth-vault-pro#58 | every type always clickable, picked by its label | disabled when the type has no files | pills carry `data-type`; a type with a 0 count is `.off` (`no-drop` cursor) and ignores clicks, except while the mirror's counts stop at its first page; the inline `segpick` handler goes, the page script sets `.on`; with no creator or the vault unavailable every pill is `.off` and titled not wired |
| growth-vault-pro#59 | 9px 22px padding, 14.5px, 12px flex gap | 3px 16px, 14px, 20px line height, 12px right margin | `.seg-pill` 3px 16px, 14px, line height 20px, `margin-right:12px` (0 on the last) |
| growth-vault-pro#63 | tools row 16px gap | 32px tall | `.mrow .rgt` 32px tall |
| growth-vault-pro#64 | a headphones icon | Refresh | `#vp-refresh` titled "Refresh" reloads the grid; disabled and titled not wired with no creator or the vault unavailable |
| growth-vault-pro#66 | none | 28px boxes, 6px side margins, 20px radius | `.vp-refresh` with those values |
| growth-vault-pro#67 | untitled view icons | Grid view / Table view | the two view icons are titled "Grid view" and "Table view" |
| growth-vault-pro#68 | 34px by 32px cells, 8px radius | 2px 6px padding, 1px border each, 4px outer radius | `.viewtog span` `padding:2px 6px` with a border; 4px radius on the outer corners |
| growth-vault-pro#70 | 16px gap | 10px (5px each side) | `.vgrid` gap 10px |
| growth-vault-pro#71 | "Nothing matches this filter." / "OnlyFans returned no vault media for this creator." | No data | the empty grid reads "No data" |
| growth-vault-pro#78 | no upload card | a card over the page | `#vp-upload` covers the page while open: `.vu-pop` `position:absolute;inset:0;z-index:1000` in a `position:relative` `.main`, shown by `.main.vu-open`; its back row is `.vu-head` |
| growth-vault-pro#79 | none | 20px back arrow | `#vu-back` 20px arrow closes the card |
| growth-vault-pro#80 | none | 24px padding, scrolls | `.vu-body` |
| growth-vault-pro#81 | none | 15px marker, 9px dot, 3px line | `.vu-dot` and the step line |
| growth-vault-pro#83 | none | 0 0 65px 16px, 1px rule 32px up | `.vu-wrap` and its rule |
| growth-vault-pro#84 | none | 16px weight 500, 18px below | `.vu-title` |
| growth-vault-pro#85 | none | step 1 title, 6px, info icon | `.vu-title` with `.vu-req` 6px right margin and an info icon whose title holds #86 |
| growth-vault-pro#87 | none | OnlyFans account select | "OnlyFans account" and an input "Enter OnlyFans username", disabled, titled not wired |
| growth-vault-pro#88 | none | label 14px weight 500, 20px, 8px below; 240px by 40px | `.vu-label`; `.vu-input` 240px by 40px |
| growth-vault-pro#90 | none | Select media | step 2 title |
| growth-vault-pro#91 | none | 344px drop area | `.vu-drop` full width, 344px, centred column |
| growth-vault-pro#93 | none | a drop target | `.vu-dragger`, disabled, titled not wired |
| growth-vault-pro#94 | none | 120px by 120px | `.vu-dragger` 120px by 120px |
| growth-vault-pro#95 | none | 24px plus over "Add media" | 24px plus over "Add media" |
| growth-vault-pro#96 | none | 8px above, 14px weight 400 | `.vu-dragger-t` |
| growth-vault-pro#97 | none | the tip | `.vu-tip` text |
| growth-vault-pro#98 | none | 14px weight 400, 20px, 16px above | `.vu-tip` |
| growth-vault-pro#99 | none | 16px above, centred, 12px, 20px | `.vu-rules` |
| growth-vault-pro#101 | none | rule 1 | "Video/audio size limit: 4GB" behind marker "1" |
| growth-vault-pro#102 | none | rule 2 | "Image size limit: 100MB" behind marker "2" |
| growth-vault-pro#103 | none | rule 3 | "Image dimensions: 16px to 10,000px" behind marker "3" |
| growth-vault-pro#104 | none | 16px markers, 4px margin; rule 2 0 24px | `.vu-idx`; `.vu-rule2` |
| growth-vault-pro#108 | none | Edit media | step 3 title |

## Notes
- ASSUMPTION: colours are recorded but not applied, as in the Smart Messages and Scripts captures. The bundle ships a light palette (index.9fc9db54.css @457616) and the Clone is dark on every page, so a recolour is a site-wide theme change (rung 4). Overturned if the owner wants the Clone in the bundle's light palette.
- ASSUMPTION: the Clone's upload card is static: every control in it is disabled and titled "Not wired: uploading to the vault is not built", and only the back arrow works. The Clone has no upload backend; Phase 5 builds the real card in the app (rung 5). Overturned when the Clone gets an upload path.
- ASSUMPTION: the upload card's later states (the 106px drop box with files picked, step 3's table, the selection bar with "Bulk upload", the Batch edit modal, the guide tour, #107 and #109 to #118) and the page's Select all, video length picker, sort popover, table view and modals (#22, #36, #37, #50 to #53, #62, #65, #73 to #77) are recorded but not built in the Clone: none can show without picked files or an action the Clone does not wire (rung 5). Overturned if a Phase asks for the Clone to show them.
- ASSUMPTION: the Clone's collection chip, "Collect all", "Select" and "Tools" stay, in a strip under the header labelled "Inflowwww extra"; the bundle has none of them, and they write to the relay (rung 4). Their selection bar and drawers belong to that strip. Overturned if the owner drops them.
- ASSUMPTION: the Clone keeps its no-creator and vault-unavailable messages; the bundle's not-a-creator text (#13) is about a fan account, a state the Clone cannot reach (rung 5). Overturned if the bundle's empty states are wanted in their place, or the Clone can tell a fan account from a creator.
- ASSUMPTION: at 760px and below the Clone stacks the rail above the grid (at most 240px tall), wraps the toolbar so the search keeps a full row, and wraps the upload rules. The bundle has no phone layout, and `_shared/infloww-rea.js` has no rule for `.gcols`, `.cpanel`, `.vtoprow`, `.vsearch` or `.vu-` (grep), so these are page-local rules in `growth-vault-pro.html`, and `_shared/infloww-rea.js` is untouched (rung 5). Overturned by a bundle phone layout.
- ASSUMPTION: the sort box flips the direction on click instead of opening the bundle's popover (#50 to #53); it is the only sort the relay serves, and the title names the direction with the bundle's words (rung 5). Overturned when the relay serves another sort, or the owner wants the popover.
- Upload and import card, in render order: back arrow (#79); step 1, the OnlyFans account select (#85 to #89); step 2, the drop area: an antd `Upload.Dragger` that takes dropped files or a click (#91 to #105); no link import (#106); step 3, the picked files' table (#108 to #110). There is no "Put into folder" control: the folder (the bundle says "category") is set per file in the step 3 "Category" cell or with the Batch edit "Category" criterion (#111). Phase 5's Drive section is an Inflowwww extra and goes after the drop area's last item, #105, and before step 3, #108 (there is no #106 control between them).
- No link import: `grep -boF -i 'drive'`, and `grep -boF -i` for "Put into", "import from" and "paste", print no offset inside the upload view's modules (12858000 to 13110000); the commands are in `Reproduce:`.
- Phase 5's cited offset 12945046 is the upload guide's step text (#119), not the drop area; the drop area's own tip is #97 (index.9f50f370.js @13097326), with the same words minus "You can".
- Inventory (`docs/infloww-screens.md` §3.5.4) disagreements, the bundle values above stand:
  - Its type tabs say "Videos" and order Photo, GIF, Videos; the bundle has "Photo" / "Video" / "GIF" / "Audio" (#57).
  - Its search dropdown says "Note" / "Hashtags" / "PPV caption"; the bundle's options are "Caption" / "Note" / "Hashtag", and "PPV caption" is only the Caption placeholder (#41, #43).
  - Its "Grid" / "Table" switch is two icons with the tooltips "Grid view" / "Table view" (#67).
  - Its toggle says "creator's feed"; the bundle says "Creator's feed" (#53).
  - Its duration filter reads "Less than 1 minute" / "1 to 5 minutes" / ...; the bundle's are "< 1 min" / "1 - 5 mins" / "5 - 10 mins" / "> 10 mins" (#62).
  - Its per-file fields are "Categories / Tag co-Creators / Hashtags / Notes / Descriptions / Suggested prices"; the step 3 columns are "Category" / "Tag Creators" / "Hashtags" / "Notes" / "Suggested price" / "Action" (#109), and the description is the Notes placeholder (#116).
  - Its "Sent count" stat is "Send count" in the sort (#51); "Unlock rate" is a rail row stat, not a sort (#33).
  - Its file info "Uploader" / "Uploaded time" is the table's "Uploaded by" / "Upload time" (#73).
  - Its "Delete (max 40)" is the "Select all" tool, shown only while at most 40 files are loaded (#65).
  - Its "+ add media" is the button "Add media" with a plus icon (#10); "+ Add media" appears only in the tour text (#12).
  - Its limits (images 100 MB, videos 4 GB) match the defaults (#101, #102); the bundle adds image dimensions of 16px to 10,000px (#103).
- The tour text (#12) and the not-a-creator text (#13) use escaped curly quotes in the bundle (`“`, `’`); the verifier matches the escapes.
- #89 quotes the start of "This account doesn’t exist" ("This account doesn") and the middle of "This account’s subscription has expired," because of the escaped apostrophes.
- Version drift: none; every offset reads in the one entry chunk `index.9f50f370.js` and its stylesheet `index.9fc9db54.css`.
- Rendered-only values: none, the capture is static.
