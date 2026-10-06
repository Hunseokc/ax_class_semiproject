-- 종목이 속한 경쟁 그룹 목록 (그룹 탭용)
SELECT g.group_id, g.name,
       (SELECT COUNT(*) FROM peer_group_members x WHERE x.group_id = g.group_id) AS size
FROM peer_group_members gm
JOIN peer_groups g ON g.group_id = gm.group_id
WHERE gm.stock_id = :stock_id
ORDER BY g.name
