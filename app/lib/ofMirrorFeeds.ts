"use client";

/**
 * Real rows on the OF mirror's feed pages (ofMirrorData's Parts home, promotions, events, posts, profileMedia, bookmarks,
 * listPosts, queue and notifications; its applyData draws them, useOfData fetches them). Home shows the home feed's posts, the
 * Creator's promotions on offer and the next scheduled events. My profile (and its state pages) shows the Creator's own wall posts in
 * OF's captured post row, read by the Creator's OnlyFans id from the "who am I" query. Its Media tab shows one grid
 * tile per photo or video post. All bookmarks shows the bookmarked posts, each with its own author, in My profile's
 * post row borrowed from its capture (TEMPLATES); a list's Posts tab its users' posts the same way. The queue's month pages mark the shown month's scheduled posts,
 * messages and streams of the tabs selected (none: all) on the calendar's days, and list the selected day's in the right
 * column (the list view: the month's, by day); its saved-for-later pages the saved-for-later posts and messages, all in
 * OF's agenda markup and the Agency's time zone. Every notifications tab lists the Creator's notifications of its
 * type in the tab's own plain row, and its tab bar shows the Creator's unread counts. Streaming's dashboard lists the
 * Creator's past live streams. Home's story strip gets a tile per creator with stories after its own "Add to story" (applyStories). Statements' Earnings tab lists the Creator's
 * earning transactions in its own table rows, its Payouts tab the payout requests in its own rows, and its Referrals
 * tab the referral payouts in the Payouts tab's rows borrowed from its capture.
 * The code lives in leaves (ofMirrorFeeds{Shared,Posts,Strip,Schedule,Notifications,Statements}, on ofMirrorDom);
 * this module only re-exports them, so its importers read every name from here as before.
 */

export { isSavedForLater, QUEUE, queueActions, TEMPLATES, type MirrorPost, type Month, type QueueActions, type QueueItem, type QueueKind, type Template } from "@/lib/ofMirrorFeedsShared";
export { applyColumnPosts, applyFeedStatus, applyHome, applyPosts, applyProfileMedia, COLUMN_FEED, feedTime, type ColumnPosts } from "@/lib/ofMirrorFeedsPosts";
export { allWatched, applyPromotions, applyStories, onOffer, promotionTitle, storyItems, stripStreams, stripUsers, type FeedStream, type Promotion, type StoryEntry, type StoryUser, type StripExtras } from "@/lib/ofMirrorFeedsStrip";
export { applyEvents, applyQueue, dayBars, dayCounts, eventsRoute, fromWallClock, QUEUE_CHANGE, QUEUE_TABS, queueDay, queueMonth, queueTypes, sflCard, upcoming, useAgencyZone, wallClock, type DayBar } from "@/lib/ofMirrorFeedsSchedule";
export { applyNotificationCounts, applyNotifications, applyNotificationsStatus, NOTIFICATION_COUNTS, NOTIFICATIONS, notificationText, type MirrorNotification, type NotificationCounts } from "@/lib/ofMirrorFeedsNotifications";
export { applyPastStreams, applyPayouts, applyStatementsStatus, applyTransactions, ofMoney, zoneNote, type MorePages, type PastStream, type Payout, type Transaction } from "@/lib/ofMirrorFeedsStatements";
