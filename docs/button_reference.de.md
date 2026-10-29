# Tastenreferenz

Deutsche Fassung von [button_reference.md](button_reference.md).

Ein Knopf, vier Druckarten. Das System piept, um zu bestätigen, was es
verstanden hat.

## Druckarten

| Druckart     | Haltedauer     | Piepton    |
|--------------|----------------|------------|
| Kurz         | unter 0,8 s    | 1 kurz     |
| Lang         | 0,8 s bis 5 s  | 1 lang     |
| Sehr lang    | 5 s oder mehr  | 1 sehr lang (1 s) |
| Doppeltipp   | zwei kurze Drücke innerhalb von 0,6 s | 2 kurz |

Nach einem abgeschlossenen Filterzyklus hörst Du außerdem drei lange Pieptöne.

## Was die einzelnen Druckarten bewirken

### Im Ruhezustand

| Druck        | Wirkung                                                         |
|--------------|-----------------------------------------------------------------|
| Kurz         | Filtert für `filter_sec` (Standard 12 min)                      |
| Lang         | Filtert 1 Stunde                                                |
| Sehr lang    | Lange Spülung (`long_flush_sec`, Standard 15 min)               |
| Doppeltipp   | Handbetrieb starten (siehe unten)                               |

Stand die Anlage länger als `water_clean_sec` (Standard 5 min) still, läuft vor
der Filterphase eine kurze Vorspülung samt Verwurf. Das schützt Dich davor, das
erste abgestandene Wasser aus der Membran zu trinken.

### Während des Filterns (Pumpe läuft, Wasser kommt heraus)

| Druck        | Wirkung                                                         |
|--------------|-----------------------------------------------------------------|
| Kurz         | Stopp. Sauberes Herunterfahren.                                 |
| Lang         | Stopp UND die verstrichene Zeit als neuen `filter_sec` speichern (begrenzt auf 30 s bis 1 Stunde). Damit stellst Du die Dauer „Flasche voll“ ein. |
| Sehr lang    | Stopp und lange Spülung starten.                                |

Nach jedem Filterzyklus läuft die Membran-Nachspülung im Hintergrund,
eingestellt über `deferred_post_flush_sec` (Standard 30 s). Für Camper- und
mobile Aufbauten ist ein kleiner Wert sinnvoll, damit die Anlage schnell
abschaltbereit ist.

### Während der Vorspülung (vor einem Filterzyklus, Ventile in Spülstellung)

| Druck        | Wirkung                                                         |
|--------------|-----------------------------------------------------------------|
| Kurz         | Vorspülung überspringen, direkt filtern.                        |
| Lang         | Vorspülung überspringen, 1-Stunden-Filterung starten.           |
| Sehr lang    | Abbrechen und lange Spülung starten.                            |

### Während einer eigenständigen Spülung (Auto-Spülung oder lange Spülung per sehr langem Druck)

| Druck        | Wirkung                                                         |
|--------------|-----------------------------------------------------------------|
| Kurz         | Abbrechen. Zurück in den Ruhezustand, keine Folgefilterung.     |
| Lang         | Abbrechen. Zurück in den Ruhezustand, keine Folgefilterung.     |
| Sehr lang    | Abbrechen und eine neue lange Spülung starten.                  |

## Handbetrieb (Doppeltipp im Ruhezustand)

Der Handbetrieb dient der Desinfektionsprozedur des Herstellers (Schritte 2 und
4 im Handbuch des AquaMichel Mini), bei der nach jeder H₂O₂-Gabe 150 bis 200 ml
Wasser durch die Anlage gedrückt werden.

| Druck        | Wirkung                                                         |
|--------------|-----------------------------------------------------------------|
| Kurz         | Pumpe an/aus in Filterstellung. KEINE Vorspülung, KEINE Nachspülung, keine Hintergrundarbeit. |
| Lang         | Handbetrieb verlassen. Die Pumpe geht vorher sauber aus.        |
| Sehr lang    | Handbetrieb verlassen.                                          |
| Doppeltipp   | Wird ignoriert.                                                 |

Im Handbetrieb ist der Auto-Spül-Timer angehalten. Genau das macht die
einstündige H₂O₂-Einwirkzeit sicher: keine überraschende Spülung mittendrin.

## Verhalten im Hintergrund

- **Auto-Spülung:** alle `auto_flush_sec` (Standard 8 Stunden) läuft von selbst
  ein vollständiger Zyklus aus Vorspülung, Verwurf und Nachspülung, damit die
  Membran frisch bleibt. Der Timer startet nach jeder Spülung und jeder
  Filterung neu.
- **Verzögerte Nachspülung:** nach einem Filterzyklus wird die
  Membran-Nachspülung um `deferred_post_flush_sec` verzögert eingeplant. So
  kannst Du Dein Wasser sofort mitnehmen, und die Anlage kümmert sich im
  Hintergrund um die Membran. Ein neuer Zyklus bricht die anstehende
  Nachspülung ab.

## Geräusche, die auf einen Fehler hindeuten

| Geräusch                                     | Bedeutung                                 |
|----------------------------------------------|-------------------------------------------|
| Pumpe quält sich / kein Durchfluss            | Pumpe läuft gegen geschlossene Ventile (Deadhead). Sollte unmöglich sein; falls doch, Strom abschalten und die Relaisverdrahtung prüfen. |
| Schnelles Relaisklackern                      | Abbruch-und-Ersetzen-Konflikt. Normal sind nur saubere Klickfolgen. |
| Pumpe geht aus und sofort wieder an           | Das Druckabbau-Fenster wurde nicht eingehalten. Zwischen Aus und Ein müssen immer mindestens 3 s liegen. |
| Kein Begrüßungston beim Einschalten           | Problem mit der Summer-Verdrahtung oder beim MicroPython-Start. |
