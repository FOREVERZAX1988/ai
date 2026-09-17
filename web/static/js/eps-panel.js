/**
 * EPS 8965B4512000 flash assistant panel.
 *
 * Provides a step-by-step UI for:
 *   1. eps-telescope read-only layered probe
 *   2. classification decision
 *   3. eps-patch read-only probe
 *   4. one-click patch/restore writer (with double confirmation)
 *   5. power-cycle resume, backup display/download, emergency restore
 *
 * The panel uses /api/eps/* REST endpoints and polls running jobs.
 */
const EpsPanel = (() => {
  const $ = (id) => document.getElementById(id);

  const state = {
    running: false,
    jobId: null,
    jobKind: null,
    telescopeClassification: null,
    patchStage: null,
    probePass: false,
    stateName: 'unknown',
    powerCyclePending: false,
    pandas: [],
    pollTimer: null,
  };

  function els() {
    return {
      statusDot: $('epsStatusDot'),
      statusTitle: $('epsStatusTitle'),
      statusDetail: $('epsStatusDetail'),
      stepDotTelescope: $('epsStepDotTelescope'),
      stepDotClassify: $('epsStepDotClassify'),
      stepDotProbe: $('epsStepDotProbe'),
      stepDotWriter: $('epsStepDotWriter'),
      stepDetailTelescope: $('epsStepDetailTelescope'),
      stepDetailClassify: $('epsStepDetailClassify'),
      stepDetailProbe: $('epsStepDetailProbe'),
      stepDetailWriter: $('epsStepDetailWriter'),
      telescopeBtn: $('epsTelescopeBtn'),
      classifyBtn: $('epsClassifyBtn'),
      probeBtn: $('epsProbeBtn'),
      writerBtn: $('epsWriterBtn'),
      restoreBtn: $('epsRestoreBtn'),
      continueBtn: $('epsContinueBtn'),
      serialSelect: $('epsSerialSelect'),
      depthSelect: $('epsDepthSelect'),
      jobPanel: $('epsJobPanel'),
      jobTitle: $('epsJobTitle'),
      jobProgressBar: $('epsJobProgressBar'),
      jobLog: $('epsJobLog'),
      cancelJobBtn: $('epsCancelJobBtn'),
      commandCard: $('epsCommandCard'),
      commandTitle: $('epsCommandTitle'),
      commandBody: $('epsCommandBody'),
      commandSteps: $('epsCommandSteps'),
      commandWarning: $('epsCommandWarning'),
      copyCommandBtn: $('epsCopyCommandBtn'),
      backupCard: $('epsBackupCard'),
      backupBody: $('epsBackupBody'),
      backupDownloadTarget: $('epsBackupDownloadTarget'),
      backupDownloadCrc: $('epsBackupDownloadCrc'),
      backupDownloadMeta: $('epsBackupDownloadMeta'),
      backupExportBtn: $('epsBackupExportBtn'),
      importCard: $('epsImportCard'),
      backupFileInput: $('epsBackupFileInput'),
      backupImportBtn: $('epsBackupImportBtn'),
      backupImportName: $('epsBackupImportName'),
      backupImportStatus: $('epsBackupImportStatus'),
      historyCard: $('epsHistoryCard'),
      historyBody: $('epsHistoryBody'),
      refreshHistoryBtn: $('epsRefreshHistoryBtn'),
      auditCard: $('epsAuditCard'),
      auditBody: $('epsAuditBody'),
      refreshAuditBtn: $('epsRefreshAuditBtn'),
      continueCard: $('epsContinueCard'),
      continueHint: $('epsContinueHint'),
      confirmModal: $('epsConfirmModal'),
      confirmTitle: $('epsConfirmTitle'),
      confirmBody: $('epsConfirmBody'),
      confirmCheckbox: $('epsConfirmCheckbox'),
      confirmInput: $('epsConfirmInput'),
      confirmCancelBtn: $('epsConfirmCancelBtn'),
      confirmOkBtn: $('epsConfirmOkBtn'),
      openpilotCard: $('epsOpenpilotCard'),
      openpilotStatus: $('epsOpenpilotStatus'),
      openpilotDetail: $('epsOpenpilotDetail'),
      stopOpenpilotBtn: $('epsStopOpenpilotBtn'),
      stopOpenpilotCheckbox: $('epsStopOpenpilotCheckbox'),
      stopOpenpilotConfirmLabel: $('epsStopOpenpilotConfirmLabel'),
    };
  }

  const FETCH_TIMEOUT_MS = 15000;
  const JOB_POLL_MS = 800;
  let confirmResolve = null;

  async function fetchWithTimeout(url, options = {}, timeoutMs = FETCH_TIMEOUT_MS) {
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: ac.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  async function fetchJson(url, opts = {}) {
    const res = await fetchWithTimeout(url, { cache: 'no-store' }, opts.timeoutMs ?? FETCH_TIMEOUT_MS);
    return readJsonResponse(res);
  }

  async function readJsonResponse(res) {
    const text = await res.text();
    if (!text.trim()) return {};
    try {
      return JSON.parse(text);
    } catch (e) {
      const preview = text.slice(0, 160).replace(/\s+/g, ' ').trim();
      throw new Error(preview ? `服务器返回非 JSON（HTTP ${res.status}）：${preview}` : `服务器返回非 JSON（HTTP ${res.status}）`);
    }
  }

  async function postJson(url, payload = {}, opts = {}) {
    const res = await fetchWithTimeout(
      url,
      {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
      opts.timeoutMs ?? FETCH_TIMEOUT_MS,
    );
    return readJsonResponse(res);
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function notifyToast(msg, type = 'info') {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = msg;
    toast.className = `toast show ${type}`;
    toast.removeAttribute('aria-hidden');
    window.clearTimeout(notifyToast._timer);
    notifyToast._timer = window.setTimeout(() => {
      toast.classList.remove('show');
      toast.textContent = '';
      toast.setAttribute('aria-hidden', 'true');
    }, 3200);
  }

  function logLine(text, cls) {
    const e = els();
    if (!e.jobLog) return;
    const line = document.createElement('div');
    line.className = cls ? `eps-log-line ${cls}` : 'eps-log-line';
    line.textContent = text;
    e.jobLog.appendChild(line);
    e.jobLog.scrollTop = e.jobLog.scrollHeight;
  }

  function clearLog() {
    const e = els();
    if (e.jobLog) e.jobLog.innerHTML = '';
  }

  function setJobProgress(percent) {
    const e = els();
    if (!e.jobProgressBar) return;
    e.jobProgressBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  }

  function setRunning(running) {
    state.running = running;
    const e = els();
    [
      e.telescopeBtn, e.classifyBtn, e.probeBtn,
      e.writerBtn, e.restoreBtn, e.continueBtn,
    ].forEach((btn) => {
      if (btn) btn.disabled = running;
    });
    if (e.jobPanel) {
      e.jobPanel.classList.toggle('hidden', !running);
    }
    if (!running) {
      setJobProgress(0);
    }
  }

  function setOpenpilotStatus(running, details) {
    const e = els();
    if (!e.openpilotStatus) return;
    if (running) {
      e.openpilotStatus.textContent = '运行中';
      e.openpilotStatus.className = 'eps-openpilot-status running';
      e.openpilotDetail.textContent = '刷写 EPS 前必须先停止 openpilot 主流程，否则无法打开 Panda 硬件。';
      if (e.stopOpenpilotBtn) e.stopOpenpilotBtn.disabled = false;
      if (e.stopOpenpilotConfirmLabel) e.stopOpenpilotConfirmLabel.classList.remove('hidden');
    } else {
      e.openpilotStatus.textContent = '已停止';
      e.openpilotStatus.className = 'eps-openpilot-status stopped';
      e.openpilotDetail.textContent = 'openpilot 已停止，可以安全执行 EPS 探测/刷写。ai 服务会继续运行。';
      if (e.stopOpenpilotBtn) e.stopOpenpilotBtn.disabled = true;
      if (e.stopOpenpilotConfirmLabel) e.stopOpenpilotConfirmLabel.classList.add('hidden');
    }
  }

  async function loadOpenpilotStatus() {
    try {
      const data = await fetchJson('/api/eps/openpilot-status');
      state.openpilotRunning = data.running;
      setOpenpilotStatus(data.running, data.details);
      return data;
    } catch (err) {
      setOpenpilotStatus(false, {});
      return { running: false };
    }
  }

  async function stopOpenpilot() {
    const e = els();
    if (!e.stopOpenpilotCheckbox?.checked) {
      notifyToast('请先勾选“我已了解停止 openpilot 的后果”', 'err');
      return;
    }
    if (!confirm('即将停止 comma/openpilot 主流程。停止后无法开车，确认继续？')) return;

    if (e.stopOpenpilotBtn) {
      e.stopOpenpilotBtn.disabled = true;
      e.stopOpenpilotBtn.textContent = '停止中…';
    }
    try {
      const data = await postJson('/api/eps/stop-openpilot', {
        confirm: true,
        i_understand: 'stop_openpilot',
      }, { timeoutMs: 30000 });
      if (data.ok) {
        notifyToast('openpilot 已停止', 'ok');
        await loadOpenpilotStatus();
      } else {
        notifyToast(data.error || '停止失败', 'err');
        await loadOpenpilotStatus();
      }
    } catch (err) {
      notifyToast(`停止失败：${err.message}`, 'err');
      await loadOpenpilotStatus();
    } finally {
      if (e.stopOpenpilotBtn) {
        e.stopOpenpilotBtn.disabled = false;
        e.stopOpenpilotBtn.textContent = '停止 openpilot';
      }
    }
  }

  function setStepStatus(step, status, detail) {
    const e = els();
    const dot = e[`stepDot${step.charAt(0).toUpperCase() + step.slice(1)}`];
    const detailEl = e[`stepDetail${step.charAt(0).toUpperCase() + step.slice(1)}`];
    if (dot) {
      dot.classList.remove('ready', 'running', 'warn', 'error');
      if (status) dot.classList.add(status);
    }
    if (detailEl && detail) detailEl.textContent = detail;
  }

  function updateStatus(title, detail, cls) {
    const e = els();
    if (e.statusTitle) e.statusTitle.textContent = title;
    if (e.statusDetail) e.statusDetail.textContent = detail;
    if (e.statusDot) {
      e.statusDot.className = 'eps-status-dot';
      if (cls) e.statusDot.classList.add(cls);
    }
  }

  function showCommandCard(title, command, steps, warning) {
    const e = els();
    if (!e.commandCard) return;
    e.commandCard.classList.remove('hidden');
    if (e.commandTitle) e.commandTitle.textContent = title;
    if (e.commandBody) e.commandBody.textContent = command;
    if (e.commandSteps) {
      e.commandSteps.innerHTML = '';
      (steps || []).forEach((s) => {
        const li = document.createElement('li');
        li.textContent = s;
        e.commandSteps.appendChild(li);
      });
    }
    if (e.commandWarning) {
      e.commandWarning.textContent = warning || '';
      e.commandWarning.classList.toggle('hidden', !warning);
    }
  }

  function hideCommandCard() {
    const e = els();
    if (e.commandCard) e.commandCard.classList.add('hidden');
  }

  function showConfirmModal(title, body, opts = {}) {
    return new Promise((resolve) => {
      confirmResolve = resolve;
      const e = els();
      if (e.confirmTitle) e.confirmTitle.textContent = title;
      if (e.confirmBody) e.confirmBody.innerHTML = body;
      if (e.confirmCheckbox) {
        e.confirmCheckbox.checked = false;
        e.confirmCheckbox.parentElement?.classList.toggle('hidden', !opts.showCheckbox);
      }
      if (e.confirmInput) {
        e.confirmInput.value = '';
        e.confirmInput.parentElement?.classList.toggle('hidden', !opts.showInput);
      }
      if (e.confirmModal) e.confirmModal.classList.remove('hidden');
    });
  }

  function hideConfirmModal() {
    const e = els();
    if (e.confirmModal) e.confirmModal.classList.add('hidden');
    if (confirmResolve) confirmResolve(false);
    confirmResolve = null;
  }

  function confirmModalOk() {
    const e = els();
    const checkboxOk = !e.confirmCheckbox || e.confirmCheckbox.parentElement?.classList.contains('hidden') || e.confirmCheckbox.checked;
    const inputOk = !e.confirmInput || e.confirmInput.parentElement?.classList.contains('hidden') || e.confirmInput.value.trim() === 'YES';
    if (!checkboxOk || !inputOk) {
      notifyToast('请完成确认项后再继续', 'err');
      return;
    }
    if (confirmResolve) confirmResolve(true);
    confirmResolve = null;
    if (e.confirmModal) e.confirmModal.classList.add('hidden');
  }

  function classificationText(cls) {
    const map = {
      verified_variant: '已验证变体，可进入 patch',
      already_patched: '已经刷过 patch',
      sa_blocked: 'SecurityAccess 受阻',
      envelope_blocked: 'Envelope 认证受阻',
      egg_variant: 'egg 变体不匹配',
      egg_variant_relocated: 'egg 变体已重定位',
      no_egg: '未找到 egg 签名',
    };
    return map[cls] || cls || '未知';
  }

  function canRunProbe() {
    return state.telescopeClassification === 'verified_variant' || state.telescopeClassification === 'already_patched';
  }

  function selectedSerial() {
    const e = els();
    return e.serialSelect?.value || '';
  }

  function renderPandaList(data) {
    const e = els();
    if (!e.serialSelect) return;
    const prev = e.serialSelect.value;
    e.serialSelect.innerHTML = '<option value="">自动选择</option>';
    if (!data.ok || !data.pandas?.length) return;
    state.pandas = data.pandas;
    data.pandas.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.serial;
      opt.textContent = `${p.label} (${p.serial.slice(0, 8)}…)`;
      e.serialSelect.appendChild(opt);
    });
    if (prev && data.pandas.some((p) => p.serial === prev)) {
      e.serialSelect.value = prev;
    } else if (data.recommended) {
      e.serialSelect.value = data.recommended;
    }
  }

  async function loadPandaList() {
    try {
      const data = await fetchJson('/api/eps/panda-list');
      renderPandaList(data);
    } catch (err) {
      // non-fatal
    }
  }

  function renderBackupInfo(info) {
    const e = els();
    if (!e.backupCard || !e.backupBody) return;
    if (!info.available) {
      e.backupCard.classList.add('hidden');
      return;
    }
    e.backupCard.classList.remove('hidden');
    const target = info.target || {};
    const crc = info.crc || {};
    const meta = info.metadata || {};
    e.backupBody.innerHTML = `
      <div class="eps-backup-row"><span>目标扇区备份</span><span>${target.size || 0} bytes · ${(target.sha256 || '').slice(0, 16)}…</span></div>
      <div class="eps-backup-row"><span>CRC 扇区备份</span><span>${crc.size || 0} bytes · ${(crc.sha256 || '').slice(0, 16)}…</span></div>
      <div class="eps-backup-row"><span>元数据</span><span>${meta.size || 0} bytes</span></div>
    `;
    if (e.backupDownloadTarget) e.backupDownloadTarget.href = '/api/eps/backup/target';
    if (e.backupDownloadCrc) e.backupDownloadCrc.href = '/api/eps/backup/crc';
    if (e.backupDownloadMeta) e.backupDownloadMeta.href = '/api/eps/backup/metadata';
    if (e.backupExportBtn) e.backupExportBtn.disabled = state.running;
  }

  async function loadBackupInfo() {
    try {
      const data = await fetchJson('/api/eps/backup-info');
      renderBackupInfo(data);
    } catch (err) {
      // non-fatal
    }
  }

  function syncUiFromState() {
    const e = els();
    const high = state.stateName;

    // Classify step.
    if (state.telescopeClassification) {
      setStepStatus('classify', canRunProbe() ? 'ready' : 'warn', classificationText(state.telescopeClassification));
    }

    // Probe step.
    if (state.probePass) {
      setStepStatus('probe', 'ready', 'Probe PASS');
    } else if (state.patchStage === 'PROBED') {
      setStepStatus('probe', 'warn', 'Probe 未通过');
    }

    // Writer step and buttons.
    const already = high === 'already_patched';
    if (e.writerBtn) {
      e.writerBtn.textContent = already ? '已是 patch 状态' : '一键刷写';
      e.writerBtn.disabled = state.running || already || !(high === 'probe_pass' || high === 'patch_in_progress');
      e.writerBtn.classList.toggle('danger', !already);
    }
    if (e.restoreBtn) {
      e.restoreBtn.disabled = state.running || already || !(high === 'failed' || high === 'patch_in_progress' || state.probePass);
    }
    if (e.continueBtn) {
      const showContinue = high === 'patch_in_progress' || state.powerCyclePending;
      e.continueBtn.classList.toggle('hidden', !showContinue);
      e.continueBtn.disabled = state.running;
    }
    if (e.continueCard) {
      e.continueCard.classList.toggle('hidden', !state.powerCyclePending);
    }
    if (e.probeBtn) {
      e.probeBtn.disabled = state.running || !canRunProbe() || already;
    }
    if (e.telescopeBtn) e.telescopeBtn.disabled = state.running || already;

    // Status summary.
    let title = '未开始';
    let detail = '请先运行 eps-telescope 探测';
    let cls = '';
    switch (high) {
      case 'already_patched':
        title = '已完成';
        detail = 'EPS patch 已通过，无需操作';
        cls = 'ready';
        break;
      case 'unknown':
        title = '未开始';
        detail = '请先运行 eps-telescope 探测';
        break;
      case 'not_compatible':
        title = '不支持';
        detail = classificationText(state.telescopeClassification);
        cls = 'error';
        break;
      case 'ready_to_probe':
        title = '可进入 Probe';
        detail = 'telescope 分类通过，请点击步骤 3 运行 EPS probe';
        cls = 'ready';
        break;
      case 'probe_pass':
        title = 'Probe 通过';
        detail = '可点击“一键刷写”继续';
        cls = 'ready';
        break;
      case 'patch_in_progress':
        title = '刷写中';
        detail = state.powerCyclePending ? '请断电重启后继续' : 'patch 流程已部分执行，点击继续';
        cls = state.powerCyclePending ? 'warn' : 'running';
        break;
      case 'failed':
        title = '需要恢复';
        detail = 'patch/restore 失败，建议一键恢复';
        cls = 'error';
        break;
    }
    updateStatus(title, detail, cls);
  }

  async function refreshStatus() {
    try {
      const data = await fetchJson('/api/eps/status');
      state.telescopeClassification = data.telescope_classification || state.telescopeClassification;
      state.patchStage = data.stage || state.patchStage;
      state.probePass = !!data.probe_pass;
      state.stateName = data.state_name || 'unknown';
      state.powerCyclePending = !!data.power_cycle_checkpoint || data.state_name === 'patch_in_progress';
      if (data.power_cycle_checkpoint && els().continueHint) {
        els().continueHint.textContent = data.power_cycle_checkpoint.hint || '';
      }
      syncUiFromState();
      if (data.backup_info) renderBackupInfo(data.backup_info);
    } catch (err) {
      updateStatus('状态读取失败', String(err), 'error');
    }
  }

  async function runTelescopeProbe() {
    if (state.running) return;
    const e = els();
    setRunning(true);
    clearLog();
    hideCommandCard();
    if (e.jobTitle) e.jobTitle.textContent = 'eps-telescope 探测';
    setStepStatus('telescope', 'running', '正在执行只读分层探测…');
    updateStatus('探测中', 'eps-telescope 正在读取 ECU 指纹，请保持 offroad', 'running');

    try {
      const result = await postJson('/api/eps/telescope-probe', {
        confirm: true,
        serial: selectedSerial(),
        depth: e.depthSelect?.value || 'shellcode',
      }, { timeoutMs: 30000 });

      if (result.needs_confirmation) {
        logLine('等待确认…');
        setRunning(false);
        return;
      }
      if (!result.ok) {
        logLine(result.error || '启动失败', 'err');
        setStepStatus('telescope', 'error', result.error || '启动失败');
        setRunning(false);
        return;
      }
      state.jobId = result.job_id;
      state.jobKind = 'telescope';
      pollJob();
    } catch (err) {
      logLine(String(err), 'err');
      setStepStatus('telescope', 'error', String(err));
      setRunning(false);
    }
  }

  async function runPatchProbe() {
    if (state.running) return;
    if (!canRunProbe()) {
      notifyToast('telescope 分类未通过，不能运行 patch probe', 'err');
      return;
    }
    setRunning(true);
    clearLog();
    hideCommandCard();
    const e = els();
    if (e.jobTitle) e.jobTitle.textContent = 'EPS 只读 Probe';
    setStepStatus('probe', 'running', '正在验证 patch 点前状态…');
    updateStatus('Probe 中', 'eps_patch.py probe 正在运行', 'running');

    try {
      const result = await postJson('/api/eps/patch-probe', {
        confirm: true,
        serial: selectedSerial(),
      }, { timeoutMs: 30000 });

      if (!result.ok) {
        logLine(result.error || '启动失败', 'err');
        setStepStatus('probe', 'error', result.error || '启动失败');
        setRunning(false);
        return;
      }
      state.jobId = result.job_id;
      state.jobKind = 'patch';
      pollJob();
    } catch (err) {
      logLine(String(err), 'err');
      setStepStatus('probe', 'error', String(err));
      setRunning(false);
    }
  }

  async function runWriter(command) {
    if (state.running) return;

    // Enforce openpilot is stopped before allowing destructive writers.
    const op = await loadOpenpilotStatus();
    if (op.running) {
      notifyToast('openpilot 仍在运行，请先点击“停止 openpilot”', 'err');
      return;
    }

    const isPatch = command === 'patch';
    const title = isPatch ? '确认一键刷写 EPS？' : '确认一键恢复 EPS 到原车备份？';
    const body = isPatch
      ? '此操作将擦写 EPS Flash，把 <b>8965B4512000</b> 的 SecOC RX 校验分支禁用。' +
        '<br>失败可能导致 EPS 变砖。请确保：车辆静止、台架稳定供电、已阅读备份。'
      : '此操作将把 EPS 恢复到 probe 时保存的原车备份。' +
        '<br>失败也可能导致 EPS 变砖。请确保已完整备份当前状态。';
    const confirmed = await showConfirmModal(title, body, { showCheckbox: true, showInput: true });
    if (!confirmed) return;

    setRunning(true);
    clearLog();
    hideCommandCard();
    const e = els();
    if (e.jobTitle) e.jobTitle.textContent = isPatch ? 'EPS Patch Writer' : 'EPS Restore Writer';
    setStepStatus('writer', 'running', isPatch ? '正在执行 patch writer…' : '正在执行 restore writer…');
    updateStatus(isPatch ? '刷写中' : '恢复中', '请勿断电或断开 Panda', 'running');

    try {
      const result = await postJson(isPatch ? '/api/eps/patch-writer' : '/api/eps/restore-writer', {
        confirm: true,
        i_understand: 'brick_risk',
        serial: selectedSerial(),
      }, { timeoutMs: 30000 });

      if (result.needs_confirmation) {
        logLine('等待确认…');
        setRunning(false);
        return;
      }
      if (!result.ok) {
        logLine(result.error || '启动失败', 'err');
        setStepStatus('writer', 'error', result.error || '启动失败');
        setRunning(false);
        return;
      }
      state.jobId = result.job_id;
      state.jobKind = isPatch ? 'patch_writer' : 'restore_writer';
      pollJob();
    } catch (err) {
      logLine(String(err), 'err');
      setStepStatus('writer', 'error', String(err));
      setRunning(false);
    }
  }

  async function continueWriter() {
    // After a power-cycle checkpoint, the state.json retains the stage. The
    // same writer command is resumed by re-running patch/restore.
    const isPatch = state.stateName !== 'failed' && state.patchStage !== 'PASS';
    await runWriter(isPatch ? 'patch' : 'restore');
  }

  async function cancelJob() {
    if (!state.jobId) return;
    try {
      await postJson('/api/eps/cancel-job', { job: state.jobId });
      logLine('已取消', 'dim');
    } catch (err) {
      logLine(String(err), 'err');
    }
    state.jobId = null;
    state.jobKind = null;
    setRunning(false);
  }

  async function pollJob() {
    if (!state.jobId) {
      setRunning(false);
      return;
    }

    try {
      const data = await fetchJson(`/api/eps/job/${state.jobId}`);
      if (!data.ok || !data.job) {
        setRunning(false);
        return;
      }
      const job = data.job;
      const prevCount = (els().jobLog?.children?.length) || 0;
      (job.lines || []).slice(prevCount).forEach((ln) => {
        logLine(ln.line);
      });

      const joined = (job.lines || []).map((l) => l.line).join('\n');
      let pct = 0;
      if (state.jobKind === 'telescope') {
        if (/Layer 3/.test(joined)) pct = 70;
        else if (/Security Access/.test(joined)) pct = 40;
        else if (/Layer 1/.test(joined)) pct = 15;
      } else if (state.jobKind === 'patch') {
        if (/WRITE-CRC|CRC_PRECHECKED/.test(joined)) pct = 80;
        else if (/WRITE-TARGET|TARGET_PRECHECKED/.test(joined)) pct = 50;
        else if (/FACI PE cycle/.test(joined)) pct = 30;
      } else if (state.jobKind === 'patch_writer') {
        if (/CRC_COMMITTED|VERIFY_PENDING/.test(joined)) pct = 85;
        else if (/TARGET_COMMITTED/.test(joined)) pct = 55;
        else if (/WRITE-TARGET|WRITE-CRC/.test(joined)) pct = 40;
      } else if (state.jobKind === 'restore_writer') {
        if (/RESTORED|PASS/.test(joined)) pct = 90;
        else if (/RESTORE-SECTOR/.test(joined)) pct = 50;
      }
      setJobProgress(pct);

      if (job.status === 'running') {
        setTimeout(pollJob, JOB_POLL_MS);
        return;
      }

      setJobProgress(100);
      if (job.status === 'power_cycle') {
        logLine('已保存 checkpoint，请完全断电重启 comma/EPS', 'warn');
        state.powerCyclePending = true;
        setStepStatus('writer', 'warn', '请断电重启后继续');
      } else if (job.status === 'done') {
        logLine('完成', 'ok');
        if (state.jobKind === 'telescope') {
          setStepStatus('telescope', 'ready', '探测完成');
        } else if (state.jobKind === 'patch') {
          setStepStatus('probe', 'ready', 'Probe 完成');
        } else {
          setStepStatus('writer', 'ready', state.jobKind === 'patch_writer' ? 'Patch 完成' : 'Restore 完成');
        }
      } else if (job.status === 'cancelled') {
        logLine('已取消', 'dim');
      } else {
        logLine(job.error || '执行出错', 'err');
        if (state.jobKind === 'telescope') setStepStatus('telescope', 'error', job.error || '出错');
        else if (state.jobKind === 'patch') setStepStatus('probe', 'error', job.error || '出错');
        else setStepStatus('writer', 'error', job.error || '出错');
      }
    } catch (err) {
      logLine(`轮询失败: ${err}`, 'err');
    } finally {
      const current = state.jobId ? await fetchJson(`/api/eps/job/${state.jobId}`).catch(() => null) : null;
      if (!current || !current.job || current.job.status === 'running') {
        // still running, keep polling
        if (state.jobId) setTimeout(pollJob, JOB_POLL_MS);
        return;
      }
      state.jobId = null;
      state.jobKind = null;
      setRunning(false);
      await refreshStatus();
      await loadBackupInfo();
    }
  }

  async function showClassify() {
    try {
      const data = await fetchJson('/api/eps/telescope-classify');
      if (!data.ok) {
        notifyToast(data.error || '无法获取判定', 'err');
        return;
      }
      state.telescopeClassification = data.classification;
      setStepStatus('classify', data.safe_to_patch ? 'ready' : 'warn', classificationText(data.classification));
      syncUiFromState();
      if (data.guidance?.length) {
        notifyToast(data.guidance[0], 'info');
      }
    } catch (err) {
      notifyToast(String(err), 'err');
    }
  }

  async function prepareWriter() {
    try {
      const data = await fetchJson('/api/eps/prepare-patch');
      if (!data.ok) {
        notifyToast(data.error || '尚未满足 patch 条件', 'err');
        return;
      }
      showCommandCard(
        '手动 Patch 命令',
        data.manual_command,
        data.manual_steps,
        data.warning,
      );
      setStepStatus('writer', 'ready', '命令已生成，可一键刷写或手动执行');
    } catch (err) {
      notifyToast(String(err), 'err');
    }
  }

  async function exportBackup() {
    const e = els();
    if (e.backupExportBtn) e.backupExportBtn.disabled = true;
    try {
      const res = await fetchWithTimeout('/api/eps/backup-export', { method: 'GET' }, 60000);
      if (!res.ok) {
        const data = await readJsonResponse(res);
        notifyToast(data.error || '导出失败', 'err');
        return;
      }
      const blob = await res.blob();
      const disp = res.headers.get('content-disposition') || '';
      const match = disp.match(/filename="?([^";]+)"?/);
      const filename = match ? match[1] : 'EPS_BACKUP.tar.gz';
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      notifyToast('完整备份已导出', 'ok');
    } catch (err) {
      notifyToast(`导出失败: ${err}`, 'err');
    } finally {
      if (e.backupExportBtn) e.backupExportBtn.disabled = state.running;
    }
  }

  async function importBackup(file) {
    const e = els();
    if (!file) return;
    if (e.backupImportStatus) e.backupImportStatus.textContent = '正在上传并校验…';
    const form = new FormData();
    form.append('archive', file);
    try {
      const res = await fetchWithTimeout('/api/eps/backup-import', { method: 'POST', body: form }, 60000);
      const data = await readJsonResponse(res);
      if (data.ok) {
        if (e.backupImportStatus) e.backupImportStatus.textContent = '导入成功，可执行一键恢复。';
        notifyToast('备份导入成功', 'ok');
        await loadBackupInfo();
      } else {
        if (e.backupImportStatus) e.backupImportStatus.textContent = `导入失败: ${data.error || '未知错误'}`;
        notifyToast(data.error || '导入失败', 'err');
      }
    } catch (err) {
      if (e.backupImportStatus) e.backupImportStatus.textContent = `上传失败: ${err}`;
      notifyToast(`上传失败: ${err}`, 'err');
    }
  }

  function renderHistory(entries) {
    const e = els();
    if (!e.historyCard || !e.historyBody) return;
    if (!entries || !entries.length) {
      e.historyBody.innerHTML = '<div class="eps-backup-row"><span>暂无历史备份</span></div>';
      e.historyCard.classList.remove('hidden');
      return;
    }
    e.historyBody.innerHTML = entries.map((entry) => `
      <div class="eps-backup-row">
        <span>${entry.name}</span>
        <span>${entry.size} bytes · ${new Date(entry.mtime * 1000).toLocaleString()}</span>
      </div>
    `).join('');
    e.historyCard.classList.remove('hidden');
  }

  async function loadHistory() {
    try {
      const data = await fetchJson('/api/eps/backup-history');
      renderHistory(data.entries || []);
    } catch (err) {
      // non-fatal
    }
  }

  function renderAudit(entries) {
    const e = els();
    if (!e.auditCard || !e.auditBody) return;
    if (!entries || !entries.length) {
      e.auditBody.innerHTML = '<div class="eps-backup-row"><span>暂无审计记录</span></div>';
      e.auditCard.classList.remove('hidden');
      return;
    }
    e.auditBody.innerHTML = entries.slice(0, 20).map((entry) => `
      <div class="eps-backup-row">
        <span>${new Date(entry.ts).toLocaleString()}</span>
        <span>${entry.action} · ${entry.ok ? '成功' : '失败'}</span>
      </div>
    `).join('');
    e.auditCard.classList.remove('hidden');
  }

  async function loadAudit() {
    try {
      const data = await fetchJson('/api/eps/audit');
      renderAudit(data.entries || []);
    } catch (err) {
      // non-fatal
    }
  }

  function startPoll() {
    refreshStatus();
    loadOpenpilotStatus();
    loadPandaList();
    loadBackupInfo();
    loadHistory();
    loadAudit();
    if (state.pollTimer) return;
    state.pollTimer = setInterval(() => {
      refreshStatus();
      loadOpenpilotStatus();
      loadPandaList();
      loadBackupInfo();
    }, 4000);
  }

  function stopPoll() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function init() {
    const e = els();
    e.telescopeBtn?.addEventListener('click', runTelescopeProbe);
    e.classifyBtn?.addEventListener('click', showClassify);
    e.probeBtn?.addEventListener('click', runPatchProbe);
    e.writerBtn?.addEventListener('click', () => runWriter('patch'));
    e.restoreBtn?.addEventListener('click', () => runWriter('restore'));
    e.continueBtn?.addEventListener('click', continueWriter);
    e.cancelJobBtn?.addEventListener('click', cancelJob);
    e.confirmCancelBtn?.addEventListener('click', hideConfirmModal);
    e.confirmOkBtn?.addEventListener('click', confirmModalOk);
    e.copyCommandBtn?.addEventListener('click', () => {
      const command = e.commandBody?.textContent || '';
      if (!command) return;
      navigator.clipboard?.writeText(command).then(() => notifyToast('已复制命令', 'ok')).catch(() => notifyToast('复制失败', 'err'));
    });
    e.backupExportBtn?.addEventListener('click', exportBackup);
    e.backupImportBtn?.addEventListener('click', () => e.backupFileInput?.click());
    e.backupFileInput?.addEventListener('change', (ev) => {
      const file = ev.target.files?.[0];
      if (!file) return;
      if (e.backupImportName) e.backupImportName.textContent = file.name;
      importBackup(file);
    });
    e.refreshHistoryBtn?.addEventListener('click', loadHistory);
    e.refreshAuditBtn?.addEventListener('click', loadAudit);
    e.stopOpenpilotBtn?.addEventListener('click', stopOpenpilot);
  }

  return { init, startPoll, stopPoll };
})();

document.addEventListener('DOMContentLoaded', EpsPanel.init);
