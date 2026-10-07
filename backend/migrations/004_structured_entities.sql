ALTER TABLE entities ADD COLUMN IF NOT EXISTS description text;
ALTER TABLE entities ADD COLUMN IF NOT EXISTS parent_entity_id uuid REFERENCES entities(id) ON DELETE SET NULL;
ALTER TABLE entities ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
CREATE TABLE IF NOT EXISTS entity_aliases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  alias text NOT NULL,
  normalized_alias text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(entity_id, normalized_alias)
);
CREATE INDEX IF NOT EXISTS entity_aliases_normalized_idx ON entity_aliases(normalized_alias);
INSERT INTO entity_aliases(entity_id,alias,normalized_alias)
SELECT e.id,a,lower(regexp_replace(btrim(a), '[^[:alnum:]]+', ' ', 'g'))
FROM entities e CROSS JOIN LATERAL unnest(e.aliases) a
WHERE btrim(a) <> ''
ON CONFLICT(entity_id,normalized_alias) DO NOTHING;
CREATE TABLE IF NOT EXISTS document_entity_mentions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  entity_id uuid REFERENCES entities(id) ON DELETE SET NULL,
  surface_text text NOT NULL,
  normalized_text text NOT NULL,
  text_field text NOT NULL CHECK(text_field IN ('TITLE','EXCERPT')),
  character_start integer NOT NULL CHECK(character_start >= 0),
  character_end integer NOT NULL CHECK(character_end > character_start),
  entity_type text NOT NULL,
  extraction_method text NOT NULL DEFAULT 'DETERMINISTIC_ALIAS',
  resolution_confidence text NOT NULL CHECK(resolution_confidence IN ('HIGH','MEDIUM','LOW','UNRESOLVED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(document_id,text_field,character_start,character_end,normalized_text)
);
CREATE INDEX IF NOT EXISTS document_entity_mentions_document_idx ON document_entity_mentions(document_id,character_start);
CREATE INDEX IF NOT EXISTS document_entity_mentions_entity_idx ON document_entity_mentions(entity_id) WHERE entity_id IS NOT NULL;
