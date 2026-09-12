# FluidPy 2.2 – Speichern und Teilen

## Bedienung

1. Gefäß, Flüssigkeiten und Hindernisse im Becken gestalten.
2. **Speichern & Teilen** anklicken. Es entsteht eine unveränderliche Kopie
   des aktuellen Zustands mit einem passenden Screenshot.
3. Freigabelink kopieren oder über das Teilen-Menü weitergeben.
4. Für soziale Medien stehen **Beitrag (1080 × 1080)** und
   **Story (1080 × 1920)** als PNG-Download und, auf unterstützten Geräten,
   über das native Teilen-Menü bereit. Die Bilder enthalten den Freigabelink.

Facebook erhält zusätzlich eine serverseitige Open-Graph-Bildvorschau
(1200 × 630). Der Facebook-Button öffnet den Teilen-Dialog; er veröffentlicht
nichts automatisch. Welche Vorschau Facebook tatsächlich zeigt, entscheidet
Facebook. Die Zielseite und ihr Vorschaubild müssen öffentlich erreichbar sein.

Für Instagram das Bild herunterladen oder über das native Teilen-Menü an die
App weiterreichen, sofern das Gerät sie als Ziel anbietet. Den kopierten Link
bei Bedarf mit Instagrams Link-Sticker in eine Story einfügen. Eine PNG-Datei
selbst enthält keinen anklickbaren Link. Es gibt keine automatische Anmeldung
oder Veröffentlichung bei Facebook oder Instagram.

Ein Freigabelink zeigt zunächst ausschließlich die gespeicherte, pausierte
Kreation. **Im gemeinsamen Becken öffnen** lädt sie ausdrücklich ins globale
Live-Becken und ersetzt dessen Inhalt. Danach kann man mit „Fortsetzen“
weitersimulieren. Das Original hinter dem Freigabelink bleibt unverändert.

Gespeichert werden Gefäß, Hindernisse, eigene Materialien, Partikelpositionen,
Geschwindigkeiten, Temperaturen, Brennstoff/Brennzustände, Festkörpergruppen,
Schwerkraft, Auflösung, Simulationszeit und Zufallszustand. Darstellung,
gewähltes Material, Pinselradius und Einfülltemperatur werden ebenfalls erfasst.
Screenshot und Daten stammen aus derselben Aufnahme; die Simulation muss dafür
nicht dauerhaft angehalten werden.

## Update auf fluid.occdn.com

**Diese ZIP enthält den Code, keine bereits veröffentlichten Änderungen.**
Die vorhandenen Dateien durch die neue Version ersetzen und den Python-Prozess
neu starten. Vorhandene Datenverzeichnisse bei künftigen Updates beibehalten.

Neue Abhängigkeit: Pillow. Mit der Python-Umgebung des laufenden Servers:

```bash
python -m pip install -r requirements.txt
```

Unter Windows übernimmt `start.bat` die Installation auch bei einer schon
vorhandenen virtuellen Umgebung ohne Pillow.

Für den öffentlichen Server setzen:

```bash
export FLUIDPY_PUBLIC_URL=https://fluid.occdn.com
export FLUIDPY_DATA_DIR=/var/lib/fluidpy
python app.py --no-browser --host 0.0.0.0 --port 8765
```

`FLUIDPY_DATA_DIR` muss ein dauerhaftes, vom Serverprozess beschreibbares
Verzeichnis sein. Ohne Einstellung ist es `data/` neben `sharing.py`.
Bei pm2 diese Variablen in der vorhandenen Prozesskonfiguration setzen und
mit `--update-env` neu starten. Die vorhandene Host-/Port-Konfiguration erhalten.

Die enthaltene `docker-compose.yml` bindet für Freigaben ein benanntes Volume
`fluidpy-shares` unter `/app/data` ein. Der restliche Container bleibt
schreibgeschützt. Update: `docker compose up -d --build`.
**Das Datenvolume nicht löschen**, sonst verlieren die Links ihren Inhalt.
Wenn nur der Traefik-Sidecar genutzt wird, gelten die Datenverzeichnis- und
Umgebungsvariablen für den Python-Prozess auf dem Host, nicht für den Sidecar.

Der Reverse Proxy muss `/api/capture`, `/api/shares`, `/api/restore`,
`/api/shares/<id>` und `/s/<id>` einschließlich der PNG-Unterpfade an Python
weiterleiten. Für nginx mindestens `client_max_body_size 10m;` setzen
(das Backend akzeptiert maximal 9 MB). Eine reine statische Dateiauslieferung
reicht für die gespeicherten Links nicht. Der vorhandene Stream benötigt
weiterhin `proxy_buffering off`.

Prüfung nach dem Neustart: `/api/health` meldet **2.2**. Bei alter Oberfläche
Browser mit Strg+F5 neu laden. Einen neuen Link erzeugen und in einem anderen
Browser öffnen; auch `/s/<id>/preview.png` muss ohne Anmeldung erreichbar sein.

## Speicher und Betrieb

Die Datei `shares.sqlite3` enthält Zustand und alle drei Bilder atomar in
einem Datensatz. Links sind zufällig und bleiben über Neustarts erhalten.
Jeder mit dem Link kann sie sehen. Es gibt keine öffentliche Auflistung,
keine Konten und keine automatische Löschung alter Freigaben.

Standardgrenzen: 1000 Freigaben insgesamt und etwa 1 GB gespeicherte Nutzdaten.
`FLUIDPY_MAX_SHARES` ändert die Anzahlgrenze. Bei vollem Speicher werden neue
Freigaben mit einer Meldung abgewiesen; vorhandene bleiben erhalten.
Die SQLite-Datei regelmäßig mit SQLite-Backupwerkzeugen oder bei gestopptem
Server sichern. Die ZIP enthält keine Testfreigaben und keine Datenbank.

## Geprüft

```bash
python -m unittest -v test_physics test_inclusions test_http test_containers test_sharing
```

24 Tests: bestehende Physik, Gefäßkollisionen, vollständiger Zustands-Roundtrip,
Persistenz mit neu geöffneter Datenbank, Bildvalidierung, Freigaberouten,
Open-Graph-Metadaten, unveränderliche Vorschau und explizites Wiederherstellen.
Im Browser geprüft: Screenshot enthält Flüssigkeit, Speicherdialog liefert
Links/Bilder, Freigabeseite lädt als eigenständige pausierte Vorschau.

Grundlagen: [Open Graph](https://ogp.me/) und
[Web Share API](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/share).
