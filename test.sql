 SELECT 
    '20260619' ftime
    ,a.uid
    ,a.active_level
    ,a.passive_type
    ,CASE WHEN b.uid is not null and c.uid is not null then 'new&old'
            WHEN b.uid is not null and c.uid is  null  then 'old'
            WHEN b.uid is null and c.uid is not null then 'new' else 'other' end robot_type
    ,CASE WHEN c.uid is not null then c.algorithm_id else -911 end algorithm
FROM
(SELECT active_level,
        CASE WHEN (users_tofollow_7d+cnt_tovisit_7d+cnt_tocomment_7d+cnt_toplay_7d+cnt_toflower_7d)>0 then 'has_passive'
        ELSE 'no_passive' END  passive_type,
        uid
FROM  sng_qmkg_rec::qmkg_user_passive_features_rd 
WHERE   ftime=date_sub('20260619',1)
        and active_level<>'已流失用户')a
LEFT OUTER JOIN
u_isd_qmusic::fd_qmkg_user_robot_base_info PARTITION(p_20260619) b on a.uid=b.uid
LEFT OUTER JOIN
(SELECT * FROM sng_qqmusic_log::msg_h_qmkg_robot_action
WHERE tdbank_imp_date between '2026061900' and '2026061923') c on a.uid=c.touid
GROUP BY a.uid
,a.active_level
,a.passive_type
,CASE WHEN b.uid is not null and c.uid is not null then 'new&old'
        WHEN b.uid is not null and c.uid is  null  then 'old'
        WHEN b.uid is null and c.uid is not null then 'new' else 'other' end
,CASE WHEN c.uid is not null then c.algorithm_id else -911 end