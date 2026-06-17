# Raumzaehler — To-dos

Plan: `docs/superpowers/plans/2026-06-12-raumzaehler-v1.md`

## Version 1 — Einzelgeraet (Zaehlfunktion + lokales Dashboard)

Implementiert auf Branch `feature/v1-einzelgeraet` (50 Tests gruen, ruff sauber, Dashboard im Browser verifiziert).

- [x] Task 1: Project scaffolding (deps, tool config, packages)
- [x] Task 2: Configuration (`config.py`)
- [x] Task 3: Time helpers (`timeutils.py`)
- [x] Task 4: Event store (SQLite, WAL, aggregates)
- [x] Task 5: Centroid tracker
- [x] Task 6: Line crossing + occupancy state
- [x] Task 7: Detection sources (interface, simulator, factory)
- [x] Task 8: Counting service
- [x] Task 9: FastAPI app (lifespan, status, static, websocket hub)
- [x] Task 10: Stats endpoints, correction, WS broadcast
- [x] Task 11: Dashboard frontend (dark, live, chart)
- [x] Task 12: IMX500 camera source (Pi only)
- [x] Task 13: Deployment (systemd, deploy.sh, README)

## Pi-Inbetriebnahme (kam-01)

Erstes Bring-up am 2026-06-15 erfolgreich: Service laeuft mit `COUNTER_SOURCE=imx500`,
Kamera exklusiv gegriffen, On-Sensor-Inferenz liefert Frames, API/Dashboard erreichbar.

Dabei behoben:
- [x] Deployment war unvollstaendig (nur `deploy/`-Inhalt im Ziel) -> App lokal nach
      `/home/pi/raumzaehler` synchronisiert, venv gebaut
- [x] `python3-opencv` (cv2) fehlte -> per apt installiert; jetzt in README + deploy.sh
- [x] `deploy.sh`: repo-root-verankert, `PI_HOST=local`-Modus (kein ssh), `.env`-Schutz
- [x] Counter-Thread-Resilienz: IMX500-Quelle reconnectet mit Backoff statt Thread-Tod

Noch offen (vor Ort):
- [x] IMX500-Box-Parsing korrigiert (Boxen bereits 0..1-normiert, Reihenfolge y0,x0,y1,x1, Clamping; `_person_detections` geteilt mit Preview-Overlay); durch funktionierende Live-Zaehlung bestaetigt
- [x] Reale Durchgaenge getestet (2026-06-17 erfolgreich); `INVERT_DIRECTION=false` passt, Richtungszuordnung korrekt
- [x] Reboot-Ueberlebenstest bestanden (2026-06-17): Service-Autostart nach Boot, DB integer, alle vor dem Reboot committeten Events unversehrt (WAL + synchronous=FULL), Belegung korrekt per Replay rekonstruiert
- [x] Resilienz-Fix + Kamera-Preview deployt und live verifiziert (MJPEG, 640x480)

## Kamera-Preview (Einrichtungshilfe)

Opt-in MJPEG-Stream mit Zaehllinien-Overlay im Dashboard, `CAMERA_PREVIEW_ENABLED`
(default aus, Privacy). Aus derselben Capture-Schleife wie die Zaehlung (nur ein
Kamerazugriff moeglich). Aktuell auf kam-01 in `/home/pi/raumzaehler/.env` AKTIVIERT
fuer die Linienjustage -> nach dem Einrichten auf `false` setzen + Service neu starten.

## Tech Debt (bewusste v1-Trade-offs, aus Reviews)

- Correction-Event wird nach In-Memory-`set_count` geschrieben (winziges Audit-Ordering-Fenster)
- `OccupancyState.count`-Read ohne Lock (CPython-atomar; bei free-threaded Python pruefen)
- Ein Test greift auf `store._conn` zu (besser: `dump_events()`-Methode)
- `Centroid`-Alias dreifach definiert (source_base, tracker, counting)
- Kein Hysterese-Band an der Zaehllinie (Jitter zaehlt mehrfach; per Design durch Nacht-Reset/Korrektur abgefedert)

## Version 2 — Mehrgeraete-System (spaeter, noch ohne Plan)

- [ ] MQTT-Publisher aktivieren, zentrales Dashboard, echte Auth
