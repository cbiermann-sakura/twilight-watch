# Twilight Watch

Eine Seite, die täglich eine Frage beantwortet: **Twilight Princess jetzt in einer alten Fassung
spielen – oder auf ein Remake für Switch / Switch 2 warten?**

Ein GitHub-Actions-Cron durchsucht einmal am Tag mehrere Feeds nach Leaks, Gerüchten und
Ankündigungen. Jeder Treffer wird per Keyword-Regeln klassifiziert (Signaltyp, Quelle,
Glaubwürdigkeit), und ein deterministisches Scoring verdichtet das zu einem **Hope-Index (0–100)**.
Das statische Frontend zeigt daraus ein Verdikt plus alle verlinkten Quellen.

**Komplett kostenlos** – kein API-Key, keine externen Dienste. Läuft rein in GitHub Actions.

## Wie der Index funktioniert

```
Beitrag_pro_Item = Basisgewicht(Signaltyp) × Glaubwürdigkeit(Quelle) × exp(-Alter_Tage / 30)
Index            = clamp( Σ Beiträge , 0 , 100 )
```

- **< 30** → *Spiel jetzt.* (kein belastbares Signal)
- **30–60** → *Grauzone.* (Signal ja, harte Belege nein)
- **> 60** → *Warte.* (es braut sich etwas zusammen)

Die Klassifikation läuft über Stichwort-Regeln in `analyze.py`. Sie versteht keinen Kontext,
nur Schlagwörter – für diese eng umrissene Frage reicht das. Es werden nur echte, gefetchte
URLs verlinkt; die Zahlen entstehen deterministisch.

## Dateien

| Datei | Zweck |
|-------|-------|
| `index.html` | statisches Frontend, liest `data.json` |
| `data.json` | aktuelles Ergebnis (wird täglich überschrieben) |
| `analyze.py` | Feeds holen → per Keywords klassifizieren → Index berechnen |
| `.github/workflows/daily.yml` | täglicher Cron + Auto-Commit |

## Setup

1. Repo anlegen und diese Dateien pushen.
2. **Settings → Pages** → Source: *Deploy from a branch*, Branch `main` / root.
3. **Actions**-Tab → *Daily Twilight Watch* → *Run workflow* (einmal manuell, danach läuft der Cron).

Die Seite liegt dann unter `https://<user>.github.io/<repo>/`.

Falls der Auto-Commit mit *permission denied* abbricht:
Settings → Actions → General → *Workflow permissions* → **Read and write**.

## Justieren

- Andere Schwelle? `THRESHOLDS` in `analyze.py`.
- Quelle mehr/weniger vertrauen? `KNOWN_SOURCES`.
- Gerüchte schneller/langsamer verblassen lassen? `HALFLIFE_DAYS`.
- Neue Stichwörter/Signaltypen? Die Wortlisten oben in `analyze.py` (LEAKERS, OFFICIAL, LISTING …).
- Weitere Feeds? `FEEDS`-Dict ergänzen (reine RSS-URLs).

## Grenzen der Keyword-Variante

Regeln erkennen Muster, keinen Sinn. Ironie, ungewöhnliche Formulierungen oder Signale im
Fließtext (statt im Titel) können durchrutschen. Wenn dir das zu grob wird, lässt sich die
`classify_one`-Funktion später gegen eine LLM-Klassifikation tauschen, ohne den Rest anzufassen.

## Hinweis

Der Index misst *Signalstärke*, nicht Wahrheit. Er verlinkt Quellen, druckt aber keine Artikel nach.
