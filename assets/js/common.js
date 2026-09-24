/** Mount one release-owned draft editor. No global registry or graph mutation. */
export function setup(root, api) {
  const editor = root.matches('[data-audio-editor]') ? root : root.querySelector('[data-audio-editor]');
  if (!editor) return () => {};
  const controller = new AbortController(), {signal} = controller;
  const kind = editor.dataset.kind, mixer = editor.dataset.mixer === 'true';
  const prefix = 'block.' + kind + '.';
  const title = editor.querySelector('[data-editor-title]');
  const list = editor.querySelector('[data-source-list]');
  const apply = editor.querySelector('[data-save-sources]');
  const reset = editor.querySelector('[data-reset-sources]');
  const add = editor.querySelector('[data-add-source]');
  const message = editor.querySelector('[data-editor-status]');
  const readOnly = typeof api.isReadOnly === 'function' ? api.isReadOnly() : Boolean(api.isReadOnly);
  let saved = JSON.parse(editor.dataset.config), draft = structuredClone(saved);
  let savedTitle = title.value, busy = false;

  /** Mark live labels so a language switch keeps block-owned translations. */
  const mark = (element, key, fallback, params = {}) => {
    if (globalThis.CWI18n?.set) globalThis.CWI18n.set(element, prefix + key, params, fallback);
    else { element.dataset.i18n = prefix + key; element.textContent = api.t?.(prefix + key, params, fallback) || fallback; }
  };
  const element = (tag, className = '') => { const node = document.createElement(tag); node.className = className; return node; };
  const translated = (tag, key, fallback, className = '') => { const node = element(tag, className); mark(node, key, fallback); return node; };

  /** Keep Apply enabled for actual changes and expose why it is unavailable. */
  function refresh() {
    const dirty = title.value !== savedTitle || JSON.stringify(draft) !== JSON.stringify(saved);
    apply.disabled = readOnly || busy || !dirty;
    reset.disabled = readOnly || busy || !dirty;
    add.disabled = readOnly || busy || draft.sources.length >= 8;
    editor.querySelectorAll('input,select,[data-remove-source]').forEach(node => { node.disabled = readOnly || busy; });
    mark(message, busy ? 'saving' : dirty ? 'unsaved' : 'clean',
      busy ? 'Saving…' : dirty ? 'Unsaved changes' : 'No changes');
    message.dataset.error = 'false';
    const count = editor.querySelector('[data-source-count]');
    mark(count, 'source_count', '{count} / 8 sources', {count: draft.sources.length});
  }

  /** Wrap every control in a visible label; IDs and source names never depend on labels. */
  function field(row, key, labelKey, fallback, type, attrs = {}) {
    const label = element('label', 'am-field');
    label.append(translated('span', labelKey, fallback));
    const input = element('input');
    input.type = type;
    Object.entries(attrs).forEach(([name, value]) => input.setAttribute(name, String(value)));
    input.dataset.sourceField = key;
    if (type === 'checkbox') { input.checked = row[key]; label.classList.add('am-check'); }
    else input.value = row[key];
    input.addEventListener('input', () => {
      row[key] = type === 'checkbox' ? input.checked : type === 'number' ? Number(input.value) : input.value;
      refresh();
    }, {signal});
    label.append(input);
    return label;
  }

  /** Rebuild rows only after adding/removing/resetting, never while typing. */
  function renderSources() {
    list.replaceChildren();
    for (const row of draft.sources) {
      const card = element('section', 'am-source');
      card.dataset.sourceId = String(row.id);
      const header = element('div', 'am-source-heading');
      const badge = element('span', 'am-source-number');
      badge.textContent = String(row.id).padStart(2, '0');
      header.append(badge, field(row, 'label', 'source_name', 'Source name', 'text', {maxlength: 14, required: true}));
      if (row.id > 2) {
        const remove = translated('button', 'remove', 'Remove', 'ghost-btn am-remove');
        remove.type = 'button';
        remove.dataset.removeSource = String(row.id);
        remove.addEventListener('click', () => {
          draft.sources = draft.sources.filter(item => item.id !== row.id);
          renderSources(); refresh(); add.focus();
        }, {signal});
        header.append(remove);
      }
      card.append(header);
      const ports = element('div', 'am-port-pair');
      for (const [label, name, cls] of [['Audio', 'audio_in_', 'am-audio-port'], ['Commands', 'command_in_', 'am-command-port']]) {
        const port = element('span', cls);
        const code = element('code'); code.textContent = name + row.id;
        port.append(translated('span', label === 'Audio' ? 'audio' : 'commands', label), code);
        ports.append(port);
      }
      card.append(ports);
      if (mixer) {
        const controls = element('div', 'am-mix-controls');
        controls.append(field(row, 'gain_db', 'gain', 'Gain (dB)', 'number', {min: -60, max: 6, step: 1, required: true}),
                        field(row, 'muted', 'mute', 'Mute this source', 'checkbox'));
        card.append(controls);
      }
      list.append(card);
    }
    // Catalog lookup needs the release ancestor; rows were built detached.
    globalThis.CWI18n?.apply(list);
  }

  /** Bind advanced numeric choices to the same local draft and validation boundary. */
  editor.querySelectorAll('[data-editor-setting]').forEach(input => {
    const key = input.dataset.editorSetting;
    input.value = draft[key];
    input.addEventListener('input', () => { draft[key] = Number(input.value); refresh(); }, {signal});
  });
  title.addEventListener('input', refresh, {signal});
  add.addEventListener('click', () => {
    if (draft.sources.length >= 8 || readOnly || busy) return;
    const id = Math.max(...saved.sources.map(row => row.id), ...draft.sources.map(row => row.id)) + 1;
    draft.sources.push({id, label: 'Source ' + id, gain_db: 0, muted: false});
    renderSources(); refresh();
    list.lastElementChild?.querySelector('input')?.focus();
  }, {signal});
  reset.addEventListener('click', () => {
    draft = structuredClone(saved); title.value = savedTitle;
    editor.querySelectorAll('[data-editor-setting]').forEach(input => { input.value = draft[input.dataset.editorSetting]; });
    renderSources(); refresh();
  }, {signal});
  apply.addEventListener('click', async () => {
    if (readOnly || busy) return;
    const invalid = [...editor.querySelectorAll('input,select')].find(input => !input.checkValidity());
    if (invalid) { invalid.reportValidity(); return; }
    busy = true; refresh();
    try {
      const result = await api.applyAction('save_sources', {title: title.value, config: structuredClone(draft)});
      if (signal.aborted) return;
      if (result?.error) throw new Error(result.error);
      saved = structuredClone(draft); savedTitle = title.value;
      busy = false; refresh();
      mark(message, 'saved', 'Saved · used at the next Run');
    } catch (error) {
      if (signal.aborted) return;
      busy = false; refresh();
      mark(message, 'save_error', 'Not saved. Stop the Run before changing settings; disconnect a source before removing it. {detail}',
        {detail: error?.message || ''});
      message.dataset.error = 'true';
    }
  }, {signal});
  renderSources(); refresh();
  return () => controller.abort();
}
