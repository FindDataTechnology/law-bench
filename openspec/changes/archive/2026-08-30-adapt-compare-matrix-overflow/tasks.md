# Tasks: adapt-compare-matrix-overflow

- [x] 1.1 `compare_detail.html`: wrap `<table class="matrix" id="compare-matrix">` in `<div class="matrix-scroll" role="region" aria-label="{{ t.matrix.caption }}">…</div>`
- [x] 1.2 `style.css`: `.matrix-scroll { overflow-x: auto; }`; `table.matrix { min-width: 40rem; }`; `table.matrix thead th span.muted { white-space: normal; overflow-wrap: anywhere; }`
- [x] 1.3 Verify: render probe asserts the wrapper; test suites pass; detector clean (0 new); `openspec validate adapt-compare-matrix-overflow --strict`
