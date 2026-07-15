#!/usr/bin/env python3
"""
Twilight Watch – tägliche Analyse (Option B: keyword-basiert, kein API-Key nötig).

Ablauf:
  1. RSS-Feeds nach Twilight-Princess-Signalen abfragen.
  2. Jedes Item per Keyword-Regeln klassifizieren (Signaltyp, Quelle, Relevanz).
  3. Hope-Index DETERMINISTISCH berechnen: Gewicht × Glaubwürdigkeit × Zeit-Decay.
  4. data.json schreiben; das statische Frontend liest es.

Läuft ohne externe API. Regeln verstehen keinen Kontext, nur Stichwörter –
für diese eng umrissene Frage reicht das erstaunlich weit. Alles frei justierbar.
"""

import json, math, datetime as dt, sys
import feedparser

# --- Quellen (reine RSS-Feeds, kein Scraping) ---
FEEDS = {
    "Google News": "https://news.google.com/rss/search?q=%22Twilight+Princess%22+(remaster+OR+remake+OR+Switch)&hl=de&gl=DE&ceid=DE:de",
    "Reddit GamingLeaks": "https://www.reddit.com/r/GamingLeaksAndRumours/search.rss?q=twilight+princess&restrict_sr=on&sort=new&t=month",
    "Reddit zelda": "https://www.reddit.com/r/zelda/search.rss?q=twilight+princess+switch&restrict_sr=on&sort=new&t=month",
    "Nintendo Life": "https://www.nintendolife.com/feeds/latest",
}
UA = "TwilightWatch/1.0 (+https://github.com/)"

# --- Scoring-Parameter (frei justierbar) ---
SIGNAL_WEIGHTS = {
    "official_announcement": 100,  # offiziell bestätigt -> sofort "warten"
    "listing":                40,  # Retailer / Ratings-Board (ESRB, PEGI, ...)
    "insider_claim":          28,  # Leaker-Aussage
    "datamine":               25,  # Fund im Code / in Dateien
    "trademark":              20,  # Marken-/Patentanmeldung
    "direct_scheduled":       12,  # Nintendo Direct terminiert
    "attention":               8,  # reine Medienwelle ohne neue Primärquelle
    "context":                 6,  # Umfeld (Jubiläum, Release-Lücke, Trend)
    "negative_signal":       -10,  # glaubwürdiges Dementi / Nicht-Bestätigung
    "noise":                   0,
}
KNOWN_SOURCES = {  # Glaubwürdigkeit 0..1 nach Track Record
    "official": 1.0, "nintendo": 1.0,
    "nate the hate": 0.8, "jeff grubb": 0.75,
    "nash weedle": 0.65, "attack the backlog": 0.55,
    "context": 1.0, "attention": 0.6,
    "unknown": 0.3,
}
HALFLIFE_DAYS = 30.0
THRESHOLDS = {"play": 30, "wait": 60}
MAX_ITEMS = 40

# --- Keyword-Regeln (Reihenfolge = Priorität, erste Übereinstimmung gewinnt) ---
LEAKERS = ["nash weedle", "nate the hate", "jeff grubb", "attack the backlog"]

SPECULATIVE = ["rumor", "rumour", "rumored", "rumoured", "leak", "leaked", "insider",
               "reportedly", "allegedly", "could", "might", "may ", "claims", "hints"]

NEGATIVE   = ["denies", "denied", "debunk", "not coming", "no plans", "false", "quashed",
              "shot down", "disput", "unlikely", "won't", "not happening"]
OFFICIAL   = ["officially announced", "confirms", "confirmed", "release date", "out now",
              "now available", "shadow drop", "revealed", "announced for", "launches", "release trailer"]
LISTING    = ["listing", "rated by", "esrb", "pegi", "retailer", "pre-order", "preorder", "amazon listing"]
DATAMINE   = ["datamine", "datamined", "found in the code", "files reveal", "code reveals"]
TRADEMARK  = ["trademark", "patent", "registered", "filing"]
DIRECT_WHEN = ["scheduled", "announced", "date set", "confirmed", "incoming", "this week", "tomorrow", "happening"]
INSIDER    = ["rumor", "rumour", "leak", "insider", "reportedly", "allegedly", "sources say", "claims"]
CONTEXT    = ["anniversary", "20th", "20-year", "for years", "wishlist", "wish list", "hope", "fans want"]
NEWVERSION = ["remaster", "remake", "port", "switch", "switch 2", "nso", " hd", "revised",
              "new version", "coming to", "revive", "re-release", "rerelease"]

NOTES = {
    "official_announcement": "Klingt nach offizieller Bestätigung.",
    "listing": "Eintrag bei Händler/Ratings-Board – oft ein starkes Vorzeichen.",
    "insider_claim": "Leaker-/Gerüchte-Aussage – mit Vorsicht zu genießen.",
    "datamine": "Angeblicher Fund im Code/in Dateien.",
    "trademark": "Marken-/Patent-Hinweis.",
    "direct_scheduled": "Bezug auf einen terminierten Nintendo Direct.",
    "attention": "Medien greifen das Thema auf, ohne neue Primärquelle.",
    "context": "Umfeld-Signal (Jubiläum, Wunschliste, Release-Lücke).",
    "negative_signal": "Dementi bzw. Nicht-Bestätigung – dämpft das Bild.",
    "noise": "",
}


def has(text, words):
    return any(w in text for w in words)


def detect_source(text):
    for name in LEAKERS:
        if name in text:
            return name
    return "unknown"


def classify_one(title):
    t = title.lower()

    # Relevanz: muss es um eine mögliche NEUE Fassung gehen
    if not has(t, NEWVERSION) and not has(t, DATAMINE + TRADEMARK + LISTING):
        return {"relevant": False, "signal_type": "noise", "source_key": "unknown", "note": ""}

    speculative = has(t, SPECULATIVE)

    # Priorität von stark nach schwach
    if has(t, NEGATIVE):
        stype, skey = "negative_signal", detect_source(t)
    elif has(t, OFFICIAL) and not speculative:
        stype, skey = "official_announcement", "official"
    elif has(t, LISTING):
        stype, skey = "listing", "official"
    elif has(t, DATAMINE):
        stype, skey = "datamine", detect_source(t)
    elif has(t, TRADEMARK):
        stype, skey = "trademark", "official"
    elif "nintendo direct" in t and has(t, DIRECT_WHEN):
        stype, skey = "direct_scheduled", "official"
    elif has(t, INSIDER) or detect_source(t) != "unknown":
        stype, skey = "insider_claim", detect_source(t)
    elif has(t, CONTEXT):
        stype, skey = "context", "context"
    else:
        stype, skey = "attention", "attention"

    return {"relevant": True, "signal_type": stype, "source_key": skey, "note": NOTES[stype]}


def fetch_items():
    items, seen = [], set()
    for name, url in FEEDS.items():
        try:
            feed = feedparser.parse(url, agent=UA)
        except Exception as e:
            print(f"[warn] {name}: {e}", file=sys.stderr)
            continue
        for e in feed.entries[:25]:
            title = (e.get("title") or "").strip()
            link = e.get("link") or ""
            if not title or link in seen:
                continue
            low = title.lower()
            if "twilight princess" not in low and "tp hd" not in low:
                continue
            seen.add(link)
            items.append({"title": title, "url": link, "source": name,
                          "published": e.get("published", "") or e.get("updated", "")})
    return items[:MAX_ITEMS]


def days_old(published):
    if not published:
        return 3.0
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            d = dt.datetime.strptime(published, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return max(0.0, (dt.datetime.now(dt.timezone.utc) - d).total_seconds() / 86400)
        except ValueError:
            continue
    return 3.0


def make_reasoning(index, signals):
    if not signals:
        return "Heute keine nennenswerten neuen Signale – die alte Fassung ist die sichere Wahl."
    top = signals[0]
    labels = {"official_announcement": "offizielle Ankündigung", "listing": "Listing",
              "insider_claim": "Leaker-Gerücht", "datamine": "Datamine", "trademark": "Trademark",
              "direct_scheduled": "Direct-Termin", "attention": "Medienwelle", "context": "Umfeld-Signal",
              "negative_signal": "Gegenstimme"}
    has_neg = any(s["signal_type"] == "negative_signal" for s in signals)
    parts = [f"Stärkstes Signal heute: {labels.get(top['signal_type'], top['signal_type'])} "
             f"({top['source']}). Insgesamt {len(signals)} relevante Einträge."]
    if has_neg:
        parts.append("Mindestens ein Dementi dämpft das Bild.")
    if index >= THRESHOLDS["wait"]:
        parts.append("Genug, um noch zu warten.")
    elif index >= THRESHOLDS["play"]:
        parts.append("Signal ja – harte Belege nein.")
    else:
        parts.append("Zu dünn für belastbare Hoffnung.")
    return " ".join(parts)


def build(items):
    signals, total = [], 0.0
    for it in items:
        c = classify_one(it["title"])
        if not c["relevant"]:
            continue
        stype = c["signal_type"]
        base = SIGNAL_WEIGHTS.get(stype, 0)
        skey = c["source_key"]
        cred = KNOWN_SOURCES.get(skey, KNOWN_SOURCES["unknown"])
        age = days_old(it["published"])
        decay = math.exp(-age / HALFLIFE_DAYS)
        contrib = base * cred * decay
        total += contrib
        signals.append({
            "title": it["title"],
            "source": it["source"] + (f" / {skey}" if skey in LEAKERS else ""),
            "source_key": skey,
            "signal_type": stype,
            "credibility": round(cred, 2),
            "date": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=age)).strftime("%Y-%m-%d"),
            "age_days": round(age),
            "contribution": round(contrib, 2),
            "note": c["note"],
            "url": it["url"],
        })

    signals.sort(key=lambda s: abs(s["contribution"]), reverse=True)
    index = max(0, min(100, round(total)))
    if index >= THRESHOLDS["wait"]:
        verdict, head, reco = "wait", "Warte.", "Es braut sich etwas zusammen – ich würde noch warten."
    elif index >= THRESHOLDS["play"]:
        verdict, head, reco = "grey", "Grauzone.", "Kannst spielen – aber behalt's im Auge."
    else:
        verdict, head, reco = "play", "Spiel jetzt.", "Kein belastbares Signal – spiel die alte Version."

    return {
        "updated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "index": index,
        "verdict": verdict,
        "headline": head,
        "recommendation": reco,
        "play_suggestion": "Beste jetzige Version: Twilight Princess HD (Wii U).",
        "reasoning": make_reasoning(index, signals),
        "thresholds": THRESHOLDS,
        "signals": signals,
    }


def main():
    items = fetch_items()
    print(f"{len(items)} Twilight-Princess-Items aus den Feeds.")
    if not items:
        print("Keine Items – data.json unverändert.")
        return
    data = build(items)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"data.json geschrieben. Index={data['index']} Verdikt={data['verdict']} "
          f"({len(data['signals'])} Signale).")


if __name__ == "__main__":
    main()
