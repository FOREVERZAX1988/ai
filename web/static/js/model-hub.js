/**
 * ClawPanel-style model hub: provider accounts → model pool → primary + failover chain.
 */
const ModelHub = (() => {
  const OPTIONAL_BASE_URL = new Set(['qwen', 'minimax', 'mimo', 'bigmodel']);

  let root = null;
  let hub = { version: 1, accounts: [], primary: null, fallbacks: [] };
  let providers = [];
  let providerLabels = {};
  let getProviderLabel = (id) => id;
  let translate = (_key, fallback) => fallback ?? '';
  let apiFn = async () => ({ data: {} });
  let onLegacySync = () => {};
  let saveHubFn = null;
  let saveHubTimer = null;
  let saveHubChain = Promise.resolve();

  function getRoutes() {
    const routes = [];
    const p = hub.primary;
    if (p?.accountId) routes.push(p);
    for (const f of hub.fallbacks || []) {
      if (f?.accountId) routes.push(f);
    }
    return routes;
  }

  function setRoutes(routes) {
    const list = (routes || []).filter((r) => r?.accountId);
    hub.primary = list[0] ? { ...list[0] } : null;
    hub.fallbacks = list.slice(1).map((r) => ({ ...r }));
  }

  function t(key, fallback, vars) {
    let text = translate(key, fallback);
    if (vars && typeof text === 'string') {
      Object.entries(vars).forEach(([k, v]) => {
        text = text.replace(`{${k}}`, String(v));
      });
    }
    return text;
  }

  function escapeAttr(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  function escapeHtml(s) {
    return escapeAttr(s);
  }

  function newAccountId() {
    return `acc_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  }

  function cloneHub(data) {
    return JSON.parse(JSON.stringify(data || { version: 1, accounts: [], primary: null, fallbacks: [] }));
  }

  function accountById(id) {
    return (hub.accounts || []).find((a) => a.id === id);
  }

  function providerOptions(selected) {
    const list = providers.length ? providers : Object.keys(providerLabels);
    return list.map((p) => {
      const id = typeof p === 'string' ? p : (p.id || p);
      const label = getProviderLabel(id);
      const text = label && label !== id ? `${label} (${id})` : id;
      return `<option value="${escapeAttr(id)}"${id === selected ? ' selected' : ''}>${escapeHtml(text)}</option>`;
    }).join('');
  }

  function accountOptions(selected, { enabledOnly = false } = {}) {
    const rows = (hub.accounts || []).filter((a) => !enabledOnly || a.enabled !== false);
    if (!rows.length) {
      return `<option value="">${escapeHtml(t('modelHubNoAccount', '请先添加服务商账户'))}</option>`;
    }
    return rows.map((a) => {
      const prov = getProviderLabel(a.provider);
      const text = a.label ? `${a.label} · ${prov}` : prov;
      return `<option value="${escapeAttr(a.id)}"${a.id === selected ? ' selected' : ''}>${escapeHtml(text)}</option>`;
    }).join('');
  }

  function modelsForAccount(accountId) {
    const acc = accountById(accountId);
    if (!acc) return [];
    const ids = Array.isArray(acc.models) ? acc.models : [];
    return ids.map((id) => ({ id }));
  }

  function defaultModelForAccount(accountId) {
    const opts = modelsForAccount(accountId);
    if (opts.length) return opts[0].id;
    const primary = hub.primary;
    if (primary?.accountId === accountId && primary.model) return primary.model;
    return '';
  }

  function needsBaseUrlPrimary(provider) {
    return provider === 'custom';
  }

  function needsBaseUrlAdvanced(provider) {
    return OPTIONAL_BASE_URL.has(provider);
  }

  function accountDisplayName(acc) {
    if (!acc) return '—';
    const prov = getProviderLabel(acc.provider);
    const label = (acc.label || '').trim();
    if (!label || label === prov || label === acc.provider) return prov;
    return label;
  }

  function modelPreviewText(models, maxShow = 3) {
    const list = (models || []).filter(Boolean);
    if (!list.length) return '';
    const shown = list.slice(0, maxShow);
    let text = shown.join(', ');
    if (list.length > maxShow) text += '…';
    return text;
  }

  function removeModelFromPool(acc, modelId) {
    if (!acc || !modelId) return;
    acc.models = (acc.models || []).filter((m) => m !== modelId);
    const routes = getRoutes().filter((r) => !(r.accountId === acc.id && r.model === modelId));
    setRoutes(routes);
    renderAccounts();
    renderRouting();
    return commitHubSave();
  }

  function renderModelPoolTags(acc, idx) {
    const models = acc.models || [];
    if (!models.length) {
      return `<span class="model-hub-tag muted">${escapeHtml(t('modelHubPoolEmpty', '点击「拉取」'))}</span>`;
    }
    return models.map((m) => `
      <span class="model-hub-tag removable" title="${escapeAttr(m)}">
        <span class="model-hub-tag-text">${escapeHtml(m)}</span>
        <button type="button" class="model-hub-tag-remove" data-model="${escapeAttr(m)}" data-idx="${idx}" aria-label="${escapeAttr(t('modelHubRemoveModel', '移除模型'))}">×</button>
      </span>
    `).join('');
  }

  function resolveProviderUsageLabel(providerId) {
    const pid = String(providerId || '').trim();
    if (!pid) return '—';
    const matches = (hub.accounts || []).filter((a) => a.provider === pid);
    if (matches.length === 1) return accountDisplayName(matches[0]);
    if (matches.length > 1) {
      return matches.map((a) => accountDisplayName(a)).join(' · ');
    }
    return getProviderLabel(pid) || pid;
  }

  function accountLabel(accountId) {
    return accountDisplayName(accountById(accountId));
  }

  function routeCardParts(row) {
    if (!row?.accountId || !row?.model) return null;
    const acc = accountById(row.accountId);
    const badges = [];
    if (row.contextWindow > 0) badges.push(`${row.contextWindow} ctx`);
    if (row.maxTokens > 0) badges.push(`max ${row.maxTokens}`);
    if (row.label) badges.push(row.label);
    return {
      model: row.model,
      provider: accountDisplayName(acc),
      badges,
    };
  }

  function routeCardHtml(row) {
    const parts = routeCardParts(row);
    if (!parts) {
      return `<span class="mh-route-empty">${escapeHtml(t('modelHubRouteUnset', '未配置'))}</span>`;
    }
    const badges = parts.badges.length
      ? `<div class="mh-route-badges">${parts.badges.map((b) => `<span class="mh-pill">${escapeHtml(b)}</span>`).join('')}</div>`
      : '';
    return `
      <div class="mh-route-text">
        <div class="mh-route-model" title="${escapeAttr(parts.model)}">${escapeHtml(parts.model)}</div>
        <div class="mh-route-provider">${escapeHtml(parts.provider)}</div>
      </div>
      ${badges}
    `;
  }

  function buildSingleProviderHub({ provider, apiKey = '', model = '', baseUrl = '', models = [], label = '' }) {
    const id = newAccountId();
    const modelList = models.length ? [...models] : (model ? [model] : []);
    if (model && !modelList.includes(model)) modelList.unshift(model);
    return {
      version: 1,
      accounts: [{
        id,
        provider,
        label: label || '',
        apiKey,
        baseUrl,
        enabled: true,
        models: modelList,
      }],
      primary: model ? { accountId: id, model } : null,
      fallbacks: [],
    };
  }

  function exportRoute(row) {
    if (!row) return null;
    const item = {
      accountId: row.accountId,
      model: (row.model || '').trim(),
    };
    if (!item.accountId || !item.model) return null;
    const label = (row.label || '').trim();
    if (label) item.label = label;
    const cw = parseInt(row.contextWindow, 10);
    if (cw > 0) item.contextWindow = cw;
    const mt = parseInt(row.maxTokens, 10);
    if (mt > 0) item.maxTokens = mt;
    const temp = row.temperature;
    if (temp !== undefined && temp !== null && String(temp).trim() !== '') {
      const v = parseFloat(temp);
      if (!Number.isNaN(v)) item.temperature = v;
    }
    const topP = row.topP;
    if (topP !== undefined && topP !== null && String(topP).trim() !== '') {
      const v = parseFloat(topP);
      if (!Number.isNaN(v)) item.topP = v;
    }
    return item;
  }

  let routeModal = null;
  let routeModalCombo = null;
  let routeModalState = { index: -1 };

  function ensureRouteModal() {
    if (routeModal) return routeModal;
    const el = document.createElement('div');
    el.className = 'modal model-hub-route-modal';
    el.hidden = true;
    el.innerHTML = `
      <div class="modal-backdrop" data-close="1"></div>
      <div class="modal-content" role="dialog" aria-modal="true">
        <header class="modal-header">
          <h2 id="modelHubRouteModalTitle">${escapeHtml(t('modelHubRouteModalTitle', '模型路由配置'))}</h2>
          <button type="button" class="modal-close" data-close="1" aria-label="${escapeAttr(t('close', '关闭'))}">×</button>
        </header>
        <div class="modal-body">
          <label class="field">
            <span class="field-label">${escapeHtml(t('modelHubAccount', '账户'))}</span>
            <select id="modelHubRouteAccount"></select>
          </label>
          <label class="field">
            <span class="field-label">${escapeHtml(t('model', '模型'))}</span>
            <div id="modelHubRouteModelHost" class="model-combobox-host"></div>
          </label>
          <label class="field model-hub-route-label-field">
            <span class="field-label">${escapeHtml(t('fallbackLabel', '标签'))}</span>
            <input type="text" id="modelHubRouteLabel" placeholder="${escapeAttr(t('fallbackLabelPh', '可选'))}">
          </label>
          <div class="field-row">
            <label class="field">
              <span class="field-label">${escapeHtml(t('modelHubContextWindow', '上下文窗口'))}</span>
              <input type="number" id="modelHubRouteContext" min="0" max="2000000" step="1024" placeholder="${escapeAttr(t('modelHubUseDefault', '0=默认'))}">
            </label>
            <label class="field">
              <span class="field-label">${escapeHtml(t('maxTokens', 'Max Tokens'))}</span>
              <input type="number" id="modelHubRouteMaxTokens" min="0" max="128000" step="256" placeholder="${escapeAttr(t('modelHubUseDefault', '0=默认'))}">
            </label>
          </div>
          <div class="field-row">
            <label class="field">
              <span class="field-label">${escapeHtml(t('temperature', 'Temperature'))}</span>
              <input type="number" id="modelHubRouteTemp" min="0" max="2" step="0.1" placeholder="${escapeAttr(t('modelHubUseDefault', '默认'))}">
            </label>
            <label class="field">
              <span class="field-label">${escapeHtml(t('topP', 'Top P'))}</span>
              <input type="number" id="modelHubRouteTopP" min="0" max="1" step="0.05" placeholder="${escapeAttr(t('modelHubUseDefault', '默认'))}">
            </label>
          </div>
          <p class="field-hint">${escapeHtml(t('modelHubRouteModalHint', '留空或 0 表示使用内置默认值。'))}</p>
        </div>
        <footer class="modal-footer">
          <button type="button" class="btn ghost" data-close="1">${escapeHtml(t('cancel', '取消'))}</button>
          <button type="button" class="btn primary" id="modelHubRouteSave">${escapeHtml(t('save', '保存'))}</button>
        </footer>
      </div>
    `;
    document.body.appendChild(el);
    el.querySelectorAll('[data-close]').forEach((node) => {
      node.addEventListener('click', () => closeRouteModal());
    });
    el.querySelector('#modelHubRouteSave')?.addEventListener('click', () => saveRouteModal());
    el.querySelector('#modelHubRouteAccount')?.addEventListener('change', (e) => {
      const accountId = e.target.value;
      if (routeModalCombo) {
        routeModalCombo.setOptions(modelsForAccount(accountId));
        routeModalCombo.setValue(defaultModelForAccount(accountId), { silent: true });
      }
    });
    routeModal = el;
    return el;
  }

  function openRouteModal(opts = {}) {
    ensureRouteModal();
    routeModalState = { index: opts.index ?? -1 };
    const routes = getRoutes();
    const idx = routeModalState.index;
    const row = idx >= 0 ? { ...routes[idx] } : {
      accountId: hub.accounts?.[0]?.id || '',
      model: '',
      label: '',
    };

    routeModal.querySelector('#modelHubRouteModalTitle').textContent = idx >= 0
      ? t('modelHubEditRoute', '编辑模型')
      : t('modelHubAddRoute', '添加模型');

    routeModal.querySelector('.model-hub-route-label-field')?.classList.remove('hidden');

    const accSel = routeModal.querySelector('#modelHubRouteAccount');
    accSel.innerHTML = accountOptions(row.accountId, { enabledOnly: true });
    if (row.accountId) accSel.value = row.accountId;

    const host = routeModal.querySelector('#modelHubRouteModelHost');
    host.innerHTML = '';
    if (typeof ModelCombobox !== 'undefined') {
      routeModalCombo = ModelCombobox.mount(host, { placeholder: 'model-id' });
      routeModalCombo.setOptions(modelsForAccount(row.accountId));
      routeModalCombo.setValue(row.model || '', { silent: true });
    }

    routeModal.querySelector('#modelHubRouteLabel').value = row.label || '';
    routeModal.querySelector('#modelHubRouteContext').value = row.contextWindow > 0 ? row.contextWindow : '';
    routeModal.querySelector('#modelHubRouteMaxTokens').value = row.maxTokens > 0 ? row.maxTokens : '';
    routeModal.querySelector('#modelHubRouteTemp').value = row.temperature ?? '';
    routeModal.querySelector('#modelHubRouteTopP').value = row.topP ?? '';

    routeModal.hidden = false;
    routeModal.classList.add('is-open');
  }

  function closeRouteModal() {
    if (!routeModal) return;
    routeModal.hidden = true;
    routeModal.classList.remove('is-open');
  }

  function readRouteModal() {
    const accountId = routeModal.querySelector('#modelHubRouteAccount')?.value || '';
    const model = routeModalCombo?.getValue?.() || '';
    const row = {
      accountId,
      model: model.trim(),
      label: (routeModal.querySelector('#modelHubRouteLabel')?.value || '').trim(),
      contextWindow: parseInt(routeModal.querySelector('#modelHubRouteContext')?.value, 10) || 0,
      maxTokens: parseInt(routeModal.querySelector('#modelHubRouteMaxTokens')?.value, 10) || 0,
    };
    const tempRaw = routeModal.querySelector('#modelHubRouteTemp')?.value;
    if (tempRaw !== '' && tempRaw != null) row.temperature = parseFloat(tempRaw);
    const topPRaw = routeModal.querySelector('#modelHubRouteTopP')?.value;
    if (topPRaw !== '' && topPRaw != null) row.topP = parseFloat(topPRaw);
    return row;
  }

  async function saveRouteModal() {
    const row = readRouteModal();
    if (!row.accountId || !row.model) {
      return;
    }
    const routes = getRoutes();
    const idx = routeModalState.index;
    if (idx >= 0) {
      routes[idx] = { ...routes[idx], ...row };
    } else {
      routes.push(row);
    }
    setRoutes(routes);
    closeRouteModal();
    renderRouting();
    const btn = routeModal?.querySelector('#modelHubRouteSave');
    if (btn) btn.disabled = true;
    try {
      await commitHubSave();
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  let persistTimer = null;

  async function commitHubSave(opts = {}) {
    if (opts.debounce) {
      clearTimeout(saveHubTimer);
      saveHubTimer = setTimeout(() => commitHubSave({ silent: opts.silent }), opts.debounce);
      return;
    }
    clearTimeout(saveHubTimer);
    clearTimeout(persistTimer);
    onLegacySync(hub);
    if (!saveHubFn) {
      root?.dispatchEvent(new CustomEvent('hubchange', { bubbles: true }));
      return;
    }
    const payload = prepareForSave();
    saveHubChain = saveHubChain.then(() => saveHubFn(payload, opts)).catch(() => {});
    return saveHubChain;
  }

  function persistChange(opts = {}) {
    return commitHubSave(opts);
  }

  function bindTextPersist(input, onValue, onBlurExtra) {
    if (!input) return;
    input.addEventListener('input', (e) => {
      onValue(e.target.value);
      commitHubSave({ debounce: 600, silent: true });
    });
    input.addEventListener('blur', () => {
      onBlurExtra?.();
      commitHubSave({ silent: true });
    });
  }

  function mount(container, opts = {}) {
    root = typeof container === 'string' ? document.querySelector(container) : container;
    if (!root) return;
    providers = opts.providers || [];
    providerLabels = opts.providerLabels || {};
    getProviderLabel = opts.getProviderLabel || ((id) => providerLabels[id] || id);
    translate = opts.t || translate;
    apiFn = opts.api || apiFn;
    onLegacySync = opts.onLegacySync || onLegacySync;
    saveHubFn = opts.onSaveHub || null;

    root.innerHTML = `
      <div class="model-hub">
        <section class="model-hub-section model-hub-section-routing">
          <div class="model-hub-section-head">
            <div>
              <h4 class="model-hub-section-title">${escapeHtml(t('modelHubListTitle', '模型列表'))}</h4>
              <p class="field-hint">${escapeHtml(t('modelHubListHint', '按顺序调用，第一位为主模型。'))}</p>
            </div>
            <button type="button" class="btn small ghost" id="modelHubAddRoute">${escapeHtml(t('modelHubAddRoute', '+ 添加'))}</button>
          </div>
          <div class="mh-route-list" id="modelHubRouteList"></div>
          <p class="model-hub-empty hidden" id="modelHubRouteEmpty">${escapeHtml(t('modelHubRouteEmpty', '暂无模型，点击添加。'))}</p>
        </section>
        <section class="model-hub-section model-hub-section-accounts">
          <div class="model-hub-section-head">
            <div>
              <h4 class="model-hub-section-title">${escapeHtml(t('modelHubAccountsTitle', '服务商账户'))}</h4>
              <p class="field-hint">${escapeHtml(t('modelHubAccountsHintShort', '配置 Key 并拉取模型；可添加多个服务商。'))}</p>
            </div>
            <button type="button" class="btn small ghost" id="modelHubAddAccount">${escapeHtml(t('modelHubAddAccount', '+ 添加'))}</button>
          </div>
          <div class="model-hub-accounts" id="modelHubAccounts"></div>
          <p class="model-hub-empty hidden" id="modelHubAccountsEmpty">${escapeHtml(t('modelHubAccountsEmpty', '暂无账户'))}</p>
        </section>
      </div>
    `;

    root.querySelector('#modelHubAddAccount')?.addEventListener('click', async () => {
      const pid = providers[0] || 'opencode-zen';
      const acc = {
        id: newAccountId(),
        provider: pid,
        label: '',
        apiKey: '',
        baseUrl: '',
        enabled: true,
        models: [],
      };
      hub.accounts = [...(hub.accounts || []), acc];
      render();
      await commitHubSave({ silent: true });
    });

    root.querySelector('#modelHubAddRoute')?.addEventListener('click', () => {
      openRouteModal({ index: -1 });
    });

    if (opts.initial) setHub(opts.initial);
    else render();
  }


  function render() {
    renderAccounts();
    renderRouting();
  }

  function renderAccounts() {
    const list = root?.querySelector('#modelHubAccounts');
    const empty = root?.querySelector('#modelHubAccountsEmpty');
    if (!list) return;
    const openIds = new Set(
      [...list.querySelectorAll('.mh-account[open]')].map((node) => node.dataset.accountId).filter(Boolean),
    );
    const accounts = hub.accounts || [];
    empty?.classList.toggle('hidden', accounts.length > 0);
    list.innerHTML = '';
    accounts.forEach((acc, idx) => {
      const el = document.createElement('details');
      el.className = 'mh-account';
      el.dataset.accountId = acc.id;
      if (acc.enabled === false) el.classList.add('is-disabled');
      const showUrlPrimary = needsBaseUrlPrimary(acc.provider);
      const showUrlAdv = needsBaseUrlAdvanced(acc.provider);
      const modelCount = (acc.models || []).length;
      const hasKey = !!(acc.apiKey || '').trim();
      const preview = modelPreviewText(acc.models, 3);
      el.innerHTML = `
        <summary class="mh-account-summary">
          <span class="mh-account-dot${hasKey ? ' ok' : ''}" title="${escapeAttr(hasKey ? t('modelHubKeySet', '已配置 Key') : t('modelHubKeyMissing', '未配置 Key'))}"></span>
          <span class="mh-account-name">${escapeHtml(accountDisplayName(acc))}</span>
          <span class="mh-account-meta">${modelCount ? t('modelHubModelCount', '{n} 个模型', { n: modelCount }) : escapeHtml(t('modelHubPoolEmptyShort', '未拉取'))}</span>
          ${preview ? `<span class="mh-account-preview" title="${escapeAttr((acc.models || []).join(', '))}">${escapeHtml(preview)}</span>` : ''}
        </summary>
        <div class="mh-account-body">
          <div class="mh-account-toolbar">
            <label class="switch model-hub-enable-switch" title="${escapeAttr(t('modelHubEnabled', '启用'))}">
              <input type="checkbox" class="model-hub-enabled" data-idx="${idx}" ${acc.enabled !== false ? 'checked' : ''}>
              <span class="slider"></span>
            </label>
            <div class="model-hub-account-actions">
              <button type="button" class="btn small ghost model-hub-test" data-idx="${idx}">${escapeHtml(t('testConnection', '测试'))}</button>
              <button type="button" class="btn small ghost model-hub-fetch" data-idx="${idx}">${escapeHtml(t('fetchModels', '拉取'))}</button>
              <button type="button" class="btn small ghost danger model-hub-remove" data-idx="${idx}">${escapeHtml(t('remove', '删除'))}</button>
            </div>
          </div>
          <label class="field model-hub-label-field">
            <span class="field-label">${escapeHtml(t('modelHubLabelPh', '备注名'))}</span>
            <input type="text" class="model-hub-label" data-idx="${idx}" value="${escapeAttr(acc.label || '')}" placeholder="${escapeAttr(t('modelHubLabelPlaceholder', '可选，如：公司账号'))}">
          </label>
          <label class="field">
            <span class="field-label">${escapeHtml(t('provider', '服务商'))}</span>
            <select class="model-hub-provider" data-idx="${idx}">${providerOptions(acc.provider)}</select>
          </label>
          <label class="field">
            <span class="field-label">${escapeHtml(t('apiKey', 'API Key'))}</span>
            <input type="text" class="model-hub-apikey" data-idx="${idx}" value="${escapeAttr(acc.apiKey || '')}" autocomplete="off" spellcheck="false" placeholder="sk-...">
          </label>
          <div class="model-hub-url-primary ${showUrlPrimary ? '' : 'hidden'}">
            <label class="field">
              <span class="field-label">${escapeHtml(t('baseUrl', 'Base URL'))}</span>
              <input type="text" class="model-hub-baseurl" data-idx="${idx}" value="${escapeAttr(acc.baseUrl || '')}" placeholder="https://api.example.com/v1">
            </label>
          </div>
          <details class="model-hub-advanced ${showUrlAdv ? '' : 'hidden'}">
            <summary>${escapeHtml(t('modelHubAdvanced', '高级（Base URL）'))}</summary>
            <label class="field">
              <span class="field-label">${escapeHtml(t('baseUrl', 'Base URL'))}</span>
              <input type="text" class="model-hub-baseurl-adv" data-idx="${idx}" value="${escapeAttr(acc.baseUrl || '')}" placeholder="${escapeAttr(t('fallbackUrlOptionalPh', '留空=默认'))}">
            </label>
          </details>
          <div class="model-hub-pool">
            <span class="field-label">${escapeHtml(t('modelHubPool', '模型池'))}</span>
            <div class="model-hub-tags">${renderModelPoolTags(acc, idx)}</div>
          </div>
          <p class="model-hub-status hidden" data-idx="${idx}"></p>
        </div>
      `;
      list.appendChild(el);
      if (openIds.has(acc.id)) el.open = true;

      el.querySelectorAll('.model-hub-tag-remove').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          const modelId = btn.dataset.model;
          if (!modelId) return;
          removeModelFromPool(acc, modelId);
        });
      });
      el.querySelector('.model-hub-enabled')?.addEventListener('change', (e) => {
        acc.enabled = e.target.checked;
        el.classList.toggle('is-disabled', !acc.enabled);
        commitHubSave({ silent: true });
      });
      bindTextPersist(el.querySelector('.model-hub-label'), (v) => {
        acc.label = v;
      });
      el.querySelector('.model-hub-label')?.addEventListener('blur', () => {
        const nameEl = el.querySelector('.mh-account-name');
        if (nameEl) nameEl.textContent = accountDisplayName(acc);
        renderRouting();
        commitHubSave({ silent: true });
      });
      el.querySelector('.model-hub-provider')?.addEventListener('change', (e) => {
        acc.provider = e.target.value;
        renderAccounts();
        renderRouting();
        commitHubSave({ silent: true });
      });
      bindTextPersist(el.querySelector('.model-hub-apikey'), (v) => {
        acc.apiKey = v;
      });
      el.querySelector('.model-hub-apikey')?.addEventListener('blur', () => {
        const dot = el.querySelector('.mh-account-dot');
        if (dot) dot.classList.toggle('ok', !!(acc.apiKey || '').trim());
      });
      bindTextPersist(el.querySelector('.model-hub-baseurl'), (v) => {
        acc.baseUrl = v;
      });
      bindTextPersist(el.querySelector('.model-hub-baseurl-adv'), (v) => {
        acc.baseUrl = v;
      });
      el.querySelector('.model-hub-remove')?.addEventListener('click', async () => {
        const removedId = acc.id;
        hub.accounts = accounts.filter((_, i) => i !== idx);
        const routes = getRoutes().filter((r) => r.accountId !== removedId);
        setRoutes(routes);
        render();
        await commitHubSave();
      });
      el.querySelector('.model-hub-test')?.addEventListener('click', () => testAccount(acc, el));
      el.querySelector('.model-hub-fetch')?.addEventListener('click', () => fetchAccountModels(acc, el));
    });
  }

  function accountRequestPayload(acc) {
    return {
      accountId: acc.id,
      provider: acc.provider,
      apiKey: acc.apiKey || '',
      baseUrl: acc.baseUrl || '',
    };
  }

  async function testAccount(acc, el) {
    const status = el.querySelector('.model-hub-status');
    if (status) {
      status.classList.remove('hidden', 'ok', 'err');
      status.textContent = t('testing', '测试中…');
    }
    const { data } = await apiFn('POST', '/api/ai/test', accountRequestPayload(acc));
    if (status) {
      status.classList.remove('hidden');
      if (data?.ok) {
        status.classList.add('ok');
        status.textContent = t('testOk', '连接成功');
      } else {
        status.classList.add('err');
        status.textContent = data?.error || t('testFailed', '连接失败');
      }
    }
  }

  async function fetchAccountModels(acc, el) {
    const status = el.querySelector('.model-hub-status');
    const btn = el.querySelector('.model-hub-fetch');
    if (btn) btn.disabled = true;
    if (status) {
      status.classList.remove('hidden', 'ok', 'err');
      status.textContent = t('loadingModels', '加载中…');
    }
    try {
      await commitHubSave({ silent: true });
    } catch {
      if (btn) btn.disabled = false;
      if (status) {
        status.classList.remove('hidden');
        status.classList.add('err');
        status.textContent = t('saveFailed', '保存失败');
      }
      return;
    }
    const { status: httpStatus, data } = await apiFn('POST', '/api/ai/models', accountRequestPayload(acc));
    if (btn) btn.disabled = false;
    if (httpStatus === 404) {
      if (status) {
        status.classList.remove('hidden');
        status.classList.add('err');
        status.textContent = t('modelHubApiMissing', '模型 API 未就绪，请重启 op助手 后重试');
      }
      return;
    }
    if (data?.modelHub) {
      setHub(data.modelHub, { silent: true });
    } else if (data?.ok && Array.isArray(data.models)) {
      acc.models = data.models.map((m) => (typeof m === 'string' ? m : m.id)).filter(Boolean);
      await commitHubSave({ silent: true });
    }
    renderAccounts();
    renderRouting();
    if (status) {
      status.classList.remove('hidden');
      if (data?.ok) {
        status.classList.add('ok');
        status.textContent = t('modelHubFetchOk', '已更新模型池');
      } else {
        status.classList.add('err');
        status.textContent = data?.error || t('modelHubFetchFail', '拉取失败');
      }
    }
  }

  function renderRouting() {
    const list = root?.querySelector('#modelHubRouteList');
    const empty = root?.querySelector('#modelHubRouteEmpty');
    if (!list) return;
    const routes = getRoutes();
    empty?.classList.toggle('hidden', routes.length > 0);
    list.innerHTML = '';
    routes.forEach((row, idx) => {
      const el = document.createElement('div');
      const isMain = idx === 0;
      el.className = `mh-route-item${isMain ? ' mh-route-primary' : ''}`;
      el.innerHTML = `
        <span class="mh-route-badge${isMain ? ' is-main' : ''}" title="${escapeAttr(isMain ? t('modelHubPrimary', '主模型') : '')}">${isMain ? '★' : idx + 1}</span>
        <div class="mh-route-body">${routeCardHtml(row)}</div>
        <div class="mh-route-actions">
          <button type="button" class="btn small ghost mh-route-edit" data-idx="${idx}">${escapeHtml(t('modelHubConfigure', '配置'))}</button>
          <button type="button" class="btn small ghost mh-route-up" data-idx="${idx}" title="${escapeAttr(t('moveUp', '上移'))}" ${idx === 0 ? 'disabled' : ''}>↑</button>
          <button type="button" class="btn small ghost mh-route-down" data-idx="${idx}" title="${escapeAttr(t('moveDown', '下移'))}" ${idx >= routes.length - 1 ? 'disabled' : ''}>↓</button>
          <button type="button" class="btn small ghost danger mh-route-remove" data-idx="${idx}">×</button>
        </div>
      `;
      list.appendChild(el);

      el.querySelector('.mh-route-edit')?.addEventListener('click', () => {
        openRouteModal({ index: idx });
      });
      el.querySelector('.mh-route-remove')?.addEventListener('click', async () => {
        const next = getRoutes().filter((_, i) => i !== idx);
        setRoutes(next);
        renderRouting();
        await commitHubSave();
      });
      el.querySelector('.mh-route-up')?.addEventListener('click', async () => {
        if (idx <= 0) return;
        const r = getRoutes();
        [r[idx - 1], r[idx]] = [r[idx], r[idx - 1]];
        setRoutes(r);
        renderRouting();
        await commitHubSave({ silent: true });
      });
      el.querySelector('.mh-route-down')?.addEventListener('click', async () => {
        if (idx >= routes.length - 1) return;
        const r = getRoutes();
        [r[idx], r[idx + 1]] = [r[idx + 1], r[idx]];
        setRoutes(r);
        renderRouting();
        await commitHubSave({ silent: true });
      });
    });
  }

  function setHub(data, opts = {}) {
    hub = cloneHub(data);
    if (!Array.isArray(hub.accounts)) hub.accounts = [];
    if (!Array.isArray(hub.fallbacks)) hub.fallbacks = [];
    render();
    if (!opts.silent) {
      onLegacySync(hub);
    }
  }

  function syncHubFromUi() {
    // Routing is edited via modal; hub object is source of truth after modal save.
    return hub;
  }

  function prepareForSave() {
    clearTimeout(persistTimer);
    persistTimer = null;
    return getHub();
  }

  function getHub() {
    const out = cloneHub(hub);
    out.fallbacks = (out.fallbacks || [])
      .map((row) => exportRoute(row))
      .filter(Boolean);
    if (out.primary) {
      const primary = exportRoute(out.primary);
      out.primary = primary;
    }
    return out;
  }

  function setProviders(list, labels) {
    providers = list || [];
    if (labels) providerLabels = labels;
  }

  function getPrimaryAccount() {
    const id = hub.primary?.accountId;
    return id ? accountById(id) : hub.accounts?.[0];
  }

  return {
    mount,
    setHub,
    getHub,
    prepareForSave,
    syncHubFromUi,
    setProviders,
    getPrimaryAccount,
    buildSingleProviderHub,
    resolveProviderUsageLabel,
    render,
  };
})();
