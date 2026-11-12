document.addEventListener('DOMContentLoaded', () => {
    // Served under an app host's /p path: credit that site, not ofl.ink.
    const poweredBy = document.getElementById('poweredBy');
    if (poweredBy && !/(^|\.)ofl\.ink$/.test(location.hostname)) {
        poweredBy.textContent = location.hostname.replace(/^(www|app)\./, '');
        poweredBy.href = location.origin + '/';
    }
    const profileContainer = {
        name: document.getElementById('displayName'),
        bio: document.getElementById('bio'),
        avatar: document.getElementById('avatar'),
        verifiedBadge: document.getElementById('verifiedBadge')
    };
    const linksContainer = document.getElementById('linksContainer');
    const overlay = document.getElementById('overlay');
    const closeOverlayBtn = document.getElementById('closeOverlayBtn');
    const continueBtn = document.getElementById('continueBtn');
    const igOverlay = document.getElementById('igOverlay');
    const igCard = document.getElementById('igCard');
    const overlayError = document.getElementById('overlayError');
    const revealError = document.getElementById('revealError');
    const revealRetry = document.getElementById('revealRetry');
    const REVEAL_FAILED = "Couldn't open this link. Please try again.";

    // Store links data to simulate API fetching
    let linksData = [];
    let currentProfile = null;
    let currentLinkId = null;

    // In-App Browser: the plan's pattern, verbatim and case-insensitive. Escape Mode, Link Shortcuts and the address bar go
    // by it alone, exactly as on the phones where they work today
    const IN_APP_BROWSER = /Instagram|FBAN|FBAV|Threads|musical_ly|Bytedance|TikTok/i;
    const ua = navigator.userAgent || '';
    const isInAppBrowser = IN_APP_BROWSER.test(ua);
    // v1's Instagram check: with iOS 17+, arms the Escape Overlay card's tap escape (canTapEscape)
    const isInstagram = (navigator.userAgent || '').indexOf('Instagram') > -1;
    const isAndroid = /Android/.test(navigator.userAgent || '');
    // iOS and its major version, from the UA's "OS 17_0" (iPhone/iPad/iPod); 0 when the UA names none
    const isIOS = /iPhone|iPad|iPod/.test(ua);
    const iosMajor = isIOS ? Number((ua.match(/ OS (\d+)_/) || [])[1] || 0) : 0;

    // The Profile this page is for, as the app resolved it from the host and the path (Phase 5): its Username, the Tracking Code
    // the path carried, and the Profile path every URL the page builds for itself starts from (`/{username}`, or `/` on a
    // Custom Domain). Null when no Profile answers the path, which lands on the landing page as an unknown Username does.
    const bootstrap = JSON.parse(document.getElementById('profile-bootstrap').textContent);
    // Path mode: the prefix the app serves this page under (`/p` for `<app host>/p/{username}`), named on <body>; every
    // URL this script builds for the app starts with it. Empty on a host of its own.
    const BASE = document.body.dataset.base || '';
    if (!bootstrap) {
        window.location.href = `${BASE}/landing.html`;
        return;
    }
    let { username, profilePath } = bootstrap;
    // Tap escape on the Escape Overlay card: iOS 17+ Instagram only, and only while the server's kill switch
    // (BIO_ESCAPE_TAP, rendered on the card) is on. Other iOS apps, older iOS and Android keep a passive card.
    const canTapEscape = igCard.dataset.escapeTap === '1' && isIOS && isInstagram && iosMajor >= 17;
    const trackingId = bootstrap.trackingCode;
    // Link Shortcut: read on page load, before the address bar is touched, so ?link= survives beside the code
    const linkShortcut = new URLSearchParams(window.location.search).get('link');

    if (!username || username === 'index.html') { // Default
        username = 'juliafilippo_';
        profilePath = `${BASE}/${username}`;
    }

    // A Tracking Code in the path is stored once the Profile JSON names its Profile (below)
    if (trackingId) {
        console.log(`Captured tracking ID: ${trackingId}`);

        // Clean URL: Remove the tracking ID from the address bar, outside In-App Browsers only,
        // so the app's own "Open in browser" menu item carries the Tracking Code
        // Changes /username/123 -> /username, and on a Custom Domain /123 -> /
        if (!isInAppBrowser) {
            window.history.replaceState({}, '', profilePath);
        }
    }

    console.log(`Loading profile: ${username}`);

    fetch(`${BASE}/api/profiles/${username}.json`)
        .then(response => {
            if (!response.ok) throw new Error('Profile not found');
            return response.json();
        })
        .then(data => {
            renderProfile(data.profile);
            currentProfile = data.profile;
            if (trackingId) localStorage.setItem(trackingKey(), trackingId);
            linksData = data.links;
            renderLinks(linksData);
            siteKey = data.turnstileSiteKey || null;
            if (siteKey && linksData.some(l => l.botCheck)) loadTurnstile().catch(() => {});

            // Page View Ping (Phase 4): once per load, after the Profile has rendered, never for an unknown Username (the
            // fetch above failed for one); keepalive lets it finish when the Visitor leaves at once, and nothing waits on it
            fetch(`${BASE}/v/${username}`, { method: 'POST', keepalive: true }).catch(() => {});

            // A Link Shortcut whose Link Id is not on this Profile is ignored: the page loads as a plain visit
            const shortcutLink = linkShortcut ? linksData.find(link => link.id === linkShortcut) : null;

            const shortcutMode = shortcutLink ? effectiveMode(shortcutLink) : null;

            if (isInAppBrowser && shortcutMode === 'escape_ig') {
                // In an In-App Browser an Escape Mode Link Shortcut is v1's `?link=`: the Escape Overlay opens on every load,
                // aimed at that Link's escape target and with Close. Only Android then Reveals and bounces straight out to the
                // Destination (the Chrome intent); iOS stays on the overlay until the visitor uses its steps or taps its card.
                const target = escapeTarget(shortcutLink.id);
                pointAddressAt(target);
                openEscapeOverlay(target);
                if (isAndroid) revealAndGo(shortcutLink, popOut);
                return;
            }

            // Escape Overlay on open: In-App Browser and a Profile default of Escape Mode, as v1 shows it to Instagram; the
            // no automatic pop-out on iOS: the Visitor uses the ··· menu or taps the card; Android bounces from a Link tap
            if (isInAppBrowser && defaultMode() === 'escape_ig') {
                const target = escapeTarget(null);
                pointAddressAt(target);
                openEscapeOverlay(target);
            }

            // Link Shortcut, with no Age Gate (v1's Link Shortcut has none): the Destination as a tap gets it, Revealed then navigated to.
            // Never inside an In-App Browser: an automatic navigation to the Destination there is what gets links flagged
            if (shortcutLink && !isInAppBrowser) {
                revealAndGo(shortcutLink);
            }
        })
        .catch(error => {
            console.error('Error fetching profile:', error);
            window.location.href = `${BASE}/landing.html`;
        });

    function renderProfile(profile) {
        // User Request: Name as Title
        document.title = profile.displayName;

        profileContainer.name.textContent = profile.displayName;
        profileContainer.bio.textContent = profile.bio;
        profileContainer.avatar.src = profile.avatarUrl;

        // Backdrop, the avatar blurred: style.css body::before on desktop, #igOverlay::before at every width.
        if (profile.avatarUrl) {
            document.documentElement.style.setProperty('--backdrop-url',
                'url("' + profile.avatarUrl.replace(/["\\]/g, '\\$&') + '")');
        }

        // User Request: Avatar as Page Icon (Favicon)
        let link = document.querySelector("link[rel~='icon']");
        if (!link) {
            link = document.createElement('link');
            link.rel = 'icon';
            document.getElementsByTagName('head')[0].appendChild(link);
        }
        link.href = profile.avatarUrl;

        if (profile.verified) {
            profileContainer.verifiedBadge.style.display = 'inline-block';
        }
    }

    function renderLinks(links) {
        linksContainer.innerHTML = '';
        links.forEach(link => {
            const card = document.createElement('div');
            card.className = 'link-card';

            const content = document.createElement('div');
            content.className = 'link-content';

            const title = document.createElement('span');
            title.className = 'link-title';
            title.textContent = link.title;

            // Add lock icon to title if adult
            if (link.isAdult) {
                const tpl = document.getElementById('small-lock');
                if (tpl && tpl.content.firstElementChild) title.appendChild(tpl.content.firstElementChild.cloneNode(true));
            }

            const subtitle = document.createElement('span');
            subtitle.className = 'link-subtitle';
            subtitle.textContent = link.subtitle || (link.isAdult ? 'Exclusive Content' : 'Social Media');

            if (link.backgroundImage) {
                card.style.backgroundImage = `url('${link.backgroundImage}')`;
                card.classList.add('has-bg-image');

                // User Request: Make container height match the image aspect ratio exactly
                const img = new Image();
                img.src = link.backgroundImage;
                img.onload = function () {
                    const ratio = img.naturalWidth / img.naturalHeight;
                    // Apply aspect ratio to the card so it fits the image perfectly
                    card.style.aspectRatio = `${ratio} / 1`;
                };
            }

            // Top-left Icon (User Request)
            // Only add icon if there is a background image (Banner)
            if (link.icon && link.backgroundImage) {
                const icon = document.createElement('img');
                icon.src = link.icon;
                icon.className = 'link-icon';
                card.appendChild(icon);
            }

            content.appendChild(title);
            content.appendChild(subtitle);
            card.appendChild(content);

            // Click Handler
            card.addEventListener('click', () => {
                if (link.isAdult) {
                    openOverlay(link.id);
                } else if (isInAppBrowser && effectiveMode(link) === 'escape_ig') {
                    escapeOnTap(link);
                } else {
                    revealAndGo(link);
                }
            });

            linksContainer.appendChild(card);
        });
    }

    // Mode: the Link's own if recognised, else the Profile's default if recognised, else Escape Mode.
    const MODES = ['direct', 'escape_ig'];
    function defaultMode() {
        if (currentProfile && MODES.includes(currentProfile.mode)) return currentProfile.mode;
        return 'escape_ig';
    }

    function effectiveMode(link) {
        return MODES.includes(link.mode) ? link.mode : defaultMode();
    }

    // Tracking Code key (Phase 4): one per Profile, by the record id the Profile JSON carries, so a code that arrived on one
    // Profile never reaches another, even one that later holds its Username. v1's global `linkme_tracking_id` is never read
    // or written: at Cutover it may hold another Creator's code.
    function trackingKey() {
        return `linkme_tracking_id:${currentProfile.id}`;
    }

    // Stored Tracking Code: the path code this Profile keeps, read by Reveal and by the escape target
    function storedTrackingCode() {
        return localStorage.getItem(trackingKey());
    }

    // Reveal URL: Link Id, Username, and a Tracking Code when the Link has tracking on
    function revealUrl(linkId) {
        const link = linksData.find(l => l.id === linkId);
        let fetchUrl = `${BASE}/.netlify/functions/reveal?id=${linkId}&user=${username}`;

        if (link && link.tracking) {
            let trackingIdToUse = storedTrackingCode();

            if (!trackingIdToUse) {
                // Priority 2: Modified - Only use Link Default
                if (link.default_tracknumber) {
                    trackingIdToUse = link.default_tracknumber;
                }
            }

            if (trackingIdToUse) {
                fetchUrl += `&trackingId=${trackingIdToUse}`;
            }
        }
        return fetchUrl;
    }

    // Bot Check: a Link the Profile JSON marks botCheck Reveals only with a Cloudflare Turnstile token. The widget's
    // script is loaded only for a Profile with such a Link (the JSON then carries the site key), and stays invisible
    // unless Cloudflare asks the Visitor to interact.
    let siteKey = null;
    let turnstileLoad = null;
    function loadTurnstile() {
        if (!turnstileLoad) {
            turnstileLoad = new Promise((resolve, reject) => {
                const s = document.createElement('script');
                s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
                s.async = true;
                s.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error('Bot check missing')));
                s.onerror = () => reject(new Error('Bot check failed to load'));
                document.head.appendChild(s);
            }).catch(err => {
                turnstileLoad = null; // a failed load is retried on the next Reveal, never cached
                throw err;
            });
        }
        return turnstileLoad;
    }

    // One Turnstile token: a widget rendered into #tsBox, removed once it answers
    function botCheckToken() {
        return loadTurnstile().then(ts => new Promise((resolve, reject) => {
            const box = document.getElementById('tsBox');
            box.classList.remove('hidden');
            let widget = null;
            const finish = fn => value => {
                if (widget !== null) ts.remove(widget);
                box.classList.add('hidden');
                fn(value);
            };
            const fail = finish(() => reject(new Error('Bot check failed')));
            try {
                widget = ts.render(box, {
                    sitekey: siteKey, appearance: 'interaction-only', theme: 'dark',
                    callback: finish(resolve), 'error-callback': fail, 'expired-callback': fail, 'timeout-callback': fail
                });
            } catch (err) {
                fail();
            }
        }));
    }

    // Reveal a Link by its Link Id: the answer's JSON, with a Turnstile token first when the Link is gated
    function reveal(linkId) {
        const link = linksData.find(l => l.id === linkId);
        const token = link && link.botCheck && siteKey ? botCheckToken() : Promise.resolve(null);
        return token
            .then(t => fetch(revealUrl(linkId), t ? { headers: { 'x-turnstile-token': t } } : undefined))
            .then(res => {
                if (!res.ok) throw new Error('Network response was not ok');
                return res.json();
            });
    }

    // Reveal, then `go` to the answer (by default, navigate straight to it)
    function revealAndGo(link, go = url => { window.location.href = url; }) {
        hideRevealError();
        reveal(link.id)
            .then(data => {
                if (data.realUrl) {
                    go(data.realUrl);
                }
            })
            .catch(err => {
                console.error('Error revealing link:', err);
                showRevealError(() => revealAndGo(link, go));
            });
    }

    // A failed Reveal outside the Age Gate: the toast, whose Retry runs `again`
    let retryReveal = null;
    function showRevealError(again) {
        retryReveal = again;
        revealError.classList.remove('hidden');
    }
    function hideRevealError() {
        retryReveal = null;
        revealError.classList.add('hidden');
    }
    revealRetry.addEventListener('click', () => {
        const again = retryReveal;
        hideRevealError();
        if (again) again();
    });

    // Escape target: https on the host that served the page, at the Profile path with the stored Tracking Code
    function escapeTarget(linkId) {
        const code = storedTrackingCode();
        let path = code ? `${profilePath.replace(/\/$/, '')}/${code}` : profilePath;
        if (linkId) path += `?link=${linkId}`;
        return { path, url: `https://${window.location.host}${path}` };
    }

    // An address as https, whatever scheme it had, as v1's performBounce forced it
    const asHttps = url => 'https://' + url.replace(/^https?:\/\//i, '');

    // Android intent for an address: intent://{host}/{path}[?query] opened as https, with `extra` (package, fallback)
    function httpsIntent(url, extra) {
        return 'intent://' + asHttps(url).slice('https://'.length) + '#Intent;scheme=https;' + extra + 'end';
    }

    // Escape link, per platform, navigated by script: only Android gets a native scheme (the Chrome intent, as v1's
    // performBounce did). iOS and Instagram get none from script: the Escape Overlay carries the manual "··· menu / Open in
    // Browser" steps, and in iOS 17+ Instagram its card's own href (cardHref) is the only scheme, followed on a tap alone.
    // Handing Instagram's own open-in-browser scheme the Destination URL is what flagged OnlyFans links in-app.
    function escapeLink(url) {
        if (isAndroid) return httpsIntent(url, 'package=com.android.chrome;');
        return null; // iOS (incl. Instagram) and everything else: passive, no native scheme
    }

    // Pop out of the In-App Browser, where the platform has an escape link
    function popOut(url) {
        const href = escapeLink(url);
        if (href) window.location.href = href;
    }

    // An Escape Mode tap in an In-App Browser: fired from the tap itself, with no request before it
    function escapeOnTap(link) {
        const target = escapeTarget(link.id);
        pointAddressAt(target);
        popOut(target.url);
        openEscapeOverlay(target);
    }

    // Address bar while an Escape Overlay shows: point it at the escape target so the app's own ··· "Open in browser" opens it
    function pointAddressAt(target) {
        window.history.replaceState({}, '', target.path);
    }

    // The card's href: Instagram's own open-in-browser link to the escape target (escapeTarget(), our host, never a
    // Destination; no Reveal before it), where canTapEscape allows; else none
    function cardHref(target) {
        return canTapEscape ? 'instagram://extbrowser/?url=' + encodeURIComponent(target.url) : null;
    }

    // Escape Overlay: the manual instructions (the ··· menu) on a card over the blurred avatar. The address bar already
    // points at the escape target, so the app's own "Open in browser" carries the right URL. The card leaves only as an
    // anchor tap: no script navigation, nothing on load, no timer. Blocks scrolling while it shows.
    function openEscapeOverlay(target) {
        const href = cardHref(target);
        if (href) igCard.href = href;
        else igCard.removeAttribute('href');
        igOverlay.classList.remove('hidden');
        igOverlay.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    // Overlay Logic
    function openOverlay(linkId) {
        currentLinkId = linkId;
        overlayError.classList.add('hidden');
        continueBtn.textContent = 'Continue (18+)';
        // Continue has no href and Reveals.
        continueBtn.removeAttribute('href');
        overlay.classList.remove('hidden');
        // Add active class for transition
        setTimeout(() => overlay.classList.add('active'), 10);
    }

    function closeOverlay() {
        overlay.classList.remove('active');
        setTimeout(() => overlay.classList.add('hidden'), 300);
        currentLinkId = null;
    }

    closeOverlayBtn.addEventListener('click', closeOverlay);

    // Deep Linking / Bounce Logic
    continueBtn.addEventListener('click', () => {
        if (!currentLinkId || continueBtn.getAttribute('aria-disabled') === 'true') return;
        // Found at click time, as v1 did: closing the Age Gate mid-Reveal still travels
        const link = linksData.find(l => l.id === currentLinkId);

        // An Adult Escape Mode Link in an In-App Browser: this tap is the pop-out, with no Reveal in the app first
        if (isInAppBrowser && effectiveMode(link) === 'escape_ig') {
            escapeOnTap(link);
            closeOverlay();
            return;
        }

        continueBtn.textContent = 'loading...';
        continueBtn.setAttribute('aria-disabled', 'true');
        overlayError.classList.add('hidden');

        reveal(currentLinkId)
            .then(data => {
                if (data.realUrl) {
                    window.location.href = data.realUrl;
                }
                // Reset UI
                continueBtn.textContent = 'Continue (18+)';
                continueBtn.removeAttribute('aria-disabled');
                closeOverlay();
            })
            .catch(err => {
                // The Age Gate stays open with the reason and Retry; the button frees only once that shows
                console.error('Error revealing link:', err);
                overlayError.textContent = REVEAL_FAILED;
                overlayError.classList.remove('hidden');
                continueBtn.textContent = 'Retry';
                continueBtn.removeAttribute('aria-disabled');
            });
    });

    // Close on click outside
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            closeOverlay();
        }
    });
});
