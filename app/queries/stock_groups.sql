-- 종목이 속한 경쟁 그룹 목록 (그룹 탭용)
SELECT g.group_id, g.name,
       (SELECT COUNT(*) FROM peer_group_members x JOIN stocks st ON st.stock_id = x.stock_id
         WHERE x.group_id = g.group_id AND st.coverage = 'featured') AS size      -- 노출 종목 수
FROM peer_group_members gm
JOIN peer_groups g ON g.group_id = gm.group_id
WHERE gm.stock_id = :stock_id
ORDER BY g.name
