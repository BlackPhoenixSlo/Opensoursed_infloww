# Layout capture — growth-tracking-links

Bundle: ~/Downloads/infloww-remote-web/, entry `index.9f50f370.js`
Captured: 2026-10-17 at repo `69920d36`
Method: static — REA's web tools (inspect_web_page, capture_web_screenshot, analyze_web_bundle) watch the page passively and cannot abort a request, and `index.html` asks off-host for fonts and the Cookiebot script, so the page was not rendered; REA's JavaScript application map plus `grep -boF` and byte-offset reads stand in
Reproduce:
```sh
R=$(git rev-parse --show-toplevel); B=$HOME/Downloads/infloww-remote-web; S=/tmp/infloww-serve; J=$B/index.9f50f370.js; C=$B/index.9fc9db54.css; V=$B/vendor.bab480ce.js
# Serve tree (read-only symlinks, outside the bundle; reused when present), started from /tmp, checked for a 200, then stopped:
mkdir -p $S/35676908170/assets && ln -sf $B/index.html $S/index.html
for f in $B/*; do ln -sf "$f" $S/35676908170/assets/; done
(cd /tmp && exec python3 -I -m http.server --bind 127.0.0.1 3401 --directory $S) & P=$!
sleep 1; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3401/35676908170/assets/index.9f50f370.js   # prints 200
kill $P
# REA (MCP): mcp__rea__analyze_javascript_application input_path=$B format=directory detail=summary
#   integrity_policy=record-and-continue max_heap_mb=4096 (21 JS files parsed; the entry's semantic pass was not started, static facts kept)
# Anchors, each printed as <offset>:<match>:
grep -boF -e 'path:"/admin/promotion/tracking-links"' -e 'function TrackingLinksPage(' -e 'function TrackingLinks(' -e 'function LinkVariantPage(' -e 'function NavigationTabs(' $J
grep -boF -e 'const TRACKING_LINK_CUSTOM_METRIC_OPTIONS=' -e 'const useSelfCol=' -e 'function buildLinkListBaseColumns(' -e 'function filterVisibleLinkListColumns(' $J
grep -boF -e 'function LinkListSearchPanel(' -e 'function LinkListSearchFields(' -e 'function SearchActionGroup(' -e 'function LinkListUpdateTip(' -e 'function LinkListTablePanel(' $J
grep -boF -e 'function LinkListRowActions(' -e 'function LinkListBatchToolbar(' -e 'function LinkListReconnectEmpty(' -e 'function useLinkCopyAction(' $J
grep -boF -e 'function LinkEditorFormContent(' -e 'LinkEditorDialog=' -e 'const LinkDashboard=' -e 'function LinkListExportModal(' -e 'function TrackingInfo(' -e 'function PageHeader(' $J
grep -boF -e '._page-header_95hze_1{' -e '._navigation-tab_1qxyh_7{' -e '._content-wrap_1rlrg_7{' -e '._update-row_3cet4_31{' -e '._link-title-cell_3pwff_137{' -e '._render-item-container_1x7x3_26{' -e '._form-layout_jrg1l_17{' $C
grep -boF -e '--sizing-named-small:' -e '--typography-text-heading3-strong:' -e '--controls-huge-min-height:' -e '--surface-level-00-emphasis-opaque-00:' -e '--element-spectrum-amber-emphasis-00:' $C
grep -boF -e 'fontWeight:r,textAlign:"start"' -e 'overflowWrap:"break-word"},[`${t}-title`]' $V
# Labels, e.g.: grep -boF '"Links list"' $J prints 14137323; the capture cites the match offset + 1 (the first byte inside the quote).
# Any cited offset reads back with: dd if=$J bs=1 skip=14137324 count=80 2>/dev/null
# Every Items offset, checked at once (exit 0, 0 misses):
cd /tmp && python3 -I "$R/.scratch/infloww-parity-round-2/verify-offsets.py" "$R/docs/infloww-layouts/growth-tracking-links.md"
```
Clone: ui-redesign/infloww-exact/growth-tracking-links.html
Phase: 2 · Matrix row: 3.5.8

## Component tree
- Route `/admin/promotion/tracking-links` renders `TrackingLinksPage` (index.9f50f370.js @16917372)
  - Nav entry and page title "Tracking links" (index.9f50f370.js @10715113)
  - `TrackingLinksPage`: the Details overlay `TrackingInfo` while a row is open, over `TrackingLinks` (index.9f50f370.js @14158473)
    - `TrackingLinks` passes the tracking columns of `useSelfCol` and `TRACKING_LINK_CUSTOM_METRIC_OPTIONS` to `LinkVariantPage` (index.9f50f370.js @14157960)
    - `LinkVariantPage`: `PageHeader` (title, UTC offset, info icon), then `NavigationTabs` "Links list" / "Dashboard" / "Share links" (index.9f50f370.js @14137255; index.9f50f370.js @14137324; index.9f50f370.js @14137374; index.9f50f370.js @14137421)
      - Links list: `LinkListSearchPanel` (tips, `LinkListSearchFields`, toggles, `SearchActionGroup`), then `LinkListTablePanel` (update tip, batch toolbar, table, pagination) (index.9f50f370.js @14065911; index.9f50f370.js @14039274)
        - Table columns: selection, Tracking link (fixed left), the metric columns in `TRACKING_LINK_CUSTOM_METRIC_OPTIONS` order, Actions (fixed right) (index.9f50f370.js @14014066; index.9f50f370.js @14155322)
        - Row actions `LinkListRowActions`: Details, Edit, a dots menu with Deactivate (index.9f50f370.js @14026172)
        - Editor `LinkEditorDialog` with `LinkEditorFormContent`: name, Source, Promo cost, Tag, List (index.9f50f370.js @14010152; index.9f50f370.js @14007983)
        - Export `LinkListExportModal` (index.9f50f370.js @14050089)
      - Dashboard: `LinkDashboard`, filters and seven KPI cards (index.9f50f370.js @13981997)
      - Share links: shown only with the `newShareLinkV1` feature and the share permission (index.9f50f370.js @14136670)

## Items
| ID | Kind | Element | Value | Source |
|---|---|---|---|---|
| growth-tracking-links#1 | layout | Route | `/admin/promotion/tracking-links` | index.9f50f370.js @16917378 |
| growth-tracking-links#2 | label | Nav entry | "Tracking links", menu `id:82` | index.9f50f370.js @10715063; index.9f50f370.js @10715113 |
| growth-tracking-links#3 | label | Page title | the menu title, `pageTitle`; the page calls `jsx(PageHeader,{})` with no title | index.9f50f370.js @13295305; index.9f50f370.js @14137255 |
| growth-tracking-links#4 | spacing | Page header | 16px padding on every side (`--sizing-named-small`) | index.9fc9db54.css @2635053; index.9fc9db54.css @6060309 |
| growth-tracking-links#5 | label | Page title type | 24px weight 500, line-height 1.1666666666666667 (`--typography-text-heading3-strong`) | index.9fc9db54.css @2635612; index.9fc9db54.css @6062830 |
| growth-tracking-links#6 | spacing | UTC block | 8px left and right margin (`._page-header-utc_95hze_16{margin:0 var(--sizing-named-micro)}`); a flex row centred on its items (`className:styles$35["page-header-utc"],align:"center"`) | index.9fc9db54.css @2635474; index.9fc9db54.css @6060145; index.9f50f370.js @13296150 |
| growth-tracking-links#7 | spacing | UTC text | 8px right margin, 14px/1.5 (`--typography-text-body2-open`) | index.9fc9db54.css @2635612; index.9fc9db54.css @6061755 |
| growth-tracking-links#8 | label | UTC info icon | `InfoCircleLine,{size:16}` | index.9f50f370.js @13296301 |
| growth-tracking-links#9 | label | UTC tooltip | the report timezone (`CreatorReportTimezoneUrls` lists `"/admin/promotion/tracking-links"`), tooltip "Set by your organization" | index.9f50f370.js @13294561; index.9f50f370.js @13294628; index.9f50f370.js @13294947 |
| growth-tracking-links#10 | tab | Tabs | "Links list" / "Dashboard" / "Share links" | index.9f50f370.js @14137324; index.9f50f370.js @14137374; index.9f50f370.js @14137421 |
| growth-tracking-links#11 | layout | Share links tab | shown with the `newShareLinkV1` feature only | index.9f50f370.js @14136670 |
| growth-tracking-links#12 | spacing | Tabs | 16px left margin (`margin-left:var(--control-great-padding-vertical)`); tab text `--typography-text-body1-strong` (500 16px/1.25) | index.9fc9db54.css @2794432; index.9fc9db54.css @2794490; index.9fc9db54.css @2794858; index.9fc9db54.css @6038795; index.9fc9db54.css @6061621 |
| growth-tracking-links#13 | spacing | Search panel | 16px padding, none at the bottom (`padding:var(--sizing-named-small) var(--sizing-named-small) 0`) | index.9fc9db54.css @2781723; index.9fc9db54.css @2781757 |
| growth-tracking-links#14 | label | Attribution tip | "Each fan's spending is always attributed to the last free trial link, tracking link or promotion campaign that has been clicked by the fan." | index.9f50f370.js @14065422 |
| growth-tracking-links#15 | button | Tip link | "Learn more" | index.9f50f370.js @14065693 |
| growth-tracking-links#16 | spacing | Tip | 16px below the tips (`._header-tips-content_1l1uj_7{margin-bottom:16px}`); the link `margin-left:8px`, `--typography-text-body2-base` (400 14px/1.1428571428571428) | index.9fc9db54.css @2782772; index.9fc9db54.css @2782946; index.9fc9db54.css @2783031; index.9fc9db54.css @6061682 |
| growth-tracking-links#17 | filter | Creator | `placeholder:"Creator"`, `creatorMaxWidth:250` | index.9f50f370.js @14052790; index.9f50f370.js @14057537 |
| growth-tracking-links#18 | filter | Search | "link name" (the placeholder template reads Search tracking link name), `maxLength:100`, `linkNameWidth:280` | index.9f50f370.js @14052790; index.9f50f370.js @14052810; index.9f50f370.js @14060471; index.9f50f370.js @14060876 |
| growth-tracking-links#19 | filter | Source | `placeholder:"Source"`, "sources selected" for several, `sourceMaxWidth:250` | index.9f50f370.js @14052790; index.9f50f370.js @14052828; index.9f50f370.js @14062799; index.9f50f370.js @14062903 |
| growth-tracking-links#20 | filter | Tag | `placeholder:"Tag"`, `tagMaxWidth:250` | index.9f50f370.js @14052790; index.9f50f370.js @14052847; index.9f50f370.js @14064180 |
| growth-tracking-links#21 | filter | Date range | `prefixText:"Date created"`, "Start date", "End date", `dateWidth:424` | index.9f50f370.js @14052790; index.9f50f370.js @14052863; index.9f50f370.js @14059560; index.9f50f370.js @14059616; index.9f50f370.js @14059629 |
| growth-tracking-links#22 | spacing | Date range | 424px wide (`._date-range-picker_1rlrg_51{width:424px}`) | index.9fc9db54.css @2782731 |
| growth-tracking-links#23 | filter | Date presets | "Today" / "Yesterday" / "Last 7 days" / "Last 30 days" / "Last 6 months" / "Last 12 months" | index.9f50f370.js @14058693; index.9f50f370.js @14058755; index.9f50f370.js @14058821; index.9f50f370.js @14058889; index.9f50f370.js @14058958; index.9f50f370.js @14059028 |
| growth-tracking-links#24 | filter | Toggle | "Show deactivated links", off by default (`showDeactivatedLinks:false`) | index.9f50f370.js @14052705; index.9f50f370.js @14052726; index.9f50f370.js @14063323 |
| growth-tracking-links#25 | filter | Toggle | "Show net earnings", on by default (`showNetEarnings:true`) | index.9f50f370.js @14052705; index.9f50f370.js @14063402 |
| growth-tracking-links#26 | spacing | Search form items | 16px below each item (`margin-bottom:var(--control-great-padding-both)`); labels `margin-right:var(--control-moderate-padding-vertical)` (6px), `--typography-text-body1-base` (400 16px/1.25); the toggle row `._search-toggle-row_1rlrg_39{display:flex;align-items:center}` | index.9fc9db54.css @2781954; index.9fc9db54.css @2781997; index.9fc9db54.css @2782363; index.9fc9db54.css @2782425; index.9fc9db54.css @2782541; index.9fc9db54.css @6038719; index.9fc9db54.css @6039383; index.9fc9db54.css @6061504 |
| growth-tracking-links#27 | button | Create | "Create tracking link", `color:"primary",size:"generous"` | index.9f50f370.js @14052264; index.9f50f370.js @14061873 |
| growth-tracking-links#28 | button | Export | "Export" with `Upload01Line` | index.9f50f370.js @14048471; index.9f50f370.js @14048491 |
| growth-tracking-links#29 | spacing | Action group | 16px between buttons (`gap:16px`), right-aligned (`margin-left:auto`); buttons 36px tall (`--controls-generous-min-height`); a flex row (`._search-action-group_1rlrg_43{display:flex`) | index.9fc9db54.css @2781954; index.9fc9db54.css @2782138; index.9fc9db54.css @2782602; index.9fc9db54.css @2782722; index.9fc9db54.css @6039571 |
| growth-tracking-links#30 | label | Update tip | "Data is updated once every 2 hours" | index.9f50f370.js @14038216 |
| growth-tracking-links#31 | layout | Update row slot | `extraAction`, right of the tip | index.9f50f370.js @14061461 |
| growth-tracking-links#32 | spacing | Update row | 16px gap, 8px below (`._update-row_3cet4_31{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:8px}`); tip `._update-word_3cet4_38{display:flex;align-items:center;gap:8px;color:var(--element-emphasis-01);font:var(--typography-text-body2-base)}`; slot `._update-extra-action_3cet4_48{flex:0 0 auto}` | index.9fc9db54.css @2764027; index.9fc9db54.css @2764081; index.9fc9db54.css @2764138; index.9fc9db54.css @2764193; index.9fc9db54.css @2764243; index.9fc9db54.css @2764333 |
| growth-tracking-links#33 | spacing | Table panel | 16px side padding and 16px below (`margin-bottom:var(--sizing-named-small);padding:0 var(--sizing-named-small)`) | index.9fc9db54.css @2763479; index.9fc9db54.css @2763568 |
| growth-tracking-links#34 | layout | Table | `size:"middle",scroll:{x:1e3` | index.9f50f370.js @14038053 |
| growth-tracking-links#35 | spacing | Table cells | 48px tall (`--controls-huge-min-height`), padding 0 18px (`--control-great-padding-horizontal`); header `--typography-text-body2-strong` (500 14px/1.1428571428571428) | index.9fc9db54.css @252541; index.9fc9db54.css @253579; index.9fc9db54.css @6038754; index.9fc9db54.css @6039711; index.9fc9db54.css @6061813 |
| growth-tracking-links#36 | column | Selection | a checkbox column (`._selection-checkbox-wrap_3pwff_164{`) | index.9fc9db54.css @2775910 |
| growth-tracking-links#37 | column | Column 1 | "Tracking link", `width:271,fixed:"left"` | index.9f50f370.js @14041178; index.9f50f370.js @14041234 |
| growth-tracking-links#38 | column | Column 2 | `title:"Date created"`, `width:121`, date only (`M=LINKS_DATE_ONLY_FORMAT`) | index.9f50f370.js @14041940; index.9f50f370.js @14041999; index.9f50f370.js @14044162 |
| growth-tracking-links#39 | column | Column 3 | `title:"Clicks"`, `width:100` | index.9f50f370.js @14156096; index.9f50f370.js @14156135 |
| growth-tracking-links#40 | column | Column 4 | `title:"Subs"`, `width:100` | index.9f50f370.js @14156204; index.9f50f370.js @14156245 |
| growth-tracking-links#41 | column | Column 5 | `title:"Subscription CVR"`, `width:179` | index.9f50f370.js @14156322; index.9f50f370.js @14156541 |
| growth-tracking-links#42 | column | Column 6 | `title:"Promo cost"`, `width:139` | index.9f50f370.js @14156586; index.9f50f370.js @14156755 |
| growth-tracking-links#43 | column | Column 7 | `title:"Earnings"`, `width:139` | index.9f50f370.js @14156814; index.9f50f370.js @14156933 |
| growth-tracking-links#44 | column | Column 8 | `title:"Fans who spent"`, `width:185` | index.9f50f370.js @14157148; index.9f50f370.js @14157205 |
| growth-tracking-links#45 | column | Column 9 | `title:"Spending CVR"`, `width:159` | index.9f50f370.js @14156979; index.9f50f370.js @14157110 |
| growth-tracking-links#46 | column | Column 10 | `title:"Profit"`, `width:139` | index.9f50f370.js @14157274; index.9f50f370.js @14157350 |
| growth-tracking-links#47 | column | Column 11 | `title:"CPC"`, `width:123` | index.9f50f370.js @14157422; index.9f50f370.js @14157512 |
| growth-tracking-links#48 | column | Column 12 | `title:"EPC"`, `width:123` | index.9f50f370.js @14157557; index.9f50f370.js @14157649 |
| growth-tracking-links#49 | column | Column 13 | `title:"CPS"`, `width:123` | index.9f50f370.js @14157694; index.9f50f370.js @14157867 |
| growth-tracking-links#50 | column | Column 14 | `title:"AEPS"`, `width:123` | index.9f50f370.js @14042065; index.9f50f370.js @14042177 |
| growth-tracking-links#51 | column | Column 15 | `title:"ROI"`, `width:139` | index.9f50f370.js @14042230; index.9f50f370.js @14042336 |
| growth-tracking-links#52 | column | Column 16 | `title:"Source"`, `width:120` | index.9f50f370.js @14042401; index.9f50f370.js @14042522 |
| growth-tracking-links#53 | column | Column 17 | `title:"Tag"`, `width:180`, "Tag management" | index.9f50f370.js @14042707; index.9f50f370.js @14042769; index.9f50f370.js @14042829 |
| growth-tracking-links#54 | column | Column 18 | `title:"List"`, `width:180`, "List management" | index.9f50f370.js @14042922; index.9f50f370.js @14042986; index.9f50f370.js @14043055 |
| growth-tracking-links#55 | column | Column 19 | `title:"Last updated"`, `width:151` | index.9f50f370.js @14043202; index.9f50f370.js @14043265 |
| growth-tracking-links#56 | column | Column 20 | `title:"Actions"`, `width:mt?206:170,fixed:"right"` | index.9f50f370.js @14043454; index.9f50f370.js @14043504 |
| growth-tracking-links#57 | layout | Column order | fixed-left columns, then the unfixed in option order "Date created" / "Clicks" / "Subs" / "Subscription CVR" / "Promo cost" / "Earnings" / "Fans who spent" / "Spending CVR" / "Profit" / "CPC" / "EPC" / "CPS" / "AEPS" / "ROI" / "Source" / "Tag" / "List" / "Last updated", then fixed-right (`function filterVisibleLinkListColumns(`) | index.9f50f370.js @14014066; index.9f50f370.js @14155389; index.9f50f370.js @14155430; index.9f50f370.js @14155469; index.9f50f370.js @14155506; index.9f50f370.js @14155549; index.9f50f370.js @14155585; index.9f50f370.js @14155632; index.9f50f370.js @14155675; index.9f50f370.js @14155711; index.9f50f370.js @14155738; index.9f50f370.js @14155762; index.9f50f370.js @14155786; index.9f50f370.js @14155811; index.9f50f370.js @14155836; index.9f50f370.js @14155863; index.9f50f370.js @14155898; index.9f50f370.js @14155934; index.9f50f370.js @14155967 |
| growth-tracking-links#58 | label | Title cell | "Copy link", a divider, the "Deactivated" chip | index.9f50f370.js @14041704; index.9f50f370.js @14041899 |
| growth-tracking-links#59 | spacing | Title cell | 2px between name and meta (`._link-title-cell_3pwff_137{display:flex;flex-direction:column;align-items:flex-start;gap:2px;width:100%}`); meta row `._link-title-meta_3pwff_144{display:flex;gap:8px;align-items:center}`; the copy link `--typography-text-caption1-strong` (500 12px/1.1666666666666667), `cursor:pointer` | index.9fc9db54.css @2775446; index.9fc9db54.css @2775532; index.9fc9db54.css @2775551; index.9fc9db54.css @2775592; index.9fc9db54.css @2775733; index.9fc9db54.css @6061964 |
| growth-tracking-links#60 | colour | Copy link | #f88056 (`--element-action-primary-emphasis-00`), light theme #fe7d50 | index.9fc9db54.css @6041413; index.9fc9db54.css @6084479 |
| growth-tracking-links#61 | label | Copy feedback | "Link copied", the copy action locked for `5e3` ms | index.9f50f370.js @14043783; index.9f50f370.js @14044034 |
| growth-tracking-links#62 | button | Row actions | "Details" / "Edit" / a `DotsVerticalLine` menu with "Deactivate" | index.9f50f370.js @14026683; index.9f50f370.js @14026975; index.9f50f370.js @14027436; index.9f50f370.js @14027927 |
| growth-tracking-links#63 | spacing | Row actions | 8px between actions (`._table-action-content_3cet4_51{display:inline-flex;align-items:center;gap:8px}`) | index.9fc9db54.css @2764378 |
| growth-tracking-links#64 | label | Deactivate confirm | `Deactivate link, ${Mt}?`; content "link is no longer tracked when the link is deactivated. This action is permanent and cann"; `okText:"Deactivate",cancelText:"Cancel"`, `width:600` | index.9f50f370.js @14028314; index.9f50f370.js @14028411; index.9f50f370.js @14028515; index.9f50f370.js @14028584 |
| growth-tracking-links#65 | empty state | Table | "No data" (the table's default empty content) | index.9f50f370.js @1009378 |
| growth-tracking-links#66 | layout | Pagination | `PAGE_SIZE_OPTIONS=["10","20","50"];const DEFAULT_PAGE_SIZE=50` | index.9f50f370.js @14030275 |
| growth-tracking-links#67 | button | Batch toolbar | "Deactivate links?" confirm; the count `selected"]` | index.9f50f370.js @14035973; index.9f50f370.js @14036785 |
| growth-tracking-links#68 | empty state | Reconnect | "Creator's OnlyFans account is disconnected from Infloww" / "Relink OnlyFans account" | index.9f50f370.js @14037412; index.9f50f370.js @14037552 |
| growth-tracking-links#69 | label | Editor title | "Create" or "Edit" before "tracking link" | index.9f50f370.js @13988264; index.9f50f370.js @13988271; index.9f50f370.js @14010962 |
| growth-tracking-links#70 | label | Editor name | "Tracking link name", `maxLength:100`, "This is a required field" | index.9f50f370.js @14000758; index.9f50f370.js @14000900; index.9f50f370.js @14001018 |
| growth-tracking-links#71 | label | Editor source | `children:"Source"`, "Add source" | index.9f50f370.js @14004686; index.9f50f370.js @14004802 |
| growth-tracking-links#72 | label | Editor promo cost | "Promo cost " with "Optional", `prefix:"$",maxLength:11` | index.9f50f370.js @14004142; index.9f50f370.js @14004177; index.9f50f370.js @14004379 |
| growth-tracking-links#73 | label | Editor tag and list | "Tag " / "List " | index.9f50f370.js @14002173; index.9f50f370.js @14006321 |
| growth-tracking-links#74 | layout | Editor field order | `jsx(LinkNameField`, `jsx(SourceField`, `jsx(PromoCostField`, `jsx(TagField`, `jsx(ListField` (the free-trial fields are skipped for tracking links) | index.9f50f370.js @14008584; index.9f50f370.js @14008678; index.9f50f370.js @14009350; index.9f50f370.js @14009432; index.9f50f370.js @14009730 |
| growth-tracking-links#75 | button | Editor ok | `okText:"Save"` | index.9f50f370.js @14011065 |
| growth-tracking-links#76 | spacing | Editor form | 24px between fields (`._form-layout_jrg1l_17{display:flex;flex-direction:column;gap:24px}`); items `gap:8px`, last `margin-bottom:16px`; label `--typography-text-body1-base`; label span `--typography-text-body2-base` with `margin-left:var(--control-intermediate-padding-vertical)` (4px) | index.9fc9db54.css @2777499; index.9fc9db54.css @2777622; index.9fc9db54.css @2777662; index.9fc9db54.css @2777681; index.9fc9db54.css @2777736; index.9fc9db54.css @2777826; index.9fc9db54.css @2777856; index.9fc9db54.css @6039069 |
| growth-tracking-links#77 | label | Dashboard cards | "Total clicks" / "Avg CPC" / "Total subs" / "Avg CPS" / "Subscription CVR" / "Total earnings" / "Avg ROI" | index.9f50f370.js @13965928; index.9f50f370.js @13966010; index.9f50f370.js @13966143; index.9f50f370.js @13966221; index.9f50f370.js @13966437; index.9f50f370.js @13966694; index.9f50f370.js @13966805 |
| growth-tracking-links#78 | spacing | Dashboard cards | 16px gap and 16px above (`display:flex;flex-wrap:wrap;gap:16px;margin-top:16px`); card `width:32%`, `padding:16px;border-radius:8px` | index.9fc9db54.css @2776498; index.9fc9db54.css @2776531; index.9fc9db54.css @2776544; index.9fc9db54.css @2776613; index.9fc9db54.css @2776697 |
| growth-tracking-links#79 | spacing | Dashboard card text | 16px below a 20px title (`margin-bottom:16px;height:20px;line-height:20px;font-weight:500`); value `height:48px;font-family:"Suisse Int'l Mono"`, `font-style:normal;font-weight:400;font-size:48px;line-height:48px`, `overflow:hidden;text-overflow:ellipsis;white-space:nowrap` | index.9fc9db54.css @2776747; index.9fc9db54.css @2776782; index.9fc9db54.css @2777044; index.9fc9db54.css @2777079; index.9fc9db54.css @2777091; index.9fc9db54.css @2777123; index.9fc9db54.css @2777157; index.9fc9db54.css @2777212 |
| growth-tracking-links#80 | filter | Dashboard filters | `placeholder:"Creator"`, `placeholder:"Source"`, `placeholder:"Tag"`, "Show net earnings", "Last updated: " | index.9f50f370.js @13976604; index.9f50f370.js @13976852; index.9f50f370.js @13977140; index.9f50f370.js @13977439; index.9f50f370.js @13977735 |
| growth-tracking-links#81 | button | Export modal | "Export tracking links"; "Creators" "All creators" / "Selected creator" / "As shown on page"; "Data type"; "The download link may take a few minutes to be ready. Once ready, it will be emailed to"; `okText:"Export",cancelText:"Cancel",width:500` | index.9f50f370.js @13968690; index.9f50f370.js @14049382; index.9f50f370.js @14049463; index.9f50f370.js @14049492; index.9f50f370.js @14049531; index.9f50f370.js @14049597; index.9f50f370.js @14049922; index.9f50f370.js @14050267 |
| growth-tracking-links#82 | layout | Details overlay | `TrackingInfo` with the header "Details" and back to `tittle:S="Tracking links"` | index.9f50f370.js @14153976; index.9f50f370.js @14154065; index.9f50f370.js @14154079 |
| growth-tracking-links#83 | column | Details fan table | `title:"Fan"`, `title:"Total"`, `title:"Subs"`, `title:"Posts"`, `title:"Messages"`, `title:"Streams"`, `title:"Tips"` | index.9f50f370.js @14143942; index.9f50f370.js @14144222; index.9f50f370.js @14144305; index.9f50f370.js @14144395; index.9f50f370.js @14144488; index.9f50f370.js @14144582; index.9f50f370.js @14144681 |
| growth-tracking-links#84 | label | Details texts | "Search fan name"; "Data is updated at least once every 4 hours." | index.9f50f370.js @14146555; index.9f50f370.js @14148425 |
| growth-tracking-links#85 | colour | Page background | #0d0d0d (`--surface-level-00-emphasis-opaque-00`), light theme #f2f2f2 | index.9fc9db54.css @6046961; index.9fc9db54.css @6089058 |
| growth-tracking-links#86 | colour | Title text | #ffffff (`--element-emphasis-00`), light theme #000000 | index.9fc9db54.css @6042139; index.9fc9db54.css @6085205 |
| growth-tracking-links#87 | colour | Learn more | #f88056 (`--element-spectrum-amber-emphasis-00`), light theme #fe7d50 | index.9fc9db54.css @6043409; index.9fc9db54.css @6086475 |
| growth-tracking-links#88 | colour | Metric values | #52b03b positive (dark #58a744), #ff5c9e negative (dark #fb609f) | index.9fc9db54.css @2766323 |
| growth-tracking-links#89 | colour | Update tip text | #ffffff9e (`--element-emphasis-01: rgba(255, 255, 255, 0.62)`), set by `color:var(--element-emphasis-01)` | index.9fc9db54.css @2764138; index.9fc9db54.css @2764201; index.9fc9db54.css @6042170 |
| growth-tracking-links#90 | spacing | Title cell name | 14px (`--typography-text-body2-base: 400 14px/1.1428571428571428`), one line with an ellipsis (`._text-overflow-ellipsis_3pwff_12{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;width:100%;font:var(--typography-text-body2-base)!important}`) | index.9fc9db54.css @2772465; index.9fc9db54.css @6061682 |
| growth-tracking-links#91 | spacing | Body rows | 1px bottom border (`.hb-design-table-tbody>tr>td{border-bottom:1px solid var(--surface-level-02-emphasis-00)}`) | index.9fc9db54.css @244022 |
| growth-tracking-links#92 | colour | Row border | #ffffff17 (`--surface-level-02-emphasis-00: rgba(255, 255, 255, 0.09)`) | index.9fc9db54.css @6047431 |
| growth-tracking-links#93 | layout | Table cells | `border-collapse:collapse` (the base `table` rule); cells `overflow:hidden;text-overflow:ellipsis` | index.9fc9db54.css @252927; index.9fc9db54.css @253086; index.9fc9db54.css @6173721; index.9fc9db54.css @6173762 |
| growth-tracking-links#94 | layout | Row menu | an overlay dropdown, `jsx(Dropdown$1,{menu:{items:Lt.filter(Boolean)`, opened by the dots, on the design library's dropdown layer (`position:absolute;top:-9999px;z-index:1050`) | index.9f50f370.js @14027653; index.9fc9db54.css @217512 |
| growth-tracking-links#95 | spacing | Row action buttons | 28px tall and wide (`size:"moderate"`, `--controls-moderate-min-height: 28px`), 9px side padding (`--control-moderate-padding-horizontal: 9px`) | index.9f50f370.js @14027815; index.9fc9db54.css @6039340; index.9fc9db54.css @6040418 |
| growth-tracking-links#96 | layout | Table header cells | start-aligned, and free to wrap: vendor antd's head cells `fontWeight:r,textAlign:"start"`, no white-space rule on them, only the cell rule's `overflowWrap:"break-word"`; the design table is that antd table under the app prefix (`antdPrefixCls$1="hb-design"`) | vendor.bab480ce.js @1367586; vendor.bab480ce.js @1367418; index.9f50f370.js @536303 |

## Clone fixes
| Item | Clone had | Bundle has | Clone edit |
|---|---|---|---|
| growth-tracking-links#4 | header padded 20px 28px 0 | 16px | `.ghead` padding 16px |
| growth-tracking-links#5 | title 21px weight 600, 9px gap to the UTC | 24px weight 500, line-height 1.1666666666666667 | `.gtitle` 24px/500 with that line-height, no gap |
| growth-tracking-links#6, #7 | UTC text sat in the title's gap | UTC block margin 0 8px; text 8px right, 14px/1.5 | new `.gtitle .gutc` (flex, `margin:0 8px`); `.gtitle .utc` adds `line-height:1.5;margin-right:8px` |
| growth-tracking-links#8, #9 | no info icon | 16px info icon, tooltip "Set by your organization" | a 16px info icon titled "Set by your organization" after the UTC |
| growth-tracking-links#10, #12, #13 | tabs 15px, inline `onclick`, no space below | 16px weight 500; 16px down to the search panel | `.ptab` 16px; `.ptabs` `margin-bottom:16px`; the inline handler and margin go, the script wires `#tk-ptabs` |
| growth-tracking-links#13, #33 | body padded 24px 28px | panels padded 0 16px, search 16px on top | `.gbody` padding `0 16px 16px` |
| growth-tracking-links#15, #16 | "Learn more" a link; banner 22px down | 8px left of the tip, 14px, opens the help site; tips 16px down | "Learn more" is a button `.ib-learn` (`margin-left:8px`, 14px), disabled and titled not wired (the article is off-host); `.ibanner` margin-bottom 16px |
| growth-tracking-links#87 | "Learn more" in #e8814e | #f88056 (the default theme's accent) | `.ibanner .ib-learn` color #f88056 |
| growth-tracking-links#18 | search any width, no limit | 280px, at most 100 characters | `.fbar .f-search{width:280px}`, `maxlength="100"` |
| growth-tracking-links#21, #22 | date range with a calendar icon, its own width | 424px, text prefix "Date created" | `.fbar .f-date{width:424px}`, the inputs flex to fit, prefix is text only, the icon and arrow margins go |
| growth-tracking-links#24, #25 | toggles in a separate row with STATIC badges | in the search form, 16px labels, 6px to the switch | `.f-tgl` (16px/1.25, gap 6px) in `.fbar`; both switches disabled and titled not wired; the badges go |
| growth-tracking-links#26 | filter bar 26px down | 16px | `.fbar` margin-bottom 16px |
| growth-tracking-links#27, #28, #29 | "Create link" (38px) in a section bar, Export with the internal links | "Create tracking link" and "Export" right-aligned, 16px apart, 36px tall | `.f-act` (`margin-left:auto`, gap 16px) holds `#tk-of-create` "Create tracking link" and `#tk-export` "Export" (moved), both 36px; Export is titled as an Inflowwww extra (it downloads a CSV, #81) |
| growth-tracking-links#30, #31, #32 | freshness line inside the section bar | update row: tip left, slot right, 16px gap, 8px down; tip 14px, 8px to the icon | `.tk-update` (space-between, gap 16px, margin-bottom 8px) with `.tk-uword` (flex, gap 8px, 14px, #ffffff9e per #89; the Clone's own freshness text under an "Inflowwww extra" label) and `.tk-xslot` (`flex:0 0 auto`) holding Refresh under the same label; both labels reuse the Clone's `.ms-head` |
| growth-tracking-links#34 to #57 | columns Tracking link, Date created, Clicks, Subs, Subscription CVR, Actions | selection, 20 columns in option order, widths as listed, first two fixed left, Actions fixed right | `table.ltab` in `.lscroll`; the script's `COLS` lists all 21 in order with the bundle widths; selection and Tracking link stick left, Actions right; columns the relay has no data for show "-" titled not wired |
| growth-tracking-links#35, #96 | rows 15px padded to text, headers centred | cells 48px, padding 0 18px; header 14px weight 500, start-aligned | `.ltab th,.ltab td{height:48px;padding:0 18px}` with the cell ellipsis (#93); `.ltab` collapses its borders (#93); body cells get a 1px #ffffff17 bottom border (#91, #92); `.ltab th` 14px/500 and `text-align:start` (#96); the header and fixed-column fills reuse the Clone's `.thead` and `.actcol` rules |
| growth-tracking-links#36 | no selection column | a checkbox column | a disabled checkbox titled not wired (batch deactivate is not built) |
| growth-tracking-links#38 | date and time | date only | the cell prints the locale date |
| growth-tracking-links#58, #59, #61 | name with an open-link icon | name over "Copy link", gap 2px; "Copy link" 12px weight 500; "Link copied" for 5s | `.lt-cell` (column, gap 2px, width 100%), `.lt-name` 14px on one line with an ellipsis (#90), `.lt-meta` (gap 8px), `.lt-copy` 12px/500 button; copy shows "Link copied" and stays disabled 5000ms; without a link it is disabled and titled not wired |
| growth-tracking-links#60 | "Copy link" in #e8814e | #f88056 (the default theme's accent) | `.lt-copy` color #f88056 |
| growth-tracking-links#62, #63, #64 | a trash icon that deletes the campaign | Details, Edit, dots menu with Deactivate, 8px apart; the deactivate confirm | `.lt-act` (gap 8px) with 28px buttons, 9px side padding (#95): Details and Edit disabled and titled not wired; the dots open the Clone's `.ms-menu` (as `.tk-rowmenu`) as an overlay under the button, right-aligned to it (#94): "Deactivate" disabled and titled "Not wired: OnlyFans has no deactivate", then under an "Inflowwww extra" label "Delete on OnlyFans", which confirms in its own words and deletes the campaign |
| growth-tracking-links#65 | "No OnlyFans tracking links yet" text | "No data" | an icon over "No data" when the list is empty or filtered out |
| growth-tracking-links#69 to #76 | modal "Create OnlyFans tracking link": one name input, button "Create on OnlyFans" | name, Source, Promo cost Optional, Tag, List; "Save"; required-field error; 24px between fields | `.tk-form` (gap 24px, 16px down) of `.tk-fi` items (column, gap 8px, label 16px, span 14px 4px left, both in the modal's text colour): "Tracking link name" (maxlength 100) live, the other four disabled and titled not wired; button "Save"; an empty name shows "This is a required field" |
| growth-tracking-links#77, #78, #79 | no KPI cards | seven cards in order, 32% wide, 16px apart; title 20px weight 500, value 48px "Suisse Int'l Mono" | `#tk-kpis.kpis` with seven `.stat.kpi` cards (the Clone's `.stat` box plus the item's width, padding and radius; the title keeps the theme colour, the value is weight 400 per #79 and leads with the bundle's "Suisse Int'l Mono", then a local monospace stack) in bundle order; Total clicks, Total subs and Subscription CVR come from the links, the cost and spend cards show "-" titled not wired |

## Notes
- ASSUMPTION: colours are recorded but not applied, as in the Smart Messages, Scripts and Vault Pro captures. The default theme's tokens are dark (#0d0d0d page, #ffffff title, #f88056 accent, #85 to #87), and the Clone draws those dark values: page #0d0d0d, title #ffffff, and the #f88056 accent on Copy link and Learn more (#60, #87, set in this ticket); the light theme (#f2f2f2, #000000, #fe7d50) is a site-wide theme change (rung 4). Overturned if the owner wants the Clone in the bundle's light palette.
- ASSUMPTION: the Share links tab (#10, #11) is left out: it shows only with the `newShareLinkV1` account feature and the share permission, and the Clone has neither (rung 5). Overturned if share links get a page and the tab is wanted.
- ASSUMPTION: recorded but not built in the Clone: pagination (#66), the batch toolbar (#67), the export modal (#81), the dashboard filters and "Last updated: " (#80), the Details overlay (#82 to #84), the Source, Tag and List managers (#53, #54), the "Deactivated" chip (#58) and the editor's "$" prefix (#72). The relay has no per-fan data, no metadata and no deactivated links, so none can show (rung 5). Overturned if a Phase asks for them, or the relay serves that data.
- ASSUMPTION: "Deactivate" (#62, #64) is disabled and titled "Not wired: OnlyFans has no deactivate": the bundle keeps a deactivated link and its data, and OnlyFans can only delete one (rung 5). The Clone's delete stays in the same menu as a separate "Delete on OnlyFans" under an "Inflowwww extra" label, with a confirm that says the campaign and its click and subscriber counts are removed (rung 4). Overturned if the relay gains a deactivate that keeps the data.
- ASSUMPTION: the update row keeps the Clone's freshness text in place of "Data is updated once every 2 hours" (#30): the relay fetches on load, not every 2 hours, so the bundle's words would be false (rung 4). The text and Refresh, in the `extraAction` slot (#31), each carry an "Inflowwww extra" label. Overturned if the relay syncs every 2 hours.
- ASSUMPTION: Export downloads a CSV at once instead of opening the emailed export modal (#81); the Clone sends no email (rung 4). The button's title says so as an Inflowwww extra. Overturned when an emailed export exists.
- ASSUMPTION: the Clone keeps its "OnlyFans is not reachable right now" and no-creator messages instead of the reconnect empty state (#68): the relay cannot tell a disconnected account from a failed fetch (rung 5). Overturned if the relay reports a disconnect.
- ASSUMPTION: at 760px and below the date range wraps its prefix onto its own line, the KPI cards go full width, the update row wraps and the fixed columns stop sticking. The bundle has no phone layout, so these are page-local rules in `growth-tracking-links.html`, and `_shared/infloww-rea.js` is untouched (rung 5). Overturned by a bundle phone layout.
- ASSUMPTION: the Clone's extras stay, each under an "Inflowwww extra" label: the link-address warning, the totals and the internal redirect links under the table, the dashboard's Profile funnel, Profile visitors and Link performance (whose strip leaves out the clicks and subscriber totals the KPI cards show), and the create modal's safety note; the bundle has none of them (rung 4). Overturned if the owner drops them.
- ASSUMPTION: the KPI value font leads with "Suisse Int'l Mono" (#79) and falls back to a local monospace stack: the font is proprietary and is not fetched (floor 2), so the fallback draws unless the machine has it installed. Overturned by a licensed local copy of the font.
- ASSUMPTION: table body text stays 15px; the bundle's body cell font is set by the design table's theme, which this capture did not trace (rung 5). Overturned by a read of the body cell font.
- Table headers are start-aligned and wrap where a title is wider than its column ("Date created" sits on two lines at its 140px width): antd sets `textAlign:"start"` and no white-space rule on head cells (#96).
- Column order: `useSelfCol` builds Spending CVR before Fans who spent, but `filterVisibleLinkListColumns` orders the unfixed columns by the option keys, so the page shows Fans who spent first (#44, #45, #57); the Items follow the page.
- The deactivate content (#64) is a template, `Data from the ${…} link is …`; the Value quotes its fixed part.
- Inventory (`docs/infloww-screens.md` §3.5.8) disagreements, the bundle values above stand:
  - Its "Promo costs" is "Promo cost" (#42); its column list leaves out Date created and Fans who spent (#38, #44).
  - Its KPIs "Average CPC" / "Average CPS" / "Average ROI" are "Avg CPC" / "Avg CPS" / "Avg ROI" (#77).
  - Its "Show expired" is "Show deactivated links" (#24).
  - Its "Create link" is "Create tracking link" (#27); the editor's button is "Save", not "Create" (#75).
  - Its "channel source" with TikTok / Reddit / Twitch / custom is the "Source" field with "Add source" (#71).
  - Its "Autosync every 2h" is the update tip (#30).
  - Its Actions "✏️ promo cost" is the Edit action, which opens the whole editor (#62).
- Version drift: none; every offset reads in the one entry chunk `index.9f50f370.js`, its stylesheet `index.9fc9db54.css` and the vendor chunk `vendor.bab480ce.js` (antd, #96).
- Rendered-only values: none, the capture is static.
