# SD-Karte vorbereiten – Automatischer Erststart

Ziel: SD-Karte einlegen, Pi einschalten, fertig. Kein SSH, kein Einloggen.

---

## Was du brauchst

- Raspberry Pi Imager (https://www.raspberrypi.com/software/)
- microSD-Karte (min. 16 GB, empfohlen 32 GB Class 10 A2)
- Die `sdr_scanner.zip` Datei

---

## Schritt 1 – Image schreiben

1. Raspberry Pi Imager öffnen
2. **Gerät:** Raspberry Pi 3 (oder Zero 2 W)
3. **Betriebssystem:** Raspberry Pi OS Lite (64-bit)
4. **Speichermedium:** deine microSD-Karte
5. Vor dem Schreiben: **Einstellungen-Icon (Zahnrad)** klicken

### Einstellungen im Imager

| Einstellung | Wert |
|---|---|
| Hostname | `sdr-scanner` |
| SSH aktivieren | ✓ Ja (zur Sicherheit) |
| Benutzername | `pi` |
| Passwort | beliebig (z.B. `raspberry`) |
| WLAN | **leer lassen** – Pi macht eigenen Hotspot |
| Zeitzone | `Europe/Berlin` |
| Tastaturlayout | `de` |

→ **Schreiben** klicken, warten bis fertig

---

## Schritt 2 – Dateien auf die Boot-Partition kopieren

Nach dem Schreiben die SD-Karte kurz aus- und wieder einstecken.
Es erscheint ein Laufwerk namens **`bootfs`** (oder `boot`).

Folgende Dateien dort hineinkopieren:

```
bootfs/
├── sdr_scanner.zip     ← Das komplette Projekt-ZIP
└── firstrun.sh         ← Das Erststart-Script
```

`firstrun.sh` ist im ZIP unter `sdr_scanner/firstrun.sh` enthalten.

---

## Schritt 3 – Autostart einrichten

Es gibt zwei Methoden. **Methode A** ist einfacher, **Methode B** ist robuster bei SD-Karten die `fstrim` zum Hängen bringen.

---

### Methode A – cmdline.txt (einfach)

Auf der Boot-Partition `cmdline.txt` öffnen (Texteditor, **nicht** Word).

Die Datei enthält eine einzelne lange Zeile. **Am Ende** (kein Zeilenumbruch!) anhängen:

```
 systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot
```

> Auf älteren Pi-OS: Pfad `/boot/firstrun.sh` statt `/boot/firmware/firstrun.sh`

---

### Methode B – rc.local (robuster, empfohlen bei Hänger)

Falls der Pi beim ersten Boot bei `fstrim.service` hängt: diese Methode nutzen.

Datei `rc.local` auf der Boot-Partition anlegen (neue Datei, falls nicht vorhanden):

```bash
#!/bin/bash
# Einmalig beim ersten Boot ausgeführt (als root, nach rc.local-Service)
/boot/firmware/firstrun.sh
exit 0
```

Dann in `cmdline.txt` **nichts** ändern.

Stattdessen eine weitere Datei `firstrun_service` erstellen:

```ini
[Unit]
Description=SDR Scanner Erstinstallation
After=network.target
ConditionPathExists=/boot/firmware/firstrun.sh
ConditionPathExists=!/boot/firmware/firstrun.done

[Service]
Type=oneshot
ExecStart=/bin/bash /boot/firmware/firstrun.sh
RemainAfterExit=yes
StandardOutput=append:/boot/firmware/firstrun.log
StandardError=append:/boot/firmware/firstrun.log

[Install]
WantedBy=multi-user.target
```

Diese Datei als `firstrun.service` in `/etc/systemd/system/` ablegen – geht über die Boot-Partition nicht direkt, daher ist Methode A für die meisten Fälle einfacher.

**Kurzfassung: Methode A probieren. Wenn er bei fstrim hängt → kurz Strom weg, Methode B nutzen.**

---

## Schritt 4 – SD-Karte einlegen und einschalten

1. SD-Karte in den Pi einlegen
2. Netzteil anschließen (**min. 5V / 2,5A** beim 3B+)
3. Warten – der erste Boot dauert **3–8 Minuten**

Der Pi macht dabei automatisch:
- System-Pakete installieren
- RTL-SDR konfigurieren
- Hotspot einrichten
- Scanner-Service aktivieren
- Neu starten

Die grüne LED blinkt während der Installation unregelmäßig – das ist normal.

---

## Schritt 5 – Verbinden

Nach dem automatischen Neustart (LED hört auf unregelmäßig zu blinken):

1. WLAN-Liste öffnen
2. **`SDR-Scanner`** auswählen
3. Passwort: **`sdrscanner`**
4. Browser öffnen: **http://scanner.local**
   - oder: **http://192.168.4.1:5000**

---

## Fehlersuche

Falls etwas schiefläuft: Nach dem Boot die SD-Karte in den PC einlegen.
Auf der Boot-Partition liegt die Log-Datei:

```
bootfs/firstrun.log
```

Dort steht genau was passiert ist.

---

## SSID und Passwort anpassen (vor dem ersten Start)

Wenn du eigene WLAN-Daten willst: In `cmdline.txt` vor dem `systemd.run`-Teil anhängen:

```
FIRSTRUN_SSID=MeinScanner FIRSTRUN_PASS=meinpasswort12
```

Oder nach dem ersten Start in der Web-UI unter **WLAN-Hotspot → Einstellungen**.

---

## Nach der Einrichtung

Die `firstrun.sh` und der `systemd.run`-Eintrag in `cmdline.txt` werden automatisch entfernt.
Beim nächsten Neustart bootet der Pi normal und startet direkt den Scanner.

---

## Hinweis zur KI-Unterstützung

Diese Software wurde vollständig mithilfe von Claude (einem KI-Assistenten von Anthropic) entwickelt. Der Autor hat die Anforderungen definiert, Entscheidungen getroffen und das Ergebnis geprüft — der Code selbst wurde durch den Dialog mit der KI generiert.

---

## Haftungsausschluss

Die Software wird so bereitgestellt, wie sie ist (as-is), ohne jegliche Garantie auf Korrektheit, Vollständigkeit oder Eignung für einen bestimmten Zweck. Der Autor übernimmt keinerlei Haftung für Schäden, Datenverluste oder sonstige Probleme, die durch die Verwendung dieser Software entstehen. Die Nutzung erfolgt auf eigene Verantwortung.

---

## Lizenz

[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — Namensnennung erforderlich, keine kommerzielle Nutzung.
