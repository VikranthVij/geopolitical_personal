-- Feature 5: deterministic incident-to-event-thread assignment and relationships.
ALTER TABLE event_threads
  ADD COLUMN IF NOT EXISTS thread_status text NOT NULL DEFAULT 'UNKNOWN'
    CHECK(thread_status IN ('DEVELOPING','ONGOING','DORMANT','CONCLUDED','UNKNOWN')),
  ADD COLUMN IF NOT EXISTS started_at timestamptz,
  ADD COLUMN IF NOT EXISTS ended_at timestamptz,
  ADD COLUMN IF NOT EXISTS latest_activity_at timestamptz;

CREATE INDEX IF NOT EXISTS event_threads_thread_status_updated_idx ON event_threads(thread_status,updated_at DESC);
CREATE INDEX IF NOT EXISTS event_threads_started_at_idx ON event_threads(started_at DESC) WHERE started_at IS NOT NULL;

-- A normalized per-incident context profile derived from Feature 4 fingerprints and source claims.
CREATE TABLE IF NOT EXISTS incident_thread_contexts (
  incident_id uuid PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE,
  actor_entity_ids uuid[] NOT NULL DEFAULT '{}',
  participant_entity_ids uuid[] NOT NULL DEFAULT '{}',
  target_entity_ids uuid[] NOT NULL DEFAULT '{}',
  location_entity_ids uuid[] NOT NULL DEFAULT '{}',
  context_domains text[] NOT NULL DEFAULT '{}',
  event_time_start timestamptz,
  event_time_end timestamptz,
  time_precision text,
  relationship_cues jsonb NOT NULL DEFAULT '[]',
  source_document_ids uuid[] NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS incident_thread_contexts_actors_gin ON incident_thread_contexts USING gin(actor_entity_ids);
CREATE INDEX IF NOT EXISTS incident_thread_contexts_participants_gin ON incident_thread_contexts USING gin(participant_entity_ids);
CREATE INDEX IF NOT EXISTS incident_thread_contexts_targets_gin ON incident_thread_contexts USING gin(target_entity_ids);
CREATE INDEX IF NOT EXISTS incident_thread_contexts_locations_gin ON incident_thread_contexts USING gin(location_entity_ids);
CREATE INDEX IF NOT EXISTS incident_thread_contexts_domains_gin ON incident_thread_contexts USING gin(context_domains);
CREATE INDEX IF NOT EXISTS incident_thread_contexts_time_idx ON incident_thread_contexts(event_time_start DESC) WHERE event_time_start IS NOT NULL;

-- Cached set profile is rebuilt from member incidents after each assignment.
CREATE TABLE IF NOT EXISTS event_thread_profiles (
  event_thread_id uuid PRIMARY KEY REFERENCES event_threads(id) ON DELETE CASCADE,
  actor_entity_ids uuid[] NOT NULL DEFAULT '{}',
  participant_entity_ids uuid[] NOT NULL DEFAULT '{}',
  target_entity_ids uuid[] NOT NULL DEFAULT '{}',
  location_entity_ids uuid[] NOT NULL DEFAULT '{}',
  context_domains text[] NOT NULL DEFAULT '{}',
  started_at timestamptz,
  latest_incident_at timestamptz,
  incident_count integer NOT NULL DEFAULT 0 CHECK(incident_count >= 0),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS event_thread_profiles_actors_gin ON event_thread_profiles USING gin(actor_entity_ids);
CREATE INDEX IF NOT EXISTS event_thread_profiles_participants_gin ON event_thread_profiles USING gin(participant_entity_ids);
CREATE INDEX IF NOT EXISTS event_thread_profiles_targets_gin ON event_thread_profiles USING gin(target_entity_ids);
CREATE INDEX IF NOT EXISTS event_thread_profiles_locations_gin ON event_thread_profiles USING gin(location_entity_ids);
CREATE INDEX IF NOT EXISTS event_thread_profiles_domains_gin ON event_thread_profiles USING gin(context_domains);
CREATE INDEX IF NOT EXISTS event_thread_profiles_activity_idx ON event_thread_profiles(latest_incident_at DESC) WHERE latest_incident_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS event_thread_incident_relationships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_thread_id uuid NOT NULL REFERENCES event_threads(id) ON DELETE CASCADE,
  from_incident_id uuid NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  to_incident_id uuid NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  relation text NOT NULL CHECK(relation IN ('CAUSED_BY','RESPONDED_TO','ESCALATED_FROM','INFLUENCED_BY','RELATED_TO')),
  resolver_method text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(from_incident_id <> to_incident_id),
  UNIQUE(from_incident_id,to_incident_id,relation)
);
CREATE INDEX IF NOT EXISTS event_thread_incident_relationships_thread_idx ON event_thread_incident_relationships(event_thread_id,created_at);
CREATE INDEX IF NOT EXISTS event_thread_incident_relationships_from_idx ON event_thread_incident_relationships(from_incident_id,relation);
CREATE INDEX IF NOT EXISTS event_thread_incident_relationships_to_idx ON event_thread_incident_relationships(to_incident_id,relation);

CREATE TABLE IF NOT EXISTS event_thread_resolution_audits (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id uuid NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  event_thread_id uuid NOT NULL REFERENCES event_threads(id) ON DELETE CASCADE,
  state text NOT NULL CHECK(state IN ('NEW_THREAD','ASSIGNED_EXISTING_THREAD','AMBIGUOUS','REVIEW_REQUIRED','RESOLUTION_FAILED')),
  resolver_method text NOT NULL,
  resolver_version text NOT NULL,
  attempt integer NOT NULL DEFAULT 1 CHECK(attempt > 0),
  matched_signals jsonb NOT NULL DEFAULT '[]',
  conflicts jsonb NOT NULL DEFAULT '[]',
  candidates_considered jsonb NOT NULL DEFAULT '[]',
  relationship_ids uuid[] NOT NULL DEFAULT '{}',
  reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(incident_id,resolver_version,attempt)
);
CREATE INDEX IF NOT EXISTS event_thread_resolution_audits_thread_idx ON event_thread_resolution_audits(event_thread_id,created_at DESC);
CREATE INDEX IF NOT EXISTS event_thread_resolution_audits_incident_idx ON event_thread_resolution_audits(incident_id,created_at DESC);
CREATE INDEX IF NOT EXISTS incident_entities_entity_role_idx ON incident_entities(entity_id,role);
