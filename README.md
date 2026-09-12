# https://fluid.occdn.com 

# Neu: Milch, Zucker und Dampf

Milch mischt sich als Emulsion ein und hellt auf, womit sie in Berührung kommt;
Zucker hellt zusätzlich leicht nach. Kot löst sich in Säure langsam auf,
Erbrochenes schäumt darin statt sich aufzulösen. Heisse Oberflächen, Säure
an der Gefässwand und diese Reaktionen erzeugen aufsteigenden Dampf. Details
unten unter „Erweiterung: Emulsion, Reaktionen und Dampf“.

# Neu: Getränke und Säuren, die Gefässe durchfressen

Kaffee und Cola als weitere Flüssigkeiten. Dazu sieben ätzende Stoffe —
Schwefelsäure, Salzsäure, Salpetersäure, Flusssäure, Königswasser, Blausäure
und Natronlauge — die die Wand des gewählten Gefässes anfressen, durchlöchern
und den Inhalt auslaufen lassen. Details unten unter „Erweiterung: Säuren und
Korrosion“.

# Neu in 2.2: Speichern und Teilen

Kreationen mit Screenshot speichern und per Link teilen. PNG-Export für Beiträge und Stories. Update-Anleitung für fluid.occdn.com und dauerhafte Speicherung: [SHARING.md](SHARING.md).

# Neu: befüllbare Gefäße

Kaffeetasse, Trinkglas, Toilette, Schüssel und Eimer aus Blender sind unter dem Becken auswählbar. Details und Blender-Dateien: [ASSETS.md](ASSETS.md).

# FluidPy

Lokale 2D-Fluidsimulation: **Python berechnet die Physik**, WebGL 2 zeichnet
die Partikel und eine geglättete, beleuchtete Flüssigkeitsoberfläche. Kein externer Webdienst, keine CDN-Abhängigkeit und kein JavaScript-
Physikersatz. Deutsche Oberfläche. Python 3.10 oder neuer erforderlich.

## Start unter Windows

`start.bat` doppelklicken. Beim ersten Start wird im Projekt eine `.venv` angelegt
und NumPy installiert (dafür ist Internet nötig). Danach öffnet sich der Browser
unter http://127.0.0.1:8765. Das Konsolenfenster offen lassen; Strg+C beendet den
Server. Der Server ist ausschließlich auf der lokalen Loopback-Adresse erreichbar.

Alternativ im Projektordner:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

SciPy wird dringend empfohlen und beschleunigt die Nachbarsuche etwa um den
Faktor zwei:

```powershell
.\.venv\Scripts\python.exe -m pip install scipy
```

Anderer Port: `python app.py --port 8766`. Ohne automatisches Browserfenster:
`python app.py --no-browser`. Eine Serverinstanz teilt ein Becken zwischen allen
Browser-Tabs; nur einen aktiven Tab verwenden. Ohne pollenden Tab pausiert die
Simulationszeit.

## Dauerbetrieb (pm2, systemd, Reverse Proxy)

`python app.py --no-browser` startet ohne Browserfenster. Der Server bindet
standardmäßig nur an 127.0.0.1; `--host` ändert das, macht die Simulation aber
ohne Authentifizierung im Netz erreichbar. Für externen Zugriff gehört ein
Reverse Proxy davor.

Host und Port lassen sich auch über `FLUIDPY_HOST` und `FLUIDPY_PORT` setzen —
so ändert ein Prozessmanager die Bindung mit einem einfachen Neustart, ohne mit
neuen Kommandozeilenargumenten neu angelegt zu werden:

```bash
FLUIDPY_HOST=0.0.0.0 pm2 restart fluid-server --update-env
```

Kommandozeilenargumente haben Vorrang vor der Umgebung.

**Läuft der Reverse Proxy in einem Container**, muss die Bindung 0.0.0.0 sein:
`host.docker.internal` zeigt auf die Docker-Bridge des Hosts, nicht auf dessen
Loopback. Ein an 127.0.0.1 gebundener Prozess ist von dort nicht erreichbar und
ergibt 502. Port dann in der Host-Firewall von außen sperren.

`GET /api/health` liefert Version, Bindeadresse, Nachbarsuche und Rechenzeit —
damit ist ohne Rätselraten feststellbar, was tatsächlich läuft:

```bash
curl -s localhost:8765/api/health
# {"version": "2.0", "particles": 1248, "frame": 812, "compute_ms": 22.9,
#  "bind": "0.0.0.0:8765", "neighbours": "scipy"}
```

Dieselben Angaben stehen beim Start im Log:

```
FluidPy 2.0: http://127.0.0.1:8765
Bindung: 0.0.0.0:8765 · auf allen Adressen erreichbar, Firewall beachten · Nachbarsuche: SciPy
```

Steht dort `nur lokal, aus einem Docker-Container NICHT erreichbar`, kann ein
Reverse Proxy im Container den Prozess nicht erreichen — das ergibt 502.

nginx muss den Frame-Stream durchreichen statt ihn zu puffern. Der Server sendet
dafür `X-Accel-Buffering: no`; zusätzlich:

```nginx
location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_buffering off;
    proxy_read_timeout 180s;
}
```

Wird der Stream trotzdem verschluckt, merkt der Client das nach zwei Versuchen
und fällt selbsttätig auf Einzelabfragen zurück — langsamer, aber funktionsfähig.

Abgebrochene Verbindungen — Tab geschlossen, Seite neu geladen, Navigation
während einer laufenden Antwort — werden abgefangen, statt als
`BrokenPipeError`-Traceback im Log zu landen. Die Same-Origin-Prüfung vergleicht
ohne Schema, damit die Anwendung hinter einem TLS-Proxy funktioniert; fremde
Origins werden weiterhin mit 403 abgewiesen. Ohne verbundenen Client pausiert
der Simulationsthread und verbraucht keine CPU.

**Ein Server, ein Becken.** Die Simulation ist global: alle gleichzeitigen
Besucher teilen sich dasselbe Becken, dieselben 5000 Partikel und denselben
Solver-Thread. Für eine öffentliche Adresse ist das eine bewusste Eigenschaft,
kein Mehrbenutzerbetrieb — mehr Besucher machen die Simulation nicht langsamer
pro Person, sie greifen aber alle in dieselbe Flüssigkeit.

## Docker

```bash
docker compose up -d --build
curl -s localhost:8765/api/health     # {"version": "2.0", ...}
docker compose logs -f
```

Das Abbild enthält NumPy und SciPy; eine Build-Toolchain ist nicht nötig, beide
kommen als fertige Wheels. Der Prozess läuft unprivilegiert (UID 10001) mit
schreibgeschütztem Dateisystem, ohne Capabilities und mit `no-new-privileges`.

Der Port wird bewusst nur an `127.0.0.1` des Hosts veröffentlicht — davor gehört
der Reverse Proxy aus dem vorigen Abschnitt. `"8765:8765"` ohne das führende
`127.0.0.1` würde die Simulation ohne Authentifizierung ins Netz stellen und die
Firewall des Hosts umgehen. Anderer Host-Port: `FLUIDPY_PORT=9000 docker compose up -d`.

Der Healthcheck fragt `/api/health` ab, ohne die Simulation aufzuwecken; eine
Instanz ohne Besucher bleibt also pausiert und gilt trotzdem als gesund.
`SIGTERM` fährt den Listener geordnet herunter, der Container stoppt in unter
einer Sekunde. Das Container-Log ist auf 3 × 10 MB begrenzt.

Docker ersetzt pm2 — nicht beides gleichzeitig auf denselben Port laufen lassen,
sonst belegt der alte Prozess ihn und der Container startet nicht.

### Traefik

`docker-compose.traefik.yml` veröffentlicht `https://fluid.occdn.com` über einen
nginx-Sidecar, der auf den FluidPy-Prozess des Hosts durchreicht. Zwei Punkte
entscheiden dabei über Funktion oder Fehlersuche:

- **Bindeadresse.** `host.docker.internal` zeigt auf die Docker-Bridge des
  Hosts, nicht auf dessen Loopback. Ein an 127.0.0.1 gebundener Prozess ist aus
  dem Container nicht erreichbar und liefert 502. Also
  `--host 0.0.0.0` starten und Port 8765 in der Host-Firewall von außen sperren.
- **`proxy_buffering off`.** Ohne das hält nginx die lange chunked-Antwort
  zurück und im Browser bewegt sich nichts.

Läuft FluidPy selbst als Container, entfällt der Sidecar: dann bekommt der
FluidPy-Container die Traefik-Labels direkt, mit
`loadbalancer.server.port=8765`.

## Bedienung

- Material wählen und **linke Maustaste gedrückt halten**: Flüssigkeit erzeugen.
- Eingießen, Rühren (mit Ziehen), Erhitzen/Zünden, Kühlen, Entfernen.
- Hindernis: einmal klicken, erzeugt einen festen Kreis.
- Dichte, dynamische Viskosität, Entzündbarkeit, Zündtemperatur und Kohäsion
  lassen sich als eigenes Material festlegen. Werte gelten für neue Partikel.
- Wasser, Öl, Alkohol, Sirup als vereinfachte Materialvorgaben.
- Einfülltemperatur, Pinselradius, Schwerkraft und Darstellung einstellbar.
- Pause/Leertaste; Einzelschritt; Leeren; Dammbruch oder Wasser-Öl-Schichten.
- Zum Zünden Öl erzeugen und die Oberfläche mit dem Wärmewerkzeug erhitzen.
- **Physikauflösung** (fein/mittel/grob) und **Bildschärfe** unter „04 / Leistung“.

## Leistung

Der Solver lief zuvor im Takt der Browser-Anfrage: jeder Frame wartete auf einen
kompletten Python-Zeitschritt, und das Ergebnis kam als JSON-Text zurück. Das
erzeugte das Ruckeln. Geändert wurde:

- **Entkoppelte Simulation.** Die Physik läuft in einem eigenen Thread und
  veröffentlicht Frames; der Browser zeichnet unabhängig davon mit 60 Hz und
  **interpoliert zwischen den beiden letzten Frames**. Auch wenn der Solver nur
  30-mal pro Sekunde liefert, bleibt die Darstellung flüssig.
- **Ein Stream statt Dutzender Anfragen pro Sekunde.** Eine einzige lange
  Antwort (`GET /api/stream`, chunked) trägt alle Frames. Anfragen entstehen nur
  noch durch Eingaben: im Leerlauf null, beim Ziehen rund 20 pro Sekunde. Eine
  komplette Sitzung inklusive Zeichnen, Zünden und Rühren kostet etwa 100
  HTTP-Anfragen statt mehrerer Tausend — das ist der Unterschied zwischen „läuft
  hinter nginx“ und „Bad Gateway“.
- **Kompaktes Binärformat.** 8 Byte pro Partikel: Position und Temperatur als
  uint16, Material und Brennzustand als uint8. Die Positionsauflösung beträgt
  27 µm auf 1,8 m, also ein Fünfhundertstel des Partikelabstands. Gegenüber JSON
  ist das etwa ein Fünfzehntel der Datenmenge, gegenüber float32 ein Zweieinhalbstel.
- **Eingaben warten nicht auf den Solver.** Werkzeugbefehle gehen in eine eigene
  Warteschlange mit eigener Sperre. Vorher hielt ein Simulationsschritt bei 5000
  Partikeln die Sperre rund 100 ms und ließ Zeiger-Anfragen praktisch verhungern:
  Rühren und Zeichnen kamen bei voller Füllung gar nicht mehr an.
- **Gedeckelte Bildrate.** Der Solver rechnet mit 1/120 s Schrittweite, sendet
  aber höchstens 40 Frames pro Sekunde — mehr bringt neben der Interpolation
  nichts. Gemessen: 340 kB/s bei 1248 Partikeln, 160 kB/s bei grober Auflösung.
- **Direkter GPU-Upload.** Der empfangene Puffer geht ohne JavaScript-Schleife
  pro Partikel in den Vertexbuffer; die GPU liest das uint16/uint8-Format direkt
  als normalisierte Attribute, Materialfarben liegen als Uniform-Palette im Shader. Der Dichtepass rendert mit 55 % Auflösung, weil ihn
  der Oberflächenpass ohnehin filtert. Die Gerätepixelrate ist auf 1,5 begrenzt.
- **Schnellerer Solver, gleiche Physik.** Strukturierte 1-D-Arrays statt
  (n, 2)-Zugriffen, zusammengefasste Kraftterme, aus den Materialpaaren
  vorberechnete Koeffizienten, `cKDTree` mit unbalanciertem Aufbau und eine
  vektorisierte Gitter-Nachbarsuche als NumPy-Ersatz für die frühere
  Python-Schleife. Gemessen am Originalcode: **Faktor 2,1 bis 2,7**.

| Szenario | vorher | nachher |
| --- | --- | --- |
| Dammbruch, 1248 Partikel | 118 ms/Frame | 55 ms/Frame |
| Wasser + Öl, 2288 Partikel | 405 ms | 185 ms |
| Becken mit 3000 Partikeln | 244 ms | 90 ms |
| Becken mit 5000 Partikeln | 480 ms | 225 ms |

Die Zahlen stammen von einem langsamen Zwei-Kern-Container und dienen dem
Vergleich, nicht als Absolutwert. Ein identischer Vergleichslauf über 0,67 s
Simulationszeit weicht vom Originalsolver um maximal 1,2·10⁻⁷ m ab: die
Beschleunigung ändert das Modell nicht.

**Was das nicht ist:** ein Echtzeitsolver für 5000 Partikel. NumPy bleibt
einkernig und interpretiert; ein voller SPH-Schritt kostet weiterhin Millisekunden.
Für echte Echtzeit die Physikauflösung auf *mittel* oder *grob* stellen — das
senkt die Partikelzahl und vergrößert den Zeitschritt und wirkt damit stärker als
jede Mikrooptimierung. Die Anzeige „Simulation / Realzeit“ zeigt weiterhin
ehrlich, wie weit die Simulationszeit hinter der Uhr liegt; es gibt keine
künstlichen Zeitsprünge.

## Physikalisches Modell und ehrliche Grenzen

Schwach kompressible Smoothed Particle Hydrodynamics (WCSPH), zweidimensional,
mit einem normierten Wendland-C2-Kernel. Abstand 0,015 m, Kernelradius 0,0375 m,
künstliche Schallgeschwindigkeit 15 m/s. Partikel repräsentieren gleich große
Referenzvolumina einer Scheibe mit Einheitsdicke; Masse = Referenzdichte × Volumen.
Numerische Packungsdichte wird aus der Volumensumme ermittelt. Die Zustandsgleichung
hat Exponent 7 und keinen negativen Druck. Paarweise Druck- und Viskositätskräfte
sind gleich und entgegengesetzt; unterschiedliche Massen erfahren unterschiedliche
Druckbeschleunigungen. Die Gravitation ist unabhängig von der Materialdichte.
Zeitschritte werden durch akustische CFL- und Viskositätsgrenzen beschränkt.
Eine symmetrische künstliche Viskosität nach Monaghan dämpft akustische Störungen
bei sich nähernden Partikeln; sie erzeugt zusätzliche numerische Dissipation.

**Das ist ein interaktives Näherungsmodell, keine wissenschaftlich validierte CFD
und keine exakte Simulation realer Stoffe.** Die maximal 5000 Partikel begrenzen
die räumliche Auflösung. Hohe Last verlangsamt die Simulationszeit; die Oberfläche
zeigt den Faktor zur Echtzeit. Keine künstlichen Echtzeitsprünge bei langsamer CPU.

Wände und Hindernisse verwenden Positionsprojektion und gedämpfte Stöße statt
voller SPH-Wandrandbedingungen. Das kann Druck- und Dichtefehler am Rand erzeugen.
Kohäsion und geringere Anziehung verschiedener Materialien approximieren
Oberflächeneffekte; keine kalibrierte Grenzflächenspannung oder echte Mischchemie.
Die Materialwerte sind illustrative Vorgaben, nicht temperaturabhängige Stoffdaten.

Wärmeübertragung tauscht paarweise Energie aus, ist für Interaktion beschleunigt
und enthält Abkühlung zur Umgebung. Verbrennung erfordert Brennstoff, Temperatur
und eine aus der Nachbardichte geschätzte freie Oberfläche als Sauerstoffersatz.
Sie setzt Wärme frei und verbraucht einen endlichen Brennstoffanteil. Restpartikel
bleiben bestehen: **keine Verdampfung, Gasphase, Rauchtransport, Stoffbilanz einer
echten Reaktion, latente Wärme oder chemische Kinetik**. Flammenmarkierungen zeigen
brennende Flüssigkeitspartikel, keine berechnete Flammengeometrie.

Fachlicher Hintergrund zur SPH-Diskretisierung:
[PySPH Gleichungsreferenz](https://pysph.readthedocs.io/en/main/reference/equations.html).
FluidPy ist eine eigenständige kompakte Implementierung und verwendet PySPH nicht
als Bibliothek.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_physics
```

Tests decken paarweise Impulserhaltung bei unterschiedlichen Massen, freien Fall,
begrenzten Dammbruch-Stabilitätslauf, selektive Zündung und Kühlung, Pause,
Überlappungsvermeidung, Hindernisse und Entfernen, das Vorzeichen der Druckkraft,
den Auflösungswechsel sowie das binäre Übertragungsformat ab. Sie ersetzen keine
Konvergenzstudie oder experimentelle Validierung.

## Dateien

- `app.py`: HTTP-Server, Eingabevalidierung, Simulationsthread, Frame-Stream.
- `physics.py`: Python/NumPy-Solver, optional SciPy-Nachbarsuche.
- `web/`: HTML5-Oberfläche, CSS und Canvas-Zeichnung.
- `test_physics.py`: numerische Regressionstests.
- `test_acids.py`: Ätzlöcher, Durchlass, Hindernisauflösung, Persistenz.
- `test_mixing.py`: Emulsion, Zucker, Auflösung in Säure, Dampf.
- `start.bat`: Windows-Start mit isolierter Python-Umgebung.
- `Dockerfile`, `docker-compose.yml`: Containerbetrieb hinter einem Reverse Proxy.
- `docker-compose.traefik.yml`: Veröffentlichung von fluid.occdn.com über Traefik.

## WebGL-Darstellung

Ein WebGL-2-fähiger Browser ist erforderlich. Keine Canvas2D-Ersatzdarstellung.

Getestet mit Chrome/Chromium und Firefox. Die Shader sind bewusst strikt nach
GLSL ES 3.00 geschrieben: `int`-Präzision wird in jedem Shader explizit gesetzt
(im Vertex-Shader ist der Default `highp`, im Fragment-Shader `mediump`; ein in
beiden deklariertes Uniform muss in Typ *und* Präzision übereinstimmen, sonst
scheitert das Linken). Das Vollbild-Dreieck der Oberflächenstufe nutzt ein
echtes Vertex-Attribut statt `gl_VertexID`, weil einzelne Treiber ohne
gebundenen Puffer nichts zeichnen. Scheitert der Renderer trotzdem, steht die
konkrete WebGL-Meldung in der Statuszeile unter dem Becken.
Der Renderer sammelt gewichtete Partikelfarben und Dichte in einer GPU-Textur.
Ein zweiter Shader erzeugt daraus eine zusammenhängende Oberfläche mit weicher
Kontur und Beleuchtung. Die Temperaturansicht nutzt denselben Oberflächenpass.
Die Partikelansicht zeichnet kleinere, geglättete Punkt-Sprites direkt per WebGL.
Hindernisse, Raster und Pinsel werden ebenfalls per Shader dargestellt.

Der Teilchenabstand ist einstellbar (1,5 / 2,0 / 2,6 cm); der Kernelradius folgt
mit dem Faktor 2,5. WebGL beschleunigt die Darstellung, nicht den Python-Solver.
Die Oberfläche bleibt eine visuelle Rekonstruktion, keine zusätzliche
physikalische Berechnung. Zwischen zwei Solver-Frames interpoliert der Browser
die Partikelpositionen linear; das ist Darstellungsglättung, kein Rechenschritt.
Bei Partikelzu- oder -abgang wird nicht interpoliert. Verlust und
Wiederherstellung des WebGL-Kontexts werden behandelt.

API-Hintergrund: https://developer.mozilla.org/en-US/docs/Web/API/WebGL2RenderingContext


## Erweiterung: Emulsion, Reaktionen und Dampf

### Milch und Zucker

Zwei Zutaten in der eigenen Gruppe **Zutaten**:

- **Milch** (1032 kg/m³, 0,0021 Pa·s) startet mit voller Emulsionsladung.
- **Zucker** (1590 kg/m³) ist deutlich dichter, sinkt daher ab und rührt beim
  Absinken mit.

Jedes Partikel trägt zwei zusätzliche Werte, `milk` und `sugar`. Beide wandern
wie die Wärme entlang der Nachbarpaare und werden dabei **erhalten**: ein Schuss
Milch verteilt sich über die ganze Tasse, erzeugt aber nie mehr Weiss, als
eingegossen wurde. Viel Milch in wenig Kaffee wird fast weiss, ein Tropfen in
einer vollen Tasse nur eine Spur. Rühren beschleunigt das Vermischen.

Der Shader macht daraus die Farbe: `milk` mischt bis zu 80 % Richtung Weiss,
`sugar` weitere 20 %. Dadurch wird zuerst der Kaffee heller, und der Zucker
hellt danach noch einmal etwas nach. Milch und Zucker sind als *mischbar*
markiert und bekommen deshalb keine abgesenkte Kohäsion gegenüber fremden
Stoffen — sie entmischen sich nicht künstlich.

Das Übertragungsformat wächst dafür von 8 auf 10 Byte je Partikel:
`uint16 x, y, temp` plus `uint8 kind, burning, milk, sugar`.

### Kot und Erbrochenes in Säure

Materialien haben zwei neue Kennwerte: `dissolves` (Zerfall pro Sekunde bei
vollem Säurekontakt) und `fizz` (Gasentwicklung). Der Säureanteil in der
Nachbarschaft wird pro Partikel aus denselben Paaren berechnet, die der Solver
ohnehin bildet, und auf Oberflächenkontakt hochgezogen: ein Klumpen schwimmt
meist auf der Säure, angegriffen wird nur die benetzte Aussenseite.

- **Kot-Klumpen** lösen sich von aussen nach innen auf; ein Klumpen ist nach
  rund zehn Sekunden verschwunden und gast dabei sichtbar.
- **Speisestückchen** und **Buchstabennudeln** lösen sich langsamer.
- **Erbrochenes** löst sich nicht auf, schäumt dafür kräftig — das ist der
  sichtbare Unterschied zum Kot.

Die Reaktion ist schwach exotherm: die Zone wird wärmer, was wiederum mehr
Dampf erzeugt. In Wasser passiert nichts davon.

### Dampf

Dampf ist ein eigenes Material mit negativer Schwerkraft (`gravity_scale`) und
Luftwiderstand (`drag`), der die Steiggeschwindigkeit auf etwa 0,4 m/s
begrenzt. Er ist nicht wählbar, sondern entsteht von selbst:

1. an freien Oberflächen ab etwa 62 °C, umso stärker je heisser,
2. wo Säure ein Loch durch die Gefässwand frisst,
3. wo Säure auf Kot, Speisereste oder Erbrochenes trifft.

Damit Dampf nur oben entsteht und nicht mitten in der Flüssigkeit, zählt der
Solver für jedes Partikel die Nachbarn oberhalb; gedampft wird nur, wo darüber
nichts mehr liegt. Jedes Dampfpartikel lebt 1,4 bis 3 Sekunden und verschwindet
dann. Die Zahl ist auf 650 gedeckelt, damit das Partikelbudget nicht aufgeht.
Der Renderer zeichnet Dampf als weiche, halbdurchsichtige Punkte über der
Flüssigkeit — nicht als Teil der Flüssigkeitsoberfläche.

## Erweiterung: Säuren und Korrosion

Die Materialliste ist in **Flüssigkeiten**, **Ekliges**, **Getränke** und
**Säuren** gegliedert. Neu sind:

- **Kaffee** (1002 kg/m³, 0,0013 Pa·s) und **Cola** (1044 kg/m³, 0,0017 Pa·s).
  Cola ist durch den Zucker etwas dichter und zäher; beide greifen nichts an.
- **Schwefelsäure** 96 % (1830 kg/m³, 0,0248 Pa·s): dicht und ölig.
- **Salzsäure** 37 %, **Salpetersäure** (rauchend), **Königswasser** (3:1).
- **Flusssäure**: die einzige Säure, die real Glas löst — hier die aggressivste.
- **Blausäure**: berüchtigt, chemisch aber eine sehr schwache Säure. Sie
  hinterlässt nur Ätzspuren und geht praktisch nie durch die Wand.
- **Natronlauge**: keine Säure, sondern Lauge; ätzt trotzdem.

### Wie das Durchfressen funktioniert

Jede Säure hat eine Ätzrate `corrosion` in Metern Lochradius pro Sekunde.
Liegt Säure an der Gefässwand an (Abstand < 1,4 Partikelabstände), entsteht dort
eine Ätzstelle: ein Kreis auf der Wand. Bestehende Stellen wachsen weiter, neue
entstehen nur vereinzelt und mit mindestens 10 cm Abstand, damit der Frass über
die Wand wandert, statt sie gleichmässig zu lochen. Höchstens 32 Stellen,
maximal 7,5 cm Radius.

Bis 1,8 cm Radius ist die Stelle nur eine Mulde in der Wandstärke — sichtbar,
aber noch dicht. Erst darüber geht sie durch: die Kollision lässt Partikel in
diesem Kreis passieren, und derselbe Kreis wird im Shader aus dem Gefäss
herausgeschnitten, mit dunkelgrün angefressenem Rand. Die Statuszeile zeigt
erst „GEFÄSS WIRD ANGEÄTZT“, dann die Zahl der durchgefressenen Löcher.

Warme Säure ätzt schneller, gedeckelt bei dreifachem Tempo — das Werkzeug
„Erhitzen“ beschleunigt den Angriff spürbar. Gesetzte Hindernisse schrumpfen
unter Säure und verschwinden, wenn ihr Radius unter den Partikelabstand fällt.
„Gefäss ausleeren“ und jede neue Gefässwahl stellen die Wand wieder her;
gespeicherte Kreationen behalten ihre Löcher.

Die Ätzraten sind Spielwerte, keine kalibrierten Korrosionsdaten. Die Rangfolge
folgt dem realen Verhalten der Stoffe gegenüber Glas, Keramik und Metall, die
absoluten Zeiten nicht. Es gibt keine Reaktionsprodukte, keine Verdünnung, keine
Wärmetönung und keinen Säureverbrauch: eine Säure ätzt unbegrenzt weiter.

## Erweiterung: Klumpen, Stückchen und Buchstabensuppe

Vier zusätzliche Materialien und Startszenen sind direkt auswählbar:

- **Durchfall:** dünnflüssige braune Mischung (0,035 Pa·s).
- **Kot-Klumpen:** kompakte braune Körper mit angenäherter Formerhaltung.
- **Erbrochenes:** gelbgrüne Flüssigkeit (0,18 Pa·s) mit orangefarbenen Speisestückchen.
- **Buchstabensuppe:** rote Brühe mit hellen Nudelbuchstaben A, E, F, H, L, O, P, U.

Eingießen erzeugt pro freiem Pinselabdruck einen Klumpen bzw. eine Einlage mit
umgebender Flüssigkeit. Die Buchstaben wechseln der Reihe nach. Am Rand, in
Hindernissen oder bei Platzmangel werden unvollständige Einlagen ausgelassen.
Rühren, Schwerkraft, Temperatur, Entfernen und Auflösungswechsel funktionieren
auch mit den neuen Materialien. Stückchen und Nudeln sind interne Materialien;
eigene Mischungen bleiben über das vorhandene Formular möglich.

Einlagen bestehen aus SPH-Partikeln, deren Anordnung pro Zeitschritt auf eine
rotierte Ausgangsform projiziert wird. Dadurch reagieren sie auf Flüssigkeitskräfte
und behalten ihre Form weitgehend bei. Kollisionen können sie kurzfristig verformen.
Es handelt sich um ein illustratives Modell, nicht um kalibrierte Rheologie oder
einen exakten Starrkörpersolver. WebGL zeichnet Einlagen getrennt über der Flüssigkeit,
damit Stücke und Nudelkonturen erkennbar bleiben; thermische Farben und der
Partikelmodus bleiben verfügbar. Das Binärformat bleibt bei 8 Byte pro Partikel.

Start: `python fluid_server.py` oder unter Windows `start.bat`.
`app.py` stellt den von vorhandenen Startskripten erwarteten Einstieg bereit.
Tests: `python -m unittest -v test_physics test_inclusions test_http`.
