-- Feature 6 extends the existing claim and importance models.
ALTER TABLE contradictions ADD COLUMN IF NOT EXISTS incident_id uuid REFERENCES incidents(id) ON DELETE CASCADE;
ALTER TABLE contradictions ADD COLUMN IF NOT EXISTS event_thread_id uuid REFERENCES event_threads(id) ON DELETE CASCADE;
ALTER TABLE contradictions ADD COLUMN IF NOT EXISTS scope jsonb NOT NULL DEFAULT '{}';
ALTER TABLE contradictions ADD COLUMN IF NOT EXISTS method text NOT NULL DEFAULT 'STRUCTURED_RULES_V1';
ALTER TABLE contradictions ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE contradictions DROP CONSTRAINT IF EXISTS contradictions_type_check;
ALTER TABLE contradictions ADD CONSTRAINT contradictions_type_check CHECK(type IN ('OCCURRENCE','ATTRIBUTION','QUANTITATIVE','LOCATION','TIME','INTENT','STATUS','CONSEQUENCE'));
ALTER TABLE contradictions DROP CONSTRAINT IF EXISTS contradictions_claim_a_claim_b_key;
CREATE UNIQUE INDEX IF NOT EXISTS contradictions_pair_type_unique ON contradictions(LEAST(claim_a,claim_b),GREATEST(claim_a,claim_b),type);
CREATE INDEX IF NOT EXISTS contradictions_thread_status_idx ON contradictions(event_thread_id,status,created_at DESC);

ALTER TABLE claims ADD COLUMN IF NOT EXISTS confidence_basis jsonb NOT NULL DEFAULT '{}';
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS importance_level text NOT NULL DEFAULT 'LOW' CHECK(importance_level IN ('LOW','MEDIUM','HIGH','CRITICAL'));
ALTER TABLE event_threads ADD COLUMN IF NOT EXISTS importance_category text NOT NULL DEFAULT 'LOW' CHECK(importance_category IN ('LOW','MEDIUM','HIGH','CRITICAL'));

CREATE TABLE IF NOT EXISTS material_changes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_thread_id uuid NOT NULL REFERENCES event_threads(id) ON DELETE CASCADE,
  trigger_incident_id uuid REFERENCES incidents(id) ON DELETE SET NULL,
  change_type text NOT NULL CHECK(change_type IN ('NEW_MAJOR_ACTOR','GEOGRAPHIC_EXPANSION','MILITARY_ESCALATION','DIPLOMATIC_SHIFT','ECONOMIC_CONSEQUENCE','HUMANITARIAN_CONSEQUENCE','STATUS_CHANGE','SIGNIFICANT_CONTRADICTION','NEW_INCIDENT')),
  previous_state jsonb NOT NULL DEFAULT '{}',
  new_state jsonb NOT NULL DEFAULT '{}',
  reason text NOT NULL,
  significance text NOT NULL CHECK(significance IN ('MEDIUM','HIGH','CRITICAL')),
  dedupe_key text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS material_changes_thread_idx ON material_changes(event_thread_id,created_at DESC);

CREATE TABLE IF NOT EXISTS feature6_failures (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid REFERENCES documents(id) ON DELETE SET NULL,
  incident_id uuid REFERENCES incidents(id) ON DELETE SET NULL,
  stage text NOT NULL,
  error text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
