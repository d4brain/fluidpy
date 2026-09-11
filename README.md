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
- **Binärer Transport.** Partikel werden als rohes float32 (20 Byte pro Partikel)
  übertragen statt als JSON. Bei 5000 Partikeln entfallen damit rund 150 kB Text
  pro Frame sowie das Serialisieren und Parsen.
- **Direkter GPU-Upload.** Der Renderer schiebt den empfangenen Puffer ohne
  JavaScript-Schleife pro Partikel in den Vertexbuffer; Materialfarben liegen als
  Uniform-Palette im Shader. Der Dichtepass rendert mit 55 % Auflösung, weil ihn
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

- `app.py`: lokaler HTTP-Server, Eingabevalidierung, Simulationsthread.
- `physics.py`: Python/NumPy-Solver, optional SciPy-Nachbarsuche.
- `web/`: HTML5-Oberfläche, CSS und Canvas-Zeichnung.
- `test_physics.py`: numerische Regressionstests.
- `start.bat`: Windows-Start mit isolierter Python-Umgebung.

## WebGL-Darstellung

Ein WebGL-2-fähiger Browser ist erforderlich. Keine Canvas2D-Ersatzdarstellung.
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
