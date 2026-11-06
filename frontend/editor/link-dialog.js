(() => {
  'use strict';
  const M = globalThis.CommentailEditorModel;

  /** Modal UI for one editor. Selection stays model-owned while focus is in fields.
   * All listeners share the editor's abort lifecycle; no address is opened/fetched.
   */
  class LinkDialog {
    constructor(editor, dialog) {
      this.editor = editor;
      this.dialog = dialog;
      this.address = dialog.querySelector('[name="href"]');
      this.label = dialog.querySelector('[name="label"]');
      this.error = dialog.querySelector('[data-link-error]');
      this.remove = dialog.querySelector('[data-link-remove]');
      const signal = editor.controller.signal;
      editor.root.addEventListener('commentail:link', event => {
        event.preventDefault(); this.open(event.detail);
      }, { signal });
      editor.root.addEventListener('dblclick', event => {
        if (event.button !== 0 || editor.destroyed || editor.composing || editor.mode !== 'visual' || dialog.open) return;
        const anchor = event.target.closest('a');
        if (!anchor || !editor.root.contains(anchor)) return;
        // Native double-click selects a word; edit the actual anchor's whole span.
        const point = editor.endpoint(anchor, 0);
        if (!point) return;
        event.preventDefault();
        editor.capture();
        this.open(M.linkTarget(editor.rows, { start: point, end: point }));
      }, { signal });
      dialog.querySelector('form').addEventListener('submit', event => {
        event.preventDefault(); this.apply(false);
      }, { signal });
      this.remove.addEventListener('click', () => this.apply(true), { signal });
      for (const button of dialog.querySelectorAll('[data-link-cancel]')) {
        button.addEventListener('click', () => dialog.close(), { signal });
      }
      dialog.addEventListener('close', () => {
        if (editor.destroyed || editor.mode !== 'visual') return;
        if (!this.applied) editor.range = { ...M.selection(editor.rows, this.selection.start, this.selection.end), backward: this.selection.backward };
        editor.restoreSelection(); editor.updateButtons();
      }, { signal });
      signal.addEventListener('abort', () => { if (dialog.open) dialog.close(); }, { once: true });
    }

    open(target) {
      if (this.editor.destroyed || this.editor.composing || this.editor.mode !== 'visual' ||
          !globalThis.CommentailEditorPolicy.allowsCommand('link', this.editor.policy)) return;
      const { start, end } = target.range;
      const item = this.editor.rows[start.row];
      const text = item.text.slice(start.offset, end.offset);
      if (start.row !== end.row || item.kind === 'pre' || text.includes('\n')) {
        this.editor.message(translate("Select text in one paragraph, without line breaks or block code.")); return;
      }
      this.target = M.clone(target);
      this.selection = M.clone(this.editor.range);
      this.before = JSON.stringify(this.editor.rows);
      this.applied = false;
      this.address.value = target.href ?? '';
      this.label.value = text;
      this.error.textContent = '';
      this.address.removeAttribute('aria-invalid');
      this.remove.hidden = !target.href;
      this.dialog.querySelector('[data-link-title]').textContent = target.href ? translate("Edit link") : translate("Add link");
      this.dialog.showModal(); this.address.focus(); this.address.select();
    }

    apply(remove) {
      try {
        if (this.before !== JSON.stringify(this.editor.rows)) throw new M.EditorError(translate("Text changed. Close the dialog and select the link again."));
        const href = remove ? null : M.linkURL(this.address.value.trim());
        const label = remove ? undefined : this.label.value || href;
        if (!this.editor.setLink(this.target.range, href, label)) throw new M.EditorError(this.editor.status.textContent);
        this.applied = true; this.dialog.close();
      } catch (error) {
        this.error.textContent = error.message;
        this.address.setAttribute('aria-invalid', 'true'); this.address.focus();
      }
    }
  }
  globalThis.CommentailLinkDialog = Object.freeze({ LinkDialog });
})();
