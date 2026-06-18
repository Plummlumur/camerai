# Security-Audit — Raumzaehler Edge People Counter

- **Datum:** 2026-06-17
- **Commit:** `13efbb9` (branch `main`)
- **Scope:** Gesamte Applikation — FastAPI-API, Auth/Middleware, WebSocket,
  SQLite-Storage, XLSX-Export, IMX500-/Preview-Pfad, Frontend, Deploy-/Install-Skripte,
  Abhängigkeiten.
- **Methodik:** Manuelles Code-Review (Read/Grep), Datenfluss- und
  Trust-Boundary-Analyse, Konfig-/Default-Review, Secret-Scan über die
  Git-Historie. Kein DAST/Pentest gegen eine laufende Instanz.
- **Bedrohungsmodell:** Edge-Gerät (Raspberry Pi) im LAN, das ein Web-Dashboard
  auf `0.0.0.0` exponiert. Hauptangreifer: jeder Teilnehmer im selben Netz
  (Büro-LAN/WLAN, Gäste-VLAN, kompromittiertes Nachbargerät). Schützenswert:
  Belegungs-/Verlaufsdaten (Personenfrequenz = potenziell personenbezogen),
  Manipulation der Zählung, sowie — bei aktiviertem Preview — das Kamerabild.

---

## Zusammenfassung

Die Code-Qualität in Bezug auf die klassischen Injection-Klassen ist **gut**:
SQL ist durchgängig parametrisiert, das Frontend schreibt ausschließlich über
`textContent` (kein XSS-Sink), Secrets liegen nicht im Repo, und die
Passwort-Speicherung (PBKDF2, 200k Iterationen, Salt, konstantzeitiger
Vergleich) ist solide.

Das zentrale Risiko ist **nicht der Code, sondern die Default-Sicherheitslage**:
Authentifizierung und TLS sind ausgeschaltet ausgeliefert, die im Repo enthaltene
systemd-Unit bindet ungeschützt auf `0.0.0.0:8000` über Klartext-HTTP, und es
gibt keinerlei Brute-Force-/DoS-Schutz. Wird die App so wie geliefert deployt,
sind Daten, Belegungs­korrektur und (bei aktiviertem Preview) das Kamerabild für
das gesamte LAN offen.

| ID | Schweregrad | Titel |
|----|-------------|-------|
| H1 | **Hoch** | Auth & TLS standardmäßig deaktiviert; Repo-systemd-Unit exponiert ungeschützt auf `0.0.0.0`/HTTP |
| H2 | **Hoch** | Kein Brute-Force-/Rate-Limit-Schutz auf HTTP Basic Auth (Default-User `admin`) |
| M1 | Mittel | Klartext-HTTP als Default — Credentials & Daten unverschlüsselt im LAN |
| M2 | Mittel | Unauthentifizierter DoS: unbegrenzte MJPEG- & WebSocket-Verbindungen |
| M3 | Mittel | Fehlende Security-Header (Clickjacking, MIME-Sniffing, kein HSTS) |
| M4 | Mittel | Abhängigkeiten ungepinnt, kein Lockfile/Hashes (Supply-Chain) |
| M5 | Mittel | Kamera-Preview ohne Auth = Live-Videostream im LAN (Privacy-Bruch) |
| L1 | Niedrig | Kein CSRF-Schutz / kein `SameSite` auf zustandsändernden Endpunkten |
| L2 | Niedrig | Keine Passwort-Richtlinie; vorhersehbarer Default-Benutzername |
| L3 | Niedrig | Self-signed TLS: TOFU, keine Rotation, 10 Jahre Gültigkeit |
| L4 | Niedrig | Keine Obergrenzen (Korrektur-Wert, WS-Nachrichtengröße) |
| L5 | Info | Belegungskorrektur nicht einer Person zurechenbar (Shared Account) |

---

## Findings

### H1 — Auth & TLS standardmäßig aus; Repo-Unit exponiert ungeschützt auf `0.0.0.0`
**Schweregrad:** Hoch · **Kategorie:** Insecure Defaults / Broken Access Control

`config.py:33` setzt `auth_enabled = False`, `auth_password_hash = ""`. In
`api/main.py:107` wird die `BasicAuthMiddleware` **nur** registriert, wenn
`auth_enabled` *und* ein Hash gesetzt sind — andernfalls ist die komplette App
(Dashboard, `/api/*`, `/ws`, `/api/camera/stream`) ohne jede Authentifizierung
erreichbar.

Die mitgelieferte `deploy/raumzaehler.service:11` startet
`uvicorn … --host 0.0.0.0 --port 8000` **ohne** TLS und liest keine
Auth-Variablen. Wer diese Unit direkt verwendet (statt den interaktiven
`install.sh` zu durchlaufen), exponiert das Gerät offen im LAN. Folgen:

- Beliebiges Auslesen aller Belegungs-/Verlaufsdaten (`/api/status`,
  `/api/stats/*`, `/api/export/xlsx`).
- Manipulation der Zählung über `POST /api/occupancy` (siehe `api/routes.py:124`).
- Bei aktiviertem Preview: Zugriff auf den Live-MJPEG-Stream (siehe M5).

**Empfehlung:**
- Auth als sichere Voreinstellung behandeln: Beim Start mit
  `--host 0.0.0.0` und deaktivierter Auth mindestens eine laute Warnung loggen;
  idealerweise Default-Bind auf `127.0.0.1` und Exposition bewusst opt-in.
- Repo-`raumzaehler.service` so nicht als „ready to use" anbieten — entweder
  Auth/TLS-Platzhalter aufnehmen oder im Header dokumentieren, dass sie nur über
  `install.sh` erzeugt werden soll.
- README-Hinweis verschärfen: ohne Auth nicht auf Netzwerk-Interfaces binden.

---

### H2 — Kein Brute-Force-/Rate-Limit-Schutz auf Basic Auth
**Schweregrad:** Hoch · **Kategorie:** Broken Authentication

`BasicAuthMiddleware._authorized` (`api/auth.py:82`) prüft jede Anfrage
zustandslos, ohne Fehlversuche zu zählen, zu drosseln oder zu sperren. PBKDF2 mit
200k Iterationen begrenzt zwar die Rate serverseitig (CPU), aber auf einem Pi 4
sind weiterhin viele Versuche/Sekunde möglich. Kombiniert mit dem fest
vorhersehbaren Default-Benutzernamen `admin` (`config.py:34`) und ohne
erzwungene Passwortkomplexität (L2) ist Online-Brute-Force praktikabel —
insbesondere über Klartext-HTTP im LAN.

**Empfehlung:**
- Rate-Limiting / exponentielles Backoff pro Quell-IP auf fehlgeschlagene Auth
  (z. B. schlanke In-Memory-Sperre in der Middleware; kein zusätzliches
  Framework nötig).
- Optional fail2ban-kompatible Logzeile bei Auth-Fehlern.
- Mindest-Passwortlänge im Installer erzwingen (siehe L2).

---

### M1 — Klartext-HTTP als Default
**Schweregrad:** Mittel · **Kategorie:** Sensitive Data in Transit

TLS ist optional (`install.sh:170`) und in der Repo-Unit gar nicht vorgesehen.
Ohne HTTPS werden Basic-Auth-Credentials (Base64, nicht verschlüsselt) und alle
Daten im Klartext über das LAN übertragen — passiv mitlesbar (ARP-Spoofing,
WLAN-Sniffing, Span-Port). Das README rät zwar „Always pair auth with HTTPS",
erzwingt es aber nicht.

**Empfehlung:** Wenn `auth_enabled=true`, dann TLS verpflichtend (Start
verweigern oder laut warnen). Für reine LAN-Szenarien zumindest HSTS-fähige
Konfiguration anbieten (siehe M3).

---

### M2 — Unauthentifizierter DoS über unbegrenzte Streams/WebSockets
**Schweregrad:** Mittel · **Kategorie:** Denial of Service / Resource Exhaustion

Zwei unbeschränkte Ressourcen:

1. **MJPEG-Stream** (`api/routes.py:113`): `_mjpeg_frames` ist ein *synchroner*
   Generator, den Starlette pro Verbindung in einem Threadpool-Worker abarbeitet.
   Der Default-Threadpool (~40 Threads) ist endlich; genügend offene
   `/api/camera/stream`-Verbindungen erschöpfen ihn und blockieren dann auch alle
   übrigen sync-Endpunkte (`/api/status`, Export …). Bei deaktivierter Auth ist
   das vorbedingungsfrei auslösbar.
2. **WebSocket-Hub** (`api/hub.py`): `connect()` fügt jeden Client einer
   unbegrenzten Menge hinzu — keine Obergrenze, kein Idle-Timeout. Viele
   Verbindungen ⇒ Speicher-/Broadcast-Last.

**Empfehlung:**
- Max-Concurrent-Streams-Limit für `/api/camera/stream` (z. B. Zähler im
  `FrameBuffer`/State, 429 bei Überschreitung).
- Obergrenze für gleichzeitige WS-Clients im Hub; älteste/überschüssige
  ablehnen. Optional Ping/Idle-Timeout.
- Diese Endpunkte zwenigstens hinter Auth zwingen (H1).

---

### M3 — Fehlende Security-Header
**Schweregrad:** Mittel · **Kategorie:** Security Misconfiguration

Es werden keine `X-Frame-Options`/`Content-Security-Policy`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy` oder (bei TLS)
`Strict-Transport-Security` gesetzt (kein CORS/Headers-Setup in `api/main.py`).
Folgen: Das Dashboard inkl. Korrektur-Formular ist iframebar (Clickjacking auf
„Belegung setzen"), MIME-Sniffing auf den statisch ausgelieferten Dateien, kein
HSTS-Downgrade-Schutz.

**Empfehlung:** Schlanke Middleware, die o. g. Header setzt (`frame-ancestors
'none'`, `nosniff`, restriktive CSP — die App nutzt nur lokale Assets, also ist
`default-src 'self'` realistisch; Inline-Styles im Kamera-Overlay ggf. via
`style-src` berücksichtigen).

---

### M4 — Ungepinnte Abhängigkeiten / kein Lockfile
**Schweregrad:** Mittel · **Kategorie:** Supply-Chain

`requirements.txt` nutzt ausschließlich untere Schranken
(`fastapi>=0.115`, `uvicorn[standard]>=0.30`, `pydantic-settings>=2.6`,
`openpyxl>=3.1`). `install.sh`/`deploy.sh` führen `pip install -r` ohne
Versions-Pinning und ohne Hash-Verifikation (`--require-hashes`) aus. Ein
kompromittiertes oder fehlerhaftes Upstream-Release wird beim nächsten Deploy
ungeprüft gezogen; Builds sind nicht reproduzierbar.

**Empfehlung:** Exakte Pins + Lockfile (`pip-compile`/`uv lock`) mit Hashes;
`apt-get install` mit vorgeschaltetem `apt-get update` und definierten
Paketständen. Regelmäßiger Dependency-Scan (z. B. `pip-audit`).

---

### M5 — Kamera-Preview ohne Auth = Videostream im LAN
**Schweregrad:** Mittel · **Kategorie:** Privacy / Information Disclosure

Der Privacy-by-Design-Grundsatz (Rohvideo verlässt den Sensor nicht) gilt nur
solange `CAMERA_PREVIEW_ENABLED=false`. Ist der Preview für die Einrichtung
aktiviert *und* Auth aus (Default!), liefert `/api/camera/stream`
(`api/routes.py:113`, `counter/source_imx500.py:141`) ein Live-Kamerabild
(mit Personen-Boxen) ungeschützt an jeden im Netz. Der Schalter ist eine reine
Setup-Hilfe, aber das Zusammenspiel mit „Auth aus" hebelt das Datenschutz­ver­sprechen aus.

**Empfehlung:** Preview nur bei aktiver Auth erlauben (oder beim Start mit
„Preview an + Auth aus" hart warnen/abbrechen). Im UI/README betonen, dass der
Preview nach der Kalibrierung wieder deaktiviert wird.

---

### L1 — Kein CSRF-Schutz / kein `SameSite`
**Schweregrad:** Niedrig · **Kategorie:** CSRF

`POST /api/occupancy` ist zustandsändernd. Bei Basic Auth sendet der Browser die
Credentials automatisch mit, d. h. CSRF ist grundsätzlich relevant. Praktisch
mitigiert dadurch, dass kein CORS konfiguriert ist und der Request
`Content-Type: application/json` verlangt (Cross-Origin ⇒ Preflight ⇒ ohne
CORS-Freigabe blockiert). Verbleibendes Restrisiko, kein Token vorhanden.

**Empfehlung:** Bei späterem Wechsel auf Cookie-/Session-Auth (V2) zwingend
CSRF-Token oder `SameSite=Strict`. Solange Basic-Auth-only: niedrig, dokumentieren.

---

### L2 — Keine Passwort-Richtlinie; vorhersehbarer Default-User
**Schweregrad:** Niedrig · **Kategorie:** Authentication Hygiene

`install.sh:104` (`ask_secret`) prüft nur, dass die Wiederholung übereinstimmt —
keine Mindestlänge/Komplexität. Default-Benutzer ist `admin`. In Kombination mit
H2 erleichtert das Brute-Force.

**Empfehlung:** Mindestlänge (z. B. ≥ 12 Zeichen) erzwingen; optional Vorschlag,
den Benutzernamen zu ändern.

---

### L3 — Self-signed TLS: TOFU, keine Rotation
**Schweregrad:** Niedrig · **Kategorie:** TLS Configuration

`install.sh:280` erzeugt RSA-2048, 3650 Tage gültig, self-signed. Für LAN
akzeptabel, aber: Trust-on-First-Use (Nutzer klickt Browser-Warnung weg —
gewöhnt MITM-Akzeptanz an), keine Rotation, langer Gültigkeitszeitraum, Schlüssel
liegt unter `TARGET_DIR/certs/` (Key korrekt `chmod 600`).

**Empfehlung:** Kürzere Gültigkeit + dokumentierte Rotation; für Flotten (V2)
eine interne CA erwägen, damit Clients ein Root pinnen können.

---

### L4 — Fehlende Obergrenzen (Eingaben/Nachrichten)
**Schweregrad:** Niedrig · **Kategorie:** Input Validation / DoS

`CorrectionRequest.value` (`api/routes.py:43`) ist nur `ge=0` — kein oberes
Limit; ein absurd großer Wert wird als Occupancy gesetzt/gespeichert (kein
Speicherüberlauf, aber unsinniger Zustand). Der WS-Endpunkt
(`api/main.py:116`) liest `receive_text()` ohne Größenbeschränkung.

**Empfehlung:** Plausible Obergrenze für `value` (z. B. `le=100000`); WS-Eingaben
verwerfen/begrenzen (der Server erwartet ohnehin keine Client-Nachrichten).

---

### L5 — Belegungskorrektur nicht zurechenbar (Info)
**Schweregrad:** Info · **Kategorie:** Auditability

Single-Shared-Account by design (siehe `[[auth-architecture-split]]`). Der
`correction`-Event (`api/routes.py:129`) ist auditierbar *was/wann*, aber nicht
*wer*. Multi-User-Auth ist bewusst V2/Zentralserver. Hier nur als bekannte
Einschränkung festgehalten — keine Aktion am Edge nötig.

---

## Positiv hervorzuheben (keine Aktion nötig)

- **Keine SQL-Injection:** Alle Queries in `storage/events.py` sind
  parametrisiert (`?`-Bindings); `direction` zusätzlich per `CHECK`-Constraint
  eingeschränkt.
- **Kein XSS-Sink im Frontend:** `web/app.js` schreibt ausschließlich über
  `textContent`; kein `innerHTML`/`eval`/`document.write` mit Server-/Nutzerdaten.
- **Solide Passwort-Speicherung:** PBKDF2-HMAC-SHA256, 200k Iterationen,
  16-Byte-Zufallssalt, konstantzeitiger Vergleich (`secrets.compare_digest`).
  Auth-Vergleich ist timing-bewusst (beide Hälften werden ausgewertet,
  `api/auth.py:89`).
- **WebSocket ist von der Auth-Middleware mit abgedeckt** (`api/auth.py:64` lehnt
  den Handshake vor `accept` ab).
- **Keine Secrets im Repo:** `.env` ist gitignored und nicht eingecheckt; kein
  Passwort-Hash o. Ä. in der Historie (Secret-Scan negativ).
- **Installer-Hygiene:** Passwort wird via Umgebungsvariable (nicht argv) an
  Python übergeben (`install.sh:121`), erscheint also nicht in der Prozessliste;
  TLS-Key wird `chmod 600` gesetzt.
- **Hardware-Import-Isolation** (picamera2/cv2 nur lazy in `source_imx500.py`)
  reduziert Angriffsfläche/Abhängigkeiten auf Nicht-Pi-Systemen.
- **Statisches Ausliefern** über Starlette `StaticFiles` (Path-Traversal-sicher).

---

## Priorisierte Maßnahmenliste

1. **Sofort:** Defaults härten — bei `--host 0.0.0.0` + Auth aus laut warnen;
   Repo-`raumzaehler.service` nicht ungeschützt empfehlen; README schärfen (H1).
2. **Sofort:** Rate-Limiting/Backoff auf Auth-Fehlversuche; Mindestpasswortlänge
   im Installer (H2, L2).
3. **Kurzfristig:** TLS bei aktiver Auth verpflichten; Security-Header-Middleware
   (M1, M3).
4. **Kurzfristig:** Limits für MJPEG-/WS-Verbindungen; Preview nur bei aktiver
   Auth (M2, M5).
5. **Mittelfristig:** Dependencies pinnen + Lockfile/Hashes + `pip-audit` in den
   Workflow (M4).
6. **Backlog/V2:** CSRF/`SameSite` bei Session-Auth, interne CA für die Flotte,
   Wer-Attribution der Korrektur (L1, L3, L5).
