# EU-AI-Act-Governance-Dokumentation — Raumzaehler Edge People Counter

- **Datum:** 2026-06-18
- **Commit/Stand:** `13efbb9` (branch `main`), V1 (Einzelgerät)
- **Gegenstand:** Raumzaehler — Edge-Personenzähler auf Raspberry Pi 4 mit
  Raspberry Pi AI Camera (Sony IMX500). On-Sensor-Personendetektion
  (MobileNet-SSD), Tracking, Linienzählung, lokale SQLite-Speicherung,
  Web-Dashboard. Künftig (V2) Flotte mit MQTT-Reporting an einen Zentralserver.
- **Bezugsrahmen:** Verordnung (EU) 2024/1689 (KI-Verordnung / „AI Act"),
  ergänzend DSGVO (VO (EU) 2016/679) als der tatsächlich materiell bindende
  Rechtsrahmen für dieses System.
- **Methodik:** Code- und Datenfluss-Analyse (`counter/`, `storage/`, `api/`,
  `config.py`, Deploy-Skripte), Abgleich mit den AI-Act-Risikokategorien,
  Rollen- und Pflichtenzuordnung. Aufbauend auf dem
  [Security-Audit vom 2026-06-17](security-audit-2026-06-17.md).

> **Disclaimer / Einordnung.** Dies ist eine **technisch-organisatorische
> Governance-Bewertung**, keine Rechtsberatung. Die Risikoklassifizierung nach
> AI Act ist eine begründete Selbsteinschätzung auf Basis des aktuellen Codes;
> die finale rechtliche Einordnung — insbesondere die datenschutzrechtliche
> Würdigung am konkreten Einsatzort — obliegt dem Betreiber bzw. dessen
> Datenschutzbeauftragten/Rechtsberatung. Artikelverweise dienen der
> Orientierung.

---

## 1. Zusammenfassung (Management-Sicht)

Raumzaehler ist nach Art. 3 Abs. 1 AI Act ein **KI-System** (es nutzt ein
maschinell gelerntes Detektionsmodell, MobileNet-SSD, COCO-Klasse „person").
Entscheidend für die Governance ist jedoch **was das System tut und was nicht**:

- Es **zählt anonym** Linienüberschreitungen (Eintritt/Austritt) und führt eine
  aggregierte Belegungszahl. Es erzeugt **keine** Identität, keine
  Wiedererkennung, keine biometrische Vorlage, keine personenbezogene Kategorie.
- Die Inferenz läuft **auf dem Sensor**; den Pi erreichen ausschließlich
  Bounding-Box-Koordinaten, kein Videobild (Privacy by Design, Art. 25 DSGVO).

**Risikoeinstufung nach AI Act:**

| Kategorie | Ergebnis | Begründung (Kurz) |
|-----------|----------|-------------------|
| Verbotene Praktik (Art. 5) | **Nein** | Keine biometrische Identifizierung/Kategorisierung, keine Emotionserkennung, kein Social Scoring. |
| Hochrisiko (Anhang III) | **Nein** | Personen*detektion* ≠ biometrische Identifizierung (Anhang III Nr. 1); keine Sicherheitskomponente kritischer Infrastruktur. |
| Spezifische Transparenzpflicht (Art. 50) | **Nicht einschlägig** | Kein KI-Mensch-Dialog, keine Emotionserkennung/biometrische Kategorisierung, keine synthetischen Inhalte. |
| **Resultat** | **Minimales / begrenztes Risiko** | Leichteste AI-Act-Stufe: keine Konformitätsbewertung, keine Registrierung, keine Hochrisiko-Pflichtenkette. |

**Kernbotschaft:** Der AI Act stellt für dieses System in V1 **keine
materiellen Produktpflichten** (Hochrisiko-Regime). Die für Raumzaehler real
bindenden Anforderungen kommen aus der **DSGVO** (Datenschutz durch
Technikgestaltung, Transparenz/Beschilderung, Löschkonzept, ggf. DSFA) sowie aus
zwei AI-Act-Querschnittspflichten, die unabhängig von der Risikoklasse gelten:
**KI-Kompetenz (Art. 4)** seit 2. Februar 2025.

**Drei Governance-Brennpunkte** (Details in Abschnitt 10–12):

1. **Kamera-Preview** (`CAMERA_PREVIEW_ENABLED=true`) hebelt Privacy by Design
   aus — dann verlässt ein Live-Bild den Sensor. Hier entsteht Personenbezug.
2. **Speicherbegrenzung:** Der Event-Log hat **kein Löschkonzept/Retention** —
   DSGVO-Art. 5 Abs. 1 lit. e.
3. **V2 (Zentralserver/MQTT)** ändert Datenflüsse und Mehrbenutzer-Auth → die
   AI-Act-/DSGVO-Bewertung ist **neu durchzuführen**, bevor V2 produktiv geht.

---

## 2. Systembeschreibung & Zweckbestimmung (intended purpose)

Eine präzise **Zweckbestimmung** ist die Grundlage jeder Risikoeinstufung
(Art. 3 Abs. 12 AI Act) und sollte als verbindliches Dokument geführt werden:

> **Zweckbestimmung Raumzaehler V1:** Anonyme Erfassung der aktuellen Belegung
> eines Raumes durch Zählen von Personen, die eine virtuelle Linie überschreiten
> (Eintritt/Austritt), zur Anzeige in einem lokalen Dashboard und zur
> historischen Auswertung (Tag/Woche/Monat). **Nicht** bestimmt zur
> Identifizierung, Wiedererkennung, Profilbildung, Verhaltens- oder
> Leistungsbewertung einzelner Personen.

Technische Pipeline (siehe `README.md` / `counter/service.py`):

```
IMX500-Sensor ─ Bounding-Boxes ─▶ DetectionSource ─▶ CentroidTracker
   (Inferenz on-sensor)                                   │ stabile IDs
                                                          ▼
   Dashboard ◀─ WS/REST ◀─ EventStore (SQLite) ◀─ LineCrossingCounter
```

Governance-relevante Eigenschaften, die direkt aus dem Code belegbar sind:

- **On-Sensor-Inferenz:** `counter/source_imx500.py` empfängt vom Sensor nur
  `get_outputs(...)`-Metadaten (Boxen/Scores/Klassen). Es gibt im Normalbetrieb
  **keinen Frame-Buffer** auf dem Pi (`frame_buffer=None`), also kein Bild.
- **Anonyme Zwischenrepräsentation:** Aus Boxen werden Centroiden `(x, y)` in
  `0..1` (`_centroids`). Der Tracker (`counter/tracker.py`) vergibt eine
  **flüchtige, laufzeit-lokale Track-ID** (Integer, nie persistiert, bei
  Verlust nach `max_missed` Frames verworfen). Diese ID ist **kein**
  personenbezogenes Identifikationsmerkmal — sie existiert nur im RAM für
  wenige Sekunden und referenziert keine Person über Sessions hinweg.
- **Persistierte Daten:** Ausschließlich Zählereignisse
  (`storage/events.py`): `events(id, ts_utc, direction ∈ {in,out,correction},
  value, sensor_id)`. **Keine** Bilder, keine Koordinaten, keine Track-IDs,
  keine Geräte-/Personenkennungen werden gespeichert.
- **Belegung** ist In-Memory-State (`OccupancyState`), nie < 0, nächtlicher
  Reset, manuelle Korrektur als auditierbares `correction`-Event.

---

## 3. Anwendbarkeit des AI Act

### 3.1 Ist Raumzaehler ein „KI-System"? — Ja

Art. 3 Abs. 1 definiert ein KI-System u. a. über ein maschinengestütztes System,
das aus Eingaben Ausgaben (hier: Personen-Bounding-Boxes) ableitet. Das
verwendete **MobileNet-SSD** ist ein trainiertes neuronales Netz → Raumzaehler
fällt in den **sachlichen Anwendungsbereich** des AI Act. (Die nachgelagerte
Zähllogik — Tracker, Linienkreuzung — ist klassische deterministische Software;
KI-Charakter stammt allein aus dem Detektionsmodell.)

### 3.2 Zeitlicher Anwendungsbereich

Die KI-Verordnung trat am **1. August 2024** in Kraft, mit gestaffelter Geltung:

| Datum | Anwendbar | Relevanz für Raumzaehler |
|-------|-----------|--------------------------|
| 2. Feb 2025 | Verbote (Art. 5), **KI-Kompetenz (Art. 4)** | **Art. 4 gilt bereits** (Abschnitt 9.1). |
| 2. Aug 2025 | GPAI-Regeln, Governance, Sanktionen | Nicht einschlägig (kein GPAI). |
| 2. Aug 2026 | Großteil inkl. **Hochrisiko Anhang III** | Nur relevant **falls** je Hochrisiko (derzeit nein). |
| 2. Aug 2027 | Hochrisiko Anhang I (Produktsicherheit) | Nicht einschlägig. |

### 3.3 Rollen (Art. 3 Abs. 3 / Abs. 4)

| Rolle | Wer | Pflichtenlage |
|-------|-----|---------------|
| **Anbieter** (provider) | Entwickler/Inverkehrbringer von Raumzaehler | Bei Hochrisiko: volle Pflichtenkette. **Hier: minimales Risiko** → im Wesentlichen Art. 4. |
| **Betreiber** (deployer) | Betreibende Organisation am Einsatzort (Raum) | DSGVO-Verantwortlicher; Beschilderung/Transparenz, Rechtsgrundlage, DSFA. |
| **Modell-Zulieferer** | Upstream (MobileNet-SSD, COCO-trainiert; via `imx500-models`) | Trainingsdaten/Modellprovenienz liegen **außerhalb** dieses Projekts (Abschnitt 9.4). |

Anbieter und Betreiber können hier personell zusammenfallen (Eigenbetrieb).
Wird das Gerät an Dritte abgegeben, ist die Rollenzuordnung **schriftlich
festzuhalten** — sie bestimmt, wer welche DSGVO-/AI-Act-Pflicht trägt.

---

## 4. Risikoklassifizierung im Detail

### 4.1 Verbotene Praktiken (Art. 5 AI Act) — nicht einschlägig

Abgleich mit den Verbotstatbeständen:

- **Echtzeit-Fernidentifizierung mittels biometrischer Daten in öffentlich
  zugänglichen Räumen** (Art. 5 Abs. 1 lit. h): Nein — keine Identifizierung
  (siehe Abschnitt 5).
- **Biometrische Kategorisierung nach sensiblen Merkmalen** (lit. g): Nein —
  keine Ableitung von Eigenschaften (Ethnie, politische Meinung, sexuelle
  Orientierung etc.).
- **Emotionserkennung am Arbeitsplatz/in Bildungseinrichtungen** (lit. f):
  Nein — es werden keine Emotionen erkannt; nur Anwesenheit/Position.
- **Social Scoring** (lit. c), **Ausnutzung von Schutzbedürftigkeit** (lit. b),
  **ungezieltes Scraping von Gesichtsbildern** (lit. e): allesamt nein.

→ **Kein verbotener Einsatz.**

### 4.2 Hochrisiko (Anhang III) — nicht einschlägig

Die relevanten Anhang-III-Kategorien und warum sie nicht greifen:

- **Anhang III Nr. 1 (Biometrie):** umfasst (a) biometrische
  Fernidentifizierung, (b) biometrische Kategorisierung nach geschützten
  Merkmalen, (c) Emotionserkennung. Raumzaehler tut **nichts davon** — es
  detektiert die Objektklasse „Person" und deren Bildposition. Die zentrale
  Abgrenzung (Detektion ≠ Identifizierung) ist in **Abschnitt 5** ausgeführt.
- **Anhang III Nr. 2 (kritische Infrastruktur):** nur als
  **Sicherheitskomponente** z. B. von Verkehr/Wasser/Strom/digitaler
  Infrastruktur. Ein Raum-Belegungszähler ist keine Sicherheitskomponente; ein
  Ausfall gefährdet weder Leib/Leben noch die Infrastruktur. (Würde das Gerät
  je sicherheitskritisch eingesetzt — z. B. Evakuierungs-/Brandschutz-Kapazität
  als verbindliche Steuergröße —, wäre **neu zu bewerten**.)
- **Nr. 3–8** (Bildung, Beschäftigung, essenzielle Dienste, Strafverfolgung,
  Migration, Justiz): nicht einschlägig, **sofern** die Zähldaten nicht
  zweckentfremdet werden (z. B. zur Mitarbeiter-/Leistungsüberwachung — siehe
  Abschnitt 12, „red lines").

→ **Kein Hochrisiko-System** in der bestimmungsgemäßen V1-Verwendung.

### 4.3 Spezifische Transparenzpflichten (Art. 50) — nicht einschlägig

Art. 50 adressiert (a) KI-Systeme im direkten Dialog mit Menschen, (b)
Emotionserkennung/biometrische Kategorisierung (Informationspflicht gegenüber
Betroffenen), (c)/(d) synthetische/„Deepfake"-Inhalte. **Keiner** dieser
Tatbestände trifft auf einen anonymen Personenzähler zu.

> Achtung Abgrenzung: Die **Pflicht zur Beschilderung**, dass ein Raum von einer
> (kamerabasierten) Anlage erfasst wird, folgt hier **nicht aus Art. 50 AI Act**,
> sondern aus der **DSGVO-Transparenz** (Art. 13) — siehe Abschnitt 8.4.

### 4.4 Kein GPAI-Modell

Das eingebettete MobileNet-SSD ist ein eng spezialisiertes Detektionsmodell,
**kein** General-Purpose-AI-Modell. Kapitel V (GPAI-Pflichten) ist nicht
anwendbar.

---

## 5. Kernabgrenzung: Personendetektion ≠ biometrische Identifizierung

Dies ist der **dreh- und angelpunkt** der gesamten Einstufung und sollte in jeder
externen Kommunikation präzise vertreten werden können.

| Merkmal | Biometrische Identifizierung (AI Act / DSGVO) | Raumzaehler |
|---------|-----------------------------------------------|-------------|
| Ziel | *Wer* ist die Person (1:1 / 1:n Abgleich) | *Ob/wo* eine Person ist |
| Datenbasis | Biometrische Vorlage (Gesicht, Gang, Iris …) | Bounding-Box-Koordinaten der Klasse „person" |
| Vergleich | Gegen Referenzdatenbank/Galerie | Keiner — kein Template, keine DB |
| Wiedererkennung | Ja, über Zeit/Orte hinweg | Nein — Track-ID flüchtig, nur RAM, sekundenlang |
| Persistenz | Biometrische Daten gespeichert | Nur anonyme Zählevents gespeichert |

- **Biometrische Daten** (Art. 3 Abs. 35 AI Act / Art. 4 Nr. 14 DSGVO) entstehen
  durch *spezifische technische Verarbeitung* körperlicher Merkmale, die die
  **eindeutige Identifizierung** ermöglicht. Das MobileNet-SSD liefert eine
  Klassen-/Boxausgabe — **keine** identifizierende Vorlage. Es findet kein
  Gesichts-/Merkmalsabgleich statt; COCO-Klasse `0` ist schlicht „person".
- Die **Track-ID** des Centroid-Trackers könnte oberflächlich nach „Tracking
  einer Person" aussehen, ist aber: (i) ein bloßer Integer, (ii) ausschließlich
  im Arbeitsspeicher, (iii) ohne jeden Personenbezug, (iv) nach wenigen
  verpassten Frames endgültig verworfen, (v) **nie persistiert**. Sie dient nur
  dazu, eine Linienüberschreitung *desselben Blobs* nicht doppelt zu zählen.

→ Es werden **keine biometrischen Daten im Rechtssinn** verarbeitet — der Hebel,
der das System aus Art. 5/Anhang III heraushält. **Diese Eigenschaft ist als
Architekturentscheidung zu schützen** (siehe Brennpunkt Preview, Abschnitt 10).

---

## 6. Verhältnis zur DSGVO — der real bindende Rahmen

Auch ein „minimales Risiko"-KI-System unterliegt vollständig dem
Datenschutzrecht, **soweit personenbezogene Daten verarbeitet werden**. Die
Beurteilung des Personenbezugs ist daher die wichtigste Einzelfrage.

### 6.1 Liegt Personenbezug vor?

| Datenartefakt | Personenbezug | Bewertung |
|---------------|---------------|-----------|
| Rohvideo | — | Verlässt den Sensor **nicht** (Normalbetrieb). Kein Datum auf dem Pi. |
| Bounding-Boxes / Centroiden | grundsätzlich nein | Anonyme Koordinaten, flüchtig, nicht gespeichert. |
| Zählevents `in/out` | i. d. R. nein | Aggregierte, anonyme Ereigniszählung. |
| Belegungszahl | i. d. R. nein | Aggregat. **Aber:** in Einzelbelegungs-Szenarien (z. B. Einzelbüro) kann „1 Person im Raum um 21:14" auf eine bestimmte Person rückführbar sein → **kontextabhängig** personenbeziehbar. |
| **Preview-JPEG** (wenn aktiviert) | **ja** | Erkennbare Personen im Bild → personenbezogen, ggf. besondere Kategorie. |

**Fazit:** Im **Normalbetrieb** (Preview aus) ist Raumzaehler weitgehend
anonym; ein verbleibendes Rest-Risiko des Personenbezugs besteht nur in
**kontextspezifischen Niedrigbelegungs-Szenarien**. Diese Kontextfrage muss der
Betreiber pro Einsatzort beantworten.

### 6.2 Datenschutz durch Technikgestaltung (Art. 25) — vorbildlich erfüllt

On-Sensor-Inferenz, Verzicht auf Bildspeicherung, anonyme Aggregation und
flüchtige Track-IDs sind ein **Musterbeispiel** für „data protection by design
and by default". Diese Stärke sollte dokumentiert und nicht durch Komfort-Features
(Preview) unterlaufen werden.

### 6.3 Rechtsgrundlage (Art. 6) & DSFA (Art. 35)

- **Rechtsgrundlage:** Bei Personenbezug typischerweise berechtigtes Interesse
  (Art. 6 Abs. 1 lit. f) — Belegungs-/Kapazitätssteuerung —, abzuwägen gegen die
  Interessen der erfassten Personen. Bei Anonymität entfällt die Frage.
- **Datenschutz-Folgenabschätzung:** Eine **systematische Überwachung
  öffentlich zugänglicher Bereiche** kann eine DSFA auslösen. Aufgrund des
  anonymen, bildlosen Designs ist das Risiko gering; dennoch empfiehlt sich eine
  **kurze dokumentierte Schwellenwert-/Negativprüfung** je Standort. **Sobald
  der Preview aktiviert wird, ist eine DSFA ernsthaft zu prüfen.**

### 6.4 Transparenz / Informationspflicht (Art. 13)

Werden personenbeziehbare Daten verarbeitet (oder ist eine Kamera sichtbar
montiert), sind die Betroffenen zu informieren — praktisch durch **Beschilderung
am Raumzugang** (erfassende Stelle, Zweck „anonyme Belegungszählung",
Rechtsgrundlage, Kontakt, Hinweis „keine Bildaufzeichnung/keine Identifizierung").
Das wirkt zugleich vertrauensbildend und unterstreicht den anonymen Charakter.

### 6.5 Speicherbegrenzung / Löschkonzept (Art. 5 Abs. 1 lit. e) — **Lücke**

`storage/events.py` schreibt Events **unbegrenzt append-only**; es gibt **keine
automatische Löschung, kein Retention-Limit, keine Aggregierungs-/Verdichtungs-
oder Anonymisierungs-Routine**. Selbst wenn Einzelevents meist anonym sind, ist
ein **definiertes Aufbewahrungs-/Löschkonzept** anzulegen (z. B. Roh-Events nach
N Tagen auf Tages-/Stundenaggregate verdichten und Detaildaten löschen).

### 6.6 Betroffenenrechte

Bei echtem Personenbezug bestehen Auskunfts-/Löschrechte. Da keine
personenbezogenen Identifikatoren gespeichert werden, ist eine Zuordnung „Event →
Person" praktisch nicht möglich — das ist datenschutzfreundlich, aber im
Verzeichnis der Verarbeitungstätigkeiten als Tatsache festzuhalten.

---

## 7. Querschnitts-Governance-Pflichten des AI Act (risikoklassenunabhängig)

### 7.1 KI-Kompetenz / „AI literacy" (Art. 4) — **gilt seit 2. Feb 2025**

Anbieter **und** Betreiber müssen sicherstellen, dass mit dem System befasste
Personen über ausreichendes Verständnis verfügen. Konkret umsetzbar:

- Kurze Einweisung für Betreiber-Personal: Was misst das System (anonyme
  Zählung), was **nicht** (keine Identifizierung), Grenzen der Genauigkeit
  (Drift), Bedeutung von Korrektur/Nachtreset, wann der Preview aktiv ist.
- Diese Dokumentation + `README.md` dienen als Schulungsgrundlage; eine
  **kurze Bestätigung der Einweisung** je Betreiber genügt zur Nachweisführung.

### 7.2 Freiwillige Verhaltenskodizes (Art. 95)

Für Nicht-Hochrisiko-Systeme empfiehlt der AI Act die **freiwillige** Anwendung
von Hochrisiko-nahen Best Practices. Raumzaehler erfüllt mehrere davon bereits
(Privacy by Design, Logging via Event-Sourcing, menschliche Aufsicht durch
Korrektur). Das lässt sich als freiwilliges Bekenntnis dokumentieren.

---

## 8. Übernommene Hochrisiko-Best-Practices (freiwillig, Ist-Stand)

Auch ohne Hochrisiko-Pflicht ist es gute Governance, die einschlägigen Prinzipien
zu spiegeln. Bewertung des Ist-Standes:

| Prinzip (analog Art. 9–15) | Ist-Stand in Raumzaehler | Bewertung |
|----------------------------|--------------------------|-----------|
| **Risikomanagement (Art. 9)** | Diese Doku + Security-Audit; kein formaler laufender Prozess | teilweise — Wiederholung bei Änderungen festlegen |
| **Daten-Governance (Art. 10)** | Modell ist Zulieferung (COCO/MobileNet-SSD); keine eigene Trainingsdaten | extern — Provenienz beim Modell-Zulieferer, siehe 8.1 |
| **Technische Dokumentation (Art. 11)** | `README.md`, `CLAUDE.md`, V2-Skizze, Audits | gut |
| **Aufzeichnung/Logging (Art. 12)** | Event-Sourcing: jede Zählung/Korrektur als Zeile, UTC, `sensor_id` | gut — Nachvollziehbarkeit gegeben |
| **Transparenz/Anleitung (Art. 13)** | README + Config-Doku; Dashboard-Status „starting" | gut |
| **Menschliche Aufsicht (Art. 14)** | Manuelle Belegungskorrektur (`POST /api/occupancy`), Nachtreset, `INVERT_DIRECTION` | gut — Mensch kann jederzeit korrigieren (Abschnitt 8.2) |
| **Genauigkeit/Robustheit (Art. 15)** | Konfidenzschwelle, Backoff-Recovery, Drift-Mitigation; bekannte Grenzen | bekannt & dokumentiert (Abschnitt 8.3) |
| **Cybersicherheit (Art. 15)** | Siehe Security-Audit 2026-06-17 | **offene Punkte** (Abschnitt 8.4) |

### 8.1 Daten-/Modell-Governance (Art. 10)

Das Detektionsmodell ist eine **Drittzulieferung** (vortrainiertes MobileNet-SSD
auf COCO, ausgeliefert via `imx500-models`, Pfad in `config.py`). Eigene
Trainingsdaten existieren nicht. Governance-Implikationen:

- **Bias/Repräsentativität** der Personenerkennung (z. B. ungleiche
  Erkennungsraten je nach Kleidung, Körperhaltung, Beleuchtung, Sichtwinkel)
  liegen in der **Modell-Provenienz** und sind vom Projekt nicht direkt
  beeinflussbar. Da das System **anonym zählt** und niemanden klassifiziert,
  ist die diskriminierungsrechtliche Tragweite gering; relevant bleibt die
  **Zählgenauigkeit** (Abschnitt 8.3).
- Modell-/Firmware-Version (`IMX500_MODEL_PATH`) sollte als Teil der
  Konfiguration **versioniert dokumentiert** werden, um Reproduzierbarkeit von
  Zählergebnissen zu wahren.

### 8.2 Menschliche Aufsicht (Art. 14)

Eingebaut und wirksam: Belegung lässt sich jederzeit per Dashboard korrigieren
(auditierbares `correction`-Event), nächtlicher Reset begrenzt Drift,
`INVERT_DIRECTION` korrigiert Montagerichtung. **Einschränkung** (aus Audit L5):
Korrekturen sind mangels Mehrbenutzer-Auth **nicht personell zurechenbar** —
auditierbar ist *was/wann*, nicht *wer*. Bewusst V2-Thema.

### 8.3 Genauigkeit & Robustheit (Art. 15)

- **Drift** (verpasste/Doppelzählungen) ist als Domänenwissen dokumentiert und
  durch Nachtreset + manuelle Korrektur mitigiert — eine **inhärente Grenze**,
  die Betreibern transparent zu machen ist (keine „exakte" Personenzahl).
- **Robustheit:** `Imx500Source.frames()` fängt Kamerafehler ab, sendet
  Heartbeat-Leerframes und versucht mit exponentiellem Backoff erneut — der
  Zählloop stirbt nicht. Persistenz/Broadcast sind in `try/except` gekapselt.
- **Empfehlung:** Erwartete Genauigkeit/Fehlerbandbreite je Einbausituation
  grob quantifizieren und dokumentieren (Art.-15-Geist: bekannte
  Leistungsgrenzen offenlegen).

### 8.4 Cybersicherheit (Art. 15) — Verweis auf Security-Audit

Die KI-Verordnung verlangt für Hochrisiko angemessene Cybersicherheit; als
freiwillige Best Practice sind die Befunde des
[Security-Audits 2026-06-17](security-audit-2026-06-17.md) relevant —
insbesondere: Auth/TLS standardmäßig aus (H1), kein Brute-Force-Schutz (H2),
**Preview ohne Auth = Videostream im LAN (M5)**. Letzteres ist zugleich der
schwerste AI-Act-/Datenschutz-Brennpunkt (Abschnitt 10).

---

## 9. Sonderfall Kamera-Preview — der zentrale Governance-Brennpunkt

`CAMERA_PREVIEW_ENABLED` (Default `false`) ist die **einzige Stelle**, an der das
Privacy-by-Design-Versprechen kippen kann. Bei `true` (nur `imx500`-Quelle):

- `counter/source_imx500.py:_publish_frame` erzeugt aus dem realen Kamerabild ein
  **JPEG mit eingezeichneten Personen-Boxen** und legt es in den `FrameBuffer`.
- `GET /api/camera/stream` (`api/routes.py:113`) liefert daraus einen
  **MJPEG-Live-Stream** an das Dashboard.

Damit verlässt **erkennbares Bildmaterial von Personen** den Sensor → es entstehen
**personenbezogene Daten** und potenziell **besondere Kategorien** (Art. 9 DSGVO).
Verschärfend (Audit M5): bei Default-`auth_enabled=false` ist dieser Stream
**ohne Authentifizierung im LAN** abrufbar.

**Governance-Auflagen für den Preview:**

1. **Nur temporär** zur Kalibrierung aktivieren, danach **zwingend deaktivieren**
   (im README bereits empfohlen — als verbindliche Betriebsregel festschreiben).
2. **Nie ohne Authentifizierung** (idealerweise technisch koppeln: Preview nur
   bei `auth_enabled=true` zulassen — vgl. Audit-Empfehlung zu M5).
3. Bei dauerhaftem Preview-Betrieb: **eigene DSGVO-Würdigung** (Rechtsgrundlage,
   ggf. DSFA, Beschilderung „Videoübertragung aktiv", Löschung) — dann ist die
   „anonym/bildlos"-Argumentation dieses Dokuments **nicht mehr tragfähig**.

---

## 10. Auswirkungen von Version 2 (Zentralserver, MQTT, Mehrbenutzer)

Die [V2-Architekturskizze](v2-central-server-architecture.md) verändert mehrere
governance-relevante Parameter — die Einstufung ist vor V2-Produktivsetzung
**neu durchzuführen**:

- **Datenexport via MQTT:** Zählevents (`event_id, ts_utc, direction, value`)
  verlassen das Gerät Richtung Broker/Zentralserver. Inhaltlich weiterhin
  **anonyme Aggregatdaten** — aber: zentrale **Zusammenführung mehrerer
  Standorte über Zeit** erhöht das Re-Identifikations-/Profilbildungs-Risiko und
  damit die DSGVO-Anforderungen (Auftragsverarbeitung/Verantwortlichkeit,
  Transportverschlüsselung, Zugriffskontrolle).
  > **Hinweis (Ist-Stand):** Trotz Formulierung in `README.md`/`CLAUDE.md`
  > („MQTT-Modul vorhanden, default aus") existiert im aktuellen Code **kein**
  > `mqtt/`-Verzeichnis. MQTT ist **Roadmap, nicht implementiert** — in V1
  > findet **kein Datenexport** statt. Doku entsprechend angleichen.
- **Mehrbenutzer-Auth mit Rollen** (zentral) macht Korrekturen/Zugriffe
  **personell zurechenbar** (schließt Audit-L5) — erfordert aber ein
  eigenes Berechtigungs-/Protokollierungskonzept.
- **Transportsicherheit:** MQTT über TLS + per-Device-Credentials ist in der
  Skizze vorgesehen — als verbindliche Anforderung für V2 festschreiben.
- **Empfehlung:** Für V2 dieses Governance-Dokument fortschreiben, inkl.
  Rollenabgrenzung Anbieter/Betreiber/Auftragsverarbeiter und erneuter
  DSFA-Schwellenprüfung für die zentrale Aggregation.

---

## 11. Governance-Maßnahmenliste (priorisiert)

| # | Priorität | Maßnahme | Bezug |
|---|-----------|----------|-------|
| 1 | **Sofort** | Zweckbestimmung (Abschnitt 2) + diese Einstufung als verbindliches Dokument führen; Rollen Anbieter/Betreiber je Einsatz festhalten | Art. 3, Governance |
| 2 | **Sofort** | KI-Kompetenz: kurze Personal-Einweisung + Nachweis | Art. 4 (seit 2/2025) |
| 3 | **Sofort** | Betriebsregel: Preview nur temporär, nie ohne Auth; technisch koppeln | Abschnitt 10, Audit M5 |
| 4 | **Kurzfristig** | Beschilderung/Transparenzhinweis am Einsatzort | Art. 13 DSGVO |
| 5 | **Kurzfristig** | **Löschkonzept/Retention** für `events` definieren & umsetzen | Art. 5(1)(e) DSGVO |
| 6 | **Kurzfristig** | DSFA-Schwellenprüfung je Standort dokumentieren (zwingend bei Preview) | Art. 35 DSGVO |
| 7 | **Kurzfristig** | Security-Defaults härten (Auth/TLS) gemäß Audit | Art. 15 / Audit H1/H2 |
| 8 | **Mittel** | Modell-/Firmware-Version versioniert dokumentieren; Genauigkeitsband je Einbau grob quantifizieren | Art. 10/15 |
| 9 | **Mittel** | Doku korrigieren: MQTT als „geplant, nicht implementiert" kennzeichnen | Konsistenz |
| 10 | **V2** | Neu-Bewertung vor Zentralserver/MQTT; Auftragsverarbeitung, TLS, Rollen, zentrale DSFA | Abschnitt 10 |

### „Red lines" — Einsatzverbote, die die Einstufung kippen würden

Die „minimales Risiko"-Einstufung gilt **nur** für die bestimmungsgemäße
anonyme Zählung. Sie **verliert ihre Gültigkeit**, wenn:

- die Zähl-/Belegungsdaten zur **Überwachung oder Leistungsbewertung
  einzelner/identifizierbarer Personen oder Mitarbeiter** verwendet werden
  (potenziell Anhang III Nr. 3/4),
- das System um **Identifizierung, Wiedererkennung, Gesichts-/biometrische
  Merkmale, Emotions- oder Attributableitung** erweitert wird (Art. 5 / Anhang III),
- der **Preview dauerhaft** als Überwachungsbild betrieben wird,
- es als **Sicherheitskomponente** mit Gefährdungspotenzial eingesetzt wird.

Jede dieser Änderungen erfordert eine **vollständige Neubewertung** vor Einsatz.

---

## 12. Zusammenfassende Bewertung

Raumzaehler V1 ist ein KI-System im Sinne des AI Act, fällt aber dank seines
**anonymen, on-sensor-basierten, bildlosen Designs** in die **leichteste
Risikoklasse**: keine verbotene Praktik, kein Hochrisiko, keine spezifische
Transparenzpflicht nach Art. 50. Die einzige bereits geltende AI-Act-Pflicht ist
die **KI-Kompetenz (Art. 4)**.

Die materiell bindenden Anforderungen entstammen der **DSGVO** und sind durch das
Design größtenteils elegant adressiert (Privacy by Design). Offene Punkte sind
**organisatorisch/dokumentarisch** (Zweckbestimmung, Einweisung, Beschilderung,
**Löschkonzept**) sowie der technische **Preview-Brennpunkt** und die
**Security-Defaults**. Keiner dieser Punkte ist schwerwiegend, aber alle sind
**vor produktivem Einsatz mit Personenbezug** abzuarbeiten.

Die wichtigste Daueraufgabe: das **anonyme, identifizierungsfreie Verhalten als
Architektureigenschaft schützen** — denn genau diese Eigenschaft hält das System
außerhalb der schweren Pflichtenregime des AI Act. Jede Erweiterung in Richtung
Bild, Identität oder Zentralaggregation (V2) erfordert eine erneute Bewertung.
