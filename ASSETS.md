# Befüllbare Blender-Gefäße

Neu: **Kaffeetasse, Trinkglas, Toilette, Schüssel und Eimer**.

`start.bat` startet das Spiel wie bisher. Unter dem Becken im Bereich
„Gefäße / aus Blender“ ein Objekt wählen und oberhalb seiner Öffnung mit
gedrückter linker Maustaste eingießen. Material und Werkzeuge bleiben frei
wählbar. Es ist jeweils ein Gefäß aktiv; ein Wechsel beginnt mit leerem Becken.
„Gefäß ausleeren“ behält das Objekt, „Leeren“ entfernt auch das Objekt.
Ein Auflösungswechsel behält das gewählte Gefäß und leert seinen Inhalt.

Die Objekte wurden in Blender 5.2 als extrudierte Schnittmodelle mit
abgerundeten Kanten erstellt. Das bestehende Spiel bleibt zweidimensional:
die offene Schnittansicht zeigt die Flüssigkeit im Inneren. Die Toilette ist
ein geschlossenes Auffanggefäß ohne Abfluss oder Spülfunktion. Die Gefäße
sind fest platziert; sie lassen sich nicht bewegen oder kippen.

- `vessels.blend`: bearbeitbare Blender-Szene mit allen fünf Modellen.
- `web/assets/*.glb`: einzelne 3D-Schnittmodelle mit Materialien.
- `web/assets/vessels.json`: aus Blender exportierte, triangulierte
  Spielgeometrie und zugehörige Wandkonturen. Der WebGL-Renderer zeichnet
  diese Meshes direkt; Blender ist zum Spielen nicht erforderlich.
- `build_assets.py`: reproduzierbarer Generator. Mit
  `blender --background --factory-startup --python build_assets.py` neu erzeugen.
- `containers.py`: Kollision und Abstand zu den exportierten Wandkonturen.

Die Physik weist neue Partikel innerhalb der Wände ab und projiziert fallende
Partikel an den Wandflächen nach außen. Wie die bisherigen Hindernisse nutzt
dies Positionsprojektion statt vollständiger SPH-Wandrandbedingungen.

Prüfung: `python -m unittest -v test_physics test_inclusions test_http test_containers`.
21 Tests bestanden; darunter Auffangen von oben für fünf Gefäße bei allen
drei Auflösungen, Wandabstand, Leeren, Szenenwechsel und Asset-Auslieferung.
Tasse und Toilette wurden zusätzlich im WebGL-Browser geprüft, die Tasse
mit dem Mauswerkzeug befüllt.
