/**
 * EPS 8965B4512000 flash assistant panel.
 *
 * Provides a step-by-step UI for:
 *   1. eps-telescope read-only layered probe
 *   2. classification decision
 *   3. eps-patch read-only probe
 *   4. writer command preparation (manual SSH only)
 *
 * Destructive patch/restore writers are intentionally NOT exposed as HTTP APIs.
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
    onroad: false,
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
      serialInput: $('epsSerialInput'),
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
    };
  }

  const FETCH_TIMEOUT_MS = 15000;
  const JOB_POLL_MS = 800;

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
    [e.telescopeBtn, e.classifyBtn, e.probeBtn, e.writerBtn].forEach((btn) => {
      if (btn) btn.disabled = running;
    });
    if (e.jobPanel) {
      e.jobPanel.classList.toggle('hidden', !running);
    }
    if (!running) {
      setJobProgress(0);
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

  function syncProbeButton() {
    const e = els();
    if (!e.probeBtn) return;
    e.probeBtn.disabled = state.running || !canRunProbe();
  }

  async function refreshStatus() {
    const e = els();
    try {
      const data = await fetchJson('/api/eps/status');
      state.telescopeClassification = data.telescope_classification || state.telescopeClassification;
      state.patchStage = data.stage || state.patchStage;
      state.probePass = !!data.probe_pass;

      if (state.telescopeClassification) {
        setStepStatus('classify', canRunProbe() ? 'ready' : 'warn', classificationText(state.telescopeClassification));
      }
      if (data.probe_present) {
        setStepStatus('probe', state.probePass ? 'ready' : 'error', state.probePass ? 'Probe PASS' : 'Probe 未通过');
      }
      if (state.patchStage) {
        setStepStatus('writer', 'ready', `当前阶段: ${state.patchStage}`);
      }

      let title = '未开始';
      let detail = '请先运行 eps-telescope 探测';
      let cls = '';
      if (state.patchStage === 'PASS') {
        title = '已完成';
        detail = 'EPS patch 已通过';
        cls = 'ready';
      } else if (state.probePass) {
        title = 'Probe 通过';
        detail = data.next_command || '可准备 writer 命令';
        cls = 'ready';
      } else if (canRunProbe()) {
        title = '可进入 Probe';
        detail = 'telescope 分类通过，请点击步骤 3 运行 EPS probe';
        cls = 'ready';
      } else if (state.telescopeClassification) {
        title = '不可刷';
        detail = classificationText(state.telescopeClassification);
        cls = 'warn';
      }
      updateStatus(title, detail, cls);
      syncProbeButton();
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
        serial: e.serialInput?.value?.trim() || '',
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
    const e = els();
    setRunning(true);
    clearLog();
    hideCommandCard();
    if (e.jobTitle) e.jobTitle.textContent = 'EPS 只读 Probe';
    setStepStatus('probe', 'running', '正在验证 patch 点前状态…');
    updateStatus('Probe 中', 'eps_patch.py probe 正在运行', 'running');

    try {
      const result = await postJson('/api/eps/patch-probe', {
        confirm: true,
        serial: e.serialInput?.value?.trim() || '',
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

      // Simple heuristic progress based on log keywords.
      const joined = (job.lines || []).map((l) => l.line).join('\n');
      let pct = 0;
      if (state.jobKind === 'telescope') {
        if (/Layer 3/.test(joined)) pct = 70;
        else if (/Security Access/.test(joined)) pct = 40;
        else if (/Layer 1/.test(joined)) pct = 15;
      } else {
        if (/WRITE-CRC|CRC_PRECHECKED/.test(joined)) pct = 80;
        else if (/WRITE-TARGET|TARGET_PRECHECKED/.test(joined)) pct = 50;
        else if (/FACI PE cycle/.test(joined)) pct = 30;
      }
      setJobProgress(pct);

      if (job.status === 'running') {
        setTimeout(pollJob, JOB_POLL_MS);
        return;
      }

      setJobProgress(100);
      if (job.status === 'done') {
        logLine('完成', 'ok');
        if (state.jobKind === 'telescope') {
          setStepStatus('telescope', 'ready', '探测完成');
          await refreshStatus();
          // Also fetch classification explicitly.
          try {
            const cls = await fetchJson('/api/eps/telescope-classify');
            if (cls.ok) {
              state.telescopeClassification = cls.classification;
              setStepStatus('classify', canRunProbe() ? 'ready' : 'warn', classificationText(cls.classification));
              syncProbeButton();
            }
          } catch (_) { /* ignore */ }
        } else {
          setStepStatus('probe', 'ready', 'Probe 完成');
          await refreshStatus();
        }
      } else if (job.status === 'cancelled') {
        logLine('已取消', 'dim');
      } else {
        logLine(job.error || '执行出错', 'err');
        if (state.jobKind === 'telescope') setStepStatus('telescope', 'error', job.error || '出错');
        else setStepStatus('probe', 'error', job.error || '出错');
      }
    } catch (err) {
      logLine(`轮询失败: ${err}`, 'err');
    } finally {
      if (state.jobId && (!state.running || state.jobId)) {
        // Keep running true until job final; will be reset after timeout if needed.
      }
      const current = state.jobId ? await fetchJson(`/api/eps/job/${state.jobId}`).catch(() => null) : null;
      if (!current || !current.job || current.job.status !== 'running') {
        state.jobId = null;
        state.jobKind = null;
        setRunning(false);
        await refreshStatus();
      }
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
      syncProbeButton();
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
      setStepStatus('writer', 'ready', '命令已生成，请在 SSH 终端执行');
    } catch (err) {
      notifyToast(String(err), 'err');
    }
  }

  function startPoll() {
    refreshStatus();
    if (state.pollTimer) return;
    state.pollTimer = setInterval(refreshStatus, 4000);
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
    e.writerBtn?.addEventListener('click', prepareWriter);
    e.cancelJobBtn?.addEventListener('click', cancelJob);
    e.copyCommandBtn?.addEventListener('click', () => {
      const command = e.commandBody?.textContent || '';
      if (!command) return;
      navigator.clipboard?.writeText(command).then(() => notifyToast('已复制命令', 'ok')).catch(() => notifyToast('复制失败', 'err'));
    });
  }

  return { init, startPoll, stopPoll };
})();

document.addEventListener('DOMContentLoaded', EpsPanel.init);
