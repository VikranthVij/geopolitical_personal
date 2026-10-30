-- Keep source publication time available for continuity and dashboard coverage
-- without treating it as an incident occurrence timestamp.
ALTER TABLE event_thread_profiles
  ADD COLUMN IF NOT EXISTS latest_reported_at timestamptz;

CREATE INDEX IF NOT EXISTS event_thread_profiles_reported_idx
  ON event_thread_profiles(latest_reported_at DESC)
  WHERE latest_reported_at IS NOT NULL;
