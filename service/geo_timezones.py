from __future__ import annotations

import re


# Deterministic, never LLM-guessed: a wrong zone makes the prompt clock block defend the wrong hour. None = ambiguous, the UI asks.
_CITY_TZ: dict[str, str] = {
    "buenos aires": "America/Argentina/Buenos_Aires",
    "cordoba": "America/Argentina/Cordoba",
    "córdoba": "America/Argentina/Cordoba",
    "mendoza": "America/Argentina/Mendoza",
    "rosario": "America/Argentina/Cordoba",
    "bogota": "America/Bogota", "bogotá": "America/Bogota",
    "medellin": "America/Bogota", "medellín": "America/Bogota",
    "cartagena": "America/Bogota",
    "lima": "America/Lima", "santiago": "America/Santiago",
    "caracas": "America/Caracas", "quito": "America/Guayaquil",
    "montevideo": "America/Montevideo", "asuncion": "America/Asuncion",
    "sao paulo": "America/Sao_Paulo", "são paulo": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo",
    "mexico city": "America/Mexico_City", "ciudad de mexico": "America/Mexico_City",
    "guadalajara": "America/Mexico_City", "monterrey": "America/Monterrey",
    "cancun": "America/Cancun", "cancún": "America/Cancun",
    "quintana roo": "America/Cancun", "tulum": "America/Cancun",
    "playa del carmen": "America/Cancun", "tijuana": "America/Tijuana",
    "new york": "America/New_York", "nyc": "America/New_York",
    "brooklyn": "America/New_York", "manhattan": "America/New_York",
    "miami": "America/New_York", "tampa": "America/New_York",
    "orlando": "America/New_York", "jacksonville": "America/New_York",
    "atlanta": "America/New_York", "boston": "America/New_York",
    "philadelphia": "America/New_York", "washington": "America/New_York",
    "charlotte": "America/New_York", "nashville": "America/Chicago",
    "detroit": "America/Detroit", "chicago": "America/Chicago",
    "houston": "America/Chicago", "dallas": "America/Chicago",
    "austin": "America/Chicago", "san antonio": "America/Chicago",
    "new orleans": "America/Chicago", "minneapolis": "America/Chicago",
    "kansas city": "America/Chicago", "st louis": "America/Chicago",
    "denver": "America/Denver", "salt lake city": "America/Denver",
    "albuquerque": "America/Denver", "phoenix": "America/Phoenix",
    "los angeles": "America/Los_Angeles",
    "san diego": "America/Los_Angeles", "san francisco": "America/Los_Angeles",
    "san jose": "America/Los_Angeles", "sacramento": "America/Los_Angeles",
    "las vegas": "America/Los_Angeles", "seattle": "America/Los_Angeles",
    "portland": "America/Los_Angeles",
    # Hawaii/Alaska by name: else the IANA tail scan answers with the deprecated US/Hawaii alias.
    "honolulu": "Pacific/Honolulu", "hawaii": "Pacific/Honolulu",
    "maui": "Pacific/Honolulu", "oahu": "Pacific/Honolulu",
    "anchorage": "America/Anchorage", "alaska": "America/Anchorage",
    "vancouver": "America/Vancouver", "vancouver island": "America/Vancouver",
    "victoria": "America/Vancouver", "toronto": "America/Toronto",
    "ottawa": "America/Toronto", "montreal": "America/Toronto",
    "quebec": "America/Toronto", "calgary": "America/Edmonton",
    "edmonton": "America/Edmonton", "winnipeg": "America/Winnipeg",
    "halifax": "America/Halifax",
    "london": "Europe/London", "manchester": "Europe/London",
    "dublin": "Europe/Dublin", "paris": "Europe/Paris",
    "madrid": "Europe/Madrid", "barcelona": "Europe/Madrid",
    "valencia": "Europe/Madrid", "lisbon": "Europe/Lisbon",
    "berlin": "Europe/Berlin", "munich": "Europe/Berlin",
    "amsterdam": "Europe/Amsterdam", "brussels": "Europe/Brussels",
    "zurich": "Europe/Zurich", "vienna": "Europe/Vienna",
    "prague": "Europe/Prague", "warsaw": "Europe/Warsaw",
    "budapest": "Europe/Budapest", "bucharest": "Europe/Bucharest",
    "rome": "Europe/Rome", "milan": "Europe/Rome",
    "athens": "Europe/Athens", "istanbul": "Europe/Istanbul",
    "stockholm": "Europe/Stockholm", "oslo": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen", "helsinki": "Europe/Helsinki",
    "ljubljana": "Europe/Ljubljana", "zagreb": "Europe/Zagreb",
    "belgrade": "Europe/Belgrade", "kyiv": "Europe/Kyiv", "kiev": "Europe/Kyiv",
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane", "perth": "Australia/Perth",
    "auckland": "Pacific/Auckland", "tokyo": "Asia/Tokyo",
    "seoul": "Asia/Seoul", "singapore": "Asia/Singapore",
    "hong kong": "Asia/Hong_Kong", "bangkok": "Asia/Bangkok",
    "manila": "Asia/Manila", "jakarta": "Asia/Jakarta",
    "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata",
    "dubai": "Asia/Dubai", "tel aviv": "Asia/Jerusalem",
    "johannesburg": "Africa/Johannesburg", "cape town": "Africa/Johannesburg",
    "lagos": "Africa/Lagos", "cairo": "Africa/Cairo", "nairobi": "Africa/Nairobi",
}

# Single-zone countries only: US, Canada, Australia, Brazil, Mexico, Russia, Indonesia are excluded (a country name alone is not enough).
_COUNTRY_TZ: dict[str, str] = {
    "argentina": "America/Argentina/Buenos_Aires",
    "colombia": "America/Bogota", "peru": "America/Lima",
    "chile": "America/Santiago", "venezuela": "America/Caracas",
    "ecuador": "America/Guayaquil", "uruguay": "America/Montevideo",
    "paraguay": "America/Asuncion", "bolivia": "America/La_Paz",
    "cuba": "America/Havana", "dominican republic": "America/Santo_Domingo",
    "puerto rico": "America/Puerto_Rico", "jamaica": "America/Jamaica",
    "costa rica": "America/Costa_Rica", "panama": "America/Panama",
    "guatemala": "America/Guatemala", "honduras": "America/Tegucigalpa",
    "el salvador": "America/El_Salvador", "nicaragua": "America/Managua",
    "united kingdom": "Europe/London", "uk": "Europe/London",
    "england": "Europe/London", "scotland": "Europe/London",
    "wales": "Europe/London", "ireland": "Europe/Dublin",
    "france": "Europe/Paris", "spain": "Europe/Madrid",
    "portugal": "Europe/Lisbon", "germany": "Europe/Berlin",
    "netherlands": "Europe/Amsterdam", "belgium": "Europe/Brussels",
    "switzerland": "Europe/Zurich", "austria": "Europe/Vienna",
    "italy": "Europe/Rome", "greece": "Europe/Athens",
    "poland": "Europe/Warsaw", "czechia": "Europe/Prague",
    "czech republic": "Europe/Prague", "hungary": "Europe/Budapest",
    "romania": "Europe/Bucharest", "slovenia": "Europe/Ljubljana",
    "croatia": "Europe/Zagreb", "serbia": "Europe/Belgrade",
    "slovakia": "Europe/Bratislava", "bulgaria": "Europe/Sofia",
    "sweden": "Europe/Stockholm", "norway": "Europe/Oslo",
    "denmark": "Europe/Copenhagen", "finland": "Europe/Helsinki",
    "ukraine": "Europe/Kyiv", "turkey": "Europe/Istanbul",
    "new zealand": "Pacific/Auckland", "japan": "Asia/Tokyo",
    "south korea": "Asia/Seoul", "singapore": "Asia/Singapore",
    "thailand": "Asia/Bangkok", "philippines": "Asia/Manila",
    "vietnam": "Asia/Ho_Chi_Minh", "india": "Asia/Kolkata",
    "pakistan": "Asia/Karachi", "israel": "Asia/Jerusalem",
    "south africa": "Africa/Johannesburg", "nigeria": "Africa/Lagos",
    "egypt": "Africa/Cairo", "kenya": "Africa/Nairobi",
    "morocco": "Africa/Casablanca",
}


def _norm_place(s: str | None) -> str:
    t = re.sub(r"[^\w\s]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def resolve_timezone_for_place(city: str | None = None,
                               country: str | None = None,
                               free_text: str | None = None) -> str | None:
    blobs = [_norm_place(city), _norm_place(free_text), _norm_place(country)]

    for b in blobs:
        if b and b in _CITY_TZ:
            return _CITY_TZ[b]

    for b in blobs:
        if not b:
            continue
        # Longest key first so "vancouver island" beats "vancouver".
        for key in sorted(_CITY_TZ, key=len, reverse=True):
            if re.search(rf"\b{re.escape(key)}\b", b):
                return _CITY_TZ[key]

    try:
        from zoneinfo import available_timezones
        _LEGACY = ("US/", "Canada/", "Brazil/", "Mexico/", "Chile/", "Australia/",
                   "Etc/", "SystemV/", "Antarctica/")
        tails = {}
        # Legacy alias trees are skipped: they'd answer "hawaii" with the deprecated US/Hawaii.
        for z in sorted(available_timezones()):
            if z.startswith(_LEGACY) or "/" not in z:
                continue
            tails.setdefault(z.rsplit("/", 1)[-1].replace("_", " ").lower(), z)
    except Exception:
        tails = {}
    for b in blobs:
        if b and b in tails:
            return tails[b]

    for b in blobs:
        if b and b in _COUNTRY_TZ:
            return _COUNTRY_TZ[b]
    for b in blobs:
        if not b:
            continue
        for key in sorted(_COUNTRY_TZ, key=len, reverse=True):
            if re.search(rf"\b{re.escape(key)}\b", b):
                return _COUNTRY_TZ[key]

    return None


