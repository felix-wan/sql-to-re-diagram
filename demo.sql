-- ============================================================
-- Demo: Multi-database JOIN query with subquery
-- Features demonstrated:
--   - db::table cross-database references
--   - Subquery with alias
--   - LEFT JOIN with PARTITION hint
--   - CASE WHEN expressions
--   - Fields from SELECT / WHERE / GROUP BY
-- ============================================================
SELECT
    '20260620'                        AS ftime
    ,a.user_id
    ,a.activity_level
    ,a.interaction_type
    ,CASE
        WHEN b.user_id IS NOT NULL AND c.user_id IS NOT NULL THEN 'active&new'
        WHEN b.user_id IS NOT NULL AND c.user_id IS NULL     THEN 'active'
        WHEN b.user_id IS NULL       AND c.user_id IS NOT NULL THEN 'new'
        ELSE 'other'
     END                              AS user_segment
    ,CASE
        WHEN c.user_id IS NOT NULL THEN c.recommend_algo_id
        ELSE -1
     END                              AS algorithm
FROM
    -- Subquery: user activity features
    (
        SELECT activity_level,
               CASE
                   WHEN (follow_7d + visit_7d + comment_7d + play_7d + like_7d) > 0
                       THEN 'has_interaction'
                   ELSE 'no_interaction'
               END  AS interaction_type,
               user_id
        FROM  analytics::user_daily_features
        WHERE ftime = date_sub('20260620', 1)
          AND activity_level <> 'churned'
    ) a
LEFT OUTER JOIN
    -- Base user info with partition hint
    core::user_base_info PARTITION(p_20260620) b
    ON a.user_id = b.user_id
LEFT OUTER JOIN
    -- Subquery: recommendation logs
    (
        SELECT *
        FROM  logs::recommend_action_log
        WHERE event_date BETWEEN '2026062000' AND '2026062023'
    ) c
    ON a.user_id = c.target_user_id
GROUP BY
    a.user_id,
    a.activity_level,
    a.interaction_type,
    CASE
        WHEN b.user_id IS NOT NULL AND c.user_id IS NOT NULL THEN 'active&new'
        WHEN b.user_id IS NOT NULL AND c.user_id IS NULL     THEN 'active'
        WHEN b.user_id IS NULL       AND c.user_id IS NOT NULL THEN 'new'
        ELSE 'other'
    END,
    CASE
        WHEN c.user_id IS NOT NULL THEN c.recommend_algo_id
        ELSE -1
    END
;
