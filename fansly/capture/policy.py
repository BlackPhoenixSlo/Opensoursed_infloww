SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
WAF_ENDPOINTS: frozenset[tuple[str, str]] = frozenset()


def waf_allowed(method: str, origin: str, path: str) -> bool:
    return method == "POST" and origin.startswith("https://") and (origin, path) in WAF_ENDPOINTS
