-- 第一段 SQL：查询用户行为
SELECT a.uid, a.action, b.user_name
FROM dwd::user_action a
LEFT JOIN dim::user_info b ON a.uid = b.uid
WHERE a.ftime = '20260619'
GROUP BY a.uid, a.action, b.user_name
;

-- 第二段 SQL：查询用户订单
SELECT a.uid, a.order_id, c.amount
FROM dwd::user_action a
INNER JOIN dwd::user_order c ON a.uid = c.uid
WHERE c.ftime = '20260619'
;
