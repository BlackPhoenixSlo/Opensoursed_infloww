# Layout capture — growth-smart-messages

Bundle: ~/Downloads/infloww-remote-web/, entry `index.9f50f370.js`
Captured: 2026-10-17 at repo `d3890c68`
Method: static — REA's web tools (inspect_web_page, capture_web_screenshot, analyze_web_bundle) watch the page passively and cannot abort a request, and `index.html` asks off-host for fonts and the Cookiebot script, so the page was not rendered; REA's JavaScript application map plus `grep -boF` and byte-offset reads stand in
Reproduce:
```sh
B=~/Downloads/infloww-remote-web; S=/tmp/infloww-serve; J=$B/index.9f50f370.js; C=$B/index.9fc9db54.css
# Serve tree (read-only symlinks, outside the bundle), started from /tmp, checked for a 200, then stopped:
mkdir -p $S/35676908170/assets && ln -sf $B/index.html $S/index.html
for f in $B/*; do ln -sf "$f" $S/35676908170/assets/; done
cd /tmp && python3 -I -m http.server --bind 127.0.0.1 3401 --directory $S
# REA (MCP): mcp__rea__analyze_javascript_application input_path=$B format=directory detail=summary
#   integrity_policy=record-and-continue max_heap_mb=4096 (21 JS files parsed; the entry's semantic pass hit its budget)
# Anchors, each printed as <offset>:<match>:
grep -boF 'path:"/admin/growth/smart-message"' $J
grep -boF -e 'function SmartMessage(' -e 'function SmartMessage$1(' -e 'var MessageSendTitle' -e 'var TrackPageViewTitle$1' $J
grep -boF -e 'changeSendType({parentTab:MessageSendType.Mass' -e 'var tabList' -e 'var PriorityStatus' -e 'var OfMassMessage' $J
grep -boF -e 'var AutoMessage' -e 'var AutoStatusTypes' -e 'var Triggers' -e 'var SmartMessageAutoRulesType' $J
grep -boF -e 'var massMsgList' -e 'var automatedMsgList' -e 'xTitle:"Create message"' $J
grep -boF -e 'function hasAutoUnSend' -e 'function Unsend$1' -e '"Auto-unsend"' -e '"Auto unsend settings"' $J
grep -boF -e '_tab-wrap_' -e '_mass-message-wrap_' -e '_tabs_1osp0_' -e '_filter-bot_' -e '_auto-message-scheduled_' $C
grep -boF -e '--tc-T1:' -e '--tc-T3:' -e '--tc-B-nav:' -e '--tc-L1:' -e '--tc-M1:' -e '--tc-A1:' -e '--tc-W1:' $C
# Every label: grep -boF '"<label>"' $J, then cite the match offset + 1 (the first byte inside the quote).
# Any cited offset reads back with: dd if=$J bs=1 skip=<offset> count=80 2>/dev/null
# Every Items and Triggers offset, checked at once (exit 0, 0 misses): cd /tmp && python3 -I <repo>/.scratch/infloww-parity-round-2/verify-offsets.py <repo>/docs/infloww-layouts/growth-smart-messages.md
# Auto delete search, every line prints nothing:
for s in 'Auto delete' 'auto delete' 'Auto-delete' 'auto-delete' 'autoDelete' 'AutoDelete' 'Delete after' 'delete after' 'Unsend after' 'unsend after'; do grep -lF -- "$s" $B/*; done
```
Clone: ui-redesign/infloww-exact/growth-smart-messages.html
Phase: 2 (Smart Messages ticket); 2b reads Mass messages placement · Matrix row: 3.5.1

## Component tree
- Route `/admin/growth/smart-message` renders `SmartMessage` (index.9f50f370.js @16915219)
  - Nav entry "Smart Messages", page title "Smart Messages List" (index.9f50f370.js @10715967; index.9f50f370.js @10716029)
  - `SmartMessage`: picks the default tabs, header creator selector, OF notifications modal (index.9f50f370.js @16318808)
    - `MessageReport` (`withFonts(SmartMessage$1)`): the tab frame (index.9f50f370.js @16243566)
      - Parent tabs: Automated Messages, Mass Messages (index.9f50f370.js @16247564; index.9f50f370.js @16247766)
      - Tab bar right box: Learn, New Message (index.9f50f370.js @16246052; index.9f50f370.js @16246231)
      - Automated Messages tab: `AutoMessage` (index.9f50f370.js @16315002)
        - Filter bar (index.9f50f370.js @16287546)
        - Table, 14 columns (index.9f50f370.js @16296530)
        - Empty state; Cancel message modal (index.9f50f370.js @16304021; index.9f50f370.js @16304185)
      - Mass Messages tab: `OfMassMessage` (index.9f50f370.js @16200229)
        - Child-tab pills: Priority mass messages, OF mass messages (index.9f50f370.js @15733643)
        - Filter bar (index.9f50f370.js @15751281)
        - Table, 11 base columns, per-child extras (index.9f50f370.js @16207678)
        - Empty state (index.9f50f370.js @16171890)
  - Create message pop-up (New Message): `XModal` (index.9f50f370.js @14716722)
    - Start from scratch (index.9f50f370.js @14715428)
    - Mass messages section: `massMsgList` (index.9f50f370.js @14707943)
    - Automated messages section: `automatedMsgList`, the Triggers (index.9f50f370.js @14708609)
  - Message editor: Auto-unsend button and its modal, not on OF mass messages (index.9f50f370.js @14979383; index.9f50f370.js @14776278)

## Items
| ID | Kind | Element | Value | Source |
|---|---|---|---|---|
| growth-smart-messages#1 | layout | Route | `/admin/growth/smart-message` renders `SmartMessage` | index.9f50f370.js @16915219 |
| growth-smart-messages#2 | label | Nav entry | Smart Messages | index.9f50f370.js @10715967 |
| growth-smart-messages#3 | label | Page title | Smart Messages List | index.9f50f370.js @10716029 |
| growth-smart-messages#4 | filter | Header creator selector | `CreatorSelect`, right of the title | index.9f50f370.js @16322254 |
| growth-smart-messages#5 | tab | Parent tab 1 | "Automated Messages", rendered as `MessageSendTitle[MessageSendType.AutoMessage]` | index.9f50f370.js @14654444; index.9f50f370.js @16247564 |
| growth-smart-messages#6 | tab | Parent tab 2 | "Mass Messages", rendered as `MessageSendTitle[MessageSendType.Mass]` | index.9f50f370.js @14654487; index.9f50f370.js @16247766 |
| growth-smart-messages#7 | tab | Default parent tab | `MessageSendType.AutoMessage` (Automated Messages) when the user holds `Messages_AutoMessageStatistics`, else `MessageSendType.Mass` (Mass Messages) | index.9f50f370.js @16319752 |
| growth-smart-messages#8 | spacing | Tab bar side padding | 24px (`padding:0 24px`) | index.9fc9db54.css @4873440 |
| growth-smart-messages#9 | colour | Tab bar background | #FFFFFF (`--tc-B-nav`) | index.9fc9db54.css @4873094; index.9fc9db54.css @457914 |
| growth-smart-messages#10 | spacing | Page frame top-left radius | 16px | index.9fc9db54.css @4873658 |
| growth-smart-messages#11 | button | Tab bar right: link | Learn | index.9f50f370.js @16246052 |
| growth-smart-messages#12 | colour | Learn text | #3467ff (`--tc-M1`) | index.9fc9db54.css @4874139; index.9fc9db54.css @458249 |
| growth-smart-messages#13 | spacing | Learn font size | 14px, weight 500 | index.9fc9db54.css @4874176 |
| growth-smart-messages#14 | spacing | Learn icon gap | 4px | index.9fc9db54.css @4874322 |
| growth-smart-messages#15 | button | Tab bar right: primary | New Message | index.9f50f370.js @16246231 |
| growth-smart-messages#16 | spacing | New Message left margin | 16px | index.9fc9db54.css @4874431 |
| growth-smart-messages#17 | spacing | Right box inset | 24px (`right:24px`) | index.9fc9db54.css @4874050 |
| growth-smart-messages#18 | layout | Right box top | `-40px` or `8px`, by a layout flag | index.9f50f370.js @16245772 |
| growth-smart-messages#19 | label | Send type: automated | Smart Message - Automated Message | index.9f50f370.js @15735387 |
| growth-smart-messages#20 | label | Send type: priority mass | Smart Message - Priority Mass Message | index.9f50f370.js @15735444 |
| growth-smart-messages#21 | label | Send type: OF mass | Smart Message - OF Mass Message | index.9f50f370.js @15735504 |
| growth-smart-messages#22 | layout | Send type enum | `PMM` 1, `OF` 2, `AutoMessage` 3, `Mass` 30 | index.9f50f370.js @14438199 |
| growth-smart-messages#23 | spacing | Automated tab body padding | 16px 24px 24px | index.9fc9db54.css @5850068 |
| growth-smart-messages#24 | filter | Automated search | Search message, 320px | index.9f50f370.js @16287546; index.9f50f370.js @16287761 |
| growth-smart-messages#25 | spacing | Automated search right margin | 16px | index.9fc9db54.css @5850194 |
| growth-smart-messages#26 | spacing | Search radius | 8px | index.9fc9db54.css @5850762 |
| growth-smart-messages#27 | filter | Automated Status | Status:, 212px | index.9f50f370.js @16287849; index.9f50f370.js @16288219 |
| growth-smart-messages#28 | label | Automated status values | Scheduled / Active / Completed / Canceled | index.9f50f370.js @16272625; index.9f50f370.js @16272655; index.9f50f370.js @16272682; index.9f50f370.js @16272712 |
| growth-smart-messages#29 | filter | Trigger | Trigger:, 212px | index.9f50f370.js @16288338; index.9f50f370.js @16288676 |
| growth-smart-messages#30 | filter | Sent to | Sent to:, 212px | index.9f50f370.js @16288782; index.9f50f370.js @16288830 |
| growth-smart-messages#31 | filter | Start date | Start date: | index.9f50f370.js @16289060 |
| growth-smart-messages#32 | filter | Date created | Date created:, label 90px | index.9f50f370.js @16289336; index.9f50f370.js @16289312 |
| growth-smart-messages#33 | filter | Created by | Created by:, label 80px, select 212px | index.9f50f370.js @16289614; index.9f50f370.js @16289590; index.9f50f370.js @16289665 |
| growth-smart-messages#34 | spacing | Automated filter field margins | 16px below, 40px right | index.9fc9db54.css @5850903; index.9fc9db54.css @5850954 |
| growth-smart-messages#35 | spacing | Automated filter label | 70px wide, 4px right margin | index.9fc9db54.css @5851057; index.9fc9db54.css @5851068 |
| growth-smart-messages#36 | button | Automated filter | Reset | index.9f50f370.js @16289890 |
| growth-smart-messages#37 | button | Automated filter | Search | index.9f50f370.js @16290000 |
| growth-smart-messages#38 | spacing | Automated filter button gap | 8px | index.9fc9db54.css @5851151 |
| growth-smart-messages#39 | column | Automated column 1 | Messages, 390px | index.9f50f370.js @16296530 |
| growth-smart-messages#40 | column | Automated column 2 | Status, 230px | index.9f50f370.js @16297887 |
| growth-smart-messages#41 | column | Automated column 3 | Trigger, 160px | index.9f50f370.js @16298195 |
| growth-smart-messages#42 | column | Automated column 4 | Sent, 160px | index.9f50f370.js @16298301 |
| growth-smart-messages#43 | column | Automated column 5 | Purchased, 140px | index.9f50f370.js @16298418 |
| growth-smart-messages#44 | column | Automated column 6 | Earnings, 140px | index.9f50f370.js @16298544 |
| growth-smart-messages#45 | column | Automated column 7 | Attachment(s), 240px | index.9f50f370.js @16299052 |
| growth-smart-messages#46 | column | Automated column 8 | Price, 180px | index.9f50f370.js @16300051 |
| growth-smart-messages#47 | column | Automated column 9 | Sent to, 140px | index.9f50f370.js @16300568 |
| growth-smart-messages#48 | column | Automated column 10 | Created by, 140px | index.9f50f370.js @16300970 |
| growth-smart-messages#49 | column | Automated column 11 | Start date, 140px | index.9f50f370.js @16301218 |
| growth-smart-messages#50 | column | Automated column 12 | End date, 140px | index.9f50f370.js @16301445 |
| growth-smart-messages#51 | column | Automated column 13 | Date created, 140px | index.9f50f370.js @16301606 |
| growth-smart-messages#52 | column | Automated column 14 | Actions, 100px | index.9f50f370.js @16302024 |
| growth-smart-messages#53 | empty state | Automated list empty | No Data | index.9f50f370.js @16304021 |
| growth-smart-messages#54 | label | Cancel modal | Cancel message / Proceed with cancellation / The selected smart message will no longer be sent. | index.9f50f370.js @16304185; index.9f50f370.js @16304209; index.9f50f370.js @16304266 |
| growth-smart-messages#55 | spacing | Mass tab body padding | 16px 24px 24px | index.9fc9db54.css @5014299 |
| growth-smart-messages#56 | tab | Mass child tab 1 | Priority mass messages | index.9f50f370.js @15733662 |
| growth-smart-messages#57 | tab | Mass child tab 2 | OF mass messages | index.9f50f370.js @15733719 |
| growth-smart-messages#58 | tab | Default child tab | `MessageSendType.PMM` (Priority mass messages) when the user holds `Messages_PriorityMassMessageStatistics`, else `MessageSendType.OF` (OF mass messages); `MessageSendType.UnSelected` while the parent default is `MessageSendType.AutoMessage` | index.9f50f370.js @16320053 |
| growth-smart-messages#59 | spacing | Child pill height | 28px | index.9fc9db54.css @5014474 |
| growth-smart-messages#60 | spacing | Child pill side padding | 16px (`padding:0 16px`) | index.9fc9db54.css @5014503 |
| growth-smart-messages#61 | spacing | Child pill radius | 50px | index.9fc9db54.css @5014582 |
| growth-smart-messages#62 | spacing | Child pill gap | 16px (`margin-right`) | index.9fc9db54.css @5014601 |
| growth-smart-messages#63 | colour | Child pill border | #e6e6e6 (`--tc-L1`), 1px solid | index.9fc9db54.css @5014537; index.9fc9db54.css @458232 |
| growth-smart-messages#64 | colour | Child pill text | #151515 (`--tc-T1`) | index.9fc9db54.css @5014518; index.9fc9db54.css @457616 |
| growth-smart-messages#65 | colour | Active child pill | #3467ff (`--tc-M1`) background, #fff text, no border | index.9fc9db54.css @5014699; index.9fc9db54.css @5014688; index.9fc9db54.css @458249 |
| growth-smart-messages#66 | filter | Mass search | Search for message, 230px | index.9f50f370.js @15751281; index.9f50f370.js @15751531 |
| growth-smart-messages#67 | spacing | Mass search radius | 8px | index.9fc9db54.css @5015538 |
| growth-smart-messages#68 | filter | Mass Status (priority only) | "Status:", 212px, in the group shown when `!==MessageSendType.OF` | index.9f50f370.js @15751589; index.9f50f370.js @15751684; index.9f50f370.js @15752183 |
| growth-smart-messages#69 | label | Priority status values | Scheduled / Sending / Completed / Canceled | index.9f50f370.js @15733913; index.9f50f370.js @15733943; index.9f50f370.js @15733971; index.9f50f370.js @15734001 |
| growth-smart-messages#70 | label | OF status values | Sent / Unsent | index.9f50f370.js @15734045; index.9f50f370.js @15734073 |
| growth-smart-messages#71 | filter | Mass Sender (priority only) | "Sender:", in the group shown when `!==MessageSendType.OF` | index.9f50f370.js @15751589; index.9f50f370.js @15752258 |
| growth-smart-messages#72 | filter | Mass Price (priority only) | "Price:" "$" (60px) "-" "$" (60px), in the group shown when `!==MessageSendType.OF` | index.9f50f370.js @15751589; index.9f50f370.js @15752484; index.9f50f370.js @15752507; index.9f50f370.js @15752758; index.9f50f370.js @15752782 |
| growth-smart-messages#73 | filter | Sending Date | Sending Date: | index.9f50f370.js @15753149 |
| growth-smart-messages#74 | spacing | Mass filter field margins | 12px left and right, 16px top | index.9fc9db54.css @5015700; index.9fc9db54.css @5015717 |
| growth-smart-messages#75 | spacing | Mass filter label gap | 8px | index.9fc9db54.css @5015817 |
| growth-smart-messages#76 | button | Mass filter | Reset | index.9f50f370.js @15753442 |
| growth-smart-messages#77 | button | Mass filter | Search | index.9f50f370.js @15753553 |
| growth-smart-messages#78 | spacing | Mass filter button gap | 8px | index.9fc9db54.css @5015883 |
| growth-smart-messages#79 | button | Mass filter, OF child only | Export | index.9f50f370.js @15753704 |
| growth-smart-messages#80 | column | Mass column 1 | Message, 250px | index.9f50f370.js @16207678 |
| growth-smart-messages#81 | column | Mass column 2 | Sent date & time, 300px | index.9f50f370.js @16208370 |
| growth-smart-messages#82 | column | Mass column 3 | Sender, 120px | index.9f50f370.js @16208801 |
| growth-smart-messages#83 | column | Mass column 4 | Attachment, 210px | index.9f50f370.js @16209103 |
| growth-smart-messages#84 | column | Mass column 5 | Status, 230px | index.9f50f370.js @16210077 |
| growth-smart-messages#85 | column | Mass column 6 | Price, 110px | index.9f50f370.js @16210623 |
| growth-smart-messages#86 | column | Mass column 7 | Sent, 110px | index.9f50f370.js @16211153 |
| growth-smart-messages#87 | column | Mass column 8 | Viewed, 110px | index.9f50f370.js @16211442 |
| growth-smart-messages#88 | column | Mass column 9 | Purchased, 110px | index.9f50f370.js @16211541 |
| growth-smart-messages#89 | column | Mass column 10 | Earnings, 110px | index.9f50f370.js @16212228 |
| growth-smart-messages#90 | column | Mass column 11 | Withdrawn by, 150px | index.9f50f370.js @16212514 |
| growth-smart-messages#91 | column | Priority list | drops "Viewed" | index.9f50f370.js @16212969 |
| growth-smart-messages#92 | column | Priority list, last | Actions, 80px | index.9f50f370.js @16204276 |
| growth-smart-messages#93 | column | OF list, after the base 11 | Withdrawn date & time, 220px | index.9f50f370.js @16204496 |
| growth-smart-messages#94 | column | OF list, last | Actions, 80px | index.9f50f370.js @16204820 |
| growth-smart-messages#95 | label | Withdrawn by, automatic unsend | Auto | index.9f50f370.js @16212668 |
| growth-smart-messages#96 | empty state | Mass list empty | No Data | index.9f50f370.js @16171890 |
| growth-smart-messages#97 | empty state | Mass list empty for a period | There are no more messages for the selected time period | index.9f50f370.js @16171832 |
| growth-smart-messages#98 | spacing | Status pill | 16px radius, 2px 8px padding | index.9fc9db54.css @4779138; index.9fc9db54.css @4779157 |
| growth-smart-messages#99 | colour | Scheduled pill | #e5ecf6 background, #999999 (`--tc-T3`) text | index.9fc9db54.css @4779243; index.9fc9db54.css @4779268; index.9fc9db54.css @457650 |
| growth-smart-messages#100 | colour | Active pill | #dde7ff background, #3467ff (`--tc-M1`) text | index.9fc9db54.css @4779425; index.9fc9db54.css @4779450 |
| growth-smart-messages#101 | colour | Completed pill | #ecfdf3 background, #2ad4ac (`--tc-A1`) text | index.9fc9db54.css @4779610; index.9fc9db54.css @4779635; index.9fc9db54.css @458382 |
| growth-smart-messages#102 | colour | Canceled pill | #fff0e5 background, #ffa15f (`--tc-W1`) text | index.9fc9db54.css @4779796; index.9fc9db54.css @4779821; index.9fc9db54.css @458537 |
| growth-smart-messages#103 | label | Pop-up title | Create message, 722px wide | index.9f50f370.js @14716730; index.9f50f370.js @14716712 |
| growth-smart-messages#104 | label | Pop-up first card | Start from scratch | index.9f50f370.js @14715428 |
| growth-smart-messages#105 | label | Pop-up template line | or use one of the templates below | index.9f50f370.js @14715455 |
| growth-smart-messages#106 | label | Pop-up section 1 | Mass messages | index.9f50f370.js @14717209 |
| growth-smart-messages#107 | label | Mass card 1 | Priority mass message / Sent to priority inbox | index.9f50f370.js @14707968; index.9f50f370.js @14707997 |
| growth-smart-messages#108 | label | Mass card 2 | OF mass message / Sent to general inbox | index.9f50f370.js @14708331; index.9f50f370.js @14708354 |
| growth-smart-messages#109 | label | Pop-up section 2 | Automated messages | index.9f50f370.js @14717265 |
| growth-smart-messages#110 | button | Pop-up confirm | Next | index.9f50f370.js @14716869 |
| growth-smart-messages#111 | button | Pop-up cancel | Cancel | index.9f50f370.js @14716958 |
| growth-smart-messages#112 | label | Pop-up notice | Scheduling messages for fans who come online is temporarily disabled. | index.9f50f370.js @14711380 |
| growth-smart-messages#113 | label | OF notifications modal | You need to turn on the OF notifications so Infloww can track fan actions. / Turn on | index.9f50f370.js @16323404; index.9f50f370.js @16322883 |
| growth-smart-messages#114 | button | Message editor, not OF | "Auto-unsend", shown when `hasAutoUnSend` (`S!==MessageSendType.OF`) | index.9f50f370.js @14981346; index.9f50f370.js @14776278 |
| growth-smart-messages#115 | label | Auto-unsend modal | Auto unsend settings, 580px | index.9f50f370.js @14981410 |

## Clone fixes
| Item | Clone had | Bundle has | Clone edit |
|---|---|---|---|
| growth-smart-messages#8 | tab bar padding `0 28px` | 24px | `.gtabs{padding:0 24px}` |
| growth-smart-messages#23 | body padding `24px 28px` | 16px 24px 24px | `.gbody{padding:16px 88px 24px 24px}` (the 88px right gutter for the help bubble stays) |
| growth-smart-messages#24 | search 440px | 320px | search box 320px |
| growth-smart-messages#25 | flex gap 22px | 16px right margin | `#sm-fbar-auto>.inp:first-child{margin-right:16px}` |
| growth-smart-messages#27 | Status 200px | 212px | Status select 212px |
| growth-smart-messages#28 | Running / Off / Last run OK / Last run errored / Never run / Job queued | Scheduled / Active / Completed / Canceled | options Scheduled, Active, Completed, Canceled, with Scheduled and Completed disabled as not wired (no rule state maps onto them); the run-health options move under an "Inflowwww extra" group; rows read Active / Canceled |
| growth-smart-messages#29 | Trigger 240px | 212px | Trigger select 212px |
| growth-smart-messages#30 | Sent to 190px | 212px | Sent to 212px |
| growth-smart-messages#32 | label auto width | 90px | Date created label 90px |
| growth-smart-messages#33 | label auto width, select 180px | 80px label, 212px select | Created by label 80px, select 212px |
| growth-smart-messages#34 | flex gap `16px 22px`, 26px below the bar | 16px below, 40px right | `#sm-fbar-auto>*{margin:0 40px 16px 0}` |
| growth-smart-messages#35 | label gap 12px | 70px label, 4px | `.fld` gap 4px, label 70px |
| growth-smart-messages#38 | flex gap 22px | 8px | buttons `margin-right:8px` |
| growth-smart-messages#39 | 6 columns: Messages, Status, Trigger, Sent, Purchased, Actions | 14 columns, items #39 to #52 | the 14 columns at the bundle widths in a horizontal scroller; Purchased shows "--", the revenue moves to Earnings, Date created takes the old "created" line |
| growth-smart-messages#56 | no child tabs | Priority mass messages / OF mass messages pills | child-tab strip on the Mass Messages tab, Priority first and on by default |
| growth-smart-messages#59 | none | 28px, 0 16px, 50px radius, 16px gap, 1px border | `.sm-ctab` with those values, Clone palette |
| growth-smart-messages#66 | the Automated filter bar on both tabs | its own Mass bar: Search for message 230px, Status, Sender and Price (priority only), Sending Date, Reset, Search, Export (OF) | `#sm-fbar-mass` with those fields, shown on the Mass Messages tab |
| growth-smart-messages#74 | none | 12px sides, 16px top, 8px label gap, 8px button gap | `#sm-fbar-mass` margins and gaps |
| growth-smart-messages#80 | the Automated columns on both tabs | 11 base columns; Priority drops Viewed and ends in Actions; OF adds Withdrawn date & time | the page script swaps the header and cells per tab and child; Priority shows the empty state (nothing on the relay stores one) |

## Notes
- ASSUMPTION: colours are recorded but not applied. The bundle ships only a light `:root` palette (index.9fc9db54.css @457616 and a duplicate block near @460450) and the Clone is dark across every page, so a recolour would be a site-wide theme change outside one page's fixes (rung 4). Overturned if the owner wants the Clone in the bundle's light palette.
- ASSUMPTION: the Clone's Actions columns stay 160px, against the bundle's 100px (#52) and 80px (#92, #94): the Clone rows carry five working buttons (Disable, Run now, History, Edit, Delete) where the bundle opens a menu (rung 5). Overturned if Phase 2 moves the row actions into a menu.
- The Mass Sender select carries no width in the bundle (index.9f50f370.js @15752258); the Clone's 212px matches its Status neighbour.
- Inventory (`docs/infloww-screens.md` §3.5.1) disagreements: it lists the Automated columns without Earnings, Attachment(s), Price, End date and Date created, and does not mention the Mass child pills or the per-child Mass columns; the bundle values above stand.
- Citation error, not version drift: ADR-0014's first text (commit `fda942e0`) cited the send-type labels at `index.9f50f370.js` @15735111, the same entry chunk this capture reads, and spec user story 27 and this ticket still copy that offset. It is inside `_toPrimitive$B`, 165 bytes before `var TrackPageViewTitle$1` (@15735276). The labels start at @15735387, @15735444 and @15735504 (#19 to #21). The amended ADR-0014 no longer cites @15735111, and its other offsets re-observe exactly.
- The editor rules write the apostrophe as the escape `\u2019` (index.9f50f370.js @14775371); the Triggers show it as the character it renders.
- The Automated Trigger filter fills its options from the API (`/message/smart-message/triggers`, index.9f50f370.js @14588783), so its option list is not in the bundle; the Triggers below are the pop-up cards, the editor rules and the list's Trigger column labels.
- The OF list's Actions cell (#94) opens a menu, not a button: `OFMMOperateMenu` (index.9f50f370.js @15685010) draws a 16px `SMore` trigger (@15685560) under an antd Dropdown placed `topRight` with an arrow (@15685391); its items are "Unsent" (@16207260, greyed and not clickable @16207438 when OnlyFans no longer allows the unsend) with the tooltip "Unsend OF mass message" (@16206965), then "Duplicate" (@16206736) for a role with `createOfMassMessage`. The list's head is antd's `size:"middle"` head (@16171489): in the bundle shot (`/tmp/route-walk/bundle-growth-smart-messages-mass.png`) it is 46px tall, filled #fafbff, ruled off by a 1px #e6e6e6 line, with a 1px by 22px #e6e6e6 divider after each column. The empty row is `Abnormal.Empty` (index.9f50f370.js @4899081: a 120px by 90px illustration over a 14px line) with `margin:220px 0` (index.9fc9db54.css @5017878) in the 12px-padded cell; while loading, the cell holds a 420px box instead (index.9f50f370.js @16171771).
- Rendered-only values: none, the capture is static. The Clone's New Message keeps its own rule creator, not the Create message pop-up (#103 to #112); that pop-up is Phase 2's to build.

## Triggers
| ID | Trigger (verbatim) | Source |
|---|---|---|
| growth-smart-messages#116 | card "Nudge", "Messages fans when they come online", tag "Popular"; rule "Fan comes online"; list label "Nudge" | index.9f50f370.js @14708639; index.9f50f370.js @14708652; index.9f50f370.js @14708698; index.9f50f370.js @14775121; index.9f50f370.js @16272751 |
| growth-smart-messages#117 | card "Subscriber welcome", "Greet fans when they subscribe"; rule "Fan subscribes for the first time"; list label "Delayed welcome" | index.9f50f370.js @14708892; index.9f50f370.js @14708918; index.9f50f370.js @14775195; index.9f50f370.js @16272761 |
| growth-smart-messages#118 | card "Purchases", "Follow up with fans who purchased a PPV"; rule "Fan purchases PPV"; list label "Purchased" | index.9f50f370.js @14709120; index.9f50f370.js @14709137; index.9f50f370.js @14775294; index.9f50f370.js @16272781 |
| growth-smart-messages#119 | card "Expiring soon", " Message fans when their subscription is about to expire"; rule "Fan’s subscription near expiry"; list label "Nearing expiry" | index.9f50f370.js @14709348; index.9f50f370.js @14709369; index.9f50f370.js @14775371; index.9f50f370.js @16272813 |
| growth-smart-messages#120 | card "Expired", "Messages fans whose subscription has expired"; rule "Fan’s subscription expired"; list label "Expired" | index.9f50f370.js @14709603; index.9f50f370.js @14709618; index.9f50f370.js @14775467; index.9f50f370.js @16272832 |
| growth-smart-messages#121 | card "Resubscribe", "Greet fans when they resubscribe"; rule "Fan resubscribes after a break"; list label "Resubscribe" | index.9f50f370.js @14709845; index.9f50f370.js @14709864; index.9f50f370.js @14775565; index.9f50f370.js @16272844 |
| growth-smart-messages#122 | card "Birthday greetings", "Wish fans happy birthday"; rule "Fan’s birthday"; list label "Birthday" | index.9f50f370.js @14710064; index.9f50f370.js @14710090; index.9f50f370.js @14775654; index.9f50f370.js @16272860 |
| growth-smart-messages#123 | list label "Not Purchased" only; no key 4 in `SmartMessageAutoRulesType` | index.9f50f370.js @16272795; index.9f50f370.js @14441552 |

Order is the pop-up's `automatedMsgList` (index.9f50f370.js @14708609). The rule enum `SmartMessageAutoRulesType` (index.9f50f370.js @14441552) numbers them 1, 2, 3, 5, 6, 7, 8; key 4 has no card and no editor rule, only the list label "Not Purchased" in `Triggers` (index.9f50f370.js @16272738).
ASSUMPTION: "Not Purchased" (#123) is a legacy Trigger the list can still label but the pop-up no longer offers (rung 4, from the gap at key 4). Overturned by a bundle path that creates a key-4 message.

## Mass messages placement
Automated mass messages live in the Smart Messages page, in its second parent tab, **Mass Messages**. This agrees with ADR-0014's amended decision; nothing points at My Automations.
- Parent tab labels: `var MessageSendTitle` (index.9f50f370.js @14654355) maps AutoMessage to "Automated Messages" (@14654444) and Mass to "Mass Messages" (@14654487); `SmartMessage$1` renders them as the two tabs (index.9f50f370.js @16247564; index.9f50f370.js @16247766). Automated Messages opens by default when permitted (index.9f50f370.js @16319752).
- Inside the Mass Messages tab, the child pills `var tabList` (index.9f50f370.js @15733643) offer "Priority mass messages" and "OF mass messages"; a pill click calls `changeSendType({parentTab:MessageSendType.Mass` (index.9f50f370.js @15747892), so both kinds stay under the Mass parent tab.
- The Create message pop-up (`xTitle:"Create message"`, index.9f50f370.js @14716722) opens from the tab bar's New Message and holds both kinds: section "Mass messages" (@14717209) with `var massMsgList` (index.9f50f370.js @14707943: Priority mass message, OF mass message) and section "Automated messages" (@14717265) with the seven per-fan Triggers.
- Send types (index.9f50f370.js @14438199): PMM 1 and OF 2 are the Mass children, AutoMessage 3 and Mass 30 the parent tabs.

Auto delete: not found. No bundle file holds any of these strings (each command printed nothing):
`grep -lF -- 'Auto delete' ~/Downloads/infloww-remote-web/*`, and the same for 'auto delete', 'Auto-delete', 'auto-delete', 'autoDelete', 'AutoDelete', 'Delete after', 'delete after', 'Unsend after', 'unsend after'.
Unsend after a time: found, as **Auto-unsend** in the message editor, per message.
- `function hasAutoUnSend` (index.9f50f370.js @14776278) is true for every send type but OF, and the editor shows `Unsend$1` only then (index.9f50f370.js @15013397). So Priority mass messages and Automated messages get it; OF mass messages do not, and the switch-to-OF warning (index.9f50f370.js @14792972) lists "Auto-unsend" (@14793224) among what OF loses.
- `function Unsend$1` (index.9f50f370.js @14979383): button "Auto-unsend" (@14981346) opens "Auto unsend settings" (@14981410, 580px) with "Unsend messages" (@14981830), "Retract free messages and locked PPV content" (@14981901) a set number of hours (0 to 24) and minutes (0 to 59) after it is sent, and "Stop message sequence" (@14982532).
- The Mass list's Withdrawn by column shows "Auto" for an automatic unsend (index.9f50f370.js @16212668).
