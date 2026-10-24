// Eleventy builds src/ into dist/. The Tailwind CLI writes dist/assets/main.css
// first (see package.json), so Eleventy only renders HTML and copies files.
import { readFileSync } from "node:fs";
import { HtmlBasePlugin } from "@11ty/eleventy";

// The nine blog buckets, in index order. Only these get /blog/tag/<tag>/ pages.
const buckets = JSON.parse(readFileSync(new URL("./src/_data/buckets.json", import.meta.url), "utf8"));
const bucketIndex = new Map(buckets.map((bucket, i) => [bucket.tag, i]));
// Writers put the bucket first in `tags`; take the first tag that is a bucket to be safe.
const bucketTagOf = (tags = []) => tags.find((tag) => bucketIndex.has(tag));
const bucketRank = (post) => bucketIndex.get(bucketTagOf(post.data.tags)) ?? buckets.length;
// The second tag names a post's series (taxes, reddit, fansly...).
const topicOf = (post) => post.data.tags?.[1] ?? "";
// All posts share one date, so the index sorts by bucket, then title, to stay stable; then each series
// moves up to its first title, so a bucket's tax posts sit together and prev/next walks them.
function sortPosts(posts) {
  const byTitle = [...posts].sort(
    (a, b) => bucketRank(a) - bucketRank(b) || a.data.title.localeCompare(b.data.title, "en"),
  );
  const seriesKey = (post) => `${bucketRank(post)} ${topicOf(post)}`;
  const firstAt = new Map();
  byTitle.forEach((post, i) => firstAt.has(seriesKey(post)) || firstAt.set(seriesKey(post), i));
  return byTitle
    .map((post, i) => ({ post, rank: firstAt.get(seriesKey(post)), i }))
    .sort((a, b) => a.rank - b.rank || a.i - b.i)
    .map(({ post }) => post);
}
const TAG_PAGE_SIZE = 20;

// One screenshot figure from public/img (sizes in public/img/README.md); the file name picks the srcset:
// `<screen>-combo.webp` 1440x900 with `-combo-720`, `<screen>-phone.webp` 390x844 with `-phone-780` for 2x,
// any other `<screen>.webp` 1280x800 with `-640`. Posts call it as {% shot "vault-pro.webp", "alt", "caption" %}.
// The output is one line, so Markdown passes it through as a single HTML block.
const escapeHtml = (text = "") =>
  String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
function shotFigure(file, alt, caption = "", figureClass = "") {
  const src = `/img/${file}`;
  const base = src.replace(/\.webp$/, "");
  const img = file.endsWith("-phone.webp")
    ? `<img class="shot mx-auto h-auto w-full max-w-56 rounded-[1.75rem]" src="${src}" srcset="${src} 1x, ${base}-780.webp 2x" width="390" height="844"`
    : file.endsWith("-combo.webp")
      ? `<img class="shot h-auto w-full" src="${src}" srcset="${base}-720.webp 720w, ${src} 1440w" sizes="(min-width: 768px) 720px, 100vw" width="1440" height="900"`
      : `<img class="shot h-auto w-full" src="${src}" srcset="${base}-640.webp 640w, ${src} 1280w" sizes="(min-width: 768px) 720px, 100vw" width="1280" height="800"`;
  const figcaption = caption ? `<figcaption class="mt-3 text-center text-sm text-muted">${escapeHtml(caption)}</figcaption>` : "";
  const cls = figureClass ? ` class="${escapeHtml(figureClass)}"` : "";
  return `<figure${cls}>${img} alt="${escapeHtml(alt)}" loading="lazy" decoding="async">${figcaption}</figure>`;
}

// The index's featured post: the beginners' guide, a general read for a newcomer; else the first
// post outside the Product bucket, so the blog never opens on our own docs; else the first post.
function pickFeatured(sorted) {
  return (
    sorted.find((post) => post.fileSlug === "onlyfans-for-beginners") ??
    sorted.find((post) => bucketTagOf(post.data.tags) !== "product") ??
    sorted[0]
  );
}

// A bucket's "Start here" posts: the slugs in buckets.json `startHere` that are still in the
// bucket, topped up from the bucket's first posts so a renamed or moved post never leaves a gap.
function startHerePosts(bucket, bucketPosts, count = 3) {
  const picked = (bucket.startHere ?? [])
    .map((slug) => bucketPosts.find((post) => post.fileSlug === slug))
    .filter(Boolean);
  const rest = bucketPosts.filter((post) => !picked.includes(post));
  return [...picked, ...rest].slice(0, count);
}

export default function (eleventyConfig) {
  // GitHub Pages serves the site under /<repo>/ (PATH_PREFIX). The base plugin adds that prefix to every
  // root-relative href, src and srcset in the HTML output, including plain Markdown links like
  // [text](/blog/slug/). It does not skip URLs that already carry the prefix, so the `url` filter is a
  // pass-through here, kept only so the 40+ templates that pipe through `| url` need no edit.
  // Absolute URLs (site.url, canonical, og, feed) are untouched.
  eleventyConfig.addPlugin(HtmlBasePlugin);
  eleventyConfig.addFilter("url", (url) => url);

  // public/img/README.md documents the screenshots; it is not part of the site.
  eleventyConfig.addPassthroughCopy({ public: "/" }, { filter: (path) => !path.endsWith("img/README.md") });
  eleventyConfig.addPassthroughCopy({ "src/main.js": "assets/main.js" });
  // `eleventy --serve` reloads when Tailwind rewrites the stylesheet.
  eleventyConfig.setServerOptions({ watch: ["dist/assets/*.css"] });

  const postIndex = (api) => sortPosts(api.getFilteredByGlob("src/blog/*.md"));
  // One entry per bucket that has posts, in bucket order: its posts and its "Start here" picks.
  // `own` is the posts filed in the bucket (prev/next and "More in" walk it, so they never leave it);
  // `posts` is own first, then posts filed elsewhere that carry its tag (tag pages and counts).
  const bucketGroups = (api) => {
    const sorted = postIndex(api);
    return buckets.flatMap((bucket) => {
      const tagged = sorted.filter((post) => (post.data.tags ?? []).includes(bucket.tag));
      const own = tagged.filter((post) => bucketTagOf(post.data.tags) === bucket.tag);
      const posts = [...own, ...tagged.filter((post) => !own.includes(post))];
      return posts.length ? [{ ...bucket, own, posts, startPosts: startHerePosts(bucket, posts) }] : [];
    });
  };
  eleventyConfig.addCollection("caseStudy", (api) => api.getFilteredByGlob("src/case-studies/*.md"));
  eleventyConfig.addCollection("postIndex", postIndex);
  eleventyConfig.addCollection("featuredPost", (api) => pickFeatured(postIndex(api)) ?? null);
  // The /blog/ grid: every post except the featured one, which sits above the grid.
  eleventyConfig.addCollection("blogIndex", (api) => {
    const sorted = postIndex(api);
    const featured = pickFeatured(sorted);
    return sorted.filter((post) => post !== featured);
  });
  // /blog/ category chips and "Start here" rows, and each post's prev/next and "More in".
  eleventyConfig.addCollection("bucketHubs", bucketGroups);
  // One entry per /blog/tag/<bucket>/ page, TAG_PAGE_SIZE posts each.
  eleventyConfig.addCollection("bucketPages", (api) =>
    bucketGroups(api).flatMap((group) => {
      const hrefs = Array.from(
        { length: Math.ceil(group.posts.length / TAG_PAGE_SIZE) },
        (_, i) => `/blog/tag/${group.tag}/${i ? `page/${i + 1}/` : ""}`,
      );
      return hrefs.map((href, i) => ({
        ...group,
        total: group.posts.length,
        posts: group.posts.slice(i * TAG_PAGE_SIZE, (i + 1) * TAG_PAGE_SIZE),
        pageNumber: i,
        hrefs,
        href,
      }));
    }),
  );

  // Newest first, without mutating the shared collection array (case studies; posts share one date).
  eleventyConfig.addFilter("newestFirst", (items) => [...items].sort((a, b) => b.date - a.date));
  eleventyConfig.addFilter("bucketFor", (tags) => buckets[bucketIndex.get(bucketTagOf(tags))]);
  // Up to `count` other posts from a bucket list, after the current post, same series first. When the
  // bucket is big enough, skip the previous and next posts, which the prev/next links already show.
  eleventyConfig.addFilter("moreInBucket", (items, url, count = 3) => {
    const i = items.findIndex((item) => item.url === url);
    const others = [...items.slice(i + 1), ...items.slice(0, Math.max(i, 0))];
    const shown = others.length >= count + 2 && i >= 0 ? [items[i - 1], items[i + 1]] : [];
    const candidates = others.filter((item) => !shown.includes(item));
    const topic = i >= 0 ? topicOf(items[i]) : "";
    const sameSeries = candidates.filter((item) => topic && topicOf(item) === topic);
    return [...sameSeries, ...candidates.filter((item) => !sameSeries.includes(item))].slice(0, count);
  });
  eleventyConfig.addShortcode("shot", shotFigure);
  eleventyConfig.addFilter("isoDate", (date) => date.toISOString().slice(0, 10));
  eleventyConfig.addFilter("rssDate", (date) => date.toUTCString());
  eleventyConfig.addFilter("readableDate", (date) =>
    date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }),
  );
  eleventyConfig.addFilter("readingTime", (html = "") => {
    const words = html.replace(/<[^>]+>/g, " ").split(/\s+/).filter(Boolean).length;
    return `${Math.max(1, Math.ceil(words / 200))} min read`;
  });

  return {
    dir: { input: "src", output: "dist", includes: "_includes", data: "_data" },
    templateFormats: ["njk", "md"],
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
    // GitHub Pages serves the project under /<repo>/; the workflow sets PATH_PREFIX.
    pathPrefix: process.env.PATH_PREFIX || "/",
  };
}
