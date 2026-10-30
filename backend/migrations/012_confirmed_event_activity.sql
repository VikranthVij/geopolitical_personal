-- Incident fingerprints may contain dates that describe future validity or other
-- temporal claims. Only the incident's explicit occurred_at value represents a
-- known occurrence for dashboard activity; material-change detection remains the
-- other meaningful-activity timestamp.
WITH activity AS (
  SELECT event_thread_id, max(activity_at) AS latest_activity_at
  FROM (
    SELECT event_thread_id, occurred_at AS activity_at
    FROM incidents
    UNION ALL
    SELECT event_thread_id, created_at AS activity_at
    FROM material_changes
  ) candidates
  WHERE activity_at IS NOT NULL
  GROUP BY event_thread_id
)
UPDATE event_threads e
SET latest_activity_at = activity.latest_activity_at
FROM activity
WHERE activity.event_thread_id = e.id
  AND e.latest_activity_at IS DISTINCT FROM activity.latest_activity_at;

UPDATE event_threads e
SET latest_activity_at = NULL
WHERE e.latest_activity_at IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM incidents i
    WHERE i.event_thread_id = e.id AND i.occurred_at IS NOT NULL
  )
  AND NOT EXISTS (
    SELECT 1 FROM material_changes m WHERE m.event_thread_id = e.id
  );
