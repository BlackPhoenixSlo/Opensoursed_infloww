import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { HtmlBasePlugin } from "@11ty/eleventy";

const buckets = JSON.parse(readFileSync(new URL("./src/_data/buckets.json", import.meta.url), "utf8"));
const bucketIndex = new Map(buckets.map((bucket, i) => [bucket.tag, i]));
const bucketTagOf = (tags = []) => tags.find((tag) => bucketIndex.has(tag));
const bucketRank = (post) => bucketIndex.get(bucketTagOf(post.data.tags)) ?? buckets.length;
const topicOf = (post) => post.data.tags?.[1] ?? "";
function sortPosts(posts) {
  // All posts share one date, so sort by bucket then title to stay stable.
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

function pickFeatured(sorted) {
  return (
    sorted.find((post) => post.fileSlug === "onlyfans-for-beginners") ??
    sorted.find((post) => bucketTagOf(post.data.tags) !== "product") ??
    sorted[0]
  );
}

function startHerePosts(bucket, bucketPosts, count = 3) {
  const picked = (bucket.startHere ?? [])
    .map((slug) => bucketPosts.find((post) => post.fileSlug === slug))
    .filter(Boolean);
  const rest = bucketPosts.filter((post) => !picked.includes(post));
  return [...picked, ...rest].slice(0, count);
}

export default function (eleventyConfig) {
  eleventyConfig.addPlugin(HtmlBasePlugin);
  // GitHub Pages serves under /<repo>/ and the base plugin already prefixes root-relative URLs (not skipping ones that carry it), so `url` is a pass-through.
  eleventyConfig.addFilter("url", (url) => url);

  eleventyConfig.addPassthroughCopy({ public: "/" }, { filter: (path) => !path.endsWith("img/README.md") });
  eleventyConfig.addPassthroughCopy({ "src/main.js": "assets/main.js" });
  // The host caches /assets/* for a week: a hash in ?v= makes a changed stylesheet a new URL. A missing main.css fails `build`, only warns in dev.
  eleventyConfig.addGlobalData("assetVersion", () => {
    const hash = createHash("sha256");
    for (const file of ["./dist/assets/main.css", "./src/main.js"]) {
      try {
        hash.update(readFileSync(new URL(file, import.meta.url)));
      } catch (err) {
        if (process.env.ELEVENTY_RUN_MODE === "build") {
          throw new Error(`assetVersion: ${file} missing (run Tailwind before eleventy: pnpm build)`, { cause: err });
        }
        console.warn(`[assetVersion] ${file} missing: using a throwaway version (fine while dev starts)`);
        hash.update(String(Date.now()));
      }
    }
    return hash.digest("hex").slice(0, 10);
  });
  eleventyConfig.setServerOptions({ watch: ["dist/assets/*.css"] });

  const postIndex = (api) => sortPosts(api.getFilteredByGlob("src/blog/*.md"));
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
  eleventyConfig.addCollection("blogIndex", (api) => {
    const sorted = postIndex(api);
    const featured = pickFeatured(sorted);
    return sorted.filter((post) => post !== featured);
  });
  eleventyConfig.addCollection("bucketHubs", bucketGroups);
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

  eleventyConfig.addFilter("newestFirst", (items) => [...items].sort((a, b) => b.date - a.date));
  eleventyConfig.addFilter("bucketFor", (tags) => buckets[bucketIndex.get(bucketTagOf(tags))]);
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
    pathPrefix: process.env.PATH_PREFIX || "/",
  };
}
