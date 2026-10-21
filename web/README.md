# Inflowwww site

The parody of infloww.com: it looks like their site and says the opposite. It is static: Eleventy 3 (Nunjucks and Markdown) plus the Tailwind v4 CLI. There is no client framework and no external requests.

Every page opens with a one-line strip at the top of the header: "Unofficial parody of infloww.com. Not affiliated with Infloww. The software is real; the jokes are ours." (phones get the short "Unofficial parody. Not affiliated with Infloww."). It lives in `src/_includes/header.njk`; keep it short, muted and without a close button. `base.njk` also ends every meta description, og description and twitter description with "Not affiliated with Infloww."; a description that already ends with that phrase has it folded in, not doubled.

## Commands

- Install: `pnpm -C web install`
- Dev: `pnpm -C web dev`. The Tailwind watcher and `eleventy --serve` run on http://localhost:8080.
- Build: `pnpm -C web build`, or `pnpm build:site` from the repo root. It writes `web/dist/`: Tailwind first (`dist/assets/main.css`), then Eleventy. Run `rm -rf web/dist` first if you deleted or renamed a page, or the old file stays in `dist/`.
- Preview: `pnpm -C web preview`. It serves `web/dist/` on http://127.0.0.1:4173 with `python3 -m http.server`.
- Sub-path build: `PATH_PREFIX=/openinflowwww/ pnpm -C web build`. Eleventy's HtmlBasePlugin adds the prefix to every root-relative `href`, `src` and `srcset` in the HTML, including plain Markdown links such as `[text](/blog/slug/)`. The `url` filter is a pass-through, so templates may keep using it without getting the prefix twice.

## Structure

```
web/
  eleventy.config.js   collections, filters, HtmlBasePlugin, pathPrefix
  og.svg               source of public/og.png (render command at the top of the file)
  public/              copied to the site root as-is (favicon, touch icon, og.png, img/)
  src/
    _data/site.json    name, url, repo (the one GitHub URL), captureDate (the one capture date), the Infloww URL,
                       appUrl (your running Inflowwww app; the header and hero Log in / Register links point at it)
    _data/buckets.json the nine blog buckets: tag, label, blurb, startHere (three slugs shown first on /blog/ and the tag page)
    _includes/         base.njk (head, header, footer), page, post, case-study, partials
    main.css           Tailwind entry and the theme (light, black on white, cream panels)
    main.js            copy buttons, the earnings slider, closing the header menus; copied to assets/main.js
    index.njk          landing page
    pricing.njk        the full price ladder
    blog.njk           /blog/, 24 posts per page
    blog-tag.njk       /blog/tag/<bucket>/, 20 posts per page
    blog/*.md          posts (blog/blog.json sets their layout and permalink)
    case-studies.njk   /case-studies/
    case-studies/*.md  case studies
    404.njk, sitemap.njk, robots.njk, feed.njk
```

## Adding a post

Create `web/src/blog/<their-slug>.md`. It is published at `/blog/<their-slug>/`. `src/blog/blog.json` sets `layout` and `permalink`, so leave both out. The byline, reading time and author box come from the layout.

```md
---
title: "Our title"
description: "One sentence for the card, the meta description and the feed."
date: 2026-10-12
tags: ["money", "taxes", "self-employment"]
parodyOf: "average-taxes-to-pay"
parodyTitle: "Do you have to pay taxes as an OnlyFans Creator?"
parodyDate: "Jul 19, 2024"
---

Markdown body. End with one "> **The pitch.** ..." box.
```

- `tags`: the first tag is the bucket, one of the tags in `src/_data/buckets.json` (`product`, `getting-started`, `money`, `chatting`, `content-ideas`, `promotion`, `platforms`, `agency`, `creator-life`). Only buckets get a `/blog/tag/<bucket>/` page; the other tags are free topics, shown as plain text. Add `straight: true` when the post is sincere advice; it swaps the Parody badge for a "Straight advice" label.
- `parodyOf`: their slug; the post links to infloww.com/blog/<slug>. `parodyTitle`: their title, verbatim. `parodyDate`: their visible date, verbatim, or `""` if there is none.
- `date` is our publish date and stays unquoted.
- Internal links can be plain root-relative Markdown links; the base plugin prefixes them.

Case studies work the same way in `web/src/case-studies/`, and they can also take an optional `stats` list of `{label, value}`. The voice and truth rules are in `docs/parody-voice.md`. Quotes from Infloww must come from `docs/infloww-landing-snapshot.md` or `docs/infloww-site-inventory.md`, with the capture date.

## Deploy

The live site, https://inflowwww.com, is not served by GitHub Pages. It is `web/dist`, built on the app's own server from a checkout of the public repo and served as static files by an nginx container behind the server's Traefik (app.inflowwww.com is the app on the same host). The build sets `url` and `appUrl` in `src/_data/site.json` to the deployment's site and app URLs in a throwaway copy (the tracked file is left alone), then runs `pnpm build`; nginx serves the new files as soon as they are written, with no restart.

### GitHub Pages (optional)

`.github/workflows/site.yml` builds with `PATH_PREFIX=/openinflowwww/` and deploys on every push to `main` that touches `web/`. It can also be run by hand. After the build it fails if any root-relative `href`, `src` or `srcset` in `web/dist` lacks the prefix. You only need to change one setting, once: **Settings > Pages > Build and deployment > Source = "GitHub Actions"**. The site is then served at https://your-org.github.io/openinflowwww/.

## Lighthouse

Lighthouse 13.5.0 (headless Chrome, `web/dist` served with `npx serve`, which gzips like GitHub Pages does, 2026-10-12 after fix wave 8): `/`, `/pricing/`, `/blog/` and `/openinflowwww-vs-infloww/` score 100 for Performance, Accessibility, Best Practices and SEO on desktop and mobile. Served without compression (`python3 -m http.server`) the mobile Performance of `/` and the comparison page reads 99, from the 51 KB stylesheet. `/404.html` scores 100/100/100 and 63 for SEO, because it is `noindex` on purpose.
