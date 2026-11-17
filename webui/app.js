/* telegram_chats_bot — веб-интерфейс чата.
   Чистый ES6, без сборки и внешних библиотек. Все запросы — fetch на относительные пути. */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.prototype.slice.call((root || document).querySelectorAll(sel));

  const APP_NAME = 'telegram_chats_bot';
  const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
    'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  const CONNECTION_TEXT = {
    online: 'на связи',
    connecting: 'подключение…',
    offline: 'нет связи'
  };

  function defaultSettings() {
    return {
      theme: 'dark',
      asr_enabled: true,
      auto_transcribe: false,
      asr_model: '',
      auto_approve: false,
      api_base: '',
      local_api: true,
      limits: { download_mb: 0, upload_mb: 0 }
    };
  }

  const state = {
    settings: defaultSettings(),
    chats: [],
    activeId: null,
    messages: new Map(),
    rev: 0,
    hasOlder: false,
    loadingOlder: false,
    loadingMessages: false,
    loadToken: 0,
    polling: false,
    sending: false,
    unread: 0,
    stick: true,
    autoScroll: false,
    connection: 'connecting',
    networkDown: false,
    recovered: false,
    lastBootstrapAttempt: 0,
    bootstrapped: false,
    bootErrorShown: false,
    bot: null,
    pending: [],
    drafts: new Map(),
    draftFiles: new Map(),
    tempSeq: 0,
    transcribing: new Set(),
    chatsSignature: '',
    usersSignature: '',
    chatSearch: '',
    olderCooldownUntil: 0,
    asrModels: [],
    asrActive: '',
    asrLoading: false,
    asrError: '',
    asrTimer: null,
    findUsers: [],
    findLoading: false,
    findQuery: '',
    findToken: 0,
    findTimer: null,
    lastFocus: null,
    pollTimer: null,
    chatsTimer: null,
    bootstrapTimer: null,
    refreshTimer: null
  };

  const ui = {
    conn: $('#conn'),
    connDot: $('#connDot'),
    connText: $('#connText'),
    metaTheme: $('#metaTheme'),
    sidebar: $('#sidebar'),
    sidebarBackdrop: $('#sidebarBackdrop'),
    btnSidebarClose: $('#btnSidebarClose'),
    btnBurger: $('#btnBurger'),
    chatSearch: $('#chatSearch'),
    btnSearchClear: $('#btnSearchClear'),
    chatList: $('#chatList'),
    chatListEmpty: $('#chatListEmpty'),
    chatListEmptyTitle: $('#chatListEmptyTitle'),
    chatListEmptyText: $('#chatListEmptyText'),
    btnFindUser: $('#btnFindUser'),
    btnSettings: $('#btnSettings'),
    btnSettingsMobile: $('#btnSettingsMobile'),
    peerAvatar: $('#peerAvatar'),
    peerName: $('#peerName'),
    peerSub: $('#peerSub'),
    messages: $('#messages'),
    feed: $('#feed'),
    loadOlderWrap: $('#loadOlderWrap'),
    loadOlder: $('#loadOlder'),
    loadOlderSpin: $('#loadOlderSpin'),
    loadOlderLabel: $('#loadOlderLabel'),
    scrollDown: $('#scrollDown'),
    scrollBadge: $('#scrollBadge'),
    noChat: $('#noChat'),
    noChatTitle: $('#noChatTitle'),
    noChatText: $('#noChatText'),
    btnNoChatFind: $('#btnNoChatFind'),
    btnNoChatSettings: $('#btnNoChatSettings'),
    chatEmpty: $('#chatEmpty'),
    chatEmptyText: $('#chatEmptyText'),
    btnChatEmptyFind: $('#btnChatEmptyFind'),
    messagesLoading: $('#messagesLoading'),
    composerEl: $('#composerEl'),
    composerInput: $('#composerInput'),
    btnSend: $('#btnSend'),
    btnAttach: $('#btnAttach'),
    attachBar: $('#attachBar'),
    fileInput: $('#fileInput'),
    modalSettings: $('#modalSettings'),
    modalFind: $('#modalFind'),
    settingsTabs: $$('.settings-tab'),
    settingsPanes: $$('.settings-pane'),
    themeDark: $('#themeDark'),
    themeLight: $('#themeLight'),
    asrEnabled: $('#asrEnabled'),
    autoTranscribe: $('#autoTranscribe'),
    asrConfig: $('#asrConfig'),
    asrOffHint: $('#asrOffHint'),
    asrModel: $('#asrModel'),
    asrStatus: $('#asrStatus'),
    asrProgress: $('#asrProgress'),
    asrProgressBar: $('#asrProgressBar'),
    btnAsrDownload: $('#btnAsrDownload'),
    btnAsrRefresh: $('#btnAsrRefresh'),
    settingsUsers: $('#settingsUsers'),
    addUserInput: $('#addUserInput'),
    btnAddUser: $('#btnAddUser'),
    autoApprove: $('#autoApprove'),
    aboutApi: $('#aboutApi'),
    aboutApiMode: $('#aboutApiMode'),
    aboutDownload: $('#aboutDownload'),
    aboutUpload: $('#aboutUpload'),
    aboutAsr: $('#aboutAsr'),
    aboutAsrRow: $('#aboutAsrRow'),
    findSearch: $('#findSearch'),
    btnFindClear: $('#btnFindClear'),
    findList: $('#findList'),
    findEmpty: $('#findEmpty'),
    findEmptyTitle: $('#findEmptyTitle'),
    findEmptyText: $('#findEmptyText'),
    lightbox: $('#lightbox'),
    lightboxImg: $('#lightboxImg'),
    lightboxDownload: $('#lightboxDownload'),
    lightboxClose: $('#lightboxClose'),
    toasts: $('#toasts'),
    dropzone: $('#dropzone')
  };

  /* ------------------------------------------------------------- утилиты */
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ESC[c]);
  }

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function icon(name) {
    return '<svg aria-hidden="true"><use href="#i-' + name + '"></use></svg>';
  }

  function fmtTime(ts) {
    const d = new Date((Number(ts) || 0) * 1000);
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  function dayKey(ts) {
    const d = new Date((Number(ts) || 0) * 1000);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  function dayLabel(ts) {
    const d = new Date((Number(ts) || 0) * 1000);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const that = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff = Math.round((today - that) / 86400000);
    if (diff === 0) return 'Сегодня';
    if (diff === 1) return 'Вчера';
    const year = d.getFullYear() === now.getFullYear() ? '' : ' ' + d.getFullYear();
    return d.getDate() + ' ' + MONTHS[d.getMonth()] + year;
  }

  function chatTime(ts) {
    if (!ts) return '';
    const d = new Date(Number(ts) * 1000);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const that = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff = Math.round((today - that) / 86400000);
    if (diff === 0) return fmtTime(ts);
    if (diff === 1) return 'Вчера';
    if (diff > 1 && diff < 7) return WEEKDAYS[d.getDay()];
    return pad2(d.getDate()) + '.' + pad2(d.getMonth() + 1) + '.' + String(d.getFullYear()).slice(2);
  }

  function plainPreview(value) {
    let text = String(value == null ? '' : value).replace(/\r\n?/g, '\n');
    text = text.replace(/```[\s\S]*?```/g, ' [код] ');
    text = text.replace(/`([^`\n]+)`/g, '$1');
    text = text.replace(/!\[([^\]]*)\]\([^)\s]*\)/g, '$1');
    text = text.replace(/\[([^\]]+)\]\([^)\s]*\)/g, '$1');
    text = text.replace(/(^|\s)[*_~]{1,3}(?=\S)/g, '$1');
    text = text.replace(/(?<=\S)[*_~]{1,3}(?=\s|$)/g, '');
    text = text.replace(/^[*+-]\s+/gm, '');
    text = text.replace(/^\d{1,9}[.)]\s+/gm, '');
    text = text.replace(/^>\s?/gm, '');
    text = text.replace(/#{1,6}\s+/g, '');
    text = text.replace(/\s+/g, ' ').trim();
    return text;
  }

  function relDate(ts) {
    if (!ts) return '';
    const d = new Date(Number(ts) * 1000);
    const now = new Date();
    const diff = Math.round((now - d) / 86400000);
    if (diff <= 0) return 'сегодня';
    if (diff === 1) return 'вчера';
    if (diff < 7) return diff + ' дн. назад';
    return pad2(d.getDate()) + '.' + pad2(d.getMonth() + 1) + '.' + d.getFullYear();
  }

  function fmtDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h ? h + ':' + pad2(m) + ':' + pad2(s) : m + ':' + pad2(s);
  }

  function fmtSize(bytes) {
    const b = Number(bytes) || 0;
    if (!b) return '';
    if (b < 1024) return b + ' Б';
    if (b < 1024 * 1024) return (b / 1024).toFixed(1).replace('.', ',') + ' КБ';
    if (b < 1024 * 1024 * 1024) return (b / 1024 / 1024).toFixed(1).replace('.', ',') + ' МБ';
    return (b / 1024 / 1024 / 1024).toFixed(2).replace('.', ',') + ' ГБ';
  }

  function progressPct(p) {
    const n = Number(p);
    if (!isFinite(n) || n <= 0) return 0;
    return Math.max(0, Math.min(100, n <= 1 ? n * 100 : n));
  }

  function initials(name) {
    const value = String(name == null ? '' : name).replace(/^@/, '').trim();
    if (!value) return '?';
    const parts = value.split(/\s+/).filter(Boolean).slice(0, 2);
    return parts.map((part) => Array.from(part)[0]).join('').toUpperCase();
  }

  function avatarClass(seed) {
    const value = String(seed == null ? '' : seed);
    let hash = 0;
    for (let i = 0; i < value.length; i += 1) hash = ((hash * 31) + value.charCodeAt(i)) >>> 0;
    return 'av-' + (hash % 6);
  }

  function avatarHtml(url, name, seed, extraClass) {
    const cls = 'avatar ' + (extraClass ? extraClass + ' ' : '') + avatarClass(seed == null ? name : seed);
    const image = url ? '<img src="' + esc(url) + '" alt="" loading="lazy" data-avatar>' : '';
    return '<span class="' + cls + '">' + image +
      '<span class="avatar-letter">' + esc(initials(name)) + '</span></span>';
  }

  function setAvatar(el, url, name, seed, extraClass, fallbackPlane) {
    if (!el) return;
    el.className = 'avatar ' + (extraClass ? extraClass + ' ' : '') + avatarClass(seed == null ? name : seed);
    const fallback = fallbackPlane
      ? icon('plane')
      : '<span class="avatar-letter">' + esc(initials(name)) + '</span>';
    el.innerHTML = (url ? '<img src="' + esc(url) + '" alt="" loading="lazy" data-avatar>' : '') + fallback;
  }

  function isNumericId(id) {
    return id != null && /^\d+$/.test(String(id));
  }

  function renderMarkdown(text) {
    try {
      if (window.MD && typeof window.MD.render === 'function') return window.MD.render(text);
    } catch (_err) { /* fallback ниже */ }
    return esc(text).replace(/\n/g, '<br>');
  }

  function toast(text, type) {
    if (!ui.toasts) return;
    const kind = type || 'info';
    const box = document.createElement('div');
    box.className = 'toast ' + kind;
    const ico = document.createElement('span');
    ico.className = 'toast-ico';
    ico.innerHTML = icon(kind === 'error' ? 'warning' : kind === 'success' ? 'check' : 'info');
    const label = document.createElement('span');
    label.className = 'toast-text';
    label.textContent = String(text == null ? '' : text);
    box.appendChild(ico);
    box.appendChild(label);

    let closed = false;
    const dismiss = () => {
      if (closed) return;
      closed = true;
      box.classList.add('hide');
      setTimeout(() => box.remove(), 280);
    };
    box.addEventListener('click', dismiss);
    ui.toasts.appendChild(box);
    while (ui.toasts.children.length > 5) ui.toasts.firstElementChild.remove();
    setTimeout(dismiss, kind === 'error' ? 5200 : 3800);
  }

  function noteApiSuccess() {
    if (state.networkDown) {
      state.networkDown = false;
      state.recovered = true;
    }
  }

  async function api(path, options) {
    const opts = Object.assign({ headers: {}, cache: 'no-store' }, options || {});
    if (opts.body && typeof opts.body === 'string' && !opts.headers['Content-Type']) {
      opts.headers['Content-Type'] = 'application/json';
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (_err) {
      const err = new Error('Нет связи с сервером');
      err.network = true;
      throw err;
    }
    let data = null;
    try {
      data = await res.json();
    } catch (_err) {
      data = null;
    }
    if (!res.ok || !data || data.ok === false) {
      let message = (data && data.error) || '';
      if (!message) {
        if (res.status === 404) message = 'API недоступен (404)';
        else if (!data) message = 'Сервер вернул некорректный ответ';
        else message = 'Ошибка сервера (' + res.status + ')';
      }
      const err = new Error(message);
      err.status = res.status;
      err.data = data;
      err.network = res.status >= 500;
      throw err;
    }
    noteApiSuccess();
    return data;
  }

  function isOfflineError(err) {
    return !!(err && (err.network || err.status === 404 || err.status >= 500));
  }

  function markOffline() {
    state.networkDown = true;
    setConnection('offline');
  }

  function recoverConnection() {
    if (!state.recovered) return;
    if (Date.now() - state.lastBootstrapAttempt < 5000) return;
    state.recovered = false;
    setConnection('connecting');
    refreshBootstrap(true);
  }

  /* --------------------------------------------------------- тема и настройки */
  function normalizeSettings(raw) {
    const d = defaultSettings();
    const src = raw || {};
    const limits = src.limits || {};
    return {
      theme: src.theme === 'light' ? 'light' : d.theme,
      asr_enabled: src.asr_enabled !== false,
      auto_transcribe: !!src.auto_transcribe,
      asr_model: typeof src.asr_model === 'string' ? src.asr_model : '',
      auto_approve: !!src.auto_approve,
      api_base: typeof src.api_base === 'string' ? src.api_base : '',
      local_api: src.local_api !== false,
      limits: {
        download_mb: Number(limits.download_mb) || 0,
        upload_mb: Number(limits.upload_mb) || 0
      }
    };
  }

  function applyTheme(theme) {
    const light = theme === 'light';
    document.body.classList.toggle('theme-light', light);
    document.body.classList.toggle('theme-dark', !light);
    if (ui.metaTheme) ui.metaTheme.setAttribute('content', light ? '#e9f1f8' : '#0b141a');
    if (ui.themeDark) ui.themeDark.classList.toggle('active', !light);
    if (ui.themeLight) ui.themeLight.classList.toggle('active', light);
    try { localStorage.setItem('tcb_theme', light ? 'light' : 'dark'); } catch (_err) { /* ignore */ }
  }

  function setSwitch(input, checked) {
    if (input) input.checked = !!checked;
  }

  function updateSettingsControls() {
    const s = state.settings;
    setSwitch(ui.asrEnabled, s.asr_enabled);
    setSwitch(ui.autoTranscribe, s.auto_transcribe);
    setSwitch(ui.autoApprove, s.auto_approve);
    if (ui.autoTranscribe) ui.autoTranscribe.disabled = !s.asr_enabled;
    if (ui.asrConfig) ui.asrConfig.hidden = !s.asr_enabled;
    if (ui.asrOffHint) ui.asrOffHint.hidden = s.asr_enabled;
    if (ui.themeDark) ui.themeDark.classList.toggle('active', s.theme !== 'light');
    if (ui.themeLight) ui.themeLight.classList.toggle('active', s.theme === 'light');
    updateAbout();
  }

  function modelTitle(id) {
    const model = state.asrModels.find((m) => m.id === id);
    return model ? (model.title || model.id) : id;
  }

  function updateAbout() {
    const s = state.settings;
    const apiBase = s.api_base || 'не указан';
    if (ui.aboutApi) ui.aboutApi.textContent = apiBase;
    if (ui.aboutApiMode) ui.aboutApiMode.textContent = s.local_api ? 'Локальный Bot API' : 'Облачный Bot API';
    if (ui.aboutDownload) {
      ui.aboutDownload.textContent = s.limits.download_mb > 0
        ? 'до ' + s.limits.download_mb + ' МБ'
        : 'без ограничений';
    }
    if (ui.aboutUpload) {
      ui.aboutUpload.textContent = s.limits.upload_mb > 0
        ? 'до ' + s.limits.upload_mb + ' МБ'
        : 'без ограничений';
    }
    if (ui.aboutAsr) {
      ui.aboutAsr.textContent = s.asr_model
        ? 'включена · ' + modelTitle(s.asr_model)
        : 'включена · модель не выбрана';
    }
    if (ui.aboutAsrRow) ui.aboutAsrRow.hidden = !s.asr_enabled;
  }

  function applySettings(raw) {
    const prevAsr = state.settings.asr_enabled;
    state.settings = normalizeSettings(raw);
    applyTheme(state.settings.theme);
    updateSettingsControls();
    updateEmptyTexts();
    updateComposer();

    if (prevAsr !== state.settings.asr_enabled) {
      if (state.activeId) renderFeed();
      if (state.settings.asr_enabled) {
        if (isModalOpen(ui.modalSettings)) loadAsrModels(true);
      } else {
        if (state.asrTimer) clearTimeout(state.asrTimer);
        state.asrTimer = null;
      }
    } else {
      renderAsr();
    }
  }

  async function saveSetting(key, value) {
    const payload = {};
    payload[key] = value;
    const data = await api('/api/settings', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    if (data && data.settings) applySettings(data.settings);
    return data;
  }

  /* ------------------------------------------------------------- соединение */
  function setConnection(conn) {
    const value = CONNECTION_TEXT[conn] ? conn : 'connecting';
    state.connection = value;
    if (ui.connDot) ui.connDot.className = 'conn-dot ' + value;
    if (ui.connText) ui.connText.textContent = CONNECTION_TEXT[value];
    if (ui.conn) {
      ui.conn.title = value === 'online'
        ? 'Соединение активно'
        : value === 'offline'
          ? 'Нет связи с сервером'
          : 'Подключение к серверу…';
    }
  }

  /* ---------------------------------------------------------------- чаты */
  function getChat(id) {
    return state.chats.find((chat) => chat.id === id) || null;
  }

  function displayName(chat) {
    if (!chat) return 'Чат';
    return chat.title || chat.name || (chat.username ? '@' + chat.username : 'Чат #' + chat.id);
  }

  function chatItemHtml(chat) {
    const active = chat.id === state.activeId;
    const name = displayName(chat);
    const unread = active ? 0 : (Number(chat.unread) || 0);
    const last = plainPreview(chat.last_text) || 'Нет сообщений';
    const badge = unread > 0
      ? '<span class="unread-badge">' + (unread > 99 ? '99+' : unread) + '</span>'
      : '';
    return '<button class="chat-item' + (active ? ' active' : '') + '" type="button" data-chat-id="' + esc(chat.id) + '">' +
      avatarHtml(chat.avatar_url, name, chat.id, 'chat-avatar') +
      '<span class="chat-item-main">' +
        '<span class="chat-item-top">' +
          '<span class="chat-item-name">' + esc(name) + '</span>' +
          '<span class="chat-item-time">' + esc(chatTime(chat.last_date)) + '</span>' +
        '</span>' +
        '<span class="chat-item-bottom">' +
          '<span class="chat-item-last">' + esc(last) + '</span>' +
          badge +
        '</span>' +
      '</span>' +
    '</button>';
  }

  function updateTitle() {
    const total = state.chats.reduce((sum, chat) => {
      if (chat.id === state.activeId) return sum;
      return sum + (Number(chat.unread) || 0);
    }, 0);
    document.title = (total > 0 ? '(' + total + ') ' : '') + APP_NAME + ' — чат';
  }

  function renderChats(force) {
    const query = state.chatSearch.trim().toLowerCase();
    const filtered = state.chats.filter((chat) => {
      if (!query) return true;
      return [displayName(chat), chat.name, chat.title, chat.username, chat.last_text]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .indexOf(query) >= 0;
    }).slice().sort((a, b) => {
      const da = Number(a.last_date) || 0;
      const db = Number(b.last_date) || 0;
      if (da !== db) return db - da;
      return (Number(b.id) || 0) - (Number(a.id) || 0);
    });

    const signature = String(state.activeId) + '|' + query + '|' + filtered.map((chat) =>
      [chat.id, displayName(chat), chat.avatar_url, chat.last_date, chat.last_text, chat.unread, chat.allowed].join('\u0001')
    ).join('\u0002');

    if (!force && signature === state.chatsSignature) {
      updateTitle();
      return;
    }
    state.chatsSignature = signature;

    if (!filtered.length) {
      ui.chatList.hidden = true;
      ui.chatListEmpty.hidden = false;
      const searching = query.length > 0;
      ui.chatListEmptyTitle.textContent = searching ? 'Ничего не найдено' : 'Пока нет чатов';
      ui.chatListEmptyText.textContent = searching
        ? 'Попробуйте изменить запрос.'
        : 'Начните чат: напишите боту /start в Telegram.';
    } else {
      ui.chatList.hidden = false;
      ui.chatListEmpty.hidden = true;
      ui.chatList.innerHTML = filtered.map(chatItemHtml).join('');
    }
    updateTitle();
  }

  function renderSettingsUsers(force) {
    if (!ui.settingsUsers) return;
    const signature = state.chats.map((chat) => [
      chat.id, displayName(chat), chat.username, chat.avatar_url, chat.allowed, chat.name
    ].join('\u0001')).join('\u0002');
    if (!force && signature === state.usersSignature) return;
    state.usersSignature = signature;

    if (!state.chats.length) {
      ui.settingsUsers.innerHTML = '<div class="list-empty">Пока нет добавленных пользователей.</div>';
      return;
    }

    const sorted = state.chats.slice().sort((a, b) => displayName(a).localeCompare(displayName(b), 'ru'));
    ui.settingsUsers.innerHTML = sorted.map((chat) => {
      const name = displayName(chat);
      const bits = [];
      if (chat.username) bits.push('@' + chat.username);
      bits.push('ID ' + chat.id);
      bits.push(chat.allowed ? 'в поддержке' : 'не в поддержке');
      return '<div class="user-row" data-user-chat="' + esc(chat.id) + '">' +
        avatarHtml(chat.avatar_url, name, chat.id, 'avatar-sm') +
        '<div class="user-main">' +
          '<div class="user-name">' + esc(name) + '</div>' +
          '<div class="user-sub">' + esc(bits.join(' · ')) + '</div>' +
        '</div>' +
        '<div class="user-actions">' +
          '<button class="btn ghost small" type="button" data-remove-chat="' + esc(chat.id) + '"' +
            (chat.allowed ? '' : ' disabled') + '>Убрать из поддержки</button>' +
          '<button class="btn danger small" type="button" data-delete-chat="' + esc(chat.id) + '">Удалить чат локально</button>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  function setChats(chats) {
    state.chats = (Array.isArray(chats) ? chats : []).filter((chat) => chat && chat.id != null);

    if (state.activeId && !getChat(state.activeId)) {
      clearActiveChat();
    }
    if (state.activeId) {
      const current = getChat(state.activeId);
      if (current) current.unread = 0;
    }
    if (!state.activeId && state.chats.length) {
      selectChat(state.chats[0].id);
      return;
    }

    renderChats(true);
    renderSettingsUsers();
    updateChatHeader();
    updateOverlays();
    updateEmptyTexts();
    updateTitle();
  }

  function saveDraft() {
    if (!state.activeId) return;
    state.drafts.set(state.activeId, ui.composerInput.value);
    state.draftFiles.set(state.activeId, state.pending.slice());
  }

  function restoreDraft(id) {
    ui.composerInput.value = state.drafts.get(id) || '';
    state.pending = (state.draftFiles.get(id) || []).slice();
    renderChips();
    autosize();
    updateComposer();
  }

  function clearActiveChat() {
    state.activeId = null;
    state.messages.clear();
    state.rev = 0;
    state.hasOlder = false;
    state.loadingMessages = false;
    state.loadingOlder = false;
    state.loadToken += 1;
    state.unread = 0;
    state.stick = true;
    ui.feed.innerHTML = '';
    ui.composerInput.value = '';
    state.pending = [];
    renderChips();
    hideScrollDown();
    updateChatHeader();
    updateOverlays();
    updateComposer();
    updateLoadOlder();
  }

  function selectChat(id) {
    const chatId = Number(id);
    const chat = getChat(chatId);
    if (!chat) return;

    if (state.activeId === chatId) {
      chat.unread = 0;
      renderChats(true);
      updateTitle();
      closeSidebar();
      return;
    }

    saveDraft();
    state.activeId = chatId;
    chat.unread = 0;
    state.messages.clear();
    state.rev = 0;
    state.hasOlder = false;
    state.loadingOlder = false;
    state.loadingMessages = true;
    state.loadToken += 1;
    state.unread = 0;
    state.stick = true;
    ui.feed.innerHTML = '';
    hideScrollDown();
    restoreDraft(chatId);
    updateChatHeader();
    renderChats(true);
    updateEmptyTexts();
    updateOverlays();
    updateComposer();
    closeSidebar();
    loadInitialMessages(chatId, state.loadToken);
  }

  function touchChat(chatId, text, date) {
    const chat = getChat(chatId);
    if (!chat) return;
    chat.last_text = plainPreview(text) || 'Сообщение';
    chat.last_date = Number(date) || Math.floor(Date.now() / 1000);
    renderChats(true);
  }

  function refreshChatsSoon() {
    if (state.refreshTimer) clearTimeout(state.refreshTimer);
    state.refreshTimer = setTimeout(() => {
      state.refreshTimer = null;
      refreshChats(true);
    }, 350);
  }

  async function refreshChats(silent) {
    try {
      const data = await api('/api/chats');
      if (data && Array.isArray(data.chats)) setChats(data.chats);
      if (state.recovered) recoverConnection();
    } catch (err) {
      if (isOfflineError(err)) markOffline();
      if (!silent) {
        // действия, инициированные пользователем, сообщают об ошибке сами
      }
    }
  }

  /* --------------------------------------------------------- шапка и пустота */
  function updateChatHeader() {
    const chat = getChat(state.activeId);
    if (!chat) {
      const bot = state.bot || {};
      setAvatar(ui.peerAvatar, bot.avatar_url, bot.name || APP_NAME, 'bot', 'avatar-head', true);
      ui.peerName.textContent = 'Выберите чат';
      ui.peerSub.textContent = bot.username ? '@' + bot.username : APP_NAME;
      return;
    }
    const name = displayName(chat);
    setAvatar(ui.peerAvatar, chat.avatar_url, name, chat.id, 'avatar-head', false);
    ui.peerName.textContent = name;
    if (chat.username) ui.peerSub.textContent = '@' + chat.username;
    else if (chat.name && chat.name !== name) ui.peerSub.textContent = chat.name;
    else ui.peerSub.textContent = 'ID ' + chat.id;
  }

  function updateEmptyTexts() {
    const bot = state.bot || {};
    const mention = bot.username ? '@' + bot.username : '';
    const hint = 'Напишите боту ' + (mention ? mention + ' ' : '') +
      'команду /start — после этого переписка появится здесь.';

    if (state.chats.length) {
      ui.noChatTitle.textContent = 'Выберите чат';
      ui.noChatText.textContent = 'Откройте переписку в списке слева или найдите пользователя, который уже писал боту.';
    } else {
      ui.noChatTitle.textContent = 'Начните чат';
      ui.noChatText.textContent = hint;
    }
    ui.chatEmptyText.textContent = hint;
  }

  function updateOverlays() {
    const hasChat = !!state.activeId;
    ui.noChat.hidden = hasChat;
    ui.chatEmpty.hidden = !hasChat || state.loadingMessages || state.messages.size > 0;
    ui.messagesLoading.hidden = !hasChat || !state.loadingMessages;
    ui.composerEl.classList.toggle('is-disabled', !hasChat);
    updateLoadOlder();
  }

  function updateComposer() {
    const hasChat = !!state.activeId;
    ui.composerInput.disabled = !hasChat;
    ui.btnAttach.disabled = !hasChat;
    ui.btnSend.disabled = !hasChat || state.sending ||
      (!ui.composerInput.value.trim() && state.pending.length === 0);
    ui.composerInput.placeholder = hasChat
      ? 'Написать сообщение…'
      : 'Выберите чат, чтобы написать сообщение';
  }

  function setApiUnavailable() {
    setConnection('offline');
    if (state.bootstrapped) return;
    ui.chatList.hidden = true;
    ui.chatListEmpty.hidden = false;
    ui.chatListEmptyTitle.textContent = 'Нет связи с сервером';
    ui.chatListEmptyText.textContent = 'Проверьте, что бэкенд запущен и API доступен по этому адресу.';
    ui.noChat.hidden = false;
    ui.noChatTitle.textContent = 'Нет связи с сервером';
    ui.noChatText.textContent = 'Не удалось загрузить чаты. Проверьте подключение к API и обновите страницу.';
  }

  async function refreshConnection() {
    if (document.hidden) return;
    try {
      const serverState = await api('/api/state');
      setConnection(serverState.connection || 'online');
    } catch (err) {
      if (isOfflineError(err)) setConnection('offline');
    }
  }

  async function refreshBootstrap(silent) {
    state.lastBootstrapAttempt = Date.now();
    try {
      const data = await api('/api/bootstrap');
      state.bootstrapped = true;
      state.bootErrorShown = false;
      state.recovered = false;
      if (data.settings) applySettings(data.settings);
      const serverState = data.state || {};
      if (serverState.bot) state.bot = serverState.bot;
      setConnection(serverState.connection || 'online');
      if (Array.isArray(data.chats)) setChats(data.chats);
      updateEmptyTexts();
      updateChatHeader();
      updateOverlays();
    } catch (err) {
      if (isOfflineError(err)) {
        state.networkDown = true;
        setConnection('offline');
      }
      if (!state.bootstrapped) setApiUnavailable();
      if (!silent && !state.bootErrorShown) {
        state.bootErrorShown = true;
        toast('Не удалось загрузить данные: ' + err.message, 'error');
      }
    }
  }

  /* -------------------------------------------------------------- сообщения */
  function messageSortValue(msg) {
    if (msg.temp) return 1e15 + (Number(msg.seq) || 0);
    return Number(msg.id) || 0;
  }

  function compareMessages(a, b) {
    const da = Number(a.date) || 0;
    const db = Number(b.date) || 0;
    if (da !== db) return da - db;
    return messageSortValue(a) - messageSortValue(b);
  }

  function sortedMessages() {
    return Array.from(state.messages.values()).sort(compareMessages);
  }

  function mediaSrc(msg) {
    const rev = Number(msg.rev) || 0;
    return '/media/' + encodeURIComponent(msg.id) + (rev ? '?v=' + rev : '');
  }

  function mediaDownloadUrl(id) {
    return '/media/' + encodeURIComponent(id) + '?download=1';
  }

  function downloadAttrs(msg) {
    const media = msg.media || {};
    const name = media.file_name || media.title || '';
    return (name ? ' download="' + esc(name) + '"' : ' download') +
      ' target="_blank" rel="noopener"';
  }

  function downloadLink(msg, className, label) {
    return '<a class="' + className + '" href="' + mediaDownloadUrl(msg.id) + '"' +
      downloadAttrs(msg) + ' title="' + esc(label || 'Скачать') + '" aria-label="' + esc(label || 'Скачать') + '">' +
      icon('download') + '</a>';
  }

  function kindText(kind) {
    const map = {
      photo: 'фото',
      video: 'видео',
      animation: 'анимацию',
      voice: 'голосовое',
      audio: 'аудио',
      document: 'файл',
      sticker: 'стикер',
      video_note: 'видеосообщение'
    };
    return map[kind] || 'файл';
  }

  function missingPlaceholder(msg, text, failed) {
    const retry = isNumericId(msg.id)
      ? '<button class="retry-btn" type="button" data-retry-media="' + esc(msg.id) + '">' +
          (failed ? 'Повторить' : 'Загрузить') + '</button>'
      : '';
    return '<div class="media-placeholder">' +
      (failed ? icon('warning') : '<span class="spinner"></span>') +
      '<span>' + esc(text) + '</span>' + retry +
    '</div>';
  }

  function uploadCard(msg) {
    const media = msg.media || {};
    const name = media.file_name || 'Файл';
    return '<div class="upload-card" data-upload="' + esc(msg.id) + '">' +
      '<div class="upload-row">' +
        '<span class="spinner tiny"></span>' +
        '<span class="upload-name">' + esc(name) + '</span>' +
        '<span class="upload-pct">' + Math.round(progressPct(msg.progress)) + '%</span>' +
      '</div>' +
      '<div class="progress"><i style="width:' + progressPct(msg.progress) + '%"></i></div>' +
    '</div>';
  }

  function fileIcon(mime, name) {
    const type = String(mime || '');
    const lower = String(name || '').toLowerCase();
    if (type.indexOf('image/') === 0 || /\.(png|jpe?g|webp|gif|bmp|heic)$/.test(lower)) return 'image';
    if (type.indexOf('video/') === 0 || /\.(mp4|webm|mov|mkv|avi)$/.test(lower)) return 'video';
    if (type.indexOf('audio/') === 0 || /\.(mp3|ogg|wav|m4a|flac|opus)$/.test(lower)) return 'music';
    return 'doc';
  }

  function audioPlayerHtml(msg) {
    const media = msg.media || {};
    const title = media.title || media.performer || media.file_name ||
      (msg.kind === 'voice' ? 'Голосовое сообщение' : 'Аудио');
    const duration = Number(media.duration) || 0;
    const bars = [];
    for (let i = 0; i < 26; i += 1) {
      const height = 26 + ((i * 37 + 17) % 62);
      bars.push('<i style="height:' + height + '%"></i>');
    }
    return '<div class="audio-card" data-audio="' + esc(msg.id) + '">' +
      '<button class="audio-btn" type="button" title="Воспроизвести" aria-label="Воспроизвести">' + icon('play') + '</button>' +
      '<div class="audio-main">' +
        '<div class="audio-title">' + esc(title) + '</div>' +
        '<div class="wave">' + bars.join('') + '</div>' +
      '</div>' +
      '<span class="audio-dur">' + fmtDuration(duration) + '</span>' +
      downloadLink(msg, 'audio-dl', 'Скачать аудио') +
      '<audio preload="metadata" src="' + mediaSrc(msg) + '"></audio>' +
    '</div>';
  }

  function photoHtml(msg, label) {
    const src = mediaSrc(msg);
    return '<div class="media photo-media">' +
      '<img class="photo" src="' + esc(src) + '" data-full="' + esc(src) +
        '" data-download="' + esc(mediaDownloadUrl(msg.id)) + '" alt="' + esc(label || 'Фото') +
        '" loading="lazy">' +
      downloadLink(msg, 'media-dl', 'Скачать изображение') +
    '</div>';
  }

  function videoHtml(msg, animation) {
    const src = mediaSrc(msg);
    const attrs = animation
      ? ' autoplay loop muted playsinline preload="metadata"'
      : ' controls playsinline preload="metadata"';
    return '<div class="media video-media">' +
      '<video' + attrs + ' src="' + esc(src) + '"></video>' +
      downloadLink(msg, 'media-dl', 'Скачать видео') +
    '</div>';
  }

  function buildMedia(msg) {
    const kind = msg.kind || 'text';
    if (kind === 'text') return null;
    if (msg.uploading) return uploadCard(msg);

    const media = msg.media || {};
    const name = media.file_name || media.title || '';

    if (!msg.local) {
      if (msg.error) {
        return missingPlaceholder(msg, 'Не удалось загрузить ' + kindText(kind) +
          (name ? ': ' + name : ''), true);
      }
      const label = 'Загрузка ' + kindText(kind) + (name ? ': ' + name : '') + '…';
      return missingPlaceholder(msg, label, false);
    }

    if (kind === 'photo') {
      return photoHtml(msg, 'Фото');
    }
    if (kind === 'video') {
      return videoHtml(msg, false);
    }
    if (kind === 'video_note') {
      return '<div class="media video-note">' +
        '<video controls autoplay loop muted playsinline preload="metadata" src="' + esc(mediaSrc(msg)) + '"></video>' +
        downloadLink(msg, 'media-dl', 'Скачать видеосообщение') +
      '</div>';
    }
    if (kind === 'animation') {
      const isGif = /gif/i.test(String(media.mime_type || '')) || /\.gif$/i.test(name);
      if (isGif) return photoHtml(msg, 'GIF');
      return videoHtml(msg, true);
    }
    if (kind === 'sticker') {
      return '<div class="media sticker">' +
        '<img src="' + esc(mediaSrc(msg)) + '" alt="Стикер" loading="lazy">' +
        downloadLink(msg, 'media-dl', 'Скачать стикер') +
      '</div>';
    }
    if (kind === 'audio' || kind === 'voice') {
      return audioPlayerHtml(msg);
    }
    if (kind === 'document') {
      const size = fmtSize(media.file_size);
      return '<div class="file-card">' +
        '<span class="file-ico">' + icon(fileIcon(media.mime_type, name)) + '</span>' +
        '<span class="file-main">' +
          '<span class="file-name">' + esc(name || 'Файл') + '</span>' +
          '<span class="file-size">' + esc(size || 'файл') + '</span>' +
        '</span>' +
        downloadLink(msg, 'file-dl', 'Скачать файл') +
      '</div>';
    }
    if (media.is_image) return photoHtml(msg, 'Изображение');
    return missingPlaceholder(msg, 'Вложение', false);
  }

  function buildTranscript(msg) {
    if (!state.settings.asr_enabled) return null;
    if (msg.kind !== 'voice' && msg.kind !== 'audio') return null;
    if (!msg.local && !msg.transcript) return null;

    const wrap = document.createElement('div');
    wrap.className = 'tr';

    if (msg.transcript) {
      const head = document.createElement('div');
      head.className = 'tr-head';
      const label = document.createElement('span');
      label.textContent = 'Расшифровка';
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'tr-toggle';
      toggle.textContent = 'Скрыть';
      head.appendChild(label);
      head.appendChild(toggle);

      const body = document.createElement('div');
      body.className = 'tr-body';
      body.textContent = msg.transcript;

      toggle.addEventListener('click', () => {
        body.hidden = !body.hidden;
        toggle.textContent = body.hidden ? 'Показать' : 'Скрыть';
      });

      wrap.appendChild(head);
      wrap.appendChild(body);
      return wrap;
    }

    const tstate = msg.transcript_state || '';
    const busy = state.transcribing.has(msg.id) || tstate === 'queued' || tstate === 'running';
    const label = tstate === 'queued'
      ? 'В очереди…'
      : busy
        ? 'Расшифровка…'
        : tstate === 'error'
          ? 'Повторить'
          : 'Расшифровать';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tr-btn';
    button.dataset.transcribe = String(msg.id);
    button.title = 'Распознать речь';
    button.disabled = busy;
    button.innerHTML = icon('text') + '<span>' + label + '</span>';
    wrap.appendChild(button);

    if (tstate === 'error' && msg.transcript_error) {
      const error = document.createElement('div');
      error.className = 'tr-error';
      error.textContent = msg.transcript_error;
      wrap.appendChild(error);
    }
    return wrap;
  }

  function statusTick(msg) {
    if (msg.status === 'failed') {
      return '<span class="tick fail" title="Не отправлено">' + icon('warning') + '</span>';
    }
    if (msg.status === 'pending') {
      return '<span class="tick" title="Отправляется"><span class="spinner tiny"></span></span>';
    }
    return '<span class="tick" title="Отправлено">' + icon('check') + '</span>';
  }

  function buildRow(msg) {
    const row = document.createElement('div');
    row.className = 'row ' + (msg.dir === 'out' ? 'out' : 'in');
    row.dataset.id = String(msg.id);
    row.dataset.date = String(Number(msg.date) || 0);
    row.dataset.day = dayKey(msg.date);
    row.dataset.dir = msg.dir || 'in';
    row.dataset.rev = String(msg.rev || 0);
    if (msg.temp) row.dataset.temp = '1';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    if (msg.status === 'failed' || msg.error) bubble.classList.add('error');

    if (msg.fwd) {
      const fwd = document.createElement('div');
      fwd.className = 'fwd';
      const isChannel = msg.fwd.type === 'channel' || msg.fwd.type === 'chat';
      const label = isChannel
        ? 'Переслано из: «' + (msg.fwd.name || 'канала') + '»'
        : 'Переслано от: ' + (msg.fwd.name || 'пользователя');
      fwd.innerHTML = icon('forward') + '<span>' + esc(label) + '</span>' +
        (msg.fwd.username && !isChannel ? '<span class="fwd-user">@' + esc(msg.fwd.username) + '</span>' : '');
      bubble.appendChild(fwd);
    }

    const media = buildMedia(msg);
    if (media) {
      const holder = document.createElement('div');
      holder.innerHTML = media;
      const first = holder.firstElementChild;
      if (first) bubble.appendChild(first);
    }

    const content = String(msg.caption || msg.text || '').trim();
    if (content) {
      const body = document.createElement('div');
      body.className = 'body';
      body.innerHTML = renderMarkdown(content);
      bubble.appendChild(body);
    } else if (!media && msg.kind === 'text') {
      const body = document.createElement('div');
      body.className = 'body';
      body.textContent = '—';
      bubble.appendChild(body);
    }

    const transcript = buildTranscript(msg);
    if (transcript) bubble.appendChild(transcript);
    if (media && !content && !transcript) bubble.classList.add('media-only');

    const meta = document.createElement('div');
    meta.className = 'meta';
    if (msg.edited) {
      const edited = document.createElement('span');
      edited.className = 'edited';
      edited.textContent = 'изм.';
      meta.appendChild(edited);
    }
    if (msg.dir === 'out') {
      const tick = document.createElement('span');
      tick.innerHTML = statusTick(msg);
      if (tick.firstChild) meta.appendChild(tick.firstChild);
    }
    const time = document.createElement('span');
    time.className = 'time';
    time.textContent = fmtTime(msg.date);
    meta.appendChild(time);
    bubble.appendChild(meta);

    if (msg.error) {
      const error = document.createElement('div');
      error.className = 'msg-error';
      error.textContent = msg.error;
      bubble.appendChild(error);
    }

    row.appendChild(bubble);
    return row;
  }

  function dayChip(ts) {
    const chip = document.createElement('div');
    chip.className = 'day-chip';
    chip.dataset.day = dayKey(ts);
    chip.textContent = dayLabel(ts);
    return chip;
  }

  function initAudioPlayers(root) {
    $$('[data-audio]', root).forEach((card) => {
      if (card.dataset.audioReady) return;
      card.dataset.audioReady = '1';
      const audio = $('audio', card);
      const button = $('.audio-btn', card);
      const wave = $('.wave', card);
      const duration = $('.audio-dur', card);
      const bars = $$('i', wave);
      if (!audio || !button || !wave) return;

      const setIcon = (playing) => {
        button.innerHTML = icon(playing ? 'pause' : 'play');
        button.title = playing ? 'Пауза' : 'Воспроизвести';
        button.setAttribute('aria-label', playing ? 'Пауза' : 'Воспроизвести');
      };
      const paint = () => {
        const total = audio.duration || 0;
        const ratio = total ? Math.min(1, audio.currentTime / total) : 0;
        bars.forEach((bar, i) => bar.classList.toggle('on', i / bars.length < ratio));
      };

      audio.addEventListener('loadedmetadata', () => {
        if (isFinite(audio.duration) && audio.duration > 0 && duration) {
          duration.textContent = fmtDuration(audio.duration);
        }
      });
      audio.addEventListener('timeupdate', paint);
      audio.addEventListener('play', () => setIcon(true));
      audio.addEventListener('pause', () => setIcon(false));
      audio.addEventListener('ended', () => {
        setIcon(false);
        paint();
        audio.currentTime = 0;
        if (duration && isFinite(audio.duration)) duration.textContent = fmtDuration(audio.duration);
      });

      button.addEventListener('click', () => {
        if (audio.paused) {
          $$('audio').forEach((other) => {
            if (other !== audio) other.pause();
          });
          const played = audio.play();
          if (played && played.catch) played.catch(() => {});
        } else {
          audio.pause();
        }
      });

      wave.addEventListener('click', (event) => {
        const rect = wave.getBoundingClientRect();
        if (!rect.width) return;
        const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
        if (isFinite(audio.duration) && audio.duration > 0) {
          audio.currentTime = ratio * audio.duration;
          paint();
        }
      });
    });
  }

  function refreshGrouping() {
    const rows = $$('.row', ui.feed);
    rows.forEach((row, index) => {
      const prev = rows[index - 1];
      const next = rows[index + 1];
      const prevOk = prev && prev.dataset.day === row.dataset.day &&
        prev.dataset.dir === row.dataset.dir &&
        Math.abs(Number(row.dataset.date) - Number(prev.dataset.date)) < 300;
      const nextOk = next && next.dataset.day === row.dataset.day &&
        next.dataset.dir === row.dataset.dir &&
        Math.abs(Number(next.dataset.date) - Number(row.dataset.date)) < 300;
      row.classList.toggle('g-first', !prevOk);
      row.classList.toggle('g-last', !nextOk);
    });
  }

  function updateLoadOlder() {
    const visible = !!state.activeId && state.hasOlder;
    ui.loadOlderWrap.hidden = !visible;
    ui.loadOlder.disabled = state.loadingOlder;
    ui.loadOlderSpin.hidden = !state.loadingOlder;
    ui.loadOlderLabel.textContent = state.loadingOlder ? 'Загрузка…' : 'Загрузить раньше';
  }

  function renderFeed() {
    ui.feed.innerHTML = '';
    let day = '';
    sortedMessages().forEach((msg) => {
      const key = dayKey(msg.date);
      if (key !== day) {
        ui.feed.appendChild(dayChip(msg.date));
        day = key;
      }
      ui.feed.appendChild(buildRow(msg));
    });
    initAudioPlayers(ui.feed);
    refreshGrouping();
    updateLoadOlder();
    updateOverlays();
  }

  function appendMessageRow(msg) {
    const rows = $$('.row', ui.feed);
    const last = rows[rows.length - 1];
    if (last) {
      const lastDate = Number(last.dataset.date) || 0;
      const lastId = last.dataset.temp ? 1e15 : (Number(last.dataset.id) || 0);
      const date = Number(msg.date) || 0;
      const sortId = messageSortValue(msg);
      if (date < lastDate || (date === lastDate && sortId < lastId)) {
        const height = ui.messages.scrollHeight;
        const top = ui.messages.scrollTop;
        renderFeed();
        ui.messages.scrollTop = top + (ui.messages.scrollHeight - height);
        return false;
      }
    }
    if (!last || last.dataset.day !== dayKey(msg.date)) {
      ui.feed.appendChild(dayChip(msg.date));
    }
    const row = buildRow(msg);
    ui.feed.appendChild(row);
    initAudioPlayers(row);
    refreshGrouping();
    updateLoadOlder();
    updateOverlays();
    return true;
  }

  function updateMessageRow(msg) {
    const row = ui.feed.querySelector('.row[data-id="' + String(msg.id).replace(/["\\]/g, '\\$&') + '"]');
    if (!row) return;
    const replacement = buildRow(msg);
    row.replaceWith(replacement);
    initAudioPlayers(replacement);
    refreshGrouping();
    if (state.stick) {
      requestAnimationFrame(() => {
        if (state.stick) setScrollTop(ui.messages.scrollHeight);
      });
    }
  }

  function flashRow(id) {
    const row = ui.feed.querySelector('.row[data-id="' + String(id).replace(/["\\]/g, '\\$&') + '"]');
    if (!row) return;
    row.classList.add('flash');
    setTimeout(() => row.classList.remove('flash'), 1600);
  }

  function updateChatFromMessage(msg) {
    const chat = getChat(state.activeId);
    if (!chat) return;
    chat.last_text = plainPreview(msg.text || msg.caption || kindText(msg.kind)) || 'Сообщение';
    chat.last_date = Number(msg.date) || chat.last_date;
    renderChats(true);
  }

  function mergeMessage(msg, wasBottom) {
    if (!msg || msg.id == null) return;
    const known = state.messages.get(msg.id);
    if (known) {
      state.messages.set(msg.id, msg);
      updateMessageRow(msg);
      return;
    }
    state.messages.set(msg.id, msg);
    const appended = appendMessageRow(msg);
    if (appended) {
      updateChatFromMessage(msg);
      if (msg.dir === 'in') {
        flashRow(msg.id);
        if (wasBottom === false) {
          state.unread += 1;
          showScrollDown();
        }
      }
      if (wasBottom) scrollBottom(false);
    }
  }

  /* ------------------------------------------------------------- скролл */
  function isNearBottom() {
    return ui.messages.scrollHeight - ui.messages.scrollTop - ui.messages.clientHeight < 150;
  }

  function setScrollTop(value) {
    state.autoScroll = true;
    ui.messages.scrollTop = value;
    requestAnimationFrame(() => {
      state.autoScroll = false;
    });
  }

  function hideScrollDown() {
    ui.scrollDown.hidden = true;
    ui.scrollBadge.hidden = true;
    ui.scrollBadge.textContent = '0';
  }

  function showScrollDown() {
    ui.scrollDown.hidden = false;
    if (state.unread > 0) {
      ui.scrollBadge.hidden = false;
      ui.scrollBadge.textContent = state.unread > 99 ? '99+' : String(state.unread);
    } else {
      ui.scrollBadge.hidden = true;
    }
  }

  function scrollBottom(smooth) {
    state.stick = true;
    if (smooth && ui.messages.scrollTo) {
      state.autoScroll = true;
      ui.messages.scrollTo({ top: ui.messages.scrollHeight, behavior: 'smooth' });
      setTimeout(() => { state.autoScroll = false; }, 450);
    } else {
      setScrollTop(ui.messages.scrollHeight);
    }
    state.unread = 0;
    hideScrollDown();
  }

  async function loadInitialMessages(chatId, token) {
    try {
      const data = await api('/api/messages?chat_id=' + encodeURIComponent(chatId) +
        '&rev=0&before_id=0');
      if (state.activeId !== chatId || state.loadToken !== token) return;
      state.messages.clear();
      (data.messages || []).forEach((msg) => state.messages.set(msg.id, msg));
      state.rev = Number(data.rev) || 0;
      state.hasOlder = !!data.has_older;
      state.loadingMessages = false;
      renderFeed();
      requestAnimationFrame(() => scrollBottom(false));
      if (state.recovered) recoverConnection();
    } catch (err) {
      if (state.activeId !== chatId || state.loadToken !== token) return;
      state.loadingMessages = false;
      updateOverlays();
      toast('Не удалось загрузить сообщения: ' + err.message, 'error');
      if (isOfflineError(err)) markOffline();
    }
  }

  async function loadOlder() {
    if (!state.activeId || !state.hasOlder || state.loadingOlder || state.loadingMessages) return;
    const chatId = state.activeId;
    const token = state.loadToken;
    const firstRow = ui.feed.querySelector('.row');
    if (!firstRow) return;

    state.loadingOlder = true;
    state.stick = false;
    updateLoadOlder();

    try {
      const data = await api('/api/messages?chat_id=' + encodeURIComponent(chatId) +
        '&rev=0&before_id=' + encodeURIComponent(firstRow.dataset.id));
      if (state.activeId !== chatId || state.loadToken !== token) return;
      const messages = (data.messages || [])
        .filter((msg) => !state.messages.has(msg.id))
        .sort(compareMessages);
      state.hasOlder = !!data.has_older && messages.length > 0;

      if (!messages.length) {
        updateLoadOlder();
        return;
      }

      const currentFirst = ui.feed.querySelector('.row');
      if (!currentFirst) {
        messages.forEach((msg) => state.messages.set(msg.id, msg));
        renderFeed();
        return;
      }

      const firstDay = currentFirst.dataset.day;
      const prevHeight = ui.messages.scrollHeight;
      const prevTop = ui.messages.scrollTop;
      const fragment = document.createDocumentFragment();
      let day = '';
      messages.forEach((msg) => {
        state.messages.set(msg.id, msg);
        const key = dayKey(msg.date);
        if (key !== day) {
          fragment.appendChild(dayChip(msg.date));
          day = key;
        }
        fragment.appendChild(buildRow(msg));
      });

      if (day && day === firstDay) {
        const chip = currentFirst.previousElementSibling;
        if (chip && chip.classList.contains('day-chip')) chip.remove();
      }

      ui.feed.insertBefore(fragment, ui.feed.firstChild);
      initAudioPlayers(ui.feed);
      refreshGrouping();
      setScrollTop(prevTop + (ui.messages.scrollHeight - prevHeight));
      state.olderCooldownUntil = Date.now() + 600;
    } catch (err) {
      toast('Не удалось загрузить историю: ' + err.message, 'error');
      if (isOfflineError(err)) markOffline();
    } finally {
      if (state.activeId === chatId && state.loadToken === token) {
        state.loadingOlder = false;
        updateLoadOlder();
      }
    }
  }

  async function pollActive() {
    if (document.hidden || !state.activeId || state.polling || state.loadingMessages) return;
    const chatId = state.activeId;
    state.polling = true;
    try {
      const data = await api('/api/messages?chat_id=' + encodeURIComponent(chatId) +
        '&rev=' + encodeURIComponent(state.rev) + '&before_id=0');
      if (state.activeId !== chatId) return;
      if (typeof data.rev === 'number') state.rev = data.rev;
      const arrived = data.messages || [];
      if (arrived.length) {
        const wasBottom = isNearBottom();
        arrived.forEach((msg) => mergeMessage(msg, wasBottom));
        if (wasBottom) scrollBottom(false);
      }
      if (state.recovered) recoverConnection();
    } catch (err) {
      if (isOfflineError(err)) markOffline();
    } finally {
      state.polling = false;
    }
  }

  /* ---------------------------------------------------------------- отправка */
  function autosize() {
    ui.composerInput.style.height = 'auto';
    ui.composerInput.style.height = Math.min(ui.composerInput.scrollHeight, 160) + 'px';
    if (state.stick) {
      requestAnimationFrame(() => {
        if (state.stick) setScrollTop(ui.messages.scrollHeight);
      });
    }
  }

  function renderChips() {
    ui.attachBar.innerHTML = '';
    if (!state.pending.length) {
      ui.attachBar.hidden = true;
      updateComposer();
      return;
    }
    ui.attachBar.hidden = false;
    state.pending.forEach((file, index) => {
      const chip = document.createElement('div');
      chip.className = 'chip';

      if (file.type && file.type.indexOf('image/') === 0) {
        const img = document.createElement('img');
        img.alt = '';
        const url = URL.createObjectURL(file);
        img.src = url;
        img.onload = () => URL.revokeObjectURL(url);
        chip.appendChild(img);
      } else {
        const thumb = document.createElement('div');
        thumb.className = 'chip-ico';
        thumb.innerHTML = icon(fileIcon(file.type, file.name));
        chip.appendChild(thumb);
      }

      const main = document.createElement('div');
      main.className = 'chip-main';
      const name = document.createElement('div');
      name.className = 'chip-name';
      name.textContent = file.name;
      const size = document.createElement('div');
      size.className = 'chip-size';
      size.textContent = fmtSize(file.size) || 'файл';
      main.appendChild(name);
      main.appendChild(size);
      chip.appendChild(main);

      const remove = document.createElement('button');
      remove.className = 'chip-x';
      remove.type = 'button';
      remove.title = 'Убрать';
      remove.innerHTML = icon('close');
      remove.addEventListener('click', () => {
        state.pending.splice(index, 1);
        renderChips();
        autosize();
      });
      chip.appendChild(remove);
      ui.attachBar.appendChild(chip);
    });
    updateComposer();
  }

  function addFiles(files) {
    if (!state.activeId) {
      toast('Сначала выберите чат', 'error');
      return;
    }
    const limit = Number(state.settings.limits.upload_mb) || 0;
    Array.from(files || []).forEach((file) => {
      if (!file || !file.size) return;
      if (limit > 0 && file.size > limit * 1024 * 1024) {
        toast('«' + file.name + '» больше ' + limit + ' МБ — не помещается в лимит загрузки', 'error');
        return;
      }
      state.pending.push(file);
    });
    renderChips();
    autosize();
    ui.composerInput.focus();
  }

  function uploadKind(file) {
    const type = String(file.type || '');
    if (type.indexOf('image/') === 0) return 'photo';
    if (type.indexOf('video/') === 0) return 'video';
    if (type.indexOf('audio/') === 0) return 'audio';
    return 'document';
  }

  function addTempMessage(overrides) {
    const seq = ++state.tempSeq;
    const id = 'tmp-' + seq;
    const msg = Object.assign({
      id: id,
      seq: seq,
      chat_id: state.activeId,
      dir: 'out',
      date: Math.floor(Date.now() / 1000),
      text: '',
      caption: '',
      kind: 'text',
      media: null,
      local: true,
      transcript: '',
      transcript_state: '',
      transcript_error: '',
      edited: false,
      status: 'pending',
      error: null,
      rev: 0,
      temp: true
    }, overrides || {});
    state.messages.set(id, msg);
    appendMessageRow(msg);
    if (state.stick) scrollBottom(false);

    return {
      id: id,
      msg: msg,
      setProgress(p) {
        const value = progressPct(p);
        msg.progress = value;
        const card = ui.feed.querySelector('[data-upload="' + id + '"]');
        if (!card) return;
        const bar = $('.progress > i', card);
        const pct = $('.upload-pct', card);
        if (bar) bar.style.width = value + '%';
        if (pct) pct.textContent = Math.round(value) + '%';
      },
      remove() {
        state.messages.delete(id);
        const row = ui.feed.querySelector('.row[data-id="' + id + '"]');
        if (row) row.remove();
        refreshGrouping();
        updateOverlays();
      },
      fail(message) {
        msg.uploading = false;
        msg.status = 'failed';
        msg.error = message;
        state.messages.set(id, msg);
        updateMessageRow(msg);
      }
    };
  }

  async function handleSend() {
    if (!state.activeId || state.sending) return;
    const chatId = state.activeId;
    const text = ui.composerInput.value.trim();
    const files = state.pending.slice();
    if (!text && !files.length) return;

    if (files.length) {
      uploadFiles(chatId, files, text);
      return;
    }

    state.sending = true;
    ui.composerInput.value = '';
    autosize();
    updateComposer();
    const temp = addTempMessage({ text: text, kind: 'text' });

    try {
      const data = await api('/api/send', {
        method: 'POST',
        body: JSON.stringify({ chat_id: chatId, text: text })
      });
      temp.remove();
      (data.messages || []).forEach((msg) => {
        if (state.activeId === chatId) mergeMessage(msg, isNearBottom());
      });
      touchChat(chatId, text, Math.floor(Date.now() / 1000));
      state.drafts.delete(chatId);
      state.draftFiles.delete(chatId);
      refreshChatsSoon();
    } catch (err) {
      temp.remove();
      if (state.activeId === chatId && !ui.composerInput.value.trim()) {
        ui.composerInput.value = text;
        autosize();
      }
      toast('Не удалось отправить: ' + err.message, 'error');
      if (isOfflineError(err)) markOffline();
    } finally {
      state.sending = false;
      updateComposer();
      if (state.activeId === chatId && isNearBottom()) scrollBottom(false);
      if (state.activeId === chatId) ui.composerInput.focus();
    }
  }

  function uploadFiles(chatId, files, caption) {
    const limit = Number(state.settings.limits.upload_mb) || 0;
    const allowed = files.filter((file) => {
      if (limit > 0 && file.size > limit * 1024 * 1024) {
        toast('«' + file.name + '» больше ' + limit + ' МБ — не помещается в лимит загрузки', 'error');
        return false;
      }
      return true;
    });
    if (!allowed.length) return;

    state.sending = true;
    state.pending = [];
    renderChips();
    ui.composerInput.value = '';
    autosize();
    updateComposer();

    const temps = allowed.map((file, index) => addTempMessage({
      kind: uploadKind(file),
      media: { file_name: file.name, file_size: file.size, mime_type: file.type || '' },
      caption: index === 0 ? caption : '',
      uploading: true,
      progress: 0,
      local: false
    }));

    const form = new FormData();
    allowed.forEach((file) => form.append('file', file, file.name));
    form.append('caption', caption || '');

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload?chat_id=' + encodeURIComponent(chatId));

    const finish = (ok, payload, errorText) => {
      state.sending = false;
      updateComposer();
      if (ok) {
        temps.forEach((temp) => temp.remove());
        (payload.messages || []).forEach((msg) => {
          if (state.activeId === chatId) mergeMessage(msg, isNearBottom());
        });
        touchChat(chatId, caption || (allowed[0] && allowed[0].name) || 'Файл',
          Math.floor(Date.now() / 1000));
        state.drafts.delete(chatId);
        state.draftFiles.delete(chatId);
        refreshChatsSoon();
        if (state.activeId === chatId && isNearBottom()) scrollBottom(false);
      } else {
        const message = errorText || 'Не удалось отправить файл';
        temps.forEach((temp) => temp.fail(message));
        toast(message, 'error');
      }
    };

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const ratio = event.total ? event.loaded / event.total : 0;
      temps.forEach((temp) => temp.setProgress(ratio));
    };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch (_err) { data = null; }
      if (xhr.status >= 200 && xhr.status < 300 && data && data.ok) {
        finish(true, data, '');
      } else {
        finish(false, data, (data && data.error) || 'Не удалось отправить файл');
        if (xhr.status >= 500) markOffline();
      }
    };
    xhr.onerror = () => {
      finish(false, null, 'Нет связи с сервером');
      markOffline();
    };
    xhr.send(form);
  }

  /* ------------------------------------------------------------- форматирование */
  function wrapSelection(marker) {
    if (!state.activeId) return;
    const start = ui.composerInput.selectionStart;
    const end = ui.composerInput.selectionEnd;
    const value = ui.composerInput.value;
    const selected = value.slice(start, end);

    if (marker === '> ') {
      const lineStart = value.lastIndexOf('\n', start - 1) + 1;
      const lineEnd = value.indexOf('\n', end);
      const stop = lineEnd === -1 ? value.length : lineEnd;
      const block = value.slice(lineStart, stop);
      const quoted = block.split('\n').map((line) => '> ' + line).join('\n');
      ui.composerInput.value = value.slice(0, lineStart) + quoted + value.slice(stop);
      ui.composerInput.selectionStart = lineStart;
      ui.composerInput.selectionEnd = lineStart + quoted.length;
    } else if (marker === '[текст](url)') {
      const label = selected || 'текст';
      const insert = '[' + label + '](url)';
      ui.composerInput.value = value.slice(0, start) + insert + value.slice(end);
      if (selected) {
        ui.composerInput.selectionStart = start + label.length + 3;
        ui.composerInput.selectionEnd = start + label.length + 6;
      } else {
        ui.composerInput.selectionStart = start + 1;
        ui.composerInput.selectionEnd = start + 1 + label.length;
      }
    } else {
      const insert = marker + (selected || '') + marker;
      ui.composerInput.value = value.slice(0, start) + insert + value.slice(end);
      if (selected) {
        ui.composerInput.selectionStart = start + marker.length;
        ui.composerInput.selectionEnd = start + marker.length + selected.length;
      } else {
        ui.composerInput.selectionStart = start + marker.length;
        ui.composerInput.selectionEnd = start + marker.length;
      }
    }
    ui.composerInput.focus();
    autosize();
    updateComposer();
  }

  /* ------------------------------------------------------------------ медиа */
  async function retryMedia(id, button) {
    const numeric = Number(id);
    if (!numeric) return;
    if (button) {
      button.disabled = true;
      button.textContent = 'Загрузка…';
    }
    try {
      const data = await api('/api/retry_media', {
        method: 'POST',
        body: JSON.stringify({ id: numeric })
      });
      if (data.message) mergeMessage(data.message, isNearBottom());
    } catch (err) {
      toast(err.message, 'error');
      if (button) {
        button.disabled = false;
        button.textContent = 'Повторить';
      }
    }
  }

  async function transcribeMessage(id, button) {
    if (!state.settings.asr_enabled) return;
    const numeric = Number(id);
    if (!numeric || state.transcribing.has(numeric)) return;
    state.transcribing.add(numeric);
    if (button) {
      button.disabled = true;
      const label = button.querySelector('span');
      if (label) label.textContent = 'Расшифровка…';
    }
    try {
      const data = await api('/api/transcribe', {
        method: 'POST',
        body: JSON.stringify({ id: numeric })
      });
      if (data.message) mergeMessage(data.message, isNearBottom());
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      state.transcribing.delete(numeric);
      const msg = state.messages.get(numeric);
      if (msg) updateMessageRow(msg);
    }
  }

  /* ------------------------------------------------------------------ ASR */
  function isModalOpen(modal) {
    return !!(modal && !modal.hidden);
  }

  function currentAsrModel() {
    const selected = ui.asrModel && ui.asrModel.value;
    const id = selected || state.settings.asr_model || state.asrActive;
    return state.asrModels.find((model) => model.id === id) || null;
  }

  function renderAsr() {
    if (!state.settings.asr_enabled) {
      if (ui.asrConfig) ui.asrConfig.hidden = true;
      if (ui.asrOffHint) ui.asrOffHint.hidden = false;
      return;
    }
    if (!ui.asrModel) return;
    if (ui.asrConfig) ui.asrConfig.hidden = false;
    if (ui.asrOffHint) ui.asrOffHint.hidden = true;

    const models = state.asrModels;
    let selectedId = state.settings.asr_model || state.asrActive || (models[0] ? models[0].id : '');
    let selected = models.find((model) => model.id === selectedId) || null;
    if (!selected && models.length) {
      selectedId = models[0].id;
      selected = models[0];
    }

    if (!models.length) {
      ui.asrModel.innerHTML = '<option value="">' +
        (state.asrError ? 'Модели недоступны' : 'Модели не найдены') + '</option>';
      ui.asrModel.disabled = true;
    } else {
      ui.asrModel.disabled = false;
      ui.asrModel.innerHTML = models.map((model) => {
        const bits = [model.title || model.id];
        if (model.language) bits.push(model.language);
        if (Number(model.size_mb) > 0) bits.push(fmtSize(Number(model.size_mb) * 1024 * 1024));
        if (model.downloaded) bits.push('скачана');
        else if (model.downloading) bits.push('скачивается');
        return '<option value="' + esc(model.id) + '"' +
          (model.id === selectedId ? ' selected' : '') + '>' + esc(bits.join(' · ')) + '</option>';
      }).join('');
      ui.asrModel.value = selectedId;
    }

    ui.asrStatus.className = 'asr-status';
    if (ui.asrProgress) ui.asrProgress.hidden = true;
    if (ui.btnAsrDownload) {
      ui.btnAsrDownload.disabled = true;
      ui.btnAsrDownload.innerHTML = icon('download') + '<span>Скачать</span>';
    }

    if (state.asrError) {
      ui.asrStatus.textContent = 'Ошибка: ' + state.asrError;
      ui.asrStatus.classList.add('err');
      return;
    }
    if (!models.length) {
      ui.asrStatus.textContent = 'Модели не найдены. Проверьте сервис расшифровки на сервере.';
      return;
    }
    if (!selected) {
      ui.asrStatus.textContent = 'Выберите модель распознавания.';
      return;
    }

    const pct = progressPct(selected.progress);
    if (selected.downloading) {
      ui.asrStatus.textContent = 'Скачивание модели: ' + Math.round(pct) + '%';
      ui.asrStatus.classList.add('warn');
      if (ui.asrProgress) ui.asrProgress.hidden = false;
      if (ui.asrProgressBar) ui.asrProgressBar.style.width = pct + '%';
      ui.btnAsrDownload.disabled = true;
      ui.btnAsrDownload.innerHTML = icon('download') + '<span>Скачивание…</span>';
    } else if (selected.error) {
      ui.asrStatus.textContent = 'Ошибка скачивания: ' + selected.error;
      ui.asrStatus.classList.add('err');
      ui.btnAsrDownload.disabled = false;
      ui.btnAsrDownload.innerHTML = icon('refresh') + '<span>Повторить</span>';
    } else if (selected.downloaded) {
      ui.asrStatus.textContent = 'Модель скачана. Загружается в память только на время расшифровки.';
      ui.asrStatus.classList.add('ok');
      ui.btnAsrDownload.disabled = true;
      ui.btnAsrDownload.innerHTML = icon('check') + '<span>Модель скачана</span>';
    } else {
      ui.asrStatus.textContent = 'Модель не скачана. Нажмите «Скачать», чтобы начать.';
      ui.btnAsrDownload.disabled = false;
      ui.btnAsrDownload.innerHTML = icon('download') + '<span>Скачать</span>';
    }
  }

  async function loadAsrModels(silent) {
    if (!state.settings.asr_enabled || state.asrLoading) return;
    state.asrLoading = true;
    state.asrError = '';
    if (ui.btnAsrRefresh) ui.btnAsrRefresh.disabled = true;
    if (!silent && ui.asrStatus) {
      ui.asrStatus.className = 'asr-status';
      ui.asrStatus.textContent = 'Загрузка списка моделей…';
    }

    let modelsData = null;
    let statusData = null;
    let firstError = '';
    try {
      modelsData = await api('/api/asr/models');
    } catch (err) {
      firstError = err.message;
    }
    try {
      statusData = await api('/api/asr/status');
    } catch (err) {
      if (!firstError) firstError = err.message;
    }

    if (statusData && Array.isArray(statusData.models)) {
      state.asrModels = statusData.models;
    } else if (modelsData && Array.isArray(modelsData.models)) {
      state.asrModels = modelsData.models;
    } else {
      state.asrModels = [];
    }
    if (statusData && statusData.active) state.asrActive = statusData.active;

    if (!modelsData && !statusData) {
      state.asrError = firstError || 'Не удалось получить список моделей';
    }
    state.asrLoading = false;
    if (ui.btnAsrRefresh) ui.btnAsrRefresh.disabled = false;
    renderAsr();
    scheduleAsrPoll();
    if (state.recovered) recoverConnection();
  }

  function scheduleAsrPoll() {
    if (state.asrTimer) clearTimeout(state.asrTimer);
    state.asrTimer = null;
    if (!isModalOpen(ui.modalSettings) || !state.settings.asr_enabled) return;
    if (!state.asrModels.some((model) => model.downloading)) return;
    state.asrTimer = setTimeout(() => {
      state.asrTimer = null;
      loadAsrModels(true);
    }, 1500);
  }

  async function startAsrDownload() {
    const model = currentAsrModel();
    if (!model || model.downloading) return;
    ui.btnAsrDownload.disabled = true;
    try {
      await api('/api/asr/download', {
        method: 'POST',
        body: JSON.stringify({ model: model.id })
      });
      model.downloading = true;
      model.progress = 0;
      model.error = '';
      renderAsr();
      scheduleAsrPoll();
      toast('Скачивание модели началось', 'info');
    } catch (err) {
      toast('Не удалось начать скачивание: ' + err.message, 'error');
      renderAsr();
    }
  }

  async function changeAsrModel(id) {
    if (!id) return;
    const previous = state.settings.asr_model;
    state.settings.asr_model = id;
    renderAsr();
    try {
      await saveSetting('asr_model', id);
    } catch (err) {
      state.settings.asr_model = previous;
      renderAsr();
      toast('Не удалось сохранить модель: ' + err.message, 'error');
    }
  }

  async function changeBoolSetting(key, value, input) {
    const previous = !!state.settings[key];
    state.settings[key] = value;
    updateSettingsControls();
    try {
      await saveSetting(key, value);
      if (key === 'asr_enabled') {
        if (state.activeId) renderFeed();
        if (value && isModalOpen(ui.modalSettings) && !state.asrModels.length) {
          loadAsrModels(false);
        }
      }
    } catch (err) {
      state.settings[key] = previous;
      if (input) input.checked = previous;
      updateSettingsControls();
      if (key === 'asr_enabled' && state.activeId) renderFeed();
      toast('Не удалось сохранить настройку: ' + err.message, 'error');
    }
  }

  async function chooseTheme(theme) {
    if (state.settings.theme === theme) return;
    state.settings.theme = theme;
    applyTheme(theme);
    updateSettingsControls();
    try {
      await saveSetting('theme', theme);
    } catch (err) {
      toast('Тема применена локально, но не сохранена: ' + err.message, 'error');
    }
  }

  /* ------------------------------------------------------------- пользователи */
  async function removeFromSupport(chatId) {
    try {
      await api('/api/chats/remove', {
        method: 'POST',
        body: JSON.stringify({ chat_id: chatId })
      });
      const chat = getChat(chatId);
      if (chat) chat.allowed = false;
      renderSettingsUsers(true);
      renderChats(true);
      toast('Пользователь убран из поддержки', 'success');
      refreshChatsSoon();
    } catch (err) {
      toast('Не удалось убрать пользователя: ' + err.message, 'error');
    }
  }

  async function deleteChat(chatId) {
    const chat = getChat(chatId);
    const name = chat ? displayName(chat) : 'этот чат';
    if (!window.confirm('Удалить чат с «' + name + '» локально? В Telegram переписка останется.')) return;
    try {
      await api('/api/chats/delete', {
        method: 'POST',
        body: JSON.stringify({ chat_id: chatId })
      });
      state.chats = state.chats.filter((item) => item.id !== chatId);
      state.drafts.delete(chatId);
      state.draftFiles.delete(chatId);
      if (state.activeId === chatId) clearActiveChat();
      renderChats(true);
      renderSettingsUsers(true);
      updateChatHeader();
      updateOverlays();
      updateComposer();
      toast('Чат удалён локально', 'success');
      refreshChatsSoon();
    } catch (err) {
      toast('Не удалось удалить чат: ' + err.message, 'error');
    }
  }

  function upsertChat(chat) {
    if (!chat || chat.id == null) return;
    const index = state.chats.findIndex((item) => item.id === chat.id);
    if (index >= 0) state.chats[index] = chat;
    else state.chats.push(chat);
    renderChats(true);
    renderSettingsUsers(true);
  }

  async function submitAddUser() {
    const raw = ui.addUserInput.value.trim();
    if (!raw) {
      toast('Укажите ID или @username', 'error');
      ui.addUserInput.focus();
      return;
    }
    let payload;
    if (raw.charAt(0) === '@') {
      const username = raw.slice(1).trim();
      if (!username) {
        toast('Укажите username после @', 'error');
        return;
      }
      payload = { username: username };
    } else if (/^\d+$/.test(raw)) {
      payload = { user_id: Number(raw) };
    } else {
      payload = { username: raw.replace(/^@/, '') };
    }

    ui.btnAddUser.disabled = true;
    try {
      const data = await api('/api/chats/add', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      if (data.chat) upsertChat(data.chat);
      ui.addUserInput.value = '';
      toast('Пользователь добавлен', 'success');
      refreshChatsSoon();
    } catch (err) {
      toast('Не удалось добавить пользователя: ' + err.message, 'error');
    } finally {
      ui.btnAddUser.disabled = false;
    }
  }

  /* --------------------------------------------------------------- поиск людей */
  function renderFindUsers() {
    if (state.findLoading) {
      ui.findList.hidden = false;
      ui.findList.innerHTML = '<div class="find-loading"><span class="spinner"></span><span>Поиск…</span></div>';
      ui.findEmpty.hidden = true;
      return;
    }
    if (!state.findUsers.length) {
      ui.findList.hidden = true;
      ui.findList.innerHTML = '';
      ui.findEmpty.hidden = false;
      const searching = state.findQuery.trim().length > 0;
      ui.findEmptyTitle.textContent = searching ? 'Никого не нашли' : 'Пока никого нет';
      ui.findEmptyText.textContent = searching
        ? 'Попробуйте изменить имя, @username или ID.'
        : 'Напишите боту /start в Telegram — пользователь появится в этом списке.';
      return;
    }
    ui.findList.hidden = false;
    ui.findEmpty.hidden = true;
    ui.findList.innerHTML = state.findUsers.map((user) => {
      const name = user.name || user.username || ('Пользователь ' + user.id);
      const bits = [];
      if (user.username) bits.push('@' + user.username);
      bits.push('ID ' + user.id);
      if (user.last_seen) bits.push('был(а) ' + relDate(user.last_seen));
      return '<div class="person-row" data-known-user="' + esc(user.id) + '">' +
        avatarHtml(user.avatar_url, name, user.id, '') +
        '<div class="person-main">' +
          '<div class="person-name">' + esc(name) + '</div>' +
          '<div class="person-sub">' + esc(bits.join(' · ')) + '</div>' +
        '</div>' +
        '<div class="person-add">' +
          '<button class="btn ' + (user.allowed ? 'ghost' : 'primary') + ' small" type="button" data-add-known="' +
            esc(user.id) + '"' + (user.allowed ? ' disabled' : '') + '>' +
            (user.allowed ? 'Уже добавлен' : 'Добавить') +
          '</button>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  async function loadKnownUsers(query) {
    const token = ++state.findToken;
    state.findQuery = query;
    state.findLoading = true;
    renderFindUsers();
    try {
      const data = await api('/api/known_users?q=' + encodeURIComponent(query));
      if (token !== state.findToken) return;
      state.findUsers = Array.isArray(data.users) ? data.users : [];
      state.findLoading = false;
      renderFindUsers();
    } catch (err) {
      if (token !== state.findToken) return;
      ui.findUsers = [];
      state.findLoading = false;
      ui.findList.hidden = true;
      ui.findList.innerHTML = '';
      ui.findEmpty.hidden = false;
      ui.findEmptyTitle.textContent = 'Не удалось загрузить список';
      ui.findEmptyText.textContent = err.message;
      if (isOfflineError(err)) markOffline();
    }
  }

  async function addKnownUser(userId, button) {
    if (button) button.disabled = true;
    try {
      const data = await api('/api/chats/add', {
        method: 'POST',
        body: JSON.stringify({ user_id: Number(userId) })
      });
      const user = state.findUsers.find((item) => item.id === Number(userId));
      if (user) user.allowed = true;
      if (data.chat) upsertChat(data.chat);
      renderFindUsers();
      toast('Пользователь добавлен в чаты', 'success');
      refreshChatsSoon();
    } catch (err) {
      if (button) button.disabled = false;
      toast('Не удалось добавить: ' + err.message, 'error');
    }
  }

  function openFind() {
    ui.findSearch.value = '';
    ui.btnFindClear.hidden = true;
    state.findQuery = '';
    openModal(ui.modalFind, ui.findSearch);
    loadKnownUsers('');
  }

  /* ---------------------------------------------------------------- модалки */
  function openModal(modal, focusTarget) {
    if (!modal) return;
    $$('.modal').forEach((item) => {
      if (item !== modal) item.hidden = true;
    });
    closeSidebar();
    state.lastFocus = document.activeElement;
    modal.hidden = false;
    document.body.classList.add('modal-open');
    requestAnimationFrame(() => {
      let target = focusTarget;
      if (!target) target = $('.modal-card', modal);
      if (target && target.focus) target.focus();
    });
  }

  function closeModal(modal) {
    if (!modal) return;
    modal.hidden = true;
    if (!$$('.modal').some((item) => !item.hidden)) {
      document.body.classList.remove('modal-open');
    }
    if (state.asrTimer) {
      clearTimeout(state.asrTimer);
      state.asrTimer = null;
    }
    if (state.lastFocus && document.contains(state.lastFocus) && state.lastFocus.focus) {
      state.lastFocus.focus();
    }
  }

  function fillSettings() {
    updateSettingsControls();
    renderSettingsUsers();
    renderAsr();
  }

  function activateSettingsTab(name) {
    ui.settingsTabs.forEach((tab) => {
      const active = tab.dataset.tab === name;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    ui.settingsPanes.forEach((pane) => {
      pane.classList.toggle('active', pane.dataset.pane === name);
    });
    if (name === 'asr' && state.settings.asr_enabled && !state.asrModels.length) {
      loadAsrModels(false);
    }
  }

  function openSettings(tab) {
    fillSettings();
    openModal(ui.modalSettings, $('.modal-card', ui.modalSettings));
    activateSettingsTab(tab || 'theme');
    if (state.settings.asr_enabled) loadAsrModels(false);
    refreshChats(true);
  }

  /* --------------------------------------------------------------- лайтбокс */
  function openLightbox(src, downloadUrl, alt) {
    if (!src) return;
    ui.lightboxImg.src = src;
    ui.lightboxImg.alt = alt || 'Изображение';
    if (downloadUrl) {
      ui.lightboxDownload.href = downloadUrl;
      ui.lightboxDownload.hidden = false;
    } else {
      ui.lightboxDownload.removeAttribute('href');
      ui.lightboxDownload.hidden = true;
    }
    ui.lightbox.hidden = false;
    if (ui.lightboxClose) ui.lightboxClose.focus();
  }

  function closeLightbox() {
    ui.lightbox.hidden = true;
    ui.lightboxImg.removeAttribute('src');
  }

  /* --------------------------------------------------------------- сайдбар */
  function isMobile() {
    return window.matchMedia('(max-width: 900px)').matches;
  }

  function syncSidebar() {
    if (!isMobile()) {
      document.body.classList.remove('sidebar-open');
      ui.sidebarBackdrop.hidden = true;
    } else {
      ui.sidebarBackdrop.hidden = false;
    }
  }

  function openSidebar() {
    if (!isMobile()) return;
    ui.sidebarBackdrop.hidden = false;
    document.body.classList.add('sidebar-open');
  }

  function closeSidebar() {
    document.body.classList.remove('sidebar-open');
  }

  /* ------------------------------------------------------------- копирование */
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
      try {
        const area = document.createElement('textarea');
        area.value = text;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        area.remove();
        resolve();
      } catch (err) {
        reject(err);
      }
    });
  }

  /* ------------------------------------------------------------------ события */
  function bindEvents() {
    ui.conn.addEventListener('click', () => {
      refreshBootstrap(false);
      refreshChats(true);
    });

    ui.chatSearch.addEventListener('input', () => {
      state.chatSearch = ui.chatSearch.value;
      ui.btnSearchClear.hidden = !state.chatSearch;
      renderChats(true);
    });
    ui.chatSearch.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        ui.chatSearch.value = '';
        state.chatSearch = '';
        ui.btnSearchClear.hidden = true;
        renderChats(true);
        ui.chatSearch.blur();
      }
    });
    ui.btnSearchClear.addEventListener('click', () => {
      ui.chatSearch.value = '';
      state.chatSearch = '';
      ui.btnSearchClear.hidden = true;
      renderChats(true);
      ui.chatSearch.focus();
    });

    ui.chatList.addEventListener('click', (event) => {
      const item = event.target.closest('.chat-item');
      if (!item) return;
      selectChat(Number(item.dataset.chatId));
    });

    ui.btnBurger.addEventListener('click', openSidebar);
    ui.btnSidebarClose.addEventListener('click', closeSidebar);
    ui.sidebarBackdrop.addEventListener('click', closeSidebar);

    ui.btnSettings.addEventListener('click', () => openSettings('theme'));
    ui.btnSettingsMobile.addEventListener('click', () => openSettings('theme'));
    ui.btnFindUser.addEventListener('click', openFind);
    ui.btnNoChatFind.addEventListener('click', openFind);
    ui.btnChatEmptyFind.addEventListener('click', openFind);
    ui.btnNoChatSettings.addEventListener('click', () => openSettings('theme'));

    /* сообщения: делегированные клики */
    ui.feed.addEventListener('click', async (event) => {
      const target = event.target instanceof Element ? event.target : event.target.parentElement;
      if (!target) return;

      const link = target.closest('a');
      if (link) return;

      const copy = target.closest('.md-copy');
      if (copy) {
        const pre = copy.parentElement ? copy.parentElement.querySelector('pre') : null;
        const text = pre ? pre.innerText : '';
        try {
          await copyText(text);
          copy.textContent = '✓';
          setTimeout(() => { copy.textContent = '⧉'; }, 1200);
        } catch (_err) {
          toast('Не удалось скопировать', 'error');
        }
        return;
      }

      const spoiler = target.closest('.spoiler');
      if (spoiler) {
        spoiler.classList.toggle('open');
        return;
      }

      const retry = target.closest('[data-retry-media]');
      if (retry) {
        event.preventDefault();
        await retryMedia(retry.dataset.retryMedia, retry);
        return;
      }

      const transcribe = target.closest('[data-transcribe]');
      if (transcribe) {
        event.preventDefault();
        await transcribeMessage(transcribe.dataset.transcribe, transcribe);
        return;
      }

      const photo = target.closest('img.photo');
      if (photo) {
        openLightbox(photo.dataset.full || photo.currentSrc || photo.src,
          photo.dataset.download || '', photo.alt);
      }
    });

    ui.messages.addEventListener('scroll', () => {
      const top = ui.messages.scrollTop;
      if (top < 0) return;
      if (!state.autoScroll) {
        state.stick = isNearBottom();
        if (state.stick) {
          state.unread = 0;
          hideScrollDown();
        }
      }
      if (top < 90 && state.hasOlder && !state.loadingOlder &&
          Date.now() > state.olderCooldownUntil) {
        loadOlder();
      }
    });

    /* новые фото/видео меняют высоту — держим низ, если пользователь внизу */
    ui.feed.addEventListener('load', (event) => {
      const target = event.target;
      if (target && target.tagName === 'IMG' && state.stick) {
        requestAnimationFrame(() => {
          if (state.stick) setScrollTop(ui.messages.scrollHeight);
        });
      }
    }, true);
    ui.feed.addEventListener('loadedmetadata', (event) => {
      const target = event.target;
      if (target && (target.tagName === 'VIDEO' || target.tagName === 'AUDIO') && state.stick) {
        requestAnimationFrame(() => {
          if (state.stick) setScrollTop(ui.messages.scrollHeight);
        });
      }
    }, true);

    if (typeof ResizeObserver !== 'undefined') {
      const feedObserver = new ResizeObserver(() => {
        if (!state.stick) return;
        requestAnimationFrame(() => {
          if (state.stick) setScrollTop(ui.messages.scrollHeight);
        });
      });
      feedObserver.observe(ui.feed);
    }

    ui.scrollDown.addEventListener('click', () => scrollBottom(true));
    ui.loadOlder.addEventListener('click', loadOlder);

    /* композер */
    ui.btnAttach.addEventListener('click', () => {
      if (!state.activeId) return;
      ui.fileInput.click();
    });
    ui.fileInput.addEventListener('change', () => {
      addFiles(ui.fileInput.files);
      ui.fileInput.value = '';
    });
    ui.btnSend.addEventListener('click', handleSend);
    ui.composerInput.addEventListener('input', () => {
      autosize();
      updateComposer();
    });
    ui.composerInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        handleSend();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && !event.shiftKey) {
        const key = event.key.toLowerCase();
        if (key === 'b') {
          event.preventDefault();
          wrapSelection('**');
        } else if (key === 'i') {
          event.preventDefault();
          wrapSelection('*');
        }
      }
    });

    $$('.fmt-btn').forEach((button) => {
      button.addEventListener('click', () => wrapSelection(button.dataset.fmt));
    });

    document.addEventListener('paste', (event) => {
      if (!state.activeId || isModalOpen(ui.modalSettings) || isModalOpen(ui.modalFind)) return;
      const active = document.activeElement;
      if (active && active !== ui.composerInput &&
          (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) {
        return;
      }
      const data = event.clipboardData;
      if (!data || !data.files || !data.files.length) return;
      const images = Array.from(data.files).filter((file) => file.type && file.type.indexOf('image/') === 0);
      if (!images.length) return;
      event.preventDefault();
      addFiles(images);
    });

    let dragDepth = 0;
    document.addEventListener('dragenter', (event) => {
      if (!event.dataTransfer || Array.prototype.indexOf.call(event.dataTransfer.types, 'Files') < 0) return;
      if (!state.activeId) return;
      dragDepth += 1;
      document.body.classList.add('dragging');
    });
    document.addEventListener('dragover', (event) => {
      if (event.dataTransfer) event.preventDefault();
    });
    document.addEventListener('dragleave', () => {
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) document.body.classList.remove('dragging');
    });
    document.addEventListener('drop', (event) => {
      if (!event.dataTransfer) return;
      event.preventDefault();
      dragDepth = 0;
      document.body.classList.remove('dragging');
      if (event.dataTransfer.files && event.dataTransfer.files.length) {
        addFiles(event.dataTransfer.files);
      }
    });

    /* настройки */
    ui.settingsTabs.forEach((tab) => {
      tab.addEventListener('click', () => activateSettingsTab(tab.dataset.tab));
    });
    if (ui.themeDark) ui.themeDark.addEventListener('click', () => chooseTheme('dark'));
    if (ui.themeLight) ui.themeLight.addEventListener('click', () => chooseTheme('light'));

    if (ui.asrEnabled) {
      ui.asrEnabled.addEventListener('change', () => {
        changeBoolSetting('asr_enabled', ui.asrEnabled.checked, ui.asrEnabled);
      });
    }
    if (ui.autoTranscribe) {
      ui.autoTranscribe.addEventListener('change', () => {
        changeBoolSetting('auto_transcribe', ui.autoTranscribe.checked, ui.autoTranscribe);
      });
    }
    if (ui.autoApprove) {
      ui.autoApprove.addEventListener('change', () => {
        changeBoolSetting('auto_approve', ui.autoApprove.checked, ui.autoApprove);
      });
    }
    if (ui.asrModel) {
      ui.asrModel.addEventListener('change', () => changeAsrModel(ui.asrModel.value));
    }
    if (ui.btnAsrDownload) ui.btnAsrDownload.addEventListener('click', startAsrDownload);
    if (ui.btnAsrRefresh) {
      ui.btnAsrRefresh.addEventListener('click', () => loadAsrModels(false));
    }
    if (ui.btnAddUser) ui.btnAddUser.addEventListener('click', submitAddUser);
    if (ui.addUserInput) {
      ui.addUserInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          submitAddUser();
        }
      });
    }

    ui.modalSettings.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : event.target.parentElement;
      if (!target) return;
      const remove = target.closest('[data-remove-chat]');
      if (remove) {
        removeFromSupport(Number(remove.dataset.removeChat));
        return;
      }
      const del = target.closest('[data-delete-chat]');
      if (del) {
        deleteChat(Number(del.dataset.deleteChat));
      }
    });

    /* поиск пользователей */
    ui.findSearch.addEventListener('input', () => {
      ui.btnFindClear.hidden = !ui.findSearch.value;
      if (state.findTimer) clearTimeout(state.findTimer);
      state.findTimer = setTimeout(() => {
        state.findTimer = null;
        loadKnownUsers(ui.findSearch.value);
      }, 300);
    });
    ui.findSearch.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        if (state.findTimer) clearTimeout(state.findTimer);
        loadKnownUsers(ui.findSearch.value);
      }
    });
    ui.btnFindClear.addEventListener('click', () => {
      ui.findSearch.value = '';
      ui.btnFindClear.hidden = true;
      loadKnownUsers('');
      ui.findSearch.focus();
    });
    ui.findList.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : event.target.parentElement;
      if (!target) return;
      const add = target.closest('[data-add-known]');
      if (!add || add.disabled) return;
      addKnownUser(Number(add.dataset.addKnown), add);
    });

    /* закрытие модалок */
    document.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : event.target.parentElement;
      if (!target) return;
      const closer = target.closest('[data-close-modal]');
      if (closer) {
        const modal = closer.closest('.modal');
        if (modal) closeModal(modal);
        return;
      }
      if (target.classList && target.classList.contains('modal')) closeModal(target);
    });

    /* Esc */
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      if (!ui.lightbox.hidden) {
        closeLightbox();
        return;
      }
      const openModalEl = $$('.modal').find((modal) => !modal.hidden);
      if (openModalEl) {
        closeModal(openModalEl);
        return;
      }
      if (document.body.classList.contains('sidebar-open')) closeSidebar();
      if (document.body.classList.contains('dragging')) {
        dragDepth = 0;
        document.body.classList.remove('dragging');
      }
    });

    /* лайтбокс */
    ui.lightbox.addEventListener('click', (event) => {
      const target = event.target;
      if (target.closest('.lb-close, .lb-download')) return;
      closeLightbox();
    });
    ui.lightboxClose.addEventListener('click', (event) => {
      event.stopPropagation();
      closeLightbox();
    });

    /* битые аватары */
    document.addEventListener('error', (event) => {
      const target = event.target;
      if (!target || target.tagName !== 'IMG') return;
      if (target.hasAttribute('data-avatar')) target.hidden = true;
      if (target.classList && target.classList.contains('photo')) {
        target.classList.add('photo-broken');
      }
    }, true);

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        pollActive();
        refreshChats(true);
      }
    });

    window.addEventListener('resize', () => {
      syncSidebar();
      if (state.stick) {
        requestAnimationFrame(() => {
          if (state.stick) setScrollTop(ui.messages.scrollHeight);
        });
      }
    });
  }

  /* -------------------------------------------------------------------- init */
  async function init() {
    let initialTheme = 'dark';
    try {
      const saved = localStorage.getItem('tcb_theme');
      if (saved === 'light' || saved === 'dark') initialTheme = saved;
    } catch (_err) { /* ignore */ }
    state.settings.theme = initialTheme;
    applyTheme(initialTheme);
    updateSettingsControls();
    renderSettingsUsers();
    updateEmptyTexts();
    updateChatHeader();
    updateOverlays();
    updateComposer();
    updateLoadOlder();
    syncSidebar();
    setConnection('connecting');
    bindEvents();

    await refreshBootstrap(false);

    state.pollTimer = setInterval(pollActive, 1200);
    state.chatsTimer = setInterval(() => {
      if (!document.hidden) refreshChats(true);
    }, 5000);
    state.bootstrapTimer = setInterval(() => {
      if (!document.hidden) refreshBootstrap(true);
    }, 30000);
    state.connectionTimer = setInterval(refreshConnection, 8000);

    if (isMobile()) closeSidebar();
    if (!isMobile()) {
      ui.composerInput.focus();
    }
  }

  init();
})();
