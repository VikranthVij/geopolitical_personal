-- Feature 4: deterministic document-to-incident identity and auditable decisions.
CREATE TABLE IF NOT EXISTS incident_fingerprints (
  incident_id uuid PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE,
  primary_actor_id uuid REFERENCES entities(id) ON DELETE SET NULL,
  action_predicate text,
  target_entity_id uuid REFERENCES entities(id) ON DELETE SET NULL,
  object_entity_id uuid REFERENCES entities(id) ON DELETE SET NULL,
  location_entity_id uuid REFERENCES entities(id) ON DELETE SET NULL,
  event_time_start timestamptz,
  event_time_end timestamptz,
  event_time_expression text,
  time_precision text,
  quantity jsonb NOT NULL DEFAULT '{}',
  consequence text,
  response text,
  supporting_entities uuid[] NOT NULL DEFAULT '{}',
  source_metadata jsonb NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS incident_fingerprints_actor_idx ON incident_fingerprints(primary_actor_id) WHERE primary_actor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS incident_fingerprints_target_idx ON incident_fingerprints(target_entity_id) WHERE target_entity_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS incident_fingerprints_action_time_idx ON incident_fingerprints(action_predicate,event_time_start DESC);
CREATE INDEX IF NOT EXISTS incident_fingerprints_time_expression_idx ON incident_fingerprints(event_time_expression) WHERE event_time_expression IS NOT NULL;
CREATE INDEX IF NOT EXISTS incident_fingerprints_location_idx ON incident_fingerprints(location_entity_id) WHERE location_entity_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS incident_fingerprint_evidence (
  incident_id uuid NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  identity_key text,
  PRIMARY KEY(incident_id,evidence_id)
);
CREATE INDEX IF NOT EXISTS incident_fingerprint_evidence_identity_idx ON incident_fingerprint_evidence(identity_key) WHERE identity_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS document_incident_resolutions (
  document_id uuid PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
  incident_id uuid NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  state text NOT NULL CHECK(state IN ('NEW_INCIDENT','MATCHED_EXISTING','AMBIGUOUS','REVIEW_REQUIRED','RESOLUTION_FAILED')),
  resolution_method text NOT NULL,
  match_strength text NOT NULL CHECK(match_strength IN ('STRONG','SUPPORTED','INSUFFICIENT','UNKNOWN')),
  matched_signals jsonb NOT NULL DEFAULT '[]',
  conflicts jsonb NOT NULL DEFAULT '[]',
  candidates_considered jsonb NOT NULL DEFAULT '[]',
  limitation text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS document_incident_resolutions_incident_idx ON document_incident_resolutions(incident_id,state);
