ALTER TABLE trap_events ADD COLUMN eco2_ppm REAL CHECK (eco2_ppm >= 0);
ALTER TABLE trap_events ADD COLUMN tvoc_ppb REAL CHECK (tvoc_ppb >= 0);
