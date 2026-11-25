export function resolveShareToken(): string | null {
  if (typeof window === "undefined") return null;
  const fromUrl = new URLSearchParams(window.location.search).get("t");
  if (fromUrl) {
    try {
      window.localStorage.setItem("chatterly:share_token", fromUrl);
    } catch {
    }
    return fromUrl;
  }
  try {
    return window.localStorage.getItem("chatterly:share_token");
  } catch {
    return null;
  }
}
