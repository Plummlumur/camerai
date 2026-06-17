# Raumzähler V2 — Zentralserver-Architektur (Skizze)

> Status: **Entwurf** · Stand: 2026-06-17 · Scope: grobe Architektur, noch kein
> Implementierungsplan. Ergänzt das V1-System (Einzelgerät) um Flotten-Betrieb.

## Ziel

Mehrere V1-Edge-Geräte (Raspberry Pi + IMX500) zu einer Flotte zusammenführen:
zentrale Aggregation aller Standorte, ein Flotten-Dashboard und echte
Mehrbenutzer-Authentifizierung — **ohne** die Eigenständigkeit der Edge-Geräte
zu opfern.

## Leitprinzipien

1. **Edge bleibt autark.** Jedes Gerät zählt, speichert und bedient sein lokales
   Dashboard auch dann, wenn Broker/Zentralserver nicht erreichbar sind. Der
   Zentralserver ist *additiv*, nie eine Laufzeitabhängigkeit.
2. **Event-Sourcing durchgängig.** Die lokale SQLite-`events`-Tabelle bleibt die
   Quelle der Wahrheit des Geräts. Der Zentralserver ist ein weiterer Konsument
   desselben Event-Stroms — er rekonstruiert Belegung/Summen per Aggregation,
   hält keine parallel gepflegten Zähler.
3. **Auth-Trennung** (siehe Memory `auth-architecture-split`):
   - Edge: ein gemeinsames HTTP-Basic-Konto (V1, unverändert).
   - Zentral: Mehrbenutzer mit Rollen + Standort-Scoping.
   - MQTT: Maschine-zu-Maschine (TLS + Geräte-Credentials), getrennt davon.

## Topologie

```
  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
  │ Edge ebene-0 │   │ Edge ebene-1 │   │ Edge kam-NN  │   (V1, autark)
  │ count+local  │   │ count+local  │   │ count+local  │
  │ dashboard +  │   │ dashboard +  │   │ dashboard +  │
  │ store&forward│   │ store&forward│   │ store&forward│
  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
         │ MQTT/TLS QoS1    │                  │
         └──────────────────┼──────────────────┘
                            ▼
                   ┌─────────────────┐
                   │  MQTT-Broker    │  (Mosquitto, TLS, per-Device-Auth)
                   │  counter/<id>/* │
                   └────────┬────────┘
                            ▼ subscribe
                   ┌─────────────────────────────────────┐
                   │           Zentralserver             │
                   │  ┌───────────────┐  ┌─────────────┐ │
                   │  │ Ingest-Worker │→ │ zentrale DB │ │
                   │  └───────────────┘  └─────────────┘ │
                   │  ┌──────────────────────────────┐   │
                   │  │ FastAPI: REST + WS + Auth     │   │
                   │  └──────────────────────────────┘   │
                   │  ┌──────────────────────────────┐   │
                   │  │ Flotten-Dashboard (Web)       │   │
                   │  └──────────────────────────────┘   │
                   └─────────────────────────────────────┘
                            ▲ Login (Mehrbenutzer, Rollen)
                       Betreiber / Standortverantwortliche
```

## Komponenten

### Edge (Erweiterung von V1)
- **MQTT-Publisher aktivieren** (Modul existiert, default aus; darf den
  Zählloop nie blockieren/abstürzen lassen).
- **Store-and-forward:** ungesendete Events lokal markieren (z. B. Spalte
  `published INTEGER DEFAULT 0` in `events` oder eine separate Outbox), bei
  (Re-)Connect nachsenden. MQTT QoS 1 + persistente Session. So überleben
  Netz-/Broker-Ausfälle ohne Datenverlust.
- **Payload** je Event nach `counter/<sensor_id>/events`:
  `{event_id, ts_utc, direction, value}` — `event_id` = lokale `events.id`,
  damit der Zentralserver **idempotent** dedupliziert (Key:
  `sensor_id` + `event_id`).
- Optional `counter/<sensor_id>/status` (retained): online/letzte Belegung,
  für „Gerät offline"-Anzeige im Flotten-Dashboard.

### MQTT-Broker
- Mosquitto mit **TLS** und **per-Device-Credentials** (Username/Passwort oder
  Client-Zertifikate). ACLs: ein Gerät darf nur unter seinem eigenen
  `counter/<sensor_id>/#` publizieren.

### Zentralserver (FastAPI, gleiche Stack-Philosophie wie V1)
- **Ingest-Worker:** abonniert `counter/+/events`, schreibt idempotent in die
  zentrale DB (Upsert/Ignore auf `(sensor_id, event_id)`).
- **Zentrale DB:** vermutlich PostgreSQL (mehr Schreiber/Leser, gleichzeitige
  Dashboards) — SQLite reicht für einen kleinen Anfang. Schema analog V1:
  `events(sensor_id, event_id, ts_utc, direction, value)` + `sites(sensor_id,
  name, timezone, …)` + `users` + `user_site_access`.
- **REST/WS-API + Flotten-Dashboard:** Belegung/Verlauf pro Standort *und*
  aggregiert über die Flotte; XLSX-Export wie V1, aber multi-site.
- **Auth:** Mehrbenutzer mit Rollen (z. B. `viewer`/`admin`), Session-Login,
  Standort-Scoping (Benutzer sieht nur zugewiesene `sensor_id`s).

## Datenfluss

```
Edge: Zählevent → lokale SQLite (Quelle der Wahrheit)
                → MQTT publish (QoS1, store&forward)
Broker → Zentral-Ingest → zentrale DB (idempotent)
                        → Aggregation → REST/WS → Flotten-Dashboard
```

Belegung pro Standort wird zentral genauso wie auf dem Edge rekonstruiert
(Replay seit Tagesgrenze, `correction`-Events berücksichtigt, nie < 0).
Zeitzonen pro Standort (`sites.timezone`); Anzeige/Aggregation lokalisiert.

## Resilienz & Korrektheit

- **Edge-Autarkie:** keine Auth-/Datenpfad-Abhängigkeit vom Zentralserver.
- **Verlustfreiheit:** store-and-forward + QoS 1 → Events kommen (ggf. verzögert)
  an; Reboot-fest wie in V1 gezeigt.
- **Idempotenz:** Dedup über `(sensor_id, event_id)` macht Mehrfachzustellung
  (QoS 1 „at least once") unschädlich.
- **Uhren:** Events tragen die UTC-Zeit des Edge; bei Clock-Skew ist die
  Reihenfolge pro Gerät über `event_id` stabil.

## Offene Entscheidungen

- Zentrale DB: PostgreSQL vs. SQLite (Skalierung, gleichzeitige Zugriffe).
- Auth zentral: eigene User-Tabelle vs. OIDC/SSO-Anbindung.
- Backfill: soll der Zentralserver historische Events eines neu angebundenen
  Geräts nachladen (z. B. REST-Pull vom Edge) oder nur ab Anbindung mitschreiben?
- Dashboard: V1-Dashboard erweitern vs. eigenständige Flotten-UI.
- Broker-Hosting: auf dem Zentralserver mit oder als separater Dienst.

## Grobe Phasen

1. **MQTT-Transport absichern** (TLS, per-Device-Auth) + Edge-Publisher mit
   store-and-forward produktiv schalten.
2. **Zentral-Ingest + zentrale DB** (idempotent), ohne UI — erst Daten sammeln.
3. **Flotten-Dashboard** (read-only, multi-site) auf den aggregierten Daten.
4. **Mehrbenutzer-Auth** + Rollen + Standort-Scoping auf dem Zentralserver.

Jede Phase ist für sich nutzbar; das Edge-Verhalten bleibt in allen Phasen
unverändert autark.
