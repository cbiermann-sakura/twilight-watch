# Twilight Watch

Eine Seite, die täglich eine Frage beantwortet: **Twilight Princess jetzt in einer alten Fassung
spielen – oder auf ein Remake für Switch / Switch 2 warten?**

Ein GitHub-Actions-Cron durchsucht einmal am Tag mehrere Feeds nach Leaks, Gerüchten und
Ankündigungen. Claude klassifiziert jeden Treffer (Signaltyp, Quelle, Glaubwürdigkeit), und ein
deterministisches Scoring verdichtet das zu einem **Hope-Index (0–100)**. Das statische Frontend
zeigt daraus ein Verdikt plus alle verlinkten Quellen.

## Wie der Index funktioniert

```
Beitrag_pro_Item = Basisgewicht(Signaltyp) × Glaubwürdigkeit(Quelle) × exp(-Alter_Tage / 30)
Index            = clamp( Σ Beiträge , 0 , 100 )
```

- **< 30** → *Spiel jetzt.* (kein belastbares Signal)
- **30–60** → *Grauzone.* (Signal ja, harte Belege nein)
- **> 60** → *Warte.* (es braut sich etwas zusammen)

Das LLM **extrahiert und kategorisiert nur** – die Zahlen entstehen deterministisch in `analyze.py`.
So gibt es keine halluzinierten Scores, und es werden nur echte, gefetchte URLs verlinkt.
Alle Gewichte stehen oben in `analyze.py` und lassen sich frei justieren.

## Dateien

| Datei | Zweck |
|-------|-------|
| `index.html` | statisches Frontend, liest `data.json` |
| `data.json` | aktuelles Ergebnis (wird täglich überschrieben) |
| `analyze.py` | Feeds holen → klassifizieren → Index berechnen |
| `.github/workflows/daily.yml` | täglicher Cron + Auto-Commit |

## Setup

1. Repo anlegen und diese Dateien pushen.
2. **Settings → Secrets and variables → Actions** → Secret `ANTHROPIC_API_KEY` hinterlegen.
3. **Settings → Pages** → Source: *Deploy from a branch*, Branch `main` / root.
4. **Actions**-Tab → *Daily Twilight Watch* → *Run workflow* (einmal manuell, danach läuft der Cron).

Die Seite liegt dann unter `https://<user>.github.io/<repo>/`.

## Justieren

- Andere Schwelle? `THRESHOLDS` in `analyze.py`.
- Quelle mehr/weniger vertrauen? `KNOWN_SOURCES`.
- Gerüchte schneller/langsamer verblassen lassen? `HALFLIFE_DAYS`.
- Weitere Feeds? `FEEDS`-Dict ergänzen (reine RSS-URLs).

## Hinweis

Der Index misst *Signalstärke*, nicht Wahrheit. Er verlinkt Quellen, druckt aber keine Artikel nach.
