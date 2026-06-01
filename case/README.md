# 3D-Druck Gehäuse

## Dateien

| Datei | Zweck |
|-------|-------|
| `case_params.scad` | Gemeinsame Maße — wird von beiden Hauptdateien eingebunden |
| `scanner_base.scad` | **Unterteil mit integrierter Frontplatte** — als ein Stück gedruckt |
| `scanner_lid.scad` | **Deckel** — separat gedruckt, mit 4× M2.5 Schrauben befestigt |
| `scanner_assembly.scad` | Vorschau der Montage (nur zur Visualisierung) |

## Druck-Reihenfolge

### 1. Unterteil (`scanner_base.scad`)
- Auf den **Boden** legen, Frontplatte zeigt nach **oben/vorne**
- Wandstärke: 2.4 mm → mindestens **3 Perimeter**
- Infill: 20 % Gyroid
- Schichthöhe: 0.2 mm
- **Keine Stützen nötig**, falls dein Slicer mit ≤45° Überhängen klarkommt
- Drucksdauer: ~6 h auf einem Standard-Drucker

### 2. Deckel (`scanner_lid.scad`)
- Wird automatisch **auf den Kopf gedreht** (PART="print")
- → Die später sichtbare Oberseite liegt auf dem Druckbett = beste Optik
- Gleiche Druckeinstellungen wie Unterteil
- Druckdauer: ~3 h

## Material

**PETG empfohlen:**
- Hitzebeständig (RPi kann 60 °C werden)
- Schlagfest, biegt eher als zu brechen
- UV-stabil, gut für Tisch/Werkstatt

Alternative: **PLA+** für reinen Innenraum-Einsatz (günstiger, einfacher zu drucken).

## Hardware-Stückliste

- **4× M2.5 × 8 mm Senkkopfschrauben** (für Deckel an Unterteil)
- **4× M2.5 Wärmeeinsätze** (Voron-Style, OD 3.8 mm) für die 4 Deckel-Bossen
- **4× M2.5 × 6 mm Schrauben + Wärmeeinsätze** für RPi-Befestigung
- **4× M2 × 5 mm Schrauben** für Display-Befestigung (direkt ins Kunststoff)

## Anpassen

Alle Maße liegen in `case_params.scad`. Häufige Anpassungen:

```scad
DISP_X = 5;          // Display nach links/rechts verschieben
DISP_Y = (H - DISP_H) / 2;   // vertikal mittig

ENC_X = W - 18;      // Encoder-Position
BUTTONS = [...];     // Anzahl/Position der Tasten

VENT_N = 18;         // Anzahl Belüftungsschlitze
```

Nach Änderung beide Hauptdateien neu rendern — die Parameter werden automatisch übernommen.

## Slicen-Tipps

- **Unterteil**: Naht hinten platzieren (nicht an Display oder Anschlüssen)
- **Deckel**: Naht in einer Ecke
- **Brim**: Bei PETG 5 mm rundherum gegen Warping
- **Z-Hop** aktivieren wegen der Bossen
