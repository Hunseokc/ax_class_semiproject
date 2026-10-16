-- 종목이 속한 경쟁 그룹 목록 (그룹 탭용)
-- TODO(연결): Stage 5-D의 peer_groups.kind가 생기면 테마 그룹만 고른다(화면 경쟁 비교는 테마 그룹). 지금 그룹은 전부 테마.
SELECT g.group_id, g.name,
       (SELECT COUNT(*) FROM peer_group_members x JOIN stocks st ON st.stock_id = x.stock_id
         WHERE x.group_id = g.group_id AND st.coverage = 'featured') AS size      -- 노출 종목 수
FROM peer_group_members gm
JOIN peer_groups g ON g.group_id = gm.group_id
WHERE gm.stock_id = :stock_id
ORDER BY g.name
