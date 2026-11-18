# Tasks: retoken-dashboard-no-gloss

- [x] 1.1 Rewrite dashboard.html's `<style>` block per the design's substitution table (tokens, meaning-mapped tints, flat blue bar, no transition, row-ruled tables, rem rhythm)
- [x] 1.2 Verify: `node .agents/skills/impeccable/scripts/detect.mjs src/web/templates` reports 0 findings (was 13); render probe on `/dashboard` returns 200 with the new classes intact; test suites pass; `openspec validate retoken-dashboard-no-gloss --strict`
