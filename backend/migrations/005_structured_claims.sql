ALTER TABLE claims ADD COLUMN IF NOT EXISTS normalized_representation jsonb NOT NULL DEFAULT '{}';
ALTER TABLE claims ADD COLUMN IF NOT EXISTS polarity text NOT NULL DEFAULT 'AFFIRMED' CHECK(polarity IN ('AFFIRMED','NEGATED'));
ALTER TABLE claims ADD COLUMN IF NOT EXISTS epistemic_status text NOT NULL DEFAULT 'ASSERTED' CHECK(epistemic_status IN ('ASSERTED','REPORTED','ALLEGED','POSSIBLE','UNCERTAIN','DENIED'));
ALTER TABLE claims ADD COLUMN IF NOT EXISTS attribution_type text NOT NULL DEFAULT 'DIRECT_SOURCE_ASSERTION' CHECK(attribution_type IN ('DIRECT_SOURCE_ASSERTION','ATTRIBUTED_ASSERTION','REPORTED_ASSERTION'));
ALTER TABLE claims ADD COLUMN IF NOT EXISTS attribution jsonb NOT NULL DEFAULT '{}';
ALTER TABLE claims ADD COLUMN IF NOT EXISTS extraction_method text NOT NULL DEFAULT 'LEGACY_HEADLINE';
ALTER TABLE claims ADD COLUMN IF NOT EXISTS extraction_confidence text NOT NULL DEFAULT 'LOW' CHECK(extraction_confidence IN ('HIGH','MEDIUM','LOW'));
ALTER TABLE claims ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS claim_source_spans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  text_field text NOT NULL CHECK(text_field IN ('TITLE','EXCERPT')),
  character_start integer NOT NULL CHECK(character_start >= 0),
  character_end integer NOT NULL CHECK(character_end > character_start),
  source_text text NOT NULL CHECK(length(source_text) > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(claim_id,document_id,text_field,character_start,character_end)
);
CREATE INDEX IF NOT EXISTS claim_source_spans_document_idx ON claim_source_spans(document_id,text_field,character_start);

CREATE TABLE IF NOT EXISTS claim_entities (
  claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'MENTIONED' CHECK(role IN ('ACTOR','OBJECT','TARGET','LOCATION','MENTIONED')),
  PRIMARY KEY(claim_id,entity_id,role)
);
CREATE INDEX IF NOT EXISTS claim_entities_entity_idx ON claim_entities(entity_id);
