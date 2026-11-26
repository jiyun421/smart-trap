CREATE TABLE traps (
    trap_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    empty_g REAL NOT NULL CHECK (empty_g >= 0),
    low_g REAL NOT NULL CHECK (low_g > empty_g),
    report_interval_seconds INTEGER NOT NULL CHECK (report_interval_seconds > 0)
);

CREATE TABLE locations (
    location_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    latitude REAL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL CHECK (longitude BETWEEN -180 AND 180),
    notes TEXT
);

CREATE TABLE deployments (
    deployment_id TEXT PRIMARY KEY,
    trap_id TEXT NOT NULL REFERENCES traps(trap_id),
    location_id TEXT NOT NULL REFERENCES locations(location_id),
    target_species TEXT NOT NULL CHECK (target_species <> 'unknown'),
    started_at TEXT NOT NULL,
    ended_at TEXT CHECK (ended_at > started_at),
    UNIQUE (trap_id, deployment_id)
);

CREATE UNIQUE INDEX deployments_active ON deployments(trap_id) WHERE ended_at IS NULL;
CREATE INDEX deployments_by_trap_time ON deployments(trap_id, started_at);

CREATE TABLE trap_events (
    trap_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    event_type TEXT NOT NULL CHECK (event_type IN ('telemetry', 'entry_detected', 'visit_resolved')),
    visit_id TEXT,
    observed_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    temperature_c REAL,
    humidity_pct REAL CHECK (humidity_pct BETWEEN 0 AND 100),
    illuminance_lux REAL CHECK (illuminance_lux >= 0),
    bait_g REAL CHECK (bait_g >= 0),
    species_code TEXT,
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    door_state TEXT CHECK (door_state IN ('open', 'closed', 'unknown')),
    occupancy_state TEXT CHECK (occupancy_state IN ('occupied', 'empty', 'unknown')),
    outcome TEXT CHECK (outcome IN ('capture_confirmed', 'release_confirmed', 'unconfirmed', 'failed')),
    outcome_evidence TEXT,
    payload TEXT NOT NULL,
    CHECK ((event_type = 'telemetry' AND visit_id IS NULL)
        OR (event_type IN ('entry_detected', 'visit_resolved') AND visit_id IS NOT NULL)),
    PRIMARY KEY (trap_id, event_id),
    FOREIGN KEY (trap_id, deployment_id) REFERENCES deployments(trap_id, deployment_id)
);

CREATE UNIQUE INDEX trap_events_visit_kind ON trap_events(deployment_id, visit_id, event_type)
    WHERE visit_id IS NOT NULL;
CREATE INDEX trap_events_by_time ON trap_events(observed_at, trap_id, event_id);
CREATE INDEX trap_events_by_trap_time ON trap_events(trap_id, observed_at, event_id);
CREATE INDEX trap_events_by_deployment_time ON trap_events(deployment_id, observed_at, event_id);
CREATE INDEX trap_events_by_deployment_receive ON trap_events(deployment_id, received_at);
CREATE INDEX trap_events_by_kind_time ON trap_events(event_type, observed_at, trap_id, event_id);

CREATE TABLE recommendation_runs (
    run_id TEXT PRIMARY KEY,
    trap_id TEXT NOT NULL REFERENCES traps(trap_id),
    target_species TEXT NOT NULL CHECK (target_species <> 'unknown'),
    model_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    prediction_kind TEXT NOT NULL CHECK (prediction_kind IN ('target_entry', 'target_capture')),
    data_from TEXT NOT NULL,
    data_to TEXT NOT NULL CHECK (data_to > data_from),
    forecast_from TEXT NOT NULL,
    forecast_to TEXT NOT NULL CHECK (forecast_to > forecast_from),
    status TEXT NOT NULL CHECK (status IN ('ready', 'insufficient_data')),
    score_type TEXT CHECK (score_type IN ('probability', 'relative_score')),
    reason TEXT,
    payload TEXT NOT NULL
);

CREATE INDEX recommendation_runs_by_time ON recommendation_runs(generated_at, run_id);
CREATE INDEX recommendation_runs_by_filter
    ON recommendation_runs(trap_id, target_species, prediction_kind, generated_at, run_id);

CREATE TABLE recommendation_items (
    run_id TEXT NOT NULL REFERENCES recommendation_runs(run_id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES locations(location_id),
    rank INTEGER NOT NULL CHECK (rank > 0),
    score REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
    reason TEXT NOT NULL,
    PRIMARY KEY (run_id, location_id),
    UNIQUE (run_id, rank)
);
