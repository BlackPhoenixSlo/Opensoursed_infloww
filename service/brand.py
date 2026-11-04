"""The product's name wherever the relay itself says it to people: the TOTP
issuer in authenticator apps, the help assistant's prompt, the proxy pool's
messages. `BRAND_NAME` overrides it (docker-compose.yml passes it from .env);
unset = Inflowwww. The app's twin is app/lib/brand.ts. `BRAND_LOGO` is its logo path
prefix (the app serves `<prefix>-180.png` etc. from app/public); BRAND_ICON is what a Web Push
shows (push_notice), the app's own /icon.svg when unset."""

import os

BRAND_NAME = os.environ.get("BRAND_NAME", "").strip() or "Inflowwww"
BRAND_LOGO = os.environ.get("BRAND_LOGO", "").strip()
BRAND_ICON = f"{BRAND_LOGO}-180.png" if BRAND_LOGO else "/icon.svg"
