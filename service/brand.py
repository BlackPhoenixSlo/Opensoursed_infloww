"""The product's name wherever the relay itself says it to people: the TOTP
issuer in authenticator apps, the help assistant's prompt, the proxy pool's
messages. `BRAND_NAME` overrides it (docker-compose.yml passes it from .env);
unset = Inflowwww. The app's twin is app/lib/brand.ts."""

import os

BRAND_NAME = os.environ.get("BRAND_NAME", "").strip() or "Inflowwww"
