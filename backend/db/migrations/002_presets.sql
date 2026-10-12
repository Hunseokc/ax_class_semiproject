-- =====================================================================
-- 투자 성향 프리셋 개편: quality(퀄리티형) 제거, aggressive(위험) 추가, sort_order로 순서 관리
-- 멱등: 여러 번 실행해도 결과가 같다. 새로 만드는 DB는 schema.sql·config/scoring.yaml에 반영되어 있다.
-- 실행: python -m app.ingest migrate 002_presets  →  python -m app.ingest scores
-- (migrate는 이 파일 실행 후 config/scoring.yaml로 프리셋을 한 번 더 맞춘다 — 두 값은 같다)
-- =====================================================================

ALTER TABLE scoring_presets ADD COLUMN IF NOT EXISTS sort_order SMALLINT NOT NULL DEFAULT 0;

-- 없어지는 프리셋의 점수 → 프리셋(가중치는 CASCADE)
DELETE FROM stock_scores
WHERE preset_id IN (SELECT preset_id FROM scoring_presets
                    WHERE code NOT IN ('aggressive', 'growth', 'balanced', 'value'));
DELETE FROM scoring_presets WHERE code NOT IN ('aggressive', 'growth', 'balanced', 'value');

INSERT INTO scoring_presets (code, name, description, sort_order) VALUES
  ('aggressive', '위험', '모멘텀·성장 중심',   1),
  ('growth',     '성장', '성장성 중심',        2),
  ('balanced',   '균형', '5개 팩터 균등',      3),
  ('value',      '가치', '저평가·안정성 중심', 4)
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
                                 sort_order = EXCLUDED.sort_order;

INSERT INTO scoring_weights (preset_id, factor, weight)
SELECT p.preset_id, w.factor, w.weight
FROM (VALUES
  ('aggressive', 'value', 0.05), ('aggressive', 'quality', 0.10), ('aggressive', 'growth', 0.35),
  ('aggressive', 'safety', 0.10), ('aggressive', 'momentum', 0.40),
  ('growth', 'value', 0.10), ('growth', 'quality', 0.20), ('growth', 'growth', 0.40),
  ('growth', 'safety', 0.05), ('growth', 'momentum', 0.25),
  ('balanced', 'value', 0.20), ('balanced', 'quality', 0.20), ('balanced', 'growth', 0.20),
  ('balanced', 'safety', 0.20), ('balanced', 'momentum', 0.20),
  ('value', 'value', 0.40), ('value', 'quality', 0.20), ('value', 'growth', 0.10),
  ('value', 'safety', 0.20), ('value', 'momentum', 0.10)
) AS w(code, factor, weight)
JOIN scoring_presets p ON p.code = w.code
ON CONFLICT (preset_id, factor) DO UPDATE SET weight = EXCLUDED.weight;
