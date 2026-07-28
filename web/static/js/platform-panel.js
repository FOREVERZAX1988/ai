/**
 * Platform settings — workspace, MCP, learned skills, session search, debug toggles.
 */
const PlatformPanel = (() => {
  let api = null;
  let tuneRoutesLoaded = false;

  function tr(key, fallback) {
    return (typeof t === 'function') ? t(key, fallback) : fallback;
  }

  function esc(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function init(deps = {}) {
    api = deps.api || (typeof WebApi !== 'undefined' ? WebApi.api : null);
    bind();
    loadDebugToggles();
  }

  function loadDebugToggles() {
    const prefs = (typeof LocalPrefs !== 'undefined' && LocalPrefs.getChatDebugPrefs)
      ? LocalPrefs.getChatDebugPrefs()
      : { verbose: false, trace: false };
    const verbose = document.getElementById('chatVerboseToggle');
    const trace = document.getElementById('chatTraceToggle');
    if (verbose) verbose.checked = !!prefs.verbose;
    if (trace) trace.checked = !!prefs.trace;
  }

  function saveDebugToggles() {
    if (typeof LocalPrefs === 'undefined' || !LocalPrefs.setChatDebugPrefs) return;
    LocalPrefs.setChatDebugPrefs({
      verbose: !!document.getElementById('chatVerboseToggle')?.checked,
      trace: !!document.getElementById('chatTraceToggle')?.checked,
    });
  }

  async function loadWorkspace() {
    const key = document.getElementById('platformWorkspaceKey')?.value || 'user';
    const { data } = await api('GET', `/api/ai/workspace?key=${encodeURIComponent(key)}`);
    const editor = document.getElementById('platformWorkspaceEditor');
    if (editor && data?.ok) editor.value = data.content || '';
  }

  async function saveWorkspace() {
    const key = document.getElementById('platformWorkspaceKey')?.value || 'user';
    const content = document.getElementById('platformWorkspaceEditor')?.value || '';
    await api('POST', '/api/ai/workspace', { key, content });
  }

  async function refreshMcp() {
    const box = document.getElementById('platformMcpList');
    if (!box) return;
    const { data } = await api('GET', '/api/ai/mcp');
    box.innerHTML = '';
    for (const s of (data?.servers || [])) {
      const row = document.createElement('div');
      row.className = 'platform-list-item';
      row.textContent = `${s.id} · ${s.command || ''} · tools=${s.toolCount || 0}`;
      box.appendChild(row);
    }
  }

  async function addMcp() {
    const id = document.getElementById('platformMcpId')?.value?.trim();
    const command = document.getElementById('platformMcpCmd')?.value?.trim();
    if (!id || !command) return;
    await api('POST', '/api/ai/mcp', { id, command, enabled: true });
    await refreshMcp();
  }

  async function refreshLearned() {
    const box = document.getElementById('platformLearnedList');
    if (!box) return;
    const { data } = await api('GET', '/api/ai/learned-skills');
    box.innerHTML = '';
    for (const s of (data?.skills || [])) {
      const row = document.createElement('div');
      row.className = 'platform-list-item';
      const title = document.createElement('span');
      title.textContent = `${s.title || s.id} [${s.status}]`;
      row.appendChild(title);
      if (s.status === 'pending') {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn small';
        btn.textContent = '批准';
        btn.addEventListener('click', async () => {
          await api('POST', '/api/ai/learned-skills', { skill_id: s.id });
          refreshLearned();
        });
        row.appendChild(btn);
      }
      box.appendChild(row);
    }
  }

  async function searchSessions() {
    const q = document.getElementById('platformSessionQuery')?.value?.trim();
    const box = document.getElementById('platformSessionHits');
    if (!box || !q) return;
    const { data } = await api('GET', `/api/ai/sessions/search?q=${encodeURIComponent(q)}`);
    box.innerHTML = '';
    for (const hit of (data?.hits || [])) {
      const row = document.createElement('div');
      row.className = 'platform-list-item';
      row.textContent = `${hit.sessionTitle || hit.sessionId}: ${hit.snippet || ''}`;
      box.appendChild(row);
    }
  }

  async function loadMemoryAndPassport() {
    const profileBox = document.getElementById('platformMemoryProfile');
    const notesBox = document.getElementById('platformMemoryNotes');
    const passportList = document.getElementById('platformPassportList');
    const passportCount = document.getElementById('platformPassportCount');
    const [{ data: mem }, { data: passport }] = await Promise.all([
      api('GET', '/api/ai/memory').catch(() => ({ data: {} })),
      api('GET', '/api/ai/tune_passport?limit=20').catch(() => ({ data: {} })),
    ]);
    const profile = mem?.vehicle_profile || {};
    if (profileBox) {
      const lines = Object.entries(profile)
        .filter(([k, v]) => k !== 'updated_at' && v)
        .map(([k, v]) => `<div><b>${k}</b>: ${String(v)}</div>`);
      profileBox.innerHTML = lines.length
        ? lines.join('')
        : `<p class="field-hint">${typeof t === 'function' ? t('platformMemoryEmpty', '暂无车型档案') : '暂无车型档案'}</p>`;
    }
    if (notesBox) {
      const notes = mem?.notes || [];
      notesBox.innerHTML = notes.length
        ? notes.slice(0, 12).map((n) => {
            const when = n.at ? new Date(n.at * 1000).toLocaleString() : '';
            return `<li class="dev-item"><div>${(n.text || '').replace(/</g, '&lt;')}</div><span class="field-hint">${when}</span></li>`;
          }).join('')
        : `<li class="dev-empty">${typeof t === 'function' ? t('platformMemoryEmpty', '暂无记忆备注') : '暂无记忆备注'}</li>`;
    }
    const entries = passport?.entries || [];
    if (passportList) {
      passportList.innerHTML = entries.length
        ? entries.map((e) => {
            const when = e.at ? new Date(e.at * 1000).toLocaleString() : '';
            const params = Object.keys(e.params_changed || {}).join(', ') || '—';
            return `<li class="dev-item"><div><b>${e.action || ''}</b> <span class="field-hint">${when}</span></div><div class="field-hint">${params}</div></li>`;
          }).join('')
        : `<li class="dev-empty">${typeof t === 'function' ? t('tunePassportEmpty', '暂无调参记录') : '暂无调参记录'}</li>`;
    }
    if (passportCount) passportCount.textContent = String(passport?.count ?? entries.length);
  }

  function fillRouteSelect(sel, routes, placeholder) {
    if (!sel) return;
    sel.innerHTML = '';
    const ph = document.createElement('option');
    ph.value = '';
    ph.textContent = placeholder;
    sel.appendChild(ph);
    for (const r of routes) {
      const opt = document.createElement('option');
      opt.value = r.name;
      const label = r.date ? `${r.date} · ${r.name}` : r.name;
      opt.textContent = label.length > 72 ? `${label.slice(0, 69)}…` : label;
      sel.appendChild(opt);
    }
  }

  async function loadTuneRouteOptions() {
    const selA = document.getElementById('platformTuneRouteA');
    const selB = document.getElementById('platformTuneRouteB');
    if (!selA || !selB || !api) return;
    const { data } = await api('GET', '/api/cabana/routes', null, { timeoutMs: 15000 }).catch(() => ({ data: {} }));
    const routes = (data?.routes || []).slice(0, 80);
    const ph = tr('platformTuneRoutePlaceholder', '选择路线…');
    fillRouteSelect(selA, routes, ph);
    fillRouteSelect(selB, routes, ph);
    if (routes.length >= 2) {
      selA.value = routes[1].name;
      selB.value = routes[0].name;
    }
    tuneRoutesLoaded = true;
  }

  function renderTuneCompareResult(data) {
    const box = document.getElementById('platformTuneCompareResult');
    if (!box) return;
    const cmp = data?.compare || {};
    const session = data?.session || {};
    const highlights = cmp.tune_highlights || session.tune_highlights || [];
    const recs = cmp.tune_recommendations || [];
    const labelA = cmp.label_a || 'before';
    const labelB = cmp.label_b || 'after';

    let html = '';
    if (session.ok) {
      const passCls = session.passed ? 'tune-ab-pass' : 'tune-ab-fail';
      html += `<div class="tune-ab-scores ${passCls}">`;
      html += `<div><span class="tune-ab-score-label">${tr('platformTuneScoreBefore', '调参前')}</span> <b>${esc(session.score_before)}</b> (${esc(session.grade_before || '—')})</div>`;
      html += `<div><span class="tune-ab-score-label">${tr('platformTuneScoreAfter', '调参后')}</span> <b>${esc(session.score_after)}</b> (${esc(session.grade_after || '—')})</div>`;
      html += `<div>Δ <b>${esc(session.score_delta)}</b> · ${session.passed ? tr('platformTunePassed', '通过') : tr('platformTuneFailed', '未通过')}</div>`;
      if (session.recommendation) html += `<p class="field-hint">${esc(session.recommendation)}</p>`;
      html += '</div>';
    }

    if (highlights.length) {
      html += `<table class="tune-ab-table"><thead><tr><th>${tr('platformTuneColSignal', '信号')}</th><th>${esc(labelA)}</th><th>${esc(labelB)}</th><th>Δ</th></tr></thead><tbody>`;
      for (const h of highlights) {
        html += `<tr><td>${esc(h.label || h.field)}<span class="field-hint"> ${esc(h.topic || '')}</span></td>`;
        html += `<td>${esc(h[labelA] ?? h.before ?? '—')}</td>`;
        html += `<td>${esc(h[labelB] ?? h.after ?? '—')}</td>`;
        html += `<td>${esc(h.delta_mean)}</td></tr>`;
      }
      html += '</tbody></table>';
    } else {
      html += `<p class="field-hint">${tr('platformTuneNoHighlights', '两路线信号差异较小')}</p>`;
    }

    if (recs.length) {
      html += `<ul class="tune-ab-recs">${recs.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>`;
    }

    box.innerHTML = html;
    box.hidden = false;
  }

  async function runTuneCompare() {
    const routeA = document.getElementById('platformTuneRouteA')?.value?.trim();
    const routeB = document.getElementById('platformTuneRouteB')?.value?.trim();
    const status = document.getElementById('platformTuneCompareStatus');
    const result = document.getElementById('platformTuneCompareResult');
    const btn = document.getElementById('platformTuneCompareBtn');
    if (!routeA || !routeB) {
      if (status) {
        status.hidden = false;
        status.textContent = tr('platformTunePickRoutes', '请选择两条路线');
      }
      return;
    }
    if (status) {
      status.hidden = false;
      status.textContent = tr('platformTuneComparing', '正在对比…');
    }
    if (result) result.hidden = true;
    if (btn) btn.disabled = true;
    try {
      const { data } = await api('POST', '/api/ai/tune/compare', {
        route_a: routeA,
        route_b: routeB,
        label_a: 'before',
        label_b: 'after',
        with_scores: true,
      }, { timeoutMs: 120000 });
      if (!data?.ok) {
        if (status) status.textContent = data?.error || tr('platformTuneCompareError', '对比失败');
        return;
      }
      if (status) status.hidden = true;
      renderTuneCompareResult(data);
    } catch (e) {
      if (status) status.textContent = String(e?.message || e);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function applyPlatformTranslations() {
    const map = [
      ['platformMemoryTitle', '设备记忆'],
      ['platformPassportTitle', '调参护照'],
      ['platformTuneCompareTitle', '调参 A/B 对比'],
      ['platformTuneRouteALabel', '路线 A（调参前）'],
      ['platformTuneRouteBLabel', '路线 B（调参后）'],
    ];
    for (const [id, fb] of map) {
      const el = document.getElementById(id);
      if (el) el.textContent = tr(id, fb);
    }
    const btn = document.getElementById('platformTuneCompareBtn');
    if (btn) btn.textContent = tr('platformTuneCompareBtn', '开始对比');
  }

  function bind() {
    document.getElementById('platformWorkspaceLoad')?.addEventListener('click', () => loadWorkspace().catch(console.error));
    document.getElementById('platformWorkspaceSave')?.addEventListener('click', () => saveWorkspace().catch(console.error));
    document.getElementById('platformWorkspaceKey')?.addEventListener('change', () => loadWorkspace().catch(console.error));
    document.getElementById('platformMcpAdd')?.addEventListener('click', () => addMcp().catch(console.error));
    document.getElementById('platformSessionSearch')?.addEventListener('click', () => searchSessions().catch(console.error));
    document.getElementById('chatVerboseToggle')?.addEventListener('change', saveDebugToggles);
    document.getElementById('chatTraceToggle')?.addEventListener('change', saveDebugToggles);
    document.getElementById('platformTuneCompareBtn')?.addEventListener('click', () => runTuneCompare().catch(console.error));
    document.getElementById('schedNlBtn')?.addEventListener('click', async () => {
      const text = document.getElementById('schedNlInput')?.value?.trim();
      if (!text || !api) return;
      await api('POST', '/api/ai/scheduler', { nl: text });
      document.getElementById('schedNlInput').value = '';
      if (typeof loadSchedulerTasks === 'function') loadSchedulerTasks();
    });
  }

  function onSettingsOpen(tab) {
    if (tab !== 'platform') return;
    loadWorkspace().catch(() => {});
    refreshMcp().catch(() => {});
    refreshLearned().catch(() => {});
    loadMemoryAndPassport().catch(() => {});
    if (!tuneRoutesLoaded) loadTuneRouteOptions().catch(() => {});
    applyPlatformTranslations();
    loadDebugToggles();
  }

  return { init, onSettingsOpen, getChatDebugPrefs: () => (
    (typeof LocalPrefs !== 'undefined' && LocalPrefs.getChatDebugPrefs)
      ? LocalPrefs.getChatDebugPrefs()
      : { verbose: false, trace: false }
  ) };
})();
