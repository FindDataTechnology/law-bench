// generation-panel.js — 「生成合同模板」面板交互
//
// 序列表单 → 按所选模式发请求：
//   A 母版骨架     只读，直接渲染母版 DOCX/PDF 下载链接（不发请求）。
//   B 标签组装     POST /api/contracts/{type}/generate            （同步 200）
//   C 存储 MinIO   POST /api/contracts/{type}/generate-stored     （同步 200）
//   D 批量组装     POST /api/contracts/{type}/generate-batch       （同步 200）
//   E 自愈流水线   POST /api/contracts/{type}/pipeline             （202 + 轮询）
//   F 自动拒绝     POST /api/contracts/{type}/auto-reject          （202 + 轮询）
//   G LLM 重生成   POST /api/contracts/{type}/regenerate-template  （202 + 轮询）
//
// 异步模式拿到 202 + {job_id} 后轮询 GET /api/generation-jobs/{id}，每 3s 一次，
// 终态(completed/failed)停止。E/F/G 提交前弹确认框，说明各自改写的状态：
//   E/F → clauses 表 + pipeline_runs；F 还会拒绝不合格自定义条款；G → 全局 contracts.json。

(function () {
  'use strict';

  // Chrome catalog for this panel (base.html bootstraps window.__LOCALE__).
  var L = (window.__LOCALE__ && window.__LOCALE__.gen) || {};
  // fmt('key', {placeholder: value}) — catalog strings carry {name} placeholders.
  function fmt(key, params) {
    var s = L[key] || '';
    if (params) Object.keys(params).forEach(function (k) {
      s = s.split('{' + k + '}').join(String(params[k]));
    });
    return s;
  }

  var panel = document.getElementById('generation-panel');
  if (!panel) return;
  var contractType = panel.getAttribute('data-contract-type') || '';
  var form = document.getElementById('generation-form');
  var submitBtn = document.getElementById('gen-submit');
  var statusEl = document.getElementById('gen-status');
  var resultEl = document.getElementById('gen-result');
  if (!form || !submitBtn || !statusEl || !resultEl) return;

  var POLL_MS = 3000;
  var MAX_POLLS = 200; // ~10 min 上限，防止无限轮询

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function setStatus(msg, kind) {
    statusEl.textContent = msg || '';
    var colors = { ok: 'var(--ok)', error: 'var(--danger)', muted: 'var(--muted)' };
    statusEl.style.color = colors[kind || 'muted'] || colors.muted;
  }

  function clearResult() { resultEl.innerHTML = ''; }

  function currentMode() {
    var checked = form.querySelector('input[name="mode"]:checked');
    return checked ? checked.value : 'A';
  }

  // 切换模式时显隐 mode 专属字段（D 的 tag_combinations；E/F 的 rubric/迭代等）。
  function refreshExtras() {
    var mode = currentMode();
    var dExtra = panel.querySelector('.gen-extra[data-mode="D"]');
    var efExtra = panel.querySelector('.gen-extra[data-mode="EF"]');
    if (dExtra) dExtra.style.display = (mode === 'D') ? '' : 'none';
    if (efExtra) efExtra.style.display = (mode === 'E' || mode === 'F') ? '' : 'none';
  }

  function parseIds() {
    var el = form.elements['custom_clause_ids'];
    var raw = (el && el.value || '').trim();
    if (!raw) return null;
    return raw.split(',').map(function (s) {
      return parseInt(s.trim(), 10);
    }).filter(function (n) { return Number.isInteger(n); });
  }

  // 共享字段：B/C/D/E/F/G 都用得到的部分。
  function sharedBody() {
    var body = {};
    var stance = form.elements['stance'].value;
    var scenario = (form.elements['scenario'].value || '').trim();
    var fmt = form.elements['format'].value;
    if (stance) body.stance = stance;
    if (scenario) body.scenario = scenario;
    var ids = parseIds();
    if (ids && ids.length) body.custom_clause_ids = ids;
    body.format = fmt;
    return body;
  }

  // E/F 的请求体：共享字段 + 流水线参数 + mode。
  function pipelineBody(mode) {
    var body = sharedBody();
    body.mode = mode;
    var rubric = (form.elements['rubric'].value || '').trim();
    var taskDesc = (form.elements['task_desc'].value || '').trim();
    var maxIt = parseInt(form.elements['max_iterations'].value, 10);
    var temp = parseFloat(form.elements['temperature'].value);
    if (rubric) body.rubric = rubric;
    if (taskDesc) body.task_desc = taskDesc;
    if (Number.isFinite(maxIt)) body.max_iterations = maxIt;
    if (Number.isFinite(temp)) body.temperature = temp;
    return body;
  }

  // D 的请求体：共享字段 + tag_combinations / enumerate_all + mode。
  function batchBody() {
    var body = sharedBody();
    body.mode = 'D';
    body.enumerate_all = form.elements['enumerate_all'].checked;
    var tcRaw = (form.elements['tag_combinations'].value || '').trim();
    if (tcRaw) {
      try {
        var parsed = JSON.parse(tcRaw);
        if (!Array.isArray(parsed)) throw new Error(L.err_not_array);
        body.tag_combinations = parsed;
      } catch (e) {
        throw new Error(fmt('err_tc_invalid', { msg: e.message }));
      }
    }
    if (!body.enumerate_all && !(body.tag_combinations && body.tag_combinations.length)) {
      throw new Error(L.err_d_requires);
    }
    return body;
  }

  // E/F/G 确认文案：点明各自改写的状态。{N} 占位替换为实际迭代上限。
  var CONFIRM = { E: L.confirm_e, F: L.confirm_f, G: L.confirm_g };

  function downloadLink(href, label) {
    if (!href) return '';
    return '<a class="btn btn-sm" href="' + escapeHtml(href) +
      '" target="_blank" rel="noopener">' + escapeHtml(label) + '</a>';
  }

  // 同步模式(B/C/D)结果渲染：下载链接 + 摘要。
  function renderSyncResult(mode, data) {
    var html = '';
    if (mode === 'B') {
      html += '<div class="flash ok">' + L.done_assemble + '</div>';
      html += '<div class="toolbar">' +
        downloadLink(data.docx_url, L.download_docx) + downloadLink(data.pdf_url, L.download_pdf) + '</div>';
      if (data.diagnostics) {
        html += '<details><summary class="muted">' + L.diagnostics + '</summary><pre class="prompt-content">' +
          escapeHtml(JSON.stringify(data.diagnostics, null, 2)) + '</pre></details>';
      }
    } else if (mode === 'C') {
      if (data.docx_url || data.pdf_url) {
        var reused = data.reused ? L.reused_suffix : '';
        html += '<div class="flash ok">' + escapeHtml(fmt('stored_ok', { reused: reused, id: data.artifact_id })) + '</div>';
        html += '<div class="toolbar">' +
          downloadLink(data.docx_url, L.download_docx) + downloadLink(data.pdf_url, L.download_pdf) + '</div>';
      } else if (Array.isArray(data.artifacts)) {
        html += '<div class="flash ok">' + escapeHtml(fmt('batch_stored', {
          count: data.count || 0, new: data.new || 0, reused: data.reused || 0, failed: data.failed || 0
        })) + '</div>';
        if (data.failed) {
          html += '<details><summary class="muted">' + L.failure_detail + '</summary><pre class="prompt-content">' +
            escapeHtml(JSON.stringify(data.failures, null, 2)) + '</pre></details>';
        }
      } else {
        html += '<pre class="prompt-content">' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
      }
    } else if (mode === 'D') {
      html += '<div class="flash ok">' + escapeHtml(fmt('batch_assembled', {
        total: data.total_requested || 0, ok: data.success_count || 0, fail: data.failure_count || 0
      })) + '</div>';
      (data.results || []).forEach(function (r) {
        var tags = r.tags ? JSON.stringify(r.tags) : '';
        if (r.success) {
          html += '<div class="toolbar"><span class="muted">' + escapeHtml(tags) + '</span>' +
            downloadLink(r.docx_url, 'DOCX') + downloadLink(r.pdf_url, 'PDF') + '</div>';
        } else {
          html += '<div class="flash error">' + escapeHtml(tags) + '：' + escapeHtml(r.error) + '</div>';
        }
      });
    } else {
      html += '<pre class="prompt-content">' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
    }
    resultEl.innerHTML = html;
  }

  // 异步模式(E/F/G)终态渲染：按 kind 渲染 result_ref 摘要。
  function renderJobResult(kind, ref, errMsg) {
    var html = '';
    if (errMsg) {
      html += '<div class="flash error">' + escapeHtml(L.failed_prefix + errMsg) + '</div>';
    } else if (kind === 'pipeline') {
      var pass = ref && ref.all_pass;
      html += '<div class="flash ' + (pass ? 'ok' : 'error') + '">' + escapeHtml(fmt('pipeline_done', {
        iter: (ref && ref.iteration != null ? ref.iteration : '-'),
        score: (ref && ref.score != null ? ref.score : '-'),
        criteria: (ref && ref.n_criteria != null ? ref.n_criteria : '-'),
        pass: pass ? L.all_pass : L.not_all_pass
      })) + '</div>';
      if (ref && ref.eval_run_id != null) {
        html += '<div class="muted">eval_run_id: ' + escapeHtml(ref.eval_run_id) +
          ' · pipeline_run_id: ' + escapeHtml(ref.pipeline_run_id) + '</div>';
      }
    } else if (kind === 'auto_reject') {
      var pass2 = ref && ref.all_pass;
      html += '<div class="flash ' + (pass2 ? 'ok' : 'error') + '">' + escapeHtml(fmt('auto_reject_done', {
        iter: (ref && ref.iteration != null ? ref.iteration : '-'),
        score: (ref && ref.score != null ? ref.score : '-'),
        criteria: (ref && ref.n_criteria != null ? ref.n_criteria : '-'),
        pass: pass2 ? L.all_pass : ''
      })) + '</div>';
      if (ref && ref.learn_applied != null) {
        html += '<div class="muted">' + escapeHtml(fmt('learn_applied', { n: ref.learn_applied })) + '</div>';
      }
    } else if (kind === 'regenerate') {
      html += '<div class="flash ok">' + L.regen_done + '</div>';
      if (ref && ref.stdout) {
        html += '<details><summary class="muted">' + L.stdout_tail + '</summary>' +
          '<pre class="prompt-content">' + escapeHtml(String(ref.stdout).slice(-2000)) + '</pre></details>';
      }
    } else {
      html += '<pre class="prompt-content">' + escapeHtml(JSON.stringify(ref, null, 2)) + '</pre>';
    }
    resultEl.innerHTML = html;
  }

  // 轮询 job 状态直到终态或超时。
  function pollJob(jobId) {
    var n = 0;
    return new Promise(function (resolve, reject) {
      function tick() {
        fetch('/api/generation-jobs/' + jobId).then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        }).then(function (job) {
          n++;
          if (job.status === 'completed' || job.status === 'failed') {
            submitBtn.disabled = false;
            setStatus(job.status === 'completed' ? L.status_done : L.status_failed,
              job.status === 'completed' ? 'ok' : 'error');
            renderJobResult(job.kind, job.result_ref, job.error_message);
            resolve(job);
          } else if (n >= MAX_POLLS) {
            submitBtn.disabled = false;
            setStatus(fmt('poll_timeout', { id: jobId }), 'error');
            reject(new Error('poll timeout'));
          } else {
            setStatus(fmt('status_running', { status: job.status }));
            setTimeout(tick, POLL_MS);
          }
        }).catch(function (err) {
          submitBtn.disabled = false;
          setStatus(fmt('status_query_failed', { msg: err.message }), 'error');
          reject(err);
        });
      }
      tick();
    });
  }

  // E/F/G：确认 → POST → 202 → 轮询。
  async function submitAsync(url, body, mode) {
    var msg = CONFIRM[mode].replace('{N}', String(body.max_iterations || 3));
    if (!window.confirm(msg)) {
      setStatus(L.status_cancelled);
      return;
    }
    submitBtn.disabled = true;
    setStatus(L.status_submitting);
    clearResult();
    try {
      var r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (r.status !== 202) {
        var err1 = await r.json().catch(function () { return {}; });
        throw new Error((err1 && (err1.detail || err1.error)) || ('HTTP ' + r.status));
      }
      var data = await r.json();
      setStatus(fmt('status_submitted', { id: data.job_id }));
      await pollJob(data.job_id);
    } catch (err) {
      submitBtn.disabled = false;
      setStatus(fmt('status_error', { msg: err.message }), 'error');
      resultEl.innerHTML = '<div class="flash error">' + escapeHtml(err.message) + '</div>';
    }
  }

  // B/C/D：同步 POST → 200 → 渲染下载链接。
  async function submitSync(url, body, mode) {
    submitBtn.disabled = true;
    setStatus(L.status_generating);
    clearResult();
    try {
      var r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      var data = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        throw new Error((data && (data.detail || data.error)) || ('HTTP ' + r.status));
      }
      setStatus(L.status_done, 'ok');
      renderSyncResult(mode, data);
    } catch (err) {
      setStatus(fmt('status_error', { msg: err.message }), 'error');
      resultEl.innerHTML = '<div class="flash error">' + escapeHtml(err.message) + '</div>';
    } finally {
      submitBtn.disabled = false;
    }
  }

  // A：只读，直接渲染母版下载链接。
  function renderModeA() {
    clearResult();
    var base = '/contracts/' + encodeURIComponent(contractType) + '/download/';
    var html = '<div class="flash ok">' + L.mode_a_hint + '</div>';
    html += '<div class="toolbar">' +
      downloadLink(base + 'docx', L.download_docx) + downloadLink(base + 'pdf', L.download_pdf) + '</div>';
    resultEl.innerHTML = html;
    setStatus('');
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var mode = currentMode();
    var base = '/api/contracts/' + encodeURIComponent(contractType);
    try {
      if (mode === 'A') {
        renderModeA();
      } else if (mode === 'B') {
        await submitSync(base + '/generate', sharedBody(), 'B');
      } else if (mode === 'C') {
        await submitSync(base + '/generate-stored', sharedBody(), 'C');
      } else if (mode === 'D') {
        await submitSync(base + '/generate-batch', batchBody(), 'D');
      } else if (mode === 'E') {
        await submitAsync(base + '/pipeline', pipelineBody('E'), 'E');
      } else if (mode === 'F') {
        await submitAsync(base + '/auto-reject', pipelineBody('F'), 'F');
      } else if (mode === 'G') {
        await submitAsync(base + '/regenerate-template', { mode: 'G' }, 'G');
      }
    } catch (err) {
      submitBtn.disabled = false;
      setStatus(fmt('status_error', { msg: err.message }), 'error');
      resultEl.innerHTML = '<div class="flash error">' + escapeHtml(err.message) + '</div>';
    }
  });

  // 切换模式时刷新专属字段显隐。
  Array.prototype.forEach.call(
    form.querySelectorAll('input[name="mode"]'),
    function (r) { r.addEventListener('change', refreshExtras); }
  );
  refreshExtras();
})();
