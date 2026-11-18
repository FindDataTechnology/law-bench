// Minimal client-side behavior for the evaluation-rules UI:
//  1. Confirm destructive (delete) actions.
//  2. Dynamic criterion rows on the create-rubric form.
//  3. Toggle inline criterion editing on the rubric detail page.
//
// UI strings are read from window.__LOCALE__, bootstrapped by base.html from
// the same catalog the server renders. Every tr() call takes an English
// fallback so the page degrades gracefully (never throws) if the bootstrap is
// absent.
const L = window.__LOCALE__ || {};
// Data-label catalog (machine keys -> display labels), bootstrapped by
// base.html alongside __LOCALE__. Degrades to raw keys if absent.
const LABELS = window.__LABELS__ || {};

function tr(path, fallback) {
  let node = L;
  for (const part of String(path).split('.')) {
    if (node && Object.prototype.hasOwnProperty.call(node, part)) node = node[part];
    else return fallback != null ? fallback : String(path);
  }
  return typeof node === 'string' ? node : (fallback != null ? fallback : String(path));
}

function fmt(template, obj) {
  return String(template).replace(/\{(\w+)\}/g, (m, k) => (obj[k] != null ? String(obj[k]) : m));
}

// Resolve a data-value machine key to a localized display label. Returns the
// raw value when the kind/value is unmapped (mirrors src/web/i18n.py::label_for).
function labelFor(kind, value) {
  const cat = LABELS[kind] || {};
  return Object.prototype.hasOwnProperty.call(cat, value) ? cat[value] : value;
}

// Localized display title for a seeded prompt name draft_<type_key> (zh:
// "<type>起草", en: "<type> Drafting"). A versioned variant draft_<type>_v<N>
// appends " v<N>" to disambiguate the law-refined variant from baseline.
// Falls back to the raw name otherwise.
function titleForPrompt(name) {
  name = name || '';
  const m = /^draft_([a-z_]+?)(?:_v(\d+))?$/.exec(name);
  if (!m) return name;
  const ct = LABELS['contract_type'] || {};
  if (!Object.prototype.hasOwnProperty.call(ct, m[1])) return name;
  const base = (window.__LANG__ === 'zh') ? ct[m[1]] + '起草' : ct[m[1]] + ' Drafting';
  return m[2] ? base + ' v' + m[2] : base;
}

// Localized display title for a seeded rubric name contract_<type_key>_vN (zh:
// "<type>评价规则 vN", en: "<type> Rubric vN"). The " vN" suffix always appears
// so v1 and v2 variants are distinguishable. Falls back to the raw name otherwise.
function titleForRubric(name) {
  name = name || '';
  const m = /^contract_([a-z_]+?)_v(\d+)$/.exec(name);
  if (!m) return name;
  const ct = LABELS['contract_type'] || {};
  if (!Object.prototype.hasOwnProperty.call(ct, m[1])) return name;
  const base = (window.__LANG__ === 'zh') ? ct[m[1]] + '评价规则' : ct[m[1]] + ' Rubric';
  return base + ' v' + m[2];
}

document.addEventListener('DOMContentLoaded', () => {
  // 1. Confirm before destructive submits.
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  // 2. Dynamic criteria editor on the create form.
  const addBtn = document.getElementById('add-criterion');
  if (addBtn) {
    const wrap = document.getElementById('criteria-list');
    addBtn.addEventListener('click', () => wrap.appendChild(makeCriterionRow()));
    if (!wrap.children.length) wrap.appendChild(makeCriterionRow());
  }

  // 3. Toggle inline edit forms on the detail page.
  document.querySelectorAll('[data-toggle-edit]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const row = btn.closest('.criterion-row');
      row.querySelector('.crit-edit').classList.toggle('open');
    });
  });
});

function makeCriterionRow() {
  const div = document.createElement('div');
  div.className = 'criterion-row';
  div.innerHTML =
    '<div class="crow-head">' +
    '<strong>' + tr('crit_row.new', 'New criterion') + '</strong>' +
    '<button type="button" class="btn btn-sm btn-danger" data-remove-row>' + tr('crit_row.remove', 'Remove') + '</button>' +
    '</div>' +
    '<div class="row"><label>' + tr('crit_row.name', 'Name') + '</label><input type="text" name="criteria_name" required placeholder="' + tr('crit_row.name_placeholder', 'e.g. party_identification') + '"></div>' +
    '<div class="grid2">' +
    '<div class="row"><label>' + tr('crit_row.description', 'Description') + '</label><textarea name="criteria_description" required></textarea></div>' +
    '<div class="row"><label>' + tr('crit_row.guidance', 'Guidance') + '</label><textarea name="criteria_guidance" required></textarea></div>' +
    '</div>';
  div.querySelector('[data-remove-row]').addEventListener('click', () => div.remove());
  return div;
}

// === Prompt compare: WIP form state, async run, localStorage mirror =========
//
// DB is the source of truth; localStorage mirrors (1) the in-progress compare
// form (so a refresh does not lose config) and (2) a compact result per compare
// (matrix + verdicts + reasoning, NO draft_text) under a byte-budget LRU cap.
// draft_text is lazy-fetched on demand. Cache key is versioned; DB wins on load.
const CACHE_PREFIX = 'lawcmp:v1:';
const CACHE_INDEX_KEY = CACHE_PREFIX + 'index';   // compare ids, most-recent last
const CACHE_BUDGET = 4 * 1024 * 1024;             // ~4 MB ceiling
const WIP_KEY = CACHE_PREFIX + 'wip';

function lsGetJSON(key, fallback) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
  catch (e) { return fallback; }
}
function lsSetJSON(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)); }
  catch (e) { /* ignore quota on small metadata keys */ }
}
function lsSetRaw(key, val) {
  localStorage.setItem(key, val);   // may throw QuotaExceededError; caller evicts
}
function lsCachedBytes() {
  let n = 0;
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(CACHE_PREFIX)) n += (localStorage.getItem(k) || '').length;
  }
  return n;
}
function cacheKey(id) { return CACHE_PREFIX + 'compare:' + id; }

function bumpLru(id) {
  const idx = lsGetJSON(CACHE_INDEX_KEY, []);
  const i = idx.indexOf(id);
  if (i !== -1) idx.splice(i, 1);
  idx.push(id);
  lsSetJSON(CACHE_INDEX_KEY, idx);
}
function evictToFit(needed) {
  const idx = lsGetJSON(CACHE_INDEX_KEY, []);
  let guard = 0;
  while (idx.length && (lsCachedBytes() + needed > CACHE_BUDGET) && guard++ < 1000) {
    const oldId = idx.shift();
    try { localStorage.removeItem(cacheKey(oldId)); } catch (e) {}
  }
  lsSetJSON(CACHE_INDEX_KEY, idx);
}
function mirrorCompare(compare) {
  // Compact mirror: everything the matrix needs, excluding draft_text.
  const compact = {
    id: compare.id, label: compare.label, contract_type: compare.contract_type,
    rubric_name: compare.rubric_name, task_desc: compare.task_desc,
    gen_mode: compare.gen_mode, n_drafts: compare.n_drafts, created_at: compare.created_at,
    runs: (compare.runs || []).map(r => ({
      id: r.id, prompt_name: r.prompt_name, prompt_type: r.prompt_type,
      variant_label: r.variant_label, score: r.score, all_pass: r.all_pass,
      n_passed: r.n_passed, n_criteria: r.n_criteria,
      criteria_results: (r.criteria_results || []).map(c => ({
        criterion_id: c.criterion_id, verdict: c.verdict, reasoning: c.reasoning,
      })),
    })),
    matrix: compare.matrix,
    _v: 1,
  };
  let payload;
  try { payload = JSON.stringify(compact); } catch (e) { return; }
  evictToFit(payload.length);
  try {
    lsSetRaw(cacheKey(compare.id), payload);
  } catch (e) {
    evictToFit(payload.length + 1024);
    try { lsSetRaw(cacheKey(compare.id), payload); } catch (e2) { /* DB remains truth */ }
  }
  bumpLru(compare.id);
}
function readMirror(id) {
  const m = lsGetJSON(cacheKey(id), null);
  return (m && m._v === 1) ? m : null;
}
function dropMirror(id) {
  try { localStorage.removeItem(cacheKey(id)); } catch (e) {}
  const idx = lsGetJSON(CACHE_INDEX_KEY, []);
  const i = idx.indexOf(id);
  if (i !== -1) { idx.splice(i, 1); lsSetJSON(CACHE_INDEX_KEY, idx); }
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// --- compare form: WIP persistence + async submit -------------------------- #
function initCompareForm() {
  const form = document.getElementById('compare-form');
  if (!form) return;

  const status = document.getElementById('compare-status');
  const elapsedEl = document.getElementById('compare-elapsed');
  const btn = document.getElementById('compare-submit');
  const cancelBtn = document.getElementById('compare-cancel');
  const countEl = document.getElementById('compare-count');
  const filterSel = document.getElementById('f-type-filter');
  const rubricSel = document.getElementById('f-rubric_name');
  const ctInput = document.getElementById('f-contract_type');
  const ndInput = document.getElementById('f-n_drafts');
  const rubricWarn = document.getElementById('compare-rubric-warning');
  const checkedBoxes = () => Array.from(document.querySelectorAll('input[name="prompts"]:checked'));

  const wip = lsGetJSON(WIP_KEY, null);
  if (wip) {
    if (wip.task) document.getElementById('f-task').value = wip.task;
    if (wip.contract_type) document.getElementById('f-contract_type').value = wip.contract_type;
    if (wip.rubric_name) document.getElementById('f-rubric_name').value = wip.rubric_name;
    if (wip.mode) document.getElementById('f-mode').value = wip.mode;
    if (wip.n_drafts) document.getElementById('f-n_drafts').value = wip.n_drafts;
    if (wip.concurrency) document.getElementById('f-concurrency').value = wip.concurrency;
    if (wip.label) document.getElementById('f-label').value = wip.label;
    if (Array.isArray(wip.prompts)) {
      document.querySelectorAll('input[name="prompts"]').forEach(cb => {
        cb.checked = wip.prompts.indexOf(cb.value) !== -1;
      });
    }
  }

  const saveWip = () => {
    const prompts = checkedBoxes().map(cb => cb.value);
    lsSetJSON(WIP_KEY, {
      task: document.getElementById('f-task').value,
      contract_type: document.getElementById('f-contract_type').value,
      rubric_name: document.getElementById('f-rubric_name').value,
      mode: document.getElementById('f-mode').value,
      n_drafts: document.getElementById('f-n_drafts').value,
      concurrency: document.getElementById('f-concurrency').value,
      label: document.getElementById('f-label').value,
      prompts,
    });
  };
  form.addEventListener('input', saveWip);
  form.addEventListener('change', ev => {
    saveWip();
    updateCount();
    if ((ev.target === rubricSel || ev.target === ctInput) && rubricWarn) {
      rubricWarn.hidden = true;              // stale mismatch clears as soon as either side moves
    }
  });

  // Live selection count + submit guard: visible text, never color alone.
  function updateCount() {
    const k = checkedBoxes().length;
    if (countEl) countEl.textContent = ' ' + fmt(tr('matrix.selected_count', '{k} selected (min 2)'), { k });
    btn.disabled = k < 2;
  }

  // Checklist filter by contract type; checked state is never touched.
  function applyFilter() {
    const f = filterSel ? filterSel.value : 'all';
    document.querySelectorAll('input[name="prompts"]').forEach(cb => {
      const row = cb.closest('label');
      if (row) row.hidden = f !== 'all' && cb.dataset.contractType !== f;
    });
  }
  if (filterSel) filterSel.addEventListener('change', () => { applyFilter(); updateCount(); });

  // Rubric guidance: float rubrics matching the chosen type to the top (no filtering).
  function orderRubrics() {
    if (!rubricSel) return;
    const type = (ctInput && ctInput.value || '').trim().toLowerCase();
    const prefix = type ? 'contract_' + type + '_' : null;
    const selected = rubricSel.value;
    const scored = Array.from(rubricSel.options).map((o, i) => ({
      o, i, s: prefix && o.value.toLowerCase().indexOf(prefix) === 0 ? 1 : 0,
    }));
    scored.sort((a, b) => b.s - a.s || a.i - b.i);
    scored.forEach(e => rubricSel.appendChild(e.o));
    rubricSel.value = selected;
  }
  if (ctInput) ctInput.addEventListener('change', orderRubrics);

  // n_drafts bound [1, 8], mirrored on the field.
  function clampDrafts() {
    if (!ndInput) return;
    const v = parseInt(ndInput.value || '1', 10);
    const c = Math.min(8, Math.max(1, isNaN(v) ? 1 : v));
    if (String(v) !== String(c)) ndInput.value = c;
  }
  if (ndInput) ndInput.addEventListener('change', clampDrafts);

  // Run instrumentation: elapsed timer, cancel via AbortController.
  // Cancel aborts the client's wait only; the server-side run may continue.
  const LAST_KEY = 'compare:lastAttempt';
  let timer = null;
  let controller = null;
  const fmtElapsed = ms => {
    const s = Math.floor(ms / 1000);
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  };
  const stopTimer = () => { if (timer) { clearInterval(timer); timer = null; } };
  const settle = () => { stopTimer(); if (cancelBtn) cancelBtn.hidden = true; controller = null; };
  if (cancelBtn) cancelBtn.onclick = () => { if (controller) controller.abort(); };

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const prompts = checkedBoxes().map(cb => cb.value);
    if (prompts.length < 2) {
      status.textContent = tr('matrix.select_min', 'Select at least 2 prompts.');
      return;                                  // guard stays; button should already be disabled
    }
    // Rubric/type mismatch guard: only rubric names following the
    // contract_<type>_v<N> convention embed a type to check — pattern-less
    // names (harbor/custom) pass through with no warning, by design.
    const ctVal = (ctInput && ctInput.value || '').trim().toLowerCase();
    const embedded = rubricSel && rubricSel.value.toLowerCase().match(/^contract_([a-z0-9_]+?)_v\d+$/);
    if (rubricWarn && embedded && ctVal && embedded[1] !== ctVal) {
      rubricWarn.textContent = fmt(tr('matrix.rubric_mismatch',
        'Rubric type {rubric_type} ({rubric_label}) does not match contract type {ct} ({ct_label}). Fix one side before running.'),
        { rubric_type: embedded[1], rubric_label: labelFor('contract_type', embedded[1]),
          ct: ctVal, ct_label: labelFor('contract_type', ctVal) });
      rubricWarn.hidden = false;
      return;                                  // block before the fetch; the form stays editable
    }
    clampDrafts();
    const body = {
      contract_type: document.getElementById('f-contract_type').value,
      rubric_name: document.getElementById('f-rubric_name').value,
      task_desc: document.getElementById('f-task').value,
      prompts,
      mode: document.getElementById('f-mode').value,
      n_drafts: parseInt(document.getElementById('f-n_drafts').value || '1', 10),
      concurrency: parseInt(document.getElementById('f-concurrency').value || '1', 10),
      label: document.getElementById('f-label').value || null,
    };
    const bodyStr = JSON.stringify(body);
    let lastAttempt = null;
    try { lastAttempt = sessionStorage.getItem(LAST_KEY); } catch (_e) { /* guard degrades off */ }
    if (lastAttempt && lastAttempt === bodyStr) {
      if (!window.confirm(tr('matrix.resubmit_confirm',
        'The same configuration failed or was cancelled last time. Run it again?'))) return;
    }
    try { sessionStorage.removeItem(LAST_KEY); } catch (_e) { /* ignore */ }
    controller = new AbortController();
    btn.disabled = true;
    if (cancelBtn) cancelBtn.hidden = false;
    const t0 = Date.now();
    const runningLabel = () => tr('matrix.running', 'Running compare… this may take a minute.');
    status.textContent = runningLabel();
    if (elapsedEl) elapsedEl.textContent = '';
    timer = setInterval(() => {
      // Only the sibling span updates each tick so the aria-live region is
      // announced once, not re-announced every second.
      if (elapsedEl) elapsedEl.textContent = fmt(tr('matrix.elapsed', 'Running {t}'), { t: fmtElapsed(Date.now() - t0) });
    }, 1000);
    try {
      const r = await fetch('/api/compare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: bodyStr, signal: controller.signal,
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.error || ('HTTP ' + r.status));
      }
      const data = await r.json();
      settle();
      mirrorCompare(data);            // cache before navigating
      saveWip();                       // keep WIP so re-running is one edit
      window.location.href = '/compare/' + data.id;
    } catch (err) {
      settle();
      try { sessionStorage.setItem(LAST_KEY, bodyStr); } catch (_e) { /* ignore */ }
      status.textContent = (err && err.name === 'AbortError')
        ? tr('matrix.cancelled',
            'Wait cancelled: the server may still be running. Your configuration is preserved; you can run again.')
        : tr('matrix.error', 'Error: ') + err.message;
      updateCount();                   // re-sync submit disabled state
    }
  });

  updateCount();                       // initial count after WIP restore
}

// --- compare detail: paint from cache, reconcile with DB, render matrix ---- #
function initCompareDetail() {
  const id = window.LAWCMP_COMPARE_ID;
  if (id === undefined) return;

  const loading = document.getElementById('compare-loading');
  const errBox = document.getElementById('compare-error');
  const result = document.getElementById('compare-result');
  const headline = document.getElementById('compare-headline');
  const meta = document.getElementById('compare-meta');
  const table = document.getElementById('compare-matrix');
  const legend = document.getElementById('compare-legend');
  const reasonBox = document.getElementById('compare-reasoning');
  const reasonTitle = document.getElementById('compare-reasoning-title');
  const reasonText = document.getElementById('compare-reasoning-text');
  const draftBox = document.getElementById('compare-draft');

  // Panels close on Escape and return focus to the control that opened them;
  // focus moves into the panel on open so keyboard users reach it immediately.
  const reasonCloseBtn = document.getElementById('compare-reasoning-close');
  const draftCloseBtn = document.getElementById('compare-draft-close');
  let reasonOpener = null;
  let draftOpener = null;
  const closeReasoning = () => {
    reasonBox.style.display = 'none';
    if (reasonOpener) { reasonOpener.focus(); reasonOpener = null; }
  };
  const closeDraft = () => {
    draftBox.style.display = 'none';
    if (draftOpener) { draftOpener.focus(); draftOpener = null; }
  };
  reasonCloseBtn.addEventListener('click', closeReasoning);
  draftCloseBtn.addEventListener('click', closeDraft);
  document.addEventListener('keydown', ev => {
    if (ev.key !== 'Escape') return;
    if (reasonBox.style.display !== 'none') { ev.preventDefault(); closeReasoning(); }
    else if (draftBox.style.display !== 'none') { ev.preventDefault(); closeDraft(); }
  });

  function render(compare) {
    loading.style.display = 'none';
    result.style.display = '';
    meta.textContent = fmt(tr('matrix.meta', '{ct} · {rubric} · {mode} · N={n}'), {
      ct: labelFor('contract_type', compare.contract_type || '-'),
      rubric: titleForRubric(compare.rubric_name || '-'),
      mode: labelFor('mode', compare.gen_mode || '-'),
      n: compare.n_drafts || 1,
    });
    const runs = compare.runs || [];
    const passed = runs.reduce((a, r) => a + (r.n_passed || 0), 0);
    const total = runs.reduce((a, r) => a + (r.n_criteria || 0), 0);
    headline.textContent = fmt(tr('matrix.headline', '{n} run(s); {passed}/{total} criteria passed (last-draft counts).'), {
      n: runs.length, passed, total,
    });
    renderMatrix(compare);
    legend.textContent = (compare.n_drafts > 1)
      ? tr('matrix.legend_multi', 'Cells show pass-rate (k/N). Click a cell for judge reasoning.')
      : tr('matrix.legend_single', 'Cells show pass/fail. Click a cell for judge reasoning.');
  }

  function renderMatrix(compare) {
    const m = compare.matrix || { criteria: [], columns: [], cells: {} };
    const runIdByPrompt = {};
    (compare.runs || []).forEach(r => { runIdByPrompt[r.prompt_name] = r.id; });

    const passLabel = tr('matrix.pass', 'pass');
    const failLabel = tr('matrix.fail', 'fail');
    let html = '<caption class="matrix-caption">'
      + escapeHtml(tr('matrix.caption', 'Verdict matrix: criteria × prompts')) + '</caption>'
      + '<thead><tr><th>' + escapeHtml(tr('matrix.criterion', 'criterion')) + '</th>';
    m.columns.forEach(col => {
      const head = col.prompt_type ? labelFor('prompt_type', col.prompt_type) : titleForPrompt(col.prompt_name);
      html += `<th>${escapeHtml(head)}<br><span class="muted">${escapeHtml(col.prompt_name)}</span></th>`;
    });
    html += '</tr></thead><tbody>';
    m.criteria.forEach(crit => {
      html += `<tr><td><strong>${escapeHtml(crit.id)}</strong><div class="muted">${escapeHtml(crit.title || '')}</div></td>`;
      m.columns.forEach(col => {
        const cell = (m.cells[col.prompt_name] || {})[crit.id] || {};
        const reasoning = cell.reasoning || '';
        let mark, cls;
        if ('verdict' in cell) {
          mark = cell.verdict === 'pass' ? '✓ ' + passLabel : '✗ ' + failLabel;
          cls = cell.verdict === 'pass' ? 'pass' : 'fail';
        } else {
          mark = `${cell.n_pass || 0}/${cell.n || 0}`;
          cls = 'rate';
        }
        // The verdict trigger is a real button inside the tinted cell so the
        // signature interaction is keyboard- and screen-reader-operable.
        html += `<td class="cell ${cls}">`
              + `<button type="button" class="cell-btn" data-reasoning="${escapeHtml(reasoning)}" `
              + `data-criterion="${escapeHtml(crit.id)}" data-prompt="${escapeHtml(col.prompt_name)}">`
              + `${mark}</button></td>`;
      });
      html += '</tr>';
    });
    const viewDraftLabel = escapeHtml(tr('matrix.view_draft', 'view draft'));
    html += '<tr><td class="muted">' + viewDraftLabel + '</td>';
    m.columns.forEach(col => {
      const runId = runIdByPrompt[col.prompt_name];
      html += `<td><button type="button" class="btn btn-sm" data-draft-run="${runId || ''}" data-prompt="${escapeHtml(col.prompt_name)}">${viewDraftLabel}</button></td>`;
    });
    html += '</tr></tbody>';
    table.innerHTML = html;

    table.querySelectorAll('button.cell-btn[data-reasoning]').forEach(btnEl => {
      btnEl.addEventListener('click', () => {
        reasonOpener = btnEl;
        reasonTitle.textContent = `${titleForPrompt(btnEl.dataset.prompt)} · ${btnEl.dataset.criterion}`;
        reasonText.textContent = btnEl.dataset.reasoning || tr('matrix.no_reasoning', '(no reasoning recorded)');
        reasonBox.style.display = '';
        reasonCloseBtn.focus();
      });
    });
    table.querySelectorAll('button[data-draft-run]').forEach(btn => {
      btn.addEventListener('click', () => {
        draftOpener = btn;
        loadDraft(id, btn.dataset.draftRun, btn.dataset.prompt);
        draftCloseBtn.focus();
      });
    });
  }

  async function loadDraft(compareId, runId, promptName) {
    const box = document.getElementById('compare-draft');
    const title = document.getElementById('compare-draft-title');
    const text = document.getElementById('compare-draft-text');
    title.textContent = tr('matrix.draft_title', 'Draft · ') + titleForPrompt(promptName);
    text.textContent = tr('matrix.loading', 'Loading…');
    box.style.display = '';
    try {
      const r = await fetch(`/api/compare/${compareId}/run/${runId}/draft`);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      text.textContent = d.draft_text || tr('matrix.empty_draft', '(empty draft)');
    } catch (e) {
      text.textContent = tr('matrix.error', 'Error: ') + e.message;
    }
  }

  // 1. Paint from cache first (instant), if present and version-current.
  const cached = readMirror(id);
  if (cached) render(cached);

  // 2. Reconcile with the server. DB wins; drop cache if the compare was deleted.
  fetch(`/api/compare/${id}`).then(r => {
    if (r.status === 404) {
      dropMirror(id);
      loading.style.display = 'none';
      result.style.display = 'none';
      errBox.style.display = '';
      errBox.textContent = fmt(tr('matrix.not_found', 'Compare #{id} was not found on the server.'), { id });
      return null;
    }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(compare => {
    if (!compare) return;
    mirrorCompare(compare);   // refresh cache (DB wins)
    render(compare);
  }).catch(() => {
    if (!cached) {
      loading.style.display = 'none';
      errBox.style.display = '';
      errBox.textContent = tr('matrix.error_loading', 'Error loading compare (and no cached copy available).');
    }
    // else: keep the cached render; server temporarily unavailable.
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initCompareForm();
  initCompareDetail();
});
