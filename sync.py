#!/usr/bin/env python3
"""
Voetbal-agenda: haalt het wedstrijdprogramma van je team uit Sportlink
(dezelfde bron als voetbal.nl) en schrijft een .ics-agenda waar je iPhone
zich op kan abonneren.

Twee bronnen, kies er een:

  A) Teampagina op de clubsite (standaard, geen sleutel nodig)
     TEAM_URLS            - URL(s) van team- of programmapagina('s), komma-gescheiden
                            standaard: teampagina WVV'34 2 + wvv34.nl/programma
     TEAM_NAAM            - welk team (standaard "WVV'34 2"); leestekens en
                            hoofdletters maken niet uit ("WVV 34 2" werkt ook)
     PLAATS_THUIS         - plaats van het eigen sportpark (voor de kaart)

  B) Sportlink Club.Dataservice-API (als je club je een client ID geeft)
     SPORTLINK_CLIENT_ID  - Club.Dataservice client ID van je club
     TEAMS                - teamnamen of teamcodes, komma-gescheiden

  Algemeen:
     AGENDA_NAAM          - naam van de agenda op je iPhone
     WEDSTRIJDDUUR_MIN    - lengte van een afspraak (standaard 105)

Gebruik:
  python sync.py            # agenda bijwerken -> docs/wedstrijden.ics
  python sync.py --teams    # (alleen API) toon alle teams + teamcodes
  python sync.py --test F   # parse een opgeslagen HTML-bestand, schrijf niets
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TEAM_URLS = ("https://www.wvv34.nl/wvv34-2-ve-zondag-speeldag-man,"
                     "https://www.wvv34.nl/programma")
DEFAULT_TEAM_NAAM = "WVV'34 2"
DEFAULT_PLAATS_THUIS = "Hengevelde"
UA = ("Mozilla/5.0 (compatible; voetbal-agenda/1.0; "
      "+https://github.com) Python-urllib")

API = "https://data.sportlink.com"
TZ = ZoneInfo("Europe/Amsterdam")
OUT_DIR = Path(__file__).parent / "docs"
ICS_FILE = OUT_DIR / "wedstrijden.ics"
STATE_FILE = OUT_DIR / "wedstrijden.json"  # bewaart gespeelde wedstrijden


# --------------------------------------------------------------------------- API
def api_get(endpoint: str, client_id: str, **params) -> list[dict]:
    params = {"client_id": client_id, **{k: v for k, v in params.items() if v is not None}}
    url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "voetbal-agenda/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    if isinstance(data, dict):  # sommige endpoints verpakken de lijst
        for key in ("items", "data", "wedstrijden"):
            if isinstance(data.get(key), list):
                return data[key]
        if "error" in data or "foutmelding" in data:
            raise RuntimeError(f"Sportlink gaf een fout: {data}")
        return [data]
    return data or []


def get_teams(client_id: str) -> list[dict]:
    return api_get("teams", client_id)


def pick(d: dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def resolve_teams(client_id: str, wanted: list[str]) -> list[dict]:
    """Zet teamnamen of -codes om naar Sportlink-teams."""
    teams = get_teams(client_id)
    if not wanted:
        return teams
    gevonden = []
    for w in wanted:
        wl = w.strip().lower()
        match = [
            t for t in teams
            if wl in (str(pick(t, "teamcode")).lower(), str(pick(t, "lokaleteamcode")).lower())
            or wl == str(pick(t, "teamnaam")).lower()
        ] or [t for t in teams if wl in str(pick(t, "teamnaam")).lower()]
        if not match:
            namen = ", ".join(sorted({str(pick(t, "teamnaam")) for t in teams}))
            raise SystemExit(f"Team '{w}' niet gevonden. Beschikbare teams: {namen}")
        gevonden.extend(match)
    # ontdubbelen op teamcode
    return list({str(pick(t, "teamcode")): t for t in gevonden}.values())


# ------------------------------------------------------------------ wedstrijden
def parse_datetime(m: dict) -> datetime | None:
    raw = pick(m, "wedstrijddatum")
    if raw:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(raw, fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
            except ValueError:
                pass
    datum, tijd = pick(m, "datum", "kaledatum"), pick(m, "aanvangstijd")
    for fmt in ("%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M", "%d %b %Y %H:%M"):
        try:
            return datetime.strptime(f"{str(datum)[:10]} {tijd}", fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    return None


def normalise(m: dict, teamnaam: str, bron: str) -> dict | None:
    start = parse_datetime(m)
    code = str(pick(m, "wedstrijdcode", "wedstrijdnummer"))
    if not start or not code:
        return None
    return {
        "code": code,
        "team": teamnaam,
        "start": start.isoformat(),
        "thuis": pick(m, "thuisteam"),
        "uit": pick(m, "uitteam"),
        "competitie": pick(m, "competitienaam", "competitiesoort"),
        "accommodatie": pick(m, "accommodatie"),
        "plaats": pick(m, "plaats"),
        "adres": pick(m, "adres", "locatie"),
        "veld": pick(m, "veld"),
        "verzameltijd": pick(m, "verzameltijd"),
        "vertrektijd": pick(m, "vertrektijd"),
        "kleedkamer_thuis": pick(m, "kleedkamerthuisteam"),
        "kleedkamer_uit": pick(m, "kleedkameruitteam"),
        "scheidsrechter": pick(m, "scheidsrechter", "scheidsrechters"),
        "status": pick(m, "status"),
        "uitslag": pick(m, "uitslag") if bron == "uitslagen" else "",
    }


def fetch_matches(client_id: str, teams: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for t in teams:
        code, naam = pick(t, "teamcode"), pick(t, "teamnaam")
        for endpoint, extra in (
            ("programma", {"aantaldagen": 365}),
            ("uitslagen", {"aantaldagen": 60}),
        ):
            try:
                rows = api_get(endpoint, client_id, teamcode=code,
                               eigenwedstrijden="JA", gebruiklokaleteamgegevens="NEE", **extra)
            except Exception as e:  # uitslagen mag falen, programma niet
                if endpoint == "programma":
                    raise
                print(f"  waarschuwing: {endpoint} voor {naam}: {e}", file=sys.stderr)
                continue
            for row in rows:
                m = normalise(row, naam, endpoint)
                if m:
                    prev = result.get(m["code"], {})
                    # uitslag niet overschrijven met lege waarde
                    if not m["uitslag"] and prev.get("uitslag"):
                        m["uitslag"] = prev["uitslag"]
                    result[m["code"]] = {**prev, **m}
        print(f"  {naam}: ok")
    return result


def fetch_cancellations(client_id: str) -> set[str]:
    try:
        rows = api_get("afgelastingen", client_id, aantaldagen=14)
    except Exception:
        return set()
    return {str(pick(r, "wedstrijdcode", "wedstrijdnummer")) for r in rows}


# ------------------------------------------------------------- bron A: clubsite
MAANDEN = {"jan": 1, "feb": 2, "mrt": 3, "maa": 3, "apr": 4, "mei": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12}
RE_CODE = re.compile(r"match-details\?wedstrijdcode=(\d+)")
RE_DATUM = re.compile(
    r"(?:(\d{1,2})[-/](\d{1,2})(?:[-/](\d{2,4}))?|(\d{1,2})\s+([a-z]{3})[a-z]*\.?(?:\s+(\d{4}))?)"
    r"\s*(?:om\s*)?(\d{1,2})[:.](\d{2})", re.I)
RE_UITSLAG = re.compile(r"^(.*?\S)\s+(\d{1,2})\s*-\s*(\d{1,2})\s+(\S.*)$")


def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nl-NL,nl"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def tekst(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def kies_jaar(dag: int, maand: int, vandaag: date) -> date:
    kandidaten = []
    for j in (vandaag.year - 1, vandaag.year, vandaag.year + 1):
        try:
            kandidaten.append(date(j, maand, dag))
        except ValueError:
            pass
    return min(kandidaten, key=lambda d: abs((d - vandaag).days))


def rij_rond(page: str, pos: int, vorige_eind: int) -> str:
    """Het HTML-blok (bij voorkeur de <tr>) rond een match-details-link."""
    tr_start = page.rfind("<tr", 0, pos)
    tr_end = page.find("</tr>", pos)
    if tr_start != -1 and tr_end != -1 and page.rfind("</tr>", 0, pos) < tr_start:
        return page[tr_start:tr_end]
    # geen tabel: neem het stuk sinds de vorige wedstrijd (max 3000 tekens)
    return page[max(vorige_eind, pos - 3000):page.find(">", pos) + 1 or pos]


def cellen(rij: str) -> list[str]:
    tds = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", rij, flags=re.S | re.I)
    if tds:
        return [c for c in (tekst(t) for t in tds) if c]
    stukken = re.split(r"<(?:/?(?:div|span|p|li|a|td|strong|b)\b)[^>]*>", rij, flags=re.I)
    return [c for c in (tekst(s) for s in stukken) if c]


def norm(naam: str) -> str:
    return re.sub(r"[^a-z0-9]", "", naam.lower())


def parse_clubpagina(page: str, plaats_thuis: str = "", team_naam: str = "",
                     vandaag: date | None = None) -> list[dict]:
    vandaag = vandaag or datetime.now(TZ).date()
    gezien, ruw = set(), []
    vorige_eind = 0
    for mo in RE_CODE.finditer(page):
        code = mo.group(1)
        rij = rij_rond(page, mo.start(), vorige_eind)
        vorige_eind = mo.end()
        if code in gezien:
            continue
        cs = cellen(rij)
        alles = " | ".join(cs)
        dm = RE_DATUM.search(alles)
        if not dm:
            continue
        if dm.group(1):
            d, mnd, jr = int(dm.group(1)), int(dm.group(2)), dm.group(3)
        else:
            d, mnd, jr = int(dm.group(4)), MAANDEN.get(dm.group(5).lower()[:3], 0), dm.group(6)
        if not mnd:
            continue
        if jr:
            jr = int(jr) + (2000 if len(jr) == 2 else 0)
            dag = date(jr, mnd, d)
        else:
            dag = kies_jaar(d, mnd, vandaag)
        start = datetime(dag.year, dag.month, dag.day,
                         int(dm.group(7)), int(dm.group(8)), tzinfo=TZ)

        # cel met de teams: "Thuis - Uit" of "Thuis 2 - 1 Uit"
        thuis = uit = uitslag = ""
        losse_score = next((re.sub(r"\s", "", c) for c in cs
                            if re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}", c)), "")
        for c in cs:
            if (RE_DATUM.search(c) or "wedstrijdcode" in c or c.startswith("http")
                    or re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}", c)):
                continue
            u = RE_UITSLAG.match(c)
            if u:
                thuis, uitslag, uit = u.group(1), f"{u.group(2)}-{u.group(3)}", u.group(4)
                break
            if " - " in c:
                thuis, uit = (x.strip() for x in c.split(" - ", 1))
                break
        if not thuis:
            continue
        uitslag = uitslag or losse_score
        locatie = next((c for c in cs if re.search(r"sportpark|sportcomplex|park|accommodatie",
                                                   c, re.I) and " - " not in c), "")
        sm = re.search(r"afgelast|uitgesteld|gestaakt|verplaatst", alles, re.I)
        status = sm.group(0).capitalize() if sm else ""
        gezien.add(code)
        ruw.append({
            "code": code, "start": start.isoformat(), "thuis": thuis, "uit": uit,
            "uitslag": uitslag, "accommodatie": locatie, "status": status,
            "afgelast": bool(re.search(r"afgelast", status, re.I)),
        })

    if not ruw:
        return []
    # Het eigen team = de naam die het vaakst voorkomt. Zo vallen losse blokken
    # zoals 'Volgende wedstrijd van het 1e' op dezelfde pagina eruit.
    teller: dict[str, int] = {}
    for m in ruw:
        for t in (m["thuis"], m["uit"]):
            teller[t] = teller.get(t, 0) + 1
    if team_naam:
        eigen = next((t for t in teller if norm(t) == norm(team_naam)), None)
        if eigen is None:
            return []
    else:
        eigen = max(teller, key=teller.get)
    out = []
    for m in ruw:
        if eigen not in (m["thuis"], m["uit"]):
            continue
        m.update(team=eigen,
                 plaats=plaats_thuis if m["thuis"] == eigen else "")
        out.append(m)
    return out


def fetch_clubsite(urls: list[str], plaats_thuis: str,
                   team_naam: str) -> tuple[dict[str, dict], set[str]]:
    """Leest alle pagina's; zolang er minstens een werkt, gaat het door."""
    result: dict[str, dict] = {}
    teams: set[str] = set()
    for url in urls:
        try:
            matches = parse_clubpagina(fetch_url(url), plaats_thuis, team_naam)
        except Exception as e:
            print(f"  waarschuwing: {url} niet te lezen: {e}", file=sys.stderr)
            continue
        if not matches:
            print(f"  waarschuwing: geen wedstrijden van {team_naam or 'het team'} "
                  f"op {url}", file=sys.stderr)
            continue
        for m in matches:
            m["details"] = urllib.parse.urljoin(url, f"/match-details?wedstrijdcode={m['code']}")
            result[m["code"]] = {**result.get(m["code"], {}), **m}
            teams.add(m["team"])
        print(f"  {matches[0]['team']}: {len(matches)} wedstrijden ({url})")
    if not result:
        raise SystemExit("Op geen enkele pagina wedstrijden gevonden - is de opbouw van "
                         "de site veranderd? Sla de pagina op en draai: "
                         "python sync.py --test pagina.html")
    return result, teams


# ------------------------------------------------------------------------- ICS
def esc(s: str) -> str:
    return (str(s).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def fold(line: str) -> str:
    """RFC 5545: regels max 75 octets."""
    out, b = [], line.encode("utf-8")
    while len(b) > 75:
        cut = 75 if not out else 74
        while (b[cut] & 0xC0) == 0x80:  # niet midden in een UTF-8-teken knippen
            cut -= 1
        out.append(b[:cut].decode("utf-8"))
        b = b[cut:]
    out.append(b.decode("utf-8"))
    return "\r\n ".join(out)


def utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(matches: dict[str, dict], naam: str, duur_min: int) -> str:
    now = utc(datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//voetbal-agenda//sportlink//NL", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", f"X-WR-CALNAME:{esc(naam)}", "X-WR-TIMEZONE:Europe/Amsterdam",
        "REFRESH-INTERVAL;VALUE=DURATION:PT3H", "X-PUBLISHED-TTL:PT3H",
    ]
    for m in sorted(matches.values(), key=lambda x: x["start"]):
        start = datetime.fromisoformat(m["start"])
        afgelast = "afgelast" in str(m.get("status", "")).lower() or m.get("afgelast")
        titel = f"{m['thuis']} - {m['uit']}"
        if m.get("uitslag"):
            titel += f" ({m['uitslag']})"
        if afgelast:
            titel = "AFGELAST: " + titel

        info = []
        for label, key in (("Competitie", "competitie"), ("Verzamelen", "verzameltijd"),
                           ("Vertrek", "vertrektijd"), ("Veld", "veld"),
                           ("Kleedkamer thuis", "kleedkamer_thuis"),
                           ("Kleedkamer uit", "kleedkamer_uit"),
                           ("Scheidsrechter", "scheidsrechter"), ("Status", "status")):
            if m.get(key):
                info.append(f"{label}: {m[key]}")
        info.append(f"Wedstrijdcode: {m['code']}")
        if m.get("details"):
            info.append(f"Details: {m['details']}")
        locatie = ", ".join(x for x in (m.get("accommodatie"), m.get("adres"), m.get("plaats")) if x)

        lines += [
            "BEGIN:VEVENT",
            f"UID:{m['code']}@voetbal-agenda",
            f"DTSTAMP:{now}",
            f"DTSTART:{utc(start)}",
            f"DTEND:{utc(start + timedelta(minutes=duur_min))}",
            f"SUMMARY:{esc(titel)}",
            f"DESCRIPTION:{esc(chr(10).join(info))}",
            f"STATUS:{'CANCELLED' if afgelast else 'CONFIRMED'}",
        ]
        if locatie:
            lines.append(f"LOCATION:{esc(locatie)}")
        if m.get("details"):
            lines.append(f"URL:{m['details']}")
        if m.get("verzameltijd") and not afgelast:
            # herinnering op verzameltijd, anders 1 uur vooraf
            try:
                vh, vm = map(int, str(m["verzameltijd"])[:5].split(":"))
                verz = start.astimezone(TZ).replace(hour=vh, minute=vm)
                mins = max(int((start - verz).total_seconds() // 60) + 30, 30)
            except ValueError:
                mins = 60
        else:
            mins = 60
        if not afgelast:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(titel)}",
                      f"TRIGGER:-PT{mins}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


# ------------------------------------------------------------------------ main
def main() -> None:
    client_id = os.environ.get("SPORTLINK_CLIENT_ID", "").strip()
    plaats_thuis = os.environ.get("PLAATS_THUIS", DEFAULT_PLAATS_THUIS).strip()
    team_naam = os.environ.get("TEAM_NAAM", DEFAULT_TEAM_NAAM).strip()

    if "--test" in sys.argv:  # parser controleren op een opgeslagen pagina
        bestand = sys.argv[sys.argv.index("--test") + 1]
        for m in parse_clubpagina(Path(bestand).read_text("utf-8"), plaats_thuis, team_naam):
            print(f"{m['start'][:16]}  {m['thuis']} - {m['uit']} {m['uitslag']}  "
                  f"@ {m['accommodatie']}  [{m['code']}] {m['status']}")
        return

    afgelast: set[str] = set()
    if client_id:
        if "--teams" in sys.argv:
            for t in sorted(get_teams(client_id), key=lambda t: str(pick(t, "teamnaam"))):
                print(f"{pick(t, 'teamnaam'):<30} teamcode={pick(t, 'teamcode')}  "
                      f"{pick(t, 'competitiesoort', 'leeftijdscategorie')}")
            return
        wanted = [t for t in os.environ.get("TEAMS", "").split(",") if t.strip()]
        teams = resolve_teams(client_id, wanted)
        print(f"Bron: Sportlink-API. Teams: {', '.join(str(pick(t, 'teamnaam')) for t in teams)}")
        nieuw = fetch_matches(client_id, teams)
        afgelast = fetch_cancellations(client_id)
        team_namen = {str(pick(t, "teamnaam")) for t in teams}
    else:
        urls = [u.strip() for u in os.environ.get("TEAM_URLS") or DEFAULT_TEAM_URLS.split(",")
                if u.strip()]
        print("Bron: teampagina('s) op de clubsite")
        nieuw, team_namen = fetch_clubsite(urls, plaats_thuis, team_naam)

    OUT_DIR.mkdir(exist_ok=True)
    state: dict[str, dict] = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text("utf-8"))

    # Toekomstige wedstrijden die niet meer in het programma staan zijn
    # verplaatst/geschrapt -> weghalen. Gespeelde wedstrijden blijven staan.
    nu = datetime.now(timezone.utc)
    for code, m in list(state.items()):
        if m.get("team") not in team_namen:
            del state[code]  # team niet meer gevolgd
        elif code not in nieuw and datetime.fromisoformat(m["start"]) > nu:
            del state[code]
    for code, m in nieuw.items():
        oud = state.get(code, {})
        # lege velden (bijv. nog geen uitslag) overschrijven bestaande info niet
        state[code] = {**oud, **{k: v for k, v in m.items() if v not in ("", None)},
                       "afgelast": bool(m.get("afgelast"))}
    for code in afgelast & state.keys():
        state[code]["afgelast"] = True

    naam = os.environ.get("AGENDA_NAAM") or (
        "Voetbal " + " / ".join(sorted(team_namen)) if len(team_namen) <= 3 else "Voetbal")
    duur = int(os.environ.get("WEDSTRIJDDUUR_MIN", "105"))

    STATE_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False), "utf-8")
    ICS_FILE.write_text(build_ics(state, naam, duur), "utf-8", newline="")
    print(f"{len(state)} wedstrijden -> {ICS_FILE}")


if __name__ == "__main__":
    main()
