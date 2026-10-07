CREATE TABLE IF NOT EXISTS event_india_exposure_paths(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_thread_id uuid NOT NULL REFERENCES event_threads ON DELETE CASCADE,
  edge_id uuid NOT NULL REFERENCES india_exposure_edges ON DELETE CASCADE,
  pathway_note text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(event_thread_id,edge_id)
);
