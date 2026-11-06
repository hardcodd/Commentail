/* Bind editor instances to native forms; the textarea remains the POST contract. */
(() => {
  const instances = new WeakMap();
  let nextIdentifier = 0;
  const containers = root => root.querySelectorAll('[data-editor-settings]');

  function destroy(root) {
    for (const node of containers(root)) {
      const state = instances.get(node);
      if (!state) continue;
      state.editor.destroy();
      state.dialog.remove();
      state.error.remove();
      instances.delete(node);
    }
  }

  function sync(root, validate = false) {
    let valid = true;
    for (const node of containers(root)) {
      const state = instances.get(node);
      if (!state) continue;
      try {
        state.editor.source.value = validate ? state.editor.getContent().text : state.editor.getDraft();
        if (validate) state.editor.clearInvalid();
      } catch (error) {
        if (validate) {
          state.editor.setInvalid(error.message);
          if (valid) state.editor.focus();
        } else state.editor.message(error.message);
        valid = false;
      }
    }
    return valid;
  }

  function mount(root) {
    for (const node of containers(root)) {
      const settings = JSON.parse(node.dataset.editorSettings);
      if (!node.isConnected || instances.has(node) || settings.guest !== 'visual') continue;
      const source = node.querySelector('textarea[name="text"]');
      const hadFocus = source === document.activeElement;
      const identifier = 'commentail-rich-' + (++nextIdentifier);
      translateChrome(node.querySelector('.editor-topbar'));
      for (const tool of node.querySelectorAll('.tool')) {
        const tip = tool.querySelector('.tooltip');
        const button = tool.querySelector('button');
        const shortcut = tip?.querySelector('kbd');
        if (shortcut && button) {
          shortcut.id = identifier + '-tip-' + (++nextIdentifier);
          button.setAttribute('aria-describedby', shortcut.id);
        }
      }
      const dialog = node.querySelector('[data-editor-dialog]').content.firstElementChild.cloneNode(true);
      const owner = document.createElement('div');
      owner.className = 'commentail-rich';
      owner.append(dialog);
      translateChrome(dialog);
      document.body.append(owner);
      // Keep the dialog's own form outside the comment form; nested forms lose fields.
      const content = dialog.querySelector('[data-link-form]');
      const form = document.createElement('form');
      form.method = 'dialog';
      form.noValidate = true;
      form.append(...content.childNodes);
      content.replaceWith(form);
      dialog.querySelector('h2').id = identifier + '-link-title';
      dialog.setAttribute('aria-labelledby', identifier + '-link-title');
      const hint = dialog.querySelector('.dialog-hint');
      const error = dialog.querySelector('[data-link-error]');
      hint.id = identifier + '-link-hint';
      error.id = identifier + '-link-error';
      dialog.querySelector('[name="href"]').setAttribute('aria-describedby', error.id + ' ' + hint.id);
      dialog.querySelector('[name="label"]').setAttribute('aria-describedby', error.id);
      const status = node.querySelector('[data-editor-status]');
      const validationError = document.createElement('div');
      validationError.id = identifier + '-error';
      validationError.setAttribute('aria-live', 'assertive');
      validationError.setAttribute('aria-atomic', 'true');
      // Announce error text urgently, without an alert event for each empty form mount.
      status.before(validationError);
      const editor = new CommentailVisualEditor.Editor({
        root: node.querySelector('[data-editor-root]'), source,
        toolbar: node.querySelector('[data-editor-toolbar]'),
        modeButton: node.querySelector('[data-editor-mode]'),
        status, error: validationError, initial: source.value, settings,
      });
      editor.root.setAttribute('aria-required', String(source.required));
      source.setAttribute('aria-required', String(source.required));
      source.required = false;
      node.querySelector('.editor-topbar').hidden = false;
      editor.updateButtons();
      new CommentailLinkDialog.LinkDialog(editor, dialog);
      new CommentailURLPaste.URLPaste(editor);
      instances.set(node, { editor, dialog: owner, error: validationError });
      status.id = identifier + '-status';
      const help = document.createElement('p');
      help.id = identifier + '-keyboard';
      help.className = 'editor-keyboard-help';
      help.textContent = translate("Keyboard: Alt+Shift+T (Mac: Option+Shift+T) opens the toolbar. Alt+F10 also works when your keyboard sends F10; on Mac this may require Fn. Use Left/Right arrows, Home or End; Escape returns to text. In lists, Escape then Tab leaves the editor.");
      const disclosure = document.createElement('details');
      disclosure.className = 'editor-help';
      const summary = document.createElement('summary');
      summary.textContent = translate("Keyboard shortcuts");
      disclosure.append(summary, help);
      status.before(disclosure);
      // Speak validation feedback before the longer usage instructions on refocus.
      const descriptions = [validationError.id, status.id, source.getAttribute('aria-describedby'), help.id].filter(Boolean).join(' ');
      editor.root.setAttribute('aria-describedby', descriptions);
      source.setAttribute('aria-describedby', descriptions);
      node.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
          for (const tool of node.querySelectorAll('.tool')) tool.dataset.dismissed = '';
        }
      }, { signal: editor.controller.signal });
      for (const tool of node.querySelectorAll('.tool')) {
        for (const event of ['pointerenter', 'focusin']) tool.addEventListener(event, () => {
          delete tool.dataset.dismissed;
        }, { signal: editor.controller.signal });
      }
      source.form.addEventListener('submit', event => {
        if (!sync(source.form, event.submitter?.name !== 'refresh')) event.preventDefault();
      }, { signal: editor.controller.signal });
      if (hadFocus) (editor.mode === 'visual' ? editor.root : source).focus({ preventScroll: true });
    }
  }

  globalThis.CommentailEditors = Object.freeze({ mount, sync, destroy });
  addEventListener('pagehide', event => {
    if (!event.persisted) destroy(document);
  });
})();
