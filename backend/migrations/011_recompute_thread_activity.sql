-- Remove legacy processing timestamps from the derived last-activity field.
-- Rebuild only from known occurrence times and recorded material changes; source
-- publication and ingestion times remain available in their own fields.
WITH activity AS (
  SELECT event_thread_id, max(activity_at) AS latest_activity_at
  FROM (
    SELECT i.event_thread_id, COALESCE(ctx.event_time_start, i.occurred_at) AS activity_at
    FROM incidents i
    LEFT JOIN incident_thread_contexts ctx ON ctx.incident_id = i.id
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
    SELECT 1
    FROM incidents i
    LEFT JOIN incident_thread_contexts ctx ON ctx.incident_id = i.id
    WHERE i.event_thread_id = e.id
      AND COALESCE(ctx.event_time_start, i.occurred_at) IS NOT NULL
  )
  AND NOT EXISTS (
    SELECT 1 FROM material_changes m WHERE m.event_thread_id = e.id
  );
