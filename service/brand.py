import os

BRAND_NAME = os.environ.get("BRAND_NAME", "").strip() or "Inflowwww"
BRAND_LOGO = os.environ.get("BRAND_LOGO", "").strip()
BRAND_ICON = f"{BRAND_LOGO}-180.png" if BRAND_LOGO else "/icon.svg"
