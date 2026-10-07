CREATE TABLE IF NOT EXISTS event_watch_indicators(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_thread_id uuid NOT NULL REFERENCES event_threads ON DELETE CASCADE,
  indicator text NOT NULL,
  why_it_matters text NOT NULL,
  source_claim_id uuid REFERENCES claims ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(event_thread_id,indicator)
);
