(() => {
  'use strict';
  const M = globalThis.CommentailEditorModel;

  /** Show only the URL host, dropping the conventional www. prefix. Keep other
   * subdomains and compound suffixes: guessing the last two labels is misleading.
   * The full validated destination remains in the model's href.
   */
  function domainLabel(value) {
    const href = M.linkURL(value);
    const url = new URL(href);
    if (!['http:', 'https:'].includes(url.protocol)) throw new M.EditorError(translate("Paste an HTTP or HTTPS address to create a link."));
    return url.hostname.replace(/^www\./i, '').replace(/\.$/, '');
  }

  /** A standalone pasted web URL becomes a domain-labelled link in one atomic
   * undo step. Code and mixed text retain the ordinary literal-paste behavior.
   * No network request or asynchronous document mutation is involved.
   */
  class URLPaste {
    constructor(editor) {
      this.editor = editor;
      editor.root.addEventListener('paste', event => this.paste(event), { capture: true, signal: editor.controller.signal });
    }

    paste(event) {
      const e = this.editor;
      if (e.destroyed || e.composing || e.mode !== 'visual' || !event.clipboardData ||
          !globalThis.CommentailEditorPolicy.allowsCommand('link', e.policy)) return;
      const text = event.clipboardData.getData('text/plain').trim();
      if (!/^https?:\/\/\S+$/i.test(text)) return;
      let href, label;
      try { href = M.linkURL(text); label = domainLabel(href); }
      catch { return; }
      e.capture();
      const range = M.clone(e.range), first = e.rows[range.start.row];
      const code = e.pending === M.CODE || first.kind === 'pre' ||
        (range.start.offset < first.text.length ? first.marks[range.start.offset] : first.marks[range.start.offset - 1]) === M.CODE;
      if (code) return;

      event.preventDefault(); event.stopImmediatePropagation();
      const start = M.clone(range.start);
      const end = { row: start.row, offset: start.offset + label.length };
      let candidate;
      const inserted = e.change((rows, selected) => {
        const result = M.replace(rows, selected, label);
        candidate = M.applyLink(result.rows, { start, end }, href, label);
        return candidate;
      }, null, true);
      // A redundant paste is a valid no-op, not a failure requiring literal fallback.
      if (!inserted && (!candidate || M.signature(candidate.rows) !== M.signature(e.rows))) e.insert(text, 'paste');
    }
  }
  globalThis.CommentailURLPaste = Object.freeze({ URLPaste, domainLabel });
})();
