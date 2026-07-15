#!/usr/bin/env python3
"""
Twilight Watch – tägliche Analyse.

Ablauf:
  1. RSS-Feeds nach Twilight-Princess-Remake-Signalen abfragen.
  2. Claude klassifiziert jedes Item (Signaltyp, Quelle, Glaubwürdigkeit, relevant ja/nein).
     -> Das LLM extrahiert/kategorisiert nur. Es erfindet nichts und vergibt keine Scores.
  3. Der Hope-Index wird DETERMINISTISCH in Python berechnet (Gewicht × Vertrauen × Zeit-Decay).
  4. Ergebnis wird als data.json geschrieben; das statische Frontend liest es.

Benötigt die Umgebungsvariable ANTHROPIC_API_KEY (in GitHub als Secret hinterlegen).
"""

import os, json, math, datetime as dt, sys
import feedparser
from anthropic import Anthropic

# --- Modell: bei Bedarf aktuellen Namen unter docs.claude.com prüfen ---
MODEL = "claude-haiku-4-5-20251001"

# --- Quellen (reine RSS/JSON-Feeds, kein Scraping) ---
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
    "direct_scheduled":       12,  # Nintendo Direct in Aussicht
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
MAX_ITEMS = 40  # wie viele Feed-Items ans LLM gehen


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
            seen.add(link)
            # grober Vorfilter: muss Twilight Princess betreffen
            low = title.lower()
            if "twilight princess" not in low and "tp hd" not in low:
                continue
            published = e.get("published", "") or e.get("updated", "")
            items.append({"title": title, "url": link, "source": name, "published": published})
    return items[:MAX_ITEMS]


CLASSIFY_PROMPT = """Du bist ein Analyst für Nintendo-Leaks. Bewerte die folgenden News-/Forum-Items
ausschließlich danach, ob sie auf eine NEUE Fassung von "The Legend of Zelda: Twilight Princess"
für moderne Nintendo-Hardware (Switch / Switch 2) hindeuten – Remake, Remaster, Port oder NSO-Release.

Für JEDES Item gib ein Objekt zurück mit:
- "i": Index des Items (Zahl, wie unten)
- "relevant": true nur, wenn es wirklich um eine mögliche neue TP-Fassung geht (sonst false)
- "signal_type": einer von [official_announcement, listing, insider_claim, datamine, trademark,
  direct_scheduled, attention, context, negative_signal, noise]
- "source_key": kleingeschriebener Name der GENANNTEN Quelle/des Leakers, falls erkennbar
  (z.B. "nash weedle", "nate the hate", "jeff grubb", "official"), sonst "unknown"
- "note": ein knapper deutscher Satz, was das Item aussagt

Erfinde nichts. Bewerte nur, was im Titel steht. Antworte NUR mit JSON:
{"items":[...], "summary_de":"2 Sätze Gesamteinschätzung auf Deutsch"}

ITEMS:
"""


def classify(items, client):
    listing = "\n".join(f'{idx}. [{it["source"]}] {it["title"]}' for idx, it in enumerate(items))
    msg = client.messages.create(
        model=MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": CLASSIFY_PROMPT + listing}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


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


def build(items, cls):
    signals, total = [], 0.0
    by_i = {c["i"]: c for c in cls.get("items", []) if isinstance(c, dict) and "i" in c}
    for i, it in enumerate(items):
        c = by_i.get(i)
        if not c or not c.get("relevant"):
            continue
        stype = c.get("signal_type", "noise")
        base = SIGNAL_WEIGHTS.get(stype, 0)
        skey = (c.get("source_key") or "unknown").lower()
        cred = KNOWN_SOURCES.get(skey, KNOWN_SOURCES["unknown"])
        age = days_old(it["published"])
        decay = math.exp(-age / HALFLIFE_DAYS)
        contrib = base * cred * decay
        total += contrib
        signals.append({
            "title": it["title"],
            "source": it["source"] + (f" / {skey}" if skey not in ("unknown", "context", "attention") else ""),
            "source_key": skey,
            "signal_type": stype,
            "credibility": round(cred, 2),
            "date": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=age)).strftime("%Y-%m-%d"),
            "age_days": round(age),
            "contribution": round(contrib, 2),
            "note": c.get("note", ""),
            "url": it["url"],
        })

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
        "reasoning": cls.get("summary_de", "") or "Heute keine nennenswerten neuen Signale.",
        "thresholds": THRESHOLDS,
        "signals": sorted(signals, key=lambda s: abs(s["contribution"]), reverse=True),
    }


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY fehlt – breche ab, behalte altes data.json.", file=sys.stderr)
        sys.exit(0)  # kein harter Fehler: alter Stand bleibt bestehen
    items = fetch_items()
    print(f"{len(items)} relevante Feed-Items gefunden.")
    if not items:
        print("Keine Items – data.json unverändert.")
        return
    client = Anthropic(api_key=key)
    cls = classify(items, client)
    data = build(items, cls)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"data.json geschrieben. Index={data['index']} Verdikt={data['verdict']}")


if __name__ == "__main__":
    main()
