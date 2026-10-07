-- Extend the existing evidence tables without introducing a second evidence model.
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}';
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS extraction_method text NOT NULL DEFAULT 'LEGACY';
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS extraction_confidence text NOT NULL DEFAULT 'LOW'
  CHECK(extraction_confidence IN ('HIGH','MEDIUM','LOW'));
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS identity_key text;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS origin_source_id uuid REFERENCES sources(id) ON DELETE SET NULL;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS origin_reference text;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
CREATE UNIQUE INDEX IF NOT EXISTS evidence_identity_key_unique ON evidence(identity_key) WHERE identity_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS evidence_origin_source_idx ON evidence(origin_source_id) WHERE origin_source_id IS NOT NULL;

-- One underlying evidence item may be referenced by many publisher documents.
CREATE TABLE IF NOT EXISTS evidence_documents (
  evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  relation text NOT NULL CHECK(relation IN ('REFERENCES','CITES','ORIGINATES_FROM','DERIVED_FROM')),
  referenced_document_id uuid REFERENCES documents(id) ON DELETE SET NULL,
  directness text NOT NULL DEFAULT 'UNKNOWN' CHECK(directness IN ('DIRECT','REPORTED','DERIVED','UNKNOWN')),
  attribution jsonb NOT NULL DEFAULT '{}',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(evidence_id,document_id,relation)
);
CREATE INDEX IF NOT EXISTS evidence_documents_document_idx ON evidence_documents(document_id);

CREATE TABLE IF NOT EXISTS evidence_source_spans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  text_field text NOT NULL CHECK(text_field IN ('TITLE','EXCERPT')),
  character_start integer NOT NULL CHECK(character_start >= 0),
  character_end integer NOT NULL CHECK(character_end > character_start),
  source_text text NOT NULL CHECK(length(source_text) > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(evidence_id,document_id,text_field,character_start,character_end)
);
CREATE INDEX IF NOT EXISTS evidence_source_spans_document_idx ON evidence_source_spans(document_id,text_field,character_start);

CREATE TABLE IF NOT EXISTS evidence_sources (
  evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  relation text NOT NULL CHECK(relation IN ('ORIGINATES_FROM','REFERENCES','CITES','DERIVED_FROM')),
  reference_text text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(evidence_id,source_id,relation)
);
CREATE INDEX IF NOT EXISTS evidence_sources_source_idx ON evidence_sources(source_id);

-- evidence_id is the derived/referencing item; related_evidence_id is its parent.
CREATE TABLE IF NOT EXISTS evidence_lineage (
  evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  related_evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  relation text NOT NULL CHECK(relation IN ('CITES','DERIVED_FROM','SAME_UNDERLYING_EVIDENCE')),
  reference_text text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(evidence_id,related_evidence_id,relation),
  CHECK(evidence_id <> related_evidence_id)
);
CREATE INDEX IF NOT EXISTS evidence_lineage_parent_idx ON evidence_lineage(related_evidence_id);

-- Keep the originating document's interpretation of a shared item auditable.
CREATE TABLE IF NOT EXISTS claim_evidence_sources (
  claim_id uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  relation text NOT NULL CHECK(relation IN ('SUPPORTS','CONTRADICTS','PARTIALLY_SUPPORTS','INCONCLUSIVE')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(claim_id,evidence_id,document_id)
);
CREATE INDEX IF NOT EXISTS claim_evidence_sources_document_idx ON claim_evidence_sources(document_id);
