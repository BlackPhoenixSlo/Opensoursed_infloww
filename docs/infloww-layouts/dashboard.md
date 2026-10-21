# Layout capture — dashboard

Bundle: ~/Downloads/infloww-remote-web/, entry `index.9f50f370.js`
Captured: 2026-10-17 at repo `881f4b50`
Method: static — REA's web tools (inspect_web_page, capture_web_screenshot, analyze_web_bundle) watch the page passively and cannot abort a request, and `index.html` asks off-host for fonts and the Cookiebot script, so the page was not rendered; REA's JavaScript application map plus `grep -boF` and byte-offset reads stand in
Reproduce:
```sh
# Run from the repo root.
R=$(git rev-parse --show-toplevel); B=~/Downloads/infloww-remote-web; S=/tmp/infloww-serve
J=$B/index.9f50f370.js; C=$B/index.9fc9db54.css; V=$B/vendor.bab480ce.js
# Serve tree (read-only symlinks, outside the bundle; reused if another capture built it), started from /tmp, checked for a 200, then stopped:
mkdir -p $S/35676908170/assets && ln -sf $B/index.html $S/index.html
for f in $B/*; do ln -sf "$f" $S/35676908170/assets/; done
(cd /tmp && exec python3 -I -m http.server --bind 127.0.0.1 3401 --directory $S >/dev/null 2>&1) & P=$!
sleep 1; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3401/index.html   # prints 200
kill $P
# REA (MCP): mcp__rea__analyze_javascript_application input_path=$B format=directory detail=summary
#   integrity_policy=record-and-continue max_heap_mb=4096 (21 JS files parsed; the entry's semantic pass hit its budget)
# Anchors, each printed as <offset>:<match>:
grep -boF -e 'path:"/admin/home",element:jsx(HomePage$1' -e 'key:"/admin/home",' -e '"/admin/home-dashboard"' $J
grep -boF -e 'function HomePage$1(' -e 'function FilterBtns$1(' -e 'function IncomeOverview(' -e 'function Shifts(' $J
grep -boF -e 'function ChattingReports(' -e 'function HoursReports(' -e 'function NetworkReport(' -e 'const fn=(Tn,jn,Nn=false' $J
grep -boF -e 'useState("week")' -e 'useState("Net")' -e 'const R=(mt,bt)=>' -e 'const mt={before:{background' $J
grep -boF -e '_filter-btns-group_1dv25_1' -e '_income-overview_1dv25_71' -e '_shifts_1dv25_32' -e '_box_1kor8_1' $C
grep -boF -e '._card_bpg1k_1{' -e '._box_1vovf_1 ._title' -e '._empty-wrap_1iayr_1 img' $C
grep -boF -e '--tc-T0:' -e '--tc-T2:' -e '--tc-T3:' -e '--tc-Home-B1:' -e '--tc-B-radio:' -e '--tc-Home-B-th:' -e '--tc-L1:' -e '--tc-M-B:' $C
# The earnings select is antd's Select (`S as Select$6`, imported from the vendor chunk), themed only for its font family:
grep -boF -e 'S as Select$6' -e 'theme:{token:{fontFamily:customFontFamily}}' $J
grep -boF -e 'sizeSM:t*(r-1)' -e 'fontSize:14,lineWidth:1' -e 'sizeUnit:4,sizeStep:4' -e 'paddingSM:i.sizeSM' -e 'const es={overflow' $V
grep -boF -e '-selection-item`]:Object.assign(Object.assign({flex:1' -e 'inputPaddingHorizontalBase:e.paddingSM-1' $V
# Every Items label and value, read back at its cited offset (exit 0, 0 misses):
cd /tmp && python3 -I $R/.scratch/infloww-parity-round-2/verify-offsets.py $R/docs/infloww-layouts/dashboard.md
# Clone-only cards and the trial banner, each line prints nothing:
for s in 'Fans & subscriptions' 'Daily earnings' 'Creators overview' '7-day free trial'; do grep -lF -- "$s" $B/*; done
```
Clone: ui-redesign/infloww-exact/dashboard.html
Phase: 1 · Matrix row: 3.1

## Component tree
- Route `/admin/home` renders `HomePage$1` (index.9f50f370.js @16913762)
  - Nav entry "Dashboard", key `/admin/home` (index.9f50f370.js @10709605; index.9f50f370.js @10709675)
  - `HomePage$1`: the period and Net/Gross state, the creator earnings read and the employee sales read (index.9f50f370.js @11240761)
    - Page frame `styles$4o.box` (index.9f50f370.js @11243027; index.9fc9db54.css @1776720)
      - Card "Creator earnings overview" (`index$k`) (index.9f50f370.js @11243074; index.9f50f370.js @4451125)
        - Title row: title and tooltip, time zone, "Set by your organization" icon on the left; `FilterBtns$1` on the right (index.9f50f370.js @11241990)
          - `FilterBtns$1`: Net/Gross select, then the four period tabs (index.9f50f370.js @11232039)
        - `IncomeOverview`: Total earnings, then three columns of two channels (index.9f50f370.js @11236803)
      - Bottom box (index.9f50f370.js @11243340; index.9fc9db54.css @1777268)
        - Card "My shifts" (`Shifts`), 240px, on the left (index.9f50f370.js @11243386; index.9f50f370.js @11234410)
        - Right column (index.9f50f370.js @11243610; index.9fc9db54.css @1777335)
          - Card "Current clocked-in employees" (index.9f50f370.js @11243783)
          - Card "Employee sales" (`ChattingReports`) (index.9f50f370.js @11244153; index.9f50f370.js @11230227)
          - Card "Scheduled hours" (`HoursReports`) (index.9f50f370.js @11244531; index.9f50f370.js @11233031)
      - `NetworkReport` modal, closed unless the URL asks for it (index.9f50f370.js @11244704; index.9f50f370.js @11242610)

## Items
| ID | Kind | Element | Value | Source |
|---|---|---|---|---|
| dashboard#1 | layout | Route | `/admin/home` renders `HomePage$1` | index.9f50f370.js @16913768 |
| dashboard#2 | label | Nav entry | Dashboard | index.9f50f370.js @10709605 |
| dashboard#3 | layout | Default period | `useState("week")`: the This week tab | index.9f50f370.js @11240831 |
| dashboard#4 | layout | Default earnings basis | `useState("Net")`: Net earnings | index.9f50f370.js @11240876 |
| dashboard#5 | layout | Page content, in order | `styles$4o.box` holds the earnings card, then the `bottom-box`, then `NetworkReport`; no Creator reports block | index.9f50f370.js @11243027; index.9f50f370.js @11243340; index.9f50f370.js @11244704 |
| dashboard#6 | spacing | Page frame padding | 16px (`padding:16px`) | index.9fc9db54.css @1776769 |
| dashboard#7 | colour | Page background | #f5f5f5 (`--tc-Home-B1`) | index.9fc9db54.css @1776755; index.9fc9db54.css @457806 |
| dashboard#8 | spacing | Card padding | 20px 24px 16px 24px (`padding:20px 24px 16px 24px`) | index.9fc9db54.css @463364 |
| dashboard#9 | spacing | Card radius | 12px (`border-radius:12px`) | index.9fc9db54.css @463425 |
| dashboard#10 | colour | Card background | #ffffff (`--tc-Home-B-th`), set as `Home-B-th` on every card | index.9f50f370.js @11243232; index.9fc9db54.css @457890 |
| dashboard#11 | spacing | Card gap | 16px (`marginBottom:16`) | index.9f50f370.js @11243201 |
| dashboard#12 | spacing | Card title | 16px (`font-size:16px`), weight 500 | index.9fc9db54.css @463475; index.9fc9db54.css @465852 |
| dashboard#13 | label | Earnings card title | Creator earnings overview | index.9f50f370.js @11243074 |
| dashboard#14 | label | Earnings card title tooltip | An overview of total earnings based on your managed Creators during this period | index.9f50f370.js @11243102 |
| dashboard#15 | spacing | Title to info icon | 9px (`margin-right:9px`) | index.9fc9db54.css @465924 |
| dashboard#16 | label | Time zone label | "UTC", then the sign and the `padStart(2,"0")` hours and minutes of the user's `reportTimezoneId` | index.9f50f370.js @7143613; index.9f50f370.js @11242265 |
| dashboard#17 | spacing | Time zone box | 8px left margin (`margin-left:8px`), 14px font, 5px padding, 5px radius | index.9fc9db54.css @1777098 |
| dashboard#18 | colour | Time zone text | #666666 (`--tc-T2`) | index.9fc9db54.css @1777124; index.9fc9db54.css @457633 |
| dashboard#19 | label | Time zone tooltip | Set by your organization | index.9f50f370.js @11242336 |
| dashboard#20 | filter | Earnings select options, in order | Gross earnings / Net earnings | index.9f50f370.js @11232424; index.9f50f370.js @11232463 |
| dashboard#21 | spacing | Earnings select | 140px wide (`width:140px`), 36px high, 16px right margin; antd's Select draws 14px text (`fontSize:14`) with 11px side padding (`paddingSM-1`), the label `flex:1` on one line with an ellipsis (`whiteSpace:"nowrap"`) | index.9fc9db54.css @1772426; vendor.bab480ce.js @230241; vendor.bab480ce.js @553684; vendor.bab480ce.js @551354; vendor.bab480ce.js @249446 |
| dashboard#22 | tab | Period tab 1 | Yesterday | index.9f50f370.js @11232154 |
| dashboard#23 | tab | Period tab 2 | Today | index.9f50f370.js @11232192 |
| dashboard#24 | tab | Period tab 3 | This week | index.9f50f370.js @11232222 |
| dashboard#25 | tab | Period tab 4 | This month | index.9f50f370.js @11232255 |
| dashboard#26 | spacing | Period strip | 4px padding (`padding:4px`), 4px radius, 1px border | index.9fc9db54.css @1772531 |
| dashboard#27 | colour | Period strip border | #e6e6e6 (`--tc-L1`) | index.9fc9db54.css @1772557; index.9fc9db54.css @458232 |
| dashboard#28 | spacing | Period tab | 24px high (`height:24px`), 12px font, 5px 20px padding, 5px right margin, 2px radius | index.9fc9db54.css @1772665 |
| dashboard#29 | colour | Period tab text | #666666 (`--tc-T2`) | index.9fc9db54.css @1772681; index.9fc9db54.css @457633 |
| dashboard#30 | colour | Active period tab | #eff4ff (`--tc-M-B`) background, #2d74ff text | index.9fc9db54.css @1772982; index.9fc9db54.css @458310 |
| dashboard#31 | colour | Period tab hover | #E9EEFD (`--tc-B-radio`) background, #2d74ff text | index.9fc9db54.css @1772861; index.9fc9db54.css @457868 |
| dashboard#32 | layout | Tile figures | every tile reads its Net field in Net mode and its Gross field otherwise (`M==="Net"?E[bt]:E[mt]`) | index.9f50f370.js @11236892 |
| dashboard#33 | spacing | Tiles row top margin | 16px (`margin-top:16px`) | index.9fc9db54.css @1773805 |
| dashboard#34 | layout | Tiles row | four equal columns (`flex:1`), a `border-right` divider after each but the last (`border-right:0`) | index.9fc9db54.css @1773864; index.9fc9db54.css @1774898 |
| dashboard#35 | spacing | Tile column height | 177px (`height:177px`) | index.9fc9db54.css @1773907 |
| dashboard#36 | label | Tile 1 | Total earnings | index.9f50f370.js @11237146 |
| dashboard#37 | layout | Tile 1 figure | `R("totalGross","totalNet")` | index.9f50f370.js @11237283 |
| dashboard#38 | spacing | Total tile left padding | 24px (`padding-left:24px`) | index.9fc9db54.css @1775014 |
| dashboard#39 | spacing | Total tile icon | 45px (`width:45px`) | index.9fc9db54.css @1775114 |
| dashboard#40 | spacing | Total tile label | 12px (`font-size:12px`), 15px line height, weight 500, margin 18px 0 12px | index.9fc9db54.css @1775330 |
| dashboard#41 | colour | Total tile label | #1890ff | index.9fc9db54.css @1775368 |
| dashboard#42 | spacing | Total tile figure | 34px (`font-size:34px`), 45px line height, weight 700; the currency sign 25px (`font-size:25px`) | index.9fc9db54.css @1775696; index.9fc9db54.css @1775517 |
| dashboard#43 | colour | Total tile figure | #2d74ff | index.9fc9db54.css @1775572; index.9fc9db54.css @1775734 |
| dashboard#44 | label | Tile 2, top | Subscriptions | index.9f50f370.js @11237638 |
| dashboard#45 | label | Tile 2, bottom | Tips | index.9f50f370.js @11238009 |
| dashboard#46 | label | Tile 3, top | Posts | index.9f50f370.js @11238470 |
| dashboard#47 | label | Tile 3, bottom | Referrals | index.9f50f370.js @11238833 |
| dashboard#48 | label | Tile 4, top | Messages | index.9f50f370.js @11239315 |
| dashboard#49 | label | Tile 4, bottom | Streams | index.9f50f370.js @11239701 |
| dashboard#50 | layout | Channel fields (Gross, Net) | Subscriptions `subscribesGross` `subscribesNet`; Tips `tipsGross` `tipsNet`; Posts `postsGross` `postsNet`; Referrals `refevrralGross` `referralNet`; Messages `chatMessagesGross` `chatMessagesNet`; Streams `streamsGross` `streamsNet` | index.9f50f370.js @11237578; index.9f50f370.js @11237961; index.9f50f370.js @11238420; index.9f50f370.js @11238776; index.9f50f370.js @11239251; index.9f50f370.js @11239647 |
| dashboard#51 | spacing | Channel column margins | 35.5px left (`margin:0 38.5px 0 35.5px`), 38.5px right | index.9fc9db54.css @1775853 |
| dashboard#52 | spacing | Channel row gap | 56px (`margin-bottom:56px`) | index.9fc9db54.css @1776645 |
| dashboard#53 | spacing | Channel figure | 21px (`font-size:21px`), 28px line height, weight 700 | index.9fc9db54.css @1776309 |
| dashboard#54 | colour | Channel figure | #000000 (`--tc-T0`) | index.9fc9db54.css @1776351; index.9fc9db54.css @457599 |
| dashboard#55 | spacing | Channel label | 12px (`font-size:12px`), 17px line height | index.9fc9db54.css @1776498 |
| dashboard#56 | colour | Channel label | #808080 | index.9fc9db54.css @1776536 |
| dashboard#57 | spacing | Channel icon circle | 45px (`width:45px`), right of the figure | index.9fc9db54.css @1774090 |
| dashboard#58 | colour | Subscriptions icon tint | #2ad4ac1a (`rgba(42,212,172,0.1)`) | index.9fc9db54.css @1774302 |
| dashboard#59 | colour | Tips icon tint | #3467ff1a (`rgba(52,103,255,0.1)`) | index.9fc9db54.css @1774404 |
| dashboard#60 | colour | Posts icon tint | #2ad4ac1a (`rgba(42,212,172,0.1)`) | index.9fc9db54.css @1774506 |
| dashboard#61 | colour | Referrals icon tint | #ff7c711a (`rgba(255,124,113,0.1)`) | index.9fc9db54.css @1774610 |
| dashboard#62 | colour | Messages icon tint | #ce63ff1a (`rgba(206,99,255,0.1)`) | index.9fc9db54.css @1774718 |
| dashboard#63 | colour | Streams icon tint | #144ecc1a (`rgba(20,78,204,0.1)`) | index.9fc9db54.css @1774824 |
| dashboard#64 | layout | Bottom box | `bottom-box`: the My shifts card on the left, the `bottom-right` column beside it | index.9f50f370.js @11243340; index.9f50f370.js @11243610; index.9fc9db54.css @1777284 |
| dashboard#65 | label | My shifts card | My shifts | index.9f50f370.js @11243386 |
| dashboard#66 | label | My shifts tooltip | Your scheduled shifts during this period | index.9f50f370.js @11243398 |
| dashboard#67 | spacing | My shifts card width | 240px (`width:240`), full height, `position:"absolute"` | index.9f50f370.js @11243448 |
| dashboard#68 | spacing | Right column inset | 255px (`padding-left:255px`) | index.9fc9db54.css @1777395 |
| dashboard#69 | layout | Shift row | the date as `dddd, MMM. D, YYYY`, then `hh:mm A` to `hh:mm A` in a tinted pill, then the creators' avatars | index.9f50f370.js @11236126; index.9f50f370.js @11236275 |
| dashboard#70 | spacing | Shift date | 12px (`font-size:12px`), margin 24px 0 8px | index.9fc9db54.css @1773284 |
| dashboard#71 | spacing | Shift avatar | 24px (`width:24px`), margin 8px 8px 16px 0 | index.9fc9db54.css @1773684 |
| dashboard#72 | colour | Shift time pill | #2AD4AC text for a shift in progress, #FF7C71 for an upcoming one, `var(--tc-T1)` for a past one | index.9f50f370.js @11234576 |
| dashboard#73 | empty state | My shifts empty | No data | index.9f50f370.js @11235947 |
| dashboard#74 | spacing | My shifts empty offset | 225px top padding (`padding:225px 0 0`) | index.9fc9db54.css @1773094 |
| dashboard#75 | label | Clocked-in card | "Current clocked-in employees", then a `SClockUses` clock icon and the count | index.9f50f370.js @11243783; index.9f50f370.js @11242899 |
| dashboard#76 | layout | Clocked-in card visibility | shown when `appMenuPower.auth([DATA_PERMISSIONS$1.HomePage])` and the clock-in setting is open or `bt?.type!==2` | index.9f50f370.js @11243635 |
| dashboard#77 | empty state | Clocked-in empty | No employees have clocked in. | index.9f50f370.js @11244093 |
| dashboard#78 | spacing | Clocked-in list height | 140px max while empty, 100px with rows (`maxHeight:qt>0?100:140`) | index.9f50f370.js @11243732 |
| dashboard#79 | label | Employee sales card | Employee sales | index.9f50f370.js @11244153 |
| dashboard#80 | label | Employee sales tooltip | Employee sales growth and trends determined by your team’s sales settings | index.9f50f370.js @11244170 |
| dashboard#81 | layout | Employee sales chart | one line series "Earnings" over the period's days (`legendBy:"Day"`) | index.9f50f370.js @11230529; index.9f50f370.js @11241949 |
| dashboard#82 | spacing | Employee sales chart height | 350px (`height:350`) | index.9f50f370.js @11230326 |
| dashboard#83 | colour | Employee sales line | #3467FF, 5px wide | index.9f50f370.js @11230634 |
| dashboard#84 | label | Employee sales point tooltip | Earnings: / Growth: / From Messages: / From Tips: / From Posts: / From Subscriptions: / From Streams: / From Referrals: | index.9f50f370.js @11229309; index.9f50f370.js @11229358; index.9f50f370.js @11229501; index.9f50f370.js @11229632; index.9f50f370.js @11229753; index.9f50f370.js @11229886; index.9f50f370.js @11230026; index.9f50f370.js @11230163 |
| dashboard#85 | layout | Employee sales loading and error | `Spin` while the read loads; `CommonRetryBox$1` with `minHeight:300` when it fails | index.9f50f370.js @11244315 |
| dashboard#86 | label | Scheduled hours card | Scheduled hours | index.9f50f370.js @11244531 |
| dashboard#87 | label | Scheduled hours tooltip | Number of hours worked based on shift schedule | index.9f50f370.js @11244549 |
| dashboard#88 | layout | Scheduled hours chart | one horizontal bar per employee, hours from `relMinutes` | index.9f50f370.js @11233296 |
| dashboard#89 | spacing | Scheduled hours bar | 12px wide (`barWidth:12`) | index.9f50f370.js @11233729 |
| dashboard#90 | colour | Scheduled hours bar | #2AD4AC | index.9f50f370.js @11233947 |
| dashboard#91 | spacing | Scheduled hours body | 24px top margin (`margin-top:24px`) | index.9fc9db54.css @1776689 |
| dashboard#92 | empty state | Scheduled hours empty | No data | index.9f50f370.js @11234391 |
| dashboard#93 | spacing | Empty state image | 100px high (`height:100px`), 8px below | index.9fc9db54.css @652840 |
| dashboard#94 | colour | Empty state text | #999999 (`--tc-T3`) | index.9fc9db54.css @652924; index.9fc9db54.css @457650 |
| dashboard#95 | layout | Network report modal | `NetworkReport`, opened when the URL search is `?showNetReport` | index.9f50f370.js @11244704; index.9f50f370.js @11242610 |
| dashboard#96 | tab | Period tab 5 (later bundle) | Last month | index.b50b8e61.js @11252393 |

## Clone fixes
| Item | Clone had | Bundle has | Clone edit |
|---|---|---|---|
| dashboard#5 | trial banner and a section header above the earnings card; Earnings by channel, Employee sales, Fans & subscriptions, Daily earnings, Creators overview, then a Team strip | the earnings card first, then the bottom box; no banner | banner removed; header moved into the earnings card; the bottom box follows the card; the four Clone-only cards move below it under an "Inflowwww extra" heading; the Team strip is removed |
| dashboard#6 | `.main` padding `20px 40px 0`, 40px bottom | 16px | `.main{padding:16px}` |
| dashboard#8 | `.cardpad` padding `22px 24px`; earnings card `26px 6px` | 20px 24px 16px 24px | `.cardpad{padding:20px 24px 16px 24px}`, and the earnings card takes `.cardpad` |
| dashboard#11 | 20px between cards | 16px | `.main{display:flex;flex-direction:column;gap:16px}` sets every gap between the page's blocks; the bottom box's top margin, the `.extra-h` 24px top margin and the four inline `margin-top:16px` are deleted; inside the right column `.col-right{gap:16px}` |
| dashboard#12 | `.card-h` 17px, weight 600; header title 19px, weight 600 | 16px, weight 500 | `.card-h` and `.sec-title` 16px, weight 500 |
| dashboard#13 | Agency earnings · all creators (rewritten by the script as the roster count changed) | Creator earnings overview | static title "Creator earnings overview"; the script's title rewrite (`syncEarnHead`) is deleted |
| dashboard#14 | no tooltip | An overview of total earnings based on your managed Creators during this period | `title` on the title's info icon |
| dashboard#17 | 16px left margin, gap 6px | 8px left margin, 14px font, 5px padding | `.sec-utc{margin-left:8px;padding:5px;font-size:14px}` |
| dashboard#19 | no tooltip | Set by your organization | `title` on the time zone's info icon |
| dashboard#20 | menu Net earnings, then Gross earnings | Gross earnings, then Net earnings; Net by default (#4) | menu order Gross earnings, Net earnings; Net stays selected |
| dashboard#21 | 44px high, auto width, 12px gap; 14.5px text, `0 14px` padding; the label wrapped | 140px wide, 36px high, 16px right margin; 14px text, 11px side padding, the label on one line with an ellipsis | `.dropdown{width:140px;height:36px;margin-right:16px;padding:0 11px;font-size:14px}`, `.head-right` gap removed; `#dd-net-label{flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}` |
| dashboard#26 | 44px high, 10px radius, no padding, `overflow:hidden` | 4px padding, 4px radius, 1px border | `.segment{padding:4px;border-radius:4px}`, `overflow:hidden` dropped; Clone-only phone rule in `_shared/infloww-rea.js` (760px and below): `#earn-card .segment` scrolls sideways, in the `.fx-seg` rule |
| dashboard#28 | 14.5px font, full height, `0 20px` padding | 24px high, 12px font, 5px 20px padding, 5px right margin, 2px radius | `.segment button{height:24px;font-size:12px;padding:5px 20px;margin-right:5px;border-radius:2px}` |
| dashboard#33 | 26px card padding above the tiles | 16px below the title row | `.earn{margin-top:16px}` |
| dashboard#34 | a 222px Total column and a 3-by-2 grid of channel cells | four equal columns, two channels stacked in each of the last three | `.earn .total` and three `.mcol` are the four direct children of `.earn`, each `flex:1` with no side padding (so the widths split evenly), the `.mcol` with a left divider; the `.metrics` wrapper and rule are deleted, and so are the two phone rules for `.metrics` in `_shared/infloww-rea.js`, whose `#earn-card .earn{flex-direction:column;gap:14px}` stacks the four columns at 760px and below (the bare `.earn` phone rule it replaces also reached the referral card, which keeps its old values as `.ref-card .earn{flex-direction:column;padding:18px 12px}`); channels regrouped Subscriptions over Tips, Posts over Referrals, Messages over Streams |
| dashboard#35 | content height | 177px | `.earn .total` and `.mcol` 177px |
| dashboard#38 | Total column centred | left-aligned, 24px left padding inside the column | the Total's contents sit in `.earn .total .first{align-items:flex-start;padding-left:24px}` |
| dashboard#39 | 56px icon | 45px | `.earn .total .oi` 45px |
| dashboard#40 | 14.5px label, 10px gap | 12px, 15px line height, weight 500, margin 18px 0 12px | `.earn .total .tl{font-size:12px;line-height:15px;margin:18px 0 12px}` |
| dashboard#42 | 44px figure | 34px, 45px line height | `.earn .total .tv{font-size:34px;line-height:45px}` |
| dashboard#51 | `14px 30px` cell padding | 35.5px left, 38.5px right, inside the column | `.metric{margin:0 38.5px 0 35.5px}`; the column itself takes no padding |
| dashboard#52 | grid rows | 56px | `.mcol .metric:first-child{margin-bottom:56px}` |
| dashboard#53 | 30px figure | 21px, 28px line height | `.metric .mv{font-size:21px;line-height:28px}` |
| dashboard#55 | 14px label, 5px above | 12px, 17px line height | `.metric .ml{font-size:12px;line-height:17px}`, its 5px top margin removed |
| dashboard#57 | 52px icon | 45px | `.mi` 45px |
| dashboard#64 | no bottom box (a Team strip at the page end) | My shifts on the left, a right column beside it | `.bottom-box` (renamed from `.grid2`, a class 16 other Clone pages share), `.col-left` (My shifts) and `.col-right` (the column) take the bundle's place and values; Clone-only phone rules in `_shared/infloww-rea.js` (760px and below): `.bottom-box{flex-direction:column;gap:16px}`, `.bottom-box>.col-left{position:static;width:auto;height:auto}`, `.bottom-box>.col-right{padding-left:0}`, so My shifts stacks above the column |
| dashboard#65 | "My shifts" only in the Team strip's sentence | card My shifts with its tooltip | My shifts card, tooltip on its info icon, NOT WIRED badge (the Clone reads no shift data) |
| dashboard#67 | none | 240px, full height | `.col-left{position:absolute;width:240px;height:100%}` |
| dashboard#68 | none | 255px | `.col-right{padding-left:255px}` |
| dashboard#73 | none | No data | the My shifts body text reads "Not wired", with the bundle's 225px offset; "No data" is not shown, since nothing was read |
| dashboard#75 | none | Current clocked-in employees, clock icon, count | the card, NOT WIRED badge, no count |
| dashboard#78 | none | 140px max while empty | clocked-in body `max-height:140px`, reading "Not wired" |
| dashboard#79 | Employee sales second, after Earnings by channel | first card below the clocked-in card in the right column | Employee sales moves into the right column, after the clocked-in card |
| dashboard#80 | no tooltip | Employee sales growth and trends determined by your team’s sales settings | `title` on its info icon |
| dashboard#82 | 322px chart | 350px | `.chart-wrap{height:350px}` |
| dashboard#86 | none | Scheduled hours, with its tooltip | the card after Employee sales, tooltip on its info icon, NOT WIRED badge, body reads "Not wired" |

## Notes
- ASSUMPTION: colours are recorded but not applied, as in `growth-smart-messages.md`. The bundle ships only a light `:root` palette (index.9fc9db54.css @457599) and the Clone is dark on every page, so a recolour would be a site-wide theme change outside one page's fixes (rung 4). Overturned if the owner wants the Clone in the bundle's light palette.
- ASSUMPTION: the Clone's Employee sales keeps its per-employee bars, against the bundle's one daily "Earnings" line (#81): the bars read `/admin/stats/per-employee` totals, and a daily line needs a per-day read the Clone does not make (rung 5). Only the card's place, title, tooltip and height follow the bundle. Overturned if Phase 1 wants the Clone to draw the line too.
- ASSUMPTION: the Clone's Total and channel figures keep one "$0.00" string, against the bundle's "$" at 25px beside a 34px number (#42); splitting the currency sign changes the script's number formatting for no layout gain (rung 5). Overturned by a Phase 1 reviewer who grades the sign size.
- ASSUMPTION: the four Clone-only cards (Earnings by channel, Fans & subscriptions, Daily earnings, Creators overview) stay below the bottom box under an "Inflowwww extra" heading, not deleted: they are wired to the Relay and the Route walk shoots this page (rung 4, additive over removal; precedent: the "Inflowwww extra" group in `growth-smart-messages.html`). Overturned if the owner wants the Clone to show only the bundle's blocks.
- The cards keep the Clone's 1px border, which the bundle's cards lack (index.9fc9db54.css @463349 has none); on the dark Clone the border is what separates a card from the canvas, the same colour reasoning as above.
- No Creator reports block on this page (#5). "Earnings by channel" exists in the bundle, but as a report card elsewhere in the entry chunk (index.9f50f370.js @13281969), not on the Dashboard; "Fans & subscriptions", "Daily earnings", "Creators overview" and the trial banner text are in no bundle file (the Reproduce block's last line).
- Default period: This week (#3), not Today. Phase 1's ASSUMPTION "with no default period in the capture, the default is Today" is overturned by this item. The default basis is Net earnings (#4), although the select lists Gross earnings first (#20).
- #96 comes from a later entry, `index.b50b8e61.js` (cached by the Desktop app; `.scratch/ai-copilot/cache-extract/362282cfb8_index.b50b8e61.js`, not in `~/Downloads/infloww-remote-web`, so `verify-offsets.py` needs that folder as its bundle_dir for this row). Its `DashboardFilterBar` maps `ranges` = Yesterday / Today / This week / This month / Last month (`lastMonth`), and `formatYearTime` draws `lastMonth` by day like `thisMonth`. Ours cuts it as the whole calendar month before This month (`periodWindow`); the bundle's server-side cut is not in the bundle.
- Channel mapping input for Phase 1: the bundle's six channels read the fields in #50. Messages is `chatMessages`, Referrals reads `refevrralGross` (misspelt in the bundle) and `referralNet`, and Streams is its own channel. The employee sales tooltip (#84) splits the same six channels.
- A second page, "Home Dashboard" (`/admin/home-dashboard`, `Dashboard`, menu code 754; index.9f50f370.js @10709960; index.9f50f370.js @16913829), is a separate menu entry with a draggable card grid, gated by its own permission. It is not the Dashboard the Inventory and the Clone describe, so this capture leaves it out.
- The error state's text and button (`Index$E`, index.9f50f370.js @7137649) and the `Empty$1` default text come from i18n keys (`request_failed`, `components-base0009`, `growth0254`) whose English strings are not in the bundle; every empty state on this page passes its own English text (#73, #77, #92).
- Inventory (`docs/infloww-screens.md` §3.1) disagreements: it says Infloww's header title is unknown (the bundle has "Creator earnings overview", #13); it lists the select as "Net earnings" / "Gross earnings" (the bundle lists Gross first, #20); it calls Employee sales a bar chart (a daily line, #81); it omits Scheduled hours (#86); it marks the My shifts and clocked-in titles as guessed (the bundle has "My shifts" and "Current clocked-in employees", #65, #75); its layout line ends with "the team cards and the creators table" (the bundle has no creators table; the team cards sit in the bottom box beside the employee charts, #64). Its "UTC-10:00" is one instance of #16. The bundle values above stand.
- Version drift: the bundle's display version is 5.7.20 (`VITE_DISPLAY_VERSION`, index.9f50f370.js @29651); the Clone's sidebar footer reads "Version 5.7.14". The footer is shell chrome shared by every Clone page, so it is not a Dashboard fix.
- The earnings select's text and padding (#21) are antd's Select defaults: the page's `ConfigProvider` overrides only the font family (index.9f50f370.js @10939119), and the seed's `sizeUnit:4,sizeStep:4` (vendor.bab480ce.js @230767) make `sizeSM` `t*(r-1)` 12px (vendor.bab480ce.js @229487), which `paddingSM:i.sizeSM` (vendor.bab480ce.js @242867) passes to the select's `paddingSM-1`, so 11px.
- `_shared/infloww-rea.js` check at 390x844: every one of the 54 Clone pages that load it was opened with off-host requests aborted, and each element's box and 13 computed styles were dumped. Two runs of the working tree match (0 of 54 differ); the working tree against a control that swaps in only HEAD's infloww-rea.js differs on `dashboard.html` alone; HEAD against the working tree differs on `dashboard.html` alone. On the Dashboard nothing inside `.main` passes the 390px edge outside a scroll box. The harness was throwaway, under /tmp.
- Rendered-only values: none, the capture is static.
