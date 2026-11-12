"""Scoped Set-Cookie intent for OF's buffered CF-cookie persistence.

No snapshot merging: header order within a response, then persistence-lock order
between responses. An empty value is an update unless expiry explicitly deletes it.
"""
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from http.cookiejar import Cookie
from http.cookies import SimpleCookie, CookieError
import ipaddress
import time
from urllib.parse import urlsplit


def cookie_key(row):
    return row['name'], row.get('domain', '').lstrip('.').lower(), row.get('path') or '/'


def cookie_state(row):
    return (row.get('value', ''), bool(row.get('secure', False)),
            row.get('expires') if (row.get('expires') or 0) > 0 else None,
            bool(row.get('hostOnly', not row.get('domain', '').startswith('.'))),
            bool(row.get('httpOnly', False)))


@dataclass(frozen=True)
class CookieEvent:
    name: str
    domain: str
    path: str
    value: str
    secure: bool
    expires: int | None
    host_only: bool
    http_only: bool
    delete: bool

    @property
    def key(self):
        return self.name, self.domain.lstrip('.'), self.path

    def row(self):
        return dict(name=self.name, domain=self.domain, path=self.path, value=self.value,
                    secure=self.secure, expires=self.expires, hostOnly=self.host_only,
                    httpOnly=self.http_only)


def response_cookie_events(url, headers, *, now=None):
    """Parse each Set-Cookie separately; validate domain against the actual URL.

    Domain cookies may target the response host or its dotted parent, never an
    unrelated host or a single-label parent. IP hosts only accept their own IP.
    No origin is guessed when the response URL is missing.
    """
    target = urlsplit(url)
    host = (target.hostname or '').lower()
    if target.scheme not in ('http', 'https') or not host:
        return ()
    now = time.time() if now is None else now
    default_path = target.path.rsplit('/', 1)[0] or '/'
    events = []
    for header in headers.get_list('set-cookie'):
        parsed = SimpleCookie()
        try:
            parsed.load(header)
        except CookieError:
            continue
        for name, morsel in parsed.items():
            domain = morsel['domain'].lstrip('.').lower()
            host_only = not domain
            if domain:
                if domain.endswith('.') or not (host == domain or host.endswith('.' + domain)):
                    continue
                if domain != host and '.' not in domain:
                    continue
                try:
                    ipaddress.ip_address(host)
                except ValueError:
                    pass
                else:
                    if domain != host:
                        continue
            else:
                domain = host
            secure = bool(morsel['secure'])
            if secure and target.scheme != 'https':
                continue
            path = morsel['path'] if morsel['path'].startswith('/') else default_path
            if name.startswith('__Secure-') and not secure:
                continue
            if name.startswith('__Host-') and (not secure or not host_only or path != '/'):
                continue
            expires = None
            if morsel['expires']:
                try:
                    expires = int(parsedate_to_datetime(morsel['expires']).timestamp())
                except (ValueError, TypeError, OverflowError):
                    pass
            if morsel['max-age']:
                try:
                    age = int(morsel['max-age'])
                    expires = int(now) + age if age > 0 else 0
                except ValueError:
                    pass
            events.append(CookieEvent(name, domain if host_only else '.' + domain, path,
                                      morsel.value, secure, expires, host_only,
                                      bool(morsel['httponly']), expires is not None and expires <= now))
    return tuple(events)


def cookie_from_row(row, *, now=None):
    """Load Playwright/session rows without reviving expired or insecure cookies."""
    now = time.time() if now is None else now
    expires = row.get('expires')
    expires = int(expires) if isinstance(expires, (int, float)) and expires >= 0 else None
    if expires is not None and expires <= now:
        return None
    domain = row.get('domain') or ''
    host_only = row.get('hostOnly', not domain.startswith('.'))
    return Cookie(0, row['name'], row['value'], None, False, domain,
                  not host_only, domain.startswith('.'), row.get('path') or '/', True,
                  bool(row.get('secure', False)), expires, expires is None,
                  None, None, {'HttpOnly': None} if row.get('httpOnly') else {}, False)


def apply_cookie_events(rows, events):
    """Mutate current disk rows, preserving other cookie scopes and row metadata."""
    changed = False
    for event in events:
        matches = [row for row in rows if cookie_key(row) == event.key]
        if event.delete:
            if matches:
                rows[:] = [row for row in rows if cookie_key(row) != event.key]
                changed = True
        elif matches:
            row = matches[0]
            if cookie_state(row) != cookie_state(event.row()):
                domain = row['domain']  # retain capture spelling; hostOnly is explicit
                row.update(event.row())
                row['domain'] = domain
                changed = True
        else:
            rows.append(event.row())
            changed = True
    return changed
