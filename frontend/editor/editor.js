(() => {
  'use strict';
  const M = globalThis.CommentailEditorModel;
  const P = globalThis.CommentailEditorPolicy;
  const equalPoint = (a, b) => a.row === b.row && a.offset === b.offset;
  const collapsed = range => equalPoint(range.start, range.end);

  /** An isolated editor instance. Owns only supplied nodes/listeners; destroy releases them.
   * Model offsets and history use UTF-16, matching native Selection/textarea APIs.
   * Native composition is never rerendered until completion. Clipboard imports plain text.
   */
  class Editor {
    constructor({ root, source, toolbar, modeButton, status, error = null, initial = '', settings, audience = 'guest' }) {
      // Existing standalone consumers retain the lab's visual default; explicit
      // Site settings use safe plain-text defaults for both audiences.
      this.policy = P.forAudience(settings === undefined ? { guest: 'visual', registered: 'visual' } : settings, audience);
      this.root = root;
      this.source = source;
      this.toolbar = toolbar;
      this.modeButton = modeButton;
      this.status = status;
      this.error = error;
      this.controller = new AbortController();
      this.destroyed = false;
      this.composing = false;
      this.pending = null;
      this.mode = this.policy.mode === 'visual' ? 'visual' : 'source';
      let initialError = null;
      this.rows = [M.row()];
      try {
        P.assertMarkdown(initial, this.policy);
        if (this.mode === 'visual') this.rows = M.fromMarkdown(initial);
      }
      catch (error) { this.rows = [M.row()]; this.mode = 'source'; initialError = error; }
      this.sourceText = initial;
      this.source.value = initial;
      this.visualSource = null;
      this.dirty = false;
      this.range = { start: { row: 0, offset: 0 }, end: { row: 0, offset: 0 } };
      this.past = [];
      this.future = [];
      this.lastEdit = null;
      this.render();
      this.listen(root, 'beforeinput', event => this.beforeInput(event));
      this.listen(root, 'input', () => { if (!this.composing) this.ingestNative(); });
      this.listen(root, 'compositionstart', () => {
        this.capture();
        this.nativeBefore = this.snapshot();
        this.composing = true;
        this.updateButtons();
      });
      this.listen(root, 'compositionend', () => {
        this.composing = false;
        this.ingestNative();
      });
      this.listen(root, 'paste', event => {
        event.preventDefault();
        if (!this.composing && event.clipboardData) this.insert(event.clipboardData.getData('text/plain'), 'paste');
      });
      this.listen(root, 'drop', event => { event.preventDefault(); this.message(translate("Dragging is disabled. Paste text instead.")); });
      this.listen(root, 'dragstart', event => event.preventDefault());
      this.listen(root, 'click', event => { if (event.target.closest('a')) event.preventDefault(); });
      this.listen(root, 'copy', event => this.clipboard(event, false));
      this.listen(root, 'cut', event => this.clipboard(event, true));
      this.listen(toolbar, 'mousedown', event => { if (event.button === 0) event.preventDefault(); });
      this.listen(toolbar, 'keydown', event => this.toolbarKey(event));
      this.listen(toolbar, 'focusin', event => {
        const button = event.target.closest('button[data-command]');
        if (button) { this.toolbarButton = button; this.updateToolbarTabstop(); }
      });
      this.listen(toolbar, 'click', event => {
        const button = event.target.closest('button[data-command]');
        if (button) this.command(button.dataset.command);
      });
      this.listen(modeButton, 'click', () => this.toggleMode());
      this.listen(root.ownerDocument, 'selectionchange', () => {
        if (this.mode !== 'visual' || this.composing) return;
        const next = this.readSelection();
        if (next && (!equalPoint(next.start, this.range.start) || !equalPoint(next.end, this.range.end) ||
            Boolean(next.backward) !== Boolean(this.range.backward))) {
          this.range = next;
          this.pending = null;
          this.lastEdit = null;
        }
        this.updateButtons();
      });
      for (const target of [root, source]) this.listen(target, 'keydown', event => this.key(event));
      this.listen(source, 'beforeinput', event => {
        if (this.composing) return;
        if (event.inputType === 'historyUndo' || event.inputType === 'historyRedo') {
          if (event.cancelable) { event.preventDefault(); this.history(event.inputType === 'historyRedo'); }
        } else this.sourceBefore = this.snapshot();
      });
      this.listen(source, 'input', () => {
        if (this.composing) return;
        this.clearInvalid();
        if (source.value === this.sourceText) { this.sourceBefore = null; return; }
        if (source.value.length > 100000) {
          const before = this.sourceBefore ?? { ...this.snapshot(), sourceText: this.sourceText };
          this.restore(before);
          this.sourceBefore = null;
          this.message(translate("Source is limited to 100,000 UTF-16 units."));
          return;
        }
        this.record(this.sourceBefore ?? { ...this.snapshot(), sourceText: this.sourceText });
        this.sourceBefore = null;
        this.sourceText = source.value;
        this.dirty = false;
        this.message(this.policy.mode === 'visual' ? translate("Source changed. Switch to the visual editor to check it.") : translate("Text changed. Site formatting rules will be checked before submission."));
        this.updateButtons();
      });
      this.listen(source, 'compositionstart', () => {
        this.sourceCompositionBefore = this.snapshot();
        this.sourceBefore = null;
        this.composing = true;
        this.updateButtons();
      });
      this.listen(source, 'compositionend', () => {
        this.composing = false;
        const before = this.sourceCompositionBefore;
        this.sourceCompositionBefore = null;
        if (source.value.length > 100000) {
          this.restore(before);
          this.message(translate("Source is limited to 100,000 UTF-16 units."));
        } else {
          if (source.value !== before.sourceText) this.record(before);
          this.sourceText = source.value;
          this.dirty = false;
          this.clearInvalid();
          this.message(translate("Source input completed."));
        }
        this.sourceBefore = null;
        this.updateButtons();
      });
      this.message(initialError?.message ?? '');
    }

    listen(target, name, handler) { target.addEventListener(name, handler, { signal: this.controller.signal }); }
    message(text) { if (this.status.textContent !== text) this.status.textContent = text; }

    /** Keep validation attached to either surface; the first invalid instance
     * receives focus from the form adapter, without moving the text selection. */
    setInvalid(message) {
      this.invalid = true;
      for (const field of [this.root, this.source]) field.setAttribute('aria-invalid', 'true');
      if (this.error) {
        this.message('');
        // A failed submit needs a fresh alert even when its message is unchanged.
        this.error.textContent = message;
      } else this.message(message);
    }
    clearInvalid() {
      if (!this.invalid) return;
      this.invalid = false;
      for (const field of [this.root, this.source]) field.removeAttribute('aria-invalid');
      if (this.error) this.error.textContent = '';
    }
    focus() { (this.mode === 'visual' ? this.root : this.source).focus(); }

    /** One Tab stop per toolbar; unavailable controls never receive arrow focus. */
    toolbarButtons() {
      return Array.from(this.toolbar.querySelectorAll('button[data-command]'))
        .filter(button => !button.disabled && !button.closest('[hidden]'));
    }
    updateToolbarTabstop() {
      const buttons = this.toolbarButtons();
      if (!buttons.includes(this.toolbarButton)) this.toolbarButton = buttons[0];
      for (const button of this.toolbar.querySelectorAll('button[data-command]')) {
        button.tabIndex = button === this.toolbarButton ? 0 : -1;
      }
    }
    toolbarKey(event) {
      if (event.altKey || event.ctrlKey || event.metaKey || event.isComposing || this.composing) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        if (this.mode === 'visual') this.restoreSelection(); else this.source.focus();
        return;
      }
      const buttons = this.toolbarButtons();
      if (!buttons.length || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const index = buttons.indexOf(this.root.ownerDocument.activeElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 :
        (index + (event.key === 'ArrowLeft' ? -1 : 1) + buttons.length) % buttons.length;
      this.toolbarButton = buttons[next];
      this.updateToolbarTabstop();
      this.toolbarButton.focus();
    }

    /** Transfer source for a new settings/audience session. Dirty visual content
     * uses the agreed comment-export normalization on a copy; raw source is exact.
     * This does not authorize submission; invalid source stays available for repair.
     * Throws if the current visual document cannot be represented in Markdown.
     */
    getDraft() {
      if (this.destroyed || this.composing) throw new M.EditorError(translate("Wait until text composition finishes."));
      if (this.mode === 'source') return this.source.value;
      return this.dirty ? M.toCommentMarkdown(this.rows, true) : this.sourceText;
    }

    /** Final client-side validation. Returns a storage-format discriminator and
     * source; it does not send or persist content. Backend validation is required
     * independently. Plain source is literal; Markdown uses the complete dialect.
     */
    getContent() {
      const text = this.getDraft();
      if (!text.trim()) throw new M.EditorError(translate("Enter your comment."));
      P.assertMarkdown(text, this.policy);
      return { format: this.policy.mode === 'plain' ? 'plain' : 'markdown', text };
    }

    snapshot() {
      return M.clone({ rows: this.rows, mode: this.mode, sourceText: this.mode === 'source' ? this.source.value : this.sourceText,
        dirty: this.dirty, range: this.range, pending: this.pending, visualSource: this.visualSource,
        sourceSelection: [this.source.selectionStart, this.source.selectionEnd, this.source.selectionDirection] });
    }

    record(before, group = null) {
      const now = performance.now();
      const coalesce = group === 'typing' && this.lastEdit?.group === group && now - this.lastEdit.time < 700 &&
        equalPoint(before.range.start, this.lastEdit.range.start) && equalPoint(before.range.end, this.lastEdit.range.end) &&
        before.pending === this.lastEdit.pending;
      if (!coalesce) this.past.push(before);
      this.future = [];
      // Bound both entry count and retained model size, independently of document size.
      while (this.past.length > 100 || this.past.length > 1 && JSON.stringify(this.past).length > 2000000) this.past.shift();
      this.lastEdit = group ? { group, time: now, range: M.clone(this.range), pending: this.pending } : null;
    }

    restore(snapshot) {
      Object.assign(this, M.clone(snapshot));
      this.clearInvalid();
      this.source.value = this.sourceText;
      this.render();
      if (this.mode === 'source') {
        this.source.focus();
        this.source.setSelectionRange(...snapshot.sourceSelection);
      } else this.restoreSelection();
    }

    history(redo = false) {
      if (this.composing || this.destroyed) return false;
      this.capture();
      const from = redo ? this.future : this.past;
      if (!from.length) return false;
      (redo ? this.past : this.future).push(this.snapshot());
      this.restore(from.pop());
      this.lastEdit = null;
      this.message(redo ? translate("Action redone.") : translate("Action undone."));
      this.updateButtons();
      return true;
    }

    /** Read a native endpoint without counting nested list descendants as parent text. */
    endpoint(node, offset) {
      if (!node || !this.root.contains(node)) return null;
      const element = node.nodeType === 1 ? node : node.parentElement;
      let line = element.closest('[data-line]');
      if (!line) {
        const after = node.nodeType === 1 ? node.childNodes[offset] : null;
        line = after?.nodeType === 1 ? after.closest('[data-line]') ?? after.querySelector('[data-line]') : null;
        if (line) return { row: Number(line.dataset.line), offset: 0 };
        line = element.closest('[data-row]')?.querySelector('[data-line]') ?? Array.from(this.root.querySelectorAll('[data-line]')).at(-1);
        if (!line) return { row: 0, offset: 0 };
        return { row: Number(line.dataset.line), offset: line.textContent.length };
      }
      const range = this.root.ownerDocument.createRange();
      range.selectNodeContents(line);
      range.setEnd(node, offset);
      return { row: Number(line.dataset.line), offset: range.toString().length };
    }

    readSelection() {
      const selection = this.root.ownerDocument.getSelection();
      const anchor = this.endpoint(selection.anchorNode, selection.anchorOffset);
      const focus = this.endpoint(selection.focusNode, selection.focusOffset);
      if (!anchor || !focus) return null;
      return { ...M.selection(this.rows, anchor, focus), backward: anchor.row > focus.row || anchor.row === focus.row && anchor.offset > focus.offset };
    }
    capture() { if (this.mode === 'visual') this.range = this.readSelection() ?? this.range; }

    domPoint(point) {
      const line = this.root.querySelector(`[data-line="${point.row}"]`);
      let offset = point.offset;
      const walker = this.root.ownerDocument.createTreeWalker(line, 4);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (offset <= node.length) return [node, offset];
        offset -= node.length;
      }
      return [line, line.childNodes.length];
    }
    restoreSelection() {
      if (this.mode !== 'visual' || this.destroyed) return;
      this.root.focus({ preventScroll: true });
      const a = this.domPoint(this.range.start), b = this.domPoint(this.range.end);
      this.root.ownerDocument.getSelection().setBaseAndExtent(...(this.range.backward ? b : a), ...(this.range.backward ? a : b));
      const caret = this.root.ownerDocument.createRange();
      const focus = this.range.backward ? a : b;
      caret.setStart(...focus); caret.collapse(true);
      let rect = caret.getBoundingClientRect();
      if (!rect.height) rect = (focus[0].nodeType === 1 ? focus[0] : focus[0].parentElement).getBoundingClientRect();
      const view = this.root.ownerDocument.defaultView;
      if (rect.height && rect.top < 12) view.scrollBy(0, rect.top - 12);
      else if (rect.height && rect.bottom > view.innerHeight - 12) view.scrollBy(0, rect.bottom - view.innerHeight + 12);
    }

    render() {
      this.root.hidden = this.mode !== 'visual';
      this.source.hidden = this.mode !== 'source';
      const modeLabel = this.mode === 'visual' ? translate("Open Markdown") : translate("Open visual editor");
      const modeCaption = this.modeButton.querySelector('[data-mode-label]') ?? this.modeButton;
      modeCaption.textContent = modeLabel;
      this.modeButton.setAttribute('aria-label', modeLabel);
      this.modeButton.setAttribute('aria-pressed', String(this.mode === 'source'));
      const doc = this.root.ownerDocument;
      const fragment = doc.createDocumentFragment();
      const lists = [];
      const numbers = [];
      this.rows.forEach((item, index) => {
        let block;
        if (item.depth) {
          while (lists.length > item.depth) lists.pop();
          if (lists.length === item.depth && lists.at(-1).tagName.toLowerCase() !== item.kind) lists.pop();
          while (lists.length < item.depth) {
            const list = doc.createElement(item.kind);
            // Safari needs explicit list semantics when CSS replaces native markers.
            list.setAttribute('role', 'list');
            if (item.kind === 'ol' && item.start !== 1) list.start = item.start;
            (lists.length ? lists.at(-1).lastElementChild : fragment).append(list);
            lists.push(list);
          }
          block = doc.createElement('li');
          numbers.length = item.depth;
          numbers[item.depth - 1] = item.kind === 'ol' ? item.start : null;
          if (item.kind === 'ol') block.dataset.marker = numbers.includes(null) ? String(item.start) : numbers.join('.');
          lists.at(-1).append(block);
        } else {
          lists.length = 0;
          numbers.length = 0;
          block = doc.createElement(item.kind === 'quote' ? 'blockquote' : item.kind === 'pre' ? 'pre' : 'p');
          fragment.append(block);
        }
        block.dataset.row = String(index);
        const line = doc.createElement(item.kind === 'pre' ? 'code' : 'span');
        line.dataset.line = String(index);
        if (!item.text) line.append(doc.createElement('br'));
        const links = item.links?.length ? M.linkValues(item) : null;
        let linkNode = null, activeHref = null;
        for (let i = 0; i < item.text.length;) {
          let end = i + 1;
          while (end < item.text.length && item.marks[end] === item.marks[i] && (!links || links[end] === links[i])) end++;
          let parent = line;
          const href = links?.[i] ?? null;
          if (href) {
            if (activeHref !== href) {
              linkNode = doc.createElement('a'); linkNode.href = href;
              linkNode.rel = 'nofollow ugc noopener noreferrer'; line.append(linkNode);
            }
            parent = linkNode;
          }
          activeHref = href;
          for (const [bit, tag] of [[M.BOLD, 'strong'], [M.ITALIC, 'em'], [M.STRIKE, 'del'], [M.CODE, 'code']]) {
            if (item.marks[i] & bit) { const child = doc.createElement(tag); parent.append(child); parent = child; }
          }
          parent.append(doc.createTextNode(item.text.slice(i, end)));
          i = end;
        }
        block.append(line);
      });
      this.root.replaceChildren(fragment);
      this.updateButtons();
    }

    updateButtons() {
      for (const button of this.toolbar.querySelectorAll('[data-command]')) {
        const command = button.dataset.command;
        const allowed = P.allowsCommand(command, this.policy);
        button.disabled = !allowed || this.composing || (command === 'undo' ? !this.past.length : command === 'redo' ? !this.future.length : this.mode !== 'visual');
        const wrapper = button.closest('.tool');
        if (wrapper) wrapper.hidden = !allowed;
        if (['bold', 'italic', 'strike', 'code'].includes(command)) {
          const bit = { bold: M.BOLD, italic: M.ITALIC, strike: M.STRIKE, code: M.CODE }[command];
          const point = this.range.start;
          const mask = this.pending ?? this.rows[point.row].marks[Math.max(0, point.offset - 1)] ?? 0;
          button.setAttribute('aria-pressed', String(Boolean(mask & bit)));
        } else if (command === 'link') {
          button.setAttribute('aria-pressed', String(Boolean(M.linkTarget(this.rows, this.range).href)));
        } else if (['pre', 'ol', 'ul', 'quote'].includes(command)) {
          const { start, end } = this.range;
          const last = end.row > start.row && end.offset === 0 ? end.row - 1 : end.row;
          button.setAttribute('aria-pressed', String(this.rows.slice(start.row, last + 1).every(item => item.kind === command)));
        }
      }
      this.modeButton.disabled = this.composing || this.policy.mode !== 'visual';
      const modeWrapper = this.modeButton.closest('.tool');
      if (modeWrapper) modeWrapper.hidden = this.policy.mode !== 'visual';
      for (const group of this.toolbar.querySelectorAll('.tool-group')) {
        group.hidden = !Array.from(group.querySelectorAll('button')).some(button => !button.closest('.tool').hidden);
      }
      this.updateToolbarTabstop();
    }

    /** Commit a pure-model transaction. Formatting must serialize before any
     * state/history/DOM mutation; text input has a separate lossless fallback.
     */
    change(transform, group = null, formatting = false) {
      if (this.destroyed || this.composing || this.mode !== 'visual') return false;
      this.capture();
      const before = this.snapshot();
      try {
        const result = transform(M.clone(this.rows), M.clone(this.range));
        const rows = M.normalize(result.rows);
        if (JSON.stringify(rows) === JSON.stringify(before.rows)) return false;
        P.assertRows(rows, this.policy);
        if (formatting) M.toCommentMarkdown(rows, true);

        this.rows = rows;
        this.clearInvalid();
        this.range = result.point ? { start: result.point, end: result.point } : M.selection(this.rows, this.range.start, this.range.end);
        if (!result.point && before.range.backward) this.range.backward = true;
        if (result.restricted) this.pending = 0;
        this.dirty = true;
        this.record(before, group);
        this.render();
        this.restoreSelection();
        try {
          if (!formatting) M.toCommentMarkdown(this.rows, true);
          this.message(result.restricted ? translate("Text inserted without new formatting: Markdown cannot represent this combination.") : translate("Changes kept in memory."));
        }
        catch (error) { this.message(error.message); }
        this.updateButtons();
        return true;
      } catch (error) {
        this.rows = before.rows;
        this.range = before.range;
        this.message(formatting ? translate("Formatting was not applied. ") + error.message : error.message);
        return false;
      }
    }

    /** Keep input text when pending/inherited styling cannot be encoded.
     * Only the new input's marks may be dropped; existing marks stay untouched.
     * Whitespace with no actual new mark does not switch off a typing format.
     */
    admitInput(rows, plain) {
      if (M.signature(rows) === M.signature(plain)) return { rows, restricted: false };
      try { M.toCommentMarkdown(rows, true); return { rows, restricted: false }; }
      catch (error) {
        if (!(error instanceof M.EditorError) && !(error instanceof globalThis.CommentailMarkdown.MarkdownLimitError)) throw error;
        return { rows: plain, restricted: true };
      }
    }

    insert(text, group = 'typing', soft = false) {
      this.capture();
      const point = this.range.start;
      const mask = this.pending ?? this.rows[point.row].marks[Math.max(0, point.offset - 1)] ?? 0;
      return this.change((rows, range) => {
        const result = M.replace(rows, range, text, mask, soft);
        if (!mask) return result;
        const plain = M.replace(rows, range, text, 0, soft).rows;
        return { ...result, ...this.admitInput(result.rows, plain) };
      }, group);
    }

    /** A separate transaction lets one undo recover the literal typed markers. */
    typingShortcut(typed) {
      if (this.mode !== 'visual' || this.composing || this.destroyed) return false;
      const result = globalThis.CommentailEditorShortcuts.apply(this.rows, this.range, typed, this.policy);
      if (!result) return false;
      const changed = this.change(() => result, null, true);
      if (changed) { this.pending = 0; this.lastEdit = null; this.updateButtons(); }
      return changed;
    }

    command(command) {
      if (command === 'undo' || command === 'redo') return this.history(command === 'redo');
      if (this.mode !== 'visual' || this.composing || this.destroyed) return false;
      if (!P.allowsCommand(command, this.policy)) {
        this.message(translate("This formatting is disabled in site settings.")); return false;
      }
      this.capture();
      if (command === 'clear') {
        if (collapsed(this.range)) {
          this.pending = 0;
          this.lastEdit = null;
          this.restoreSelection();
          this.updateButtons();
          return true;
        }
        // Recovery must work even when an unsupported span remains elsewhere.
        const changed = this.change((rows, range) => ({ rows: M.clearFormatting(rows, range) }));
        this.pending = 0;
        this.updateButtons();
        return changed;
      }
      if (command === 'link') {
        const event = new CustomEvent('commentail:link', { cancelable: true, detail: M.linkTarget(this.rows, this.range) });
        this.root.dispatchEvent(event);
        return event.defaultPrevented;
      }
      const bits = { bold: M.BOLD, italic: M.ITALIC, strike: M.STRIKE, code: M.CODE };
      if (Object.hasOwn(bits, command)) {
        const bit = bits[command];
        if (collapsed(this.range)) {
          const p = this.range.start;
          const current = this.pending ?? this.rows[p.row].marks[Math.max(0, p.offset - 1)] ?? 0;
          this.pending = current & bit ? current & ~bit : bit === M.CODE ? M.CODE : (current & ~M.CODE) | bit;
          this.lastEdit = null;
          this.restoreSelection();
          this.updateButtons();
          return true;
        }
        return this.change((rows, range) => ({ rows: M.format(rows, range, bit) }), null, true);
      }
      return this.change((rows, range) => ({ rows: M.structure(rows, range, command) }), null, true);
    }

    /** Commit the modal's saved target as one verified, undoable link operation. */
    setLink(range, href, label) {
      if (this.mode !== 'visual' || this.composing || this.destroyed) return false;
      if (href && !P.allowsCommand('link', this.policy)) { this.message(translate("Links are disabled in site settings.")); return false; }
      try {
        const result = M.applyLink(this.rows, range, href, label);
        M.toCommentMarkdown(result.rows, true);
        if (JSON.stringify(result.rows) === JSON.stringify(this.rows)) return true;
        return this.change(() => result, null, true);
      } catch (error) { this.message(error.message); return false; }
    }

    enter(soft = false) {
      this.capture();
      const item = this.rows[this.range.start.row];
      if (!soft && collapsed(this.range) && item.depth && !item.text) return this.command('outdent');
      if (!soft && collapsed(this.range) && item.kind === 'quote' && !item.text) return this.command('quote');
      this.pending = 0;
      return this.insert('\n', null, soft || item.kind === 'pre');
    }

    delete(forward = false, unit = 'grapheme') {
      this.capture();
      return this.change((rows, range) => {
        if (!collapsed(range)) return M.replace(rows, range, '');
        const p = range.start;
        const item = rows[p.row];
        if (!forward && p.offset === 0 && item.kind === 'quote') return { rows: M.structure(rows, range, 'quote') };
        if (!forward && p.offset === 0 && item.depth) return { rows: M.structure(rows, range, 'outdent') };
        if (forward && p.offset === item.text.length) {
          if (p.row === rows.length - 1) return { rows };
          range.end = { row: p.row + 1, offset: 0 };
        } else if (!forward && p.offset === 0) {
          if (!p.row) return { rows };
          range.start = { row: p.row - 1, offset: rows[p.row - 1].text.length };
        } else {
          let boundary;
          if (unit === 'line') {
            const next = item.text.indexOf('\n', p.offset);
            boundary = forward ? (next === -1 ? item.text.length : next) : item.text.lastIndexOf('\n', p.offset - 1) + 1;
          }
          else {
            const segments = Array.from(new Intl.Segmenter(undefined, { granularity: unit }).segment(item.text));
            const points = [0, ...segments.map(part => part.index + part.segment.length)];
            boundary = forward ? points.find(value => value > p.offset) : points.filter(value => value < p.offset).at(-1);
          }
          range[forward ? 'end' : 'start'] = { row: p.row, offset: boundary };
        }
        return M.replace(rows, range, '');
      });
    }

    beforeInput(event) {
      if (this.composing || event.isComposing) return;
      if (!event.cancelable) { this.capture(); this.nativeBefore = this.snapshot(); return; }
      const type = event.inputType;
      event.preventDefault();
      if (type === 'insertText' || type === 'insertReplacementText') {
        if (event.data !== null) {
          this.capture();
          const shortcut = type === 'insertText' && event.data.length === 1 && collapsed(this.range);
          if (this.insert(event.data) && shortcut) this.typingShortcut(event.data);
        }
        else this.message(translate("This input source supplied no text. Paste text or use Markdown."));
      } else if (type === 'insertParagraph' || type === 'insertLineBreak') {
        this.capture();
        if (type !== 'insertParagraph' || !this.typingShortcut('\n')) this.enter(type === 'insertLineBreak');
      }
      else if (type.startsWith('delete')) {
        this.capture();
        const target = /Word|Line/.test(type) && collapsed(this.range) ? event.getTargetRanges?.()[0] : null;
        const start = target ? this.endpoint(target.startContainer, target.startOffset) : null;
        const end = target ? this.endpoint(target.endContainer, target.endOffset) : null;
        if (start && end && !equalPoint(start, end)) this.change(rows => M.replace(rows, M.selection(rows, start, end), ''));
        else this.delete(type.endsWith('Forward'), /Word/.test(type) ? 'word' : /Line/.test(type) ? 'line' : 'grapheme');
      }
      else if (type === 'historyUndo' || type === 'historyRedo') this.history(type === 'historyRedo');
      else if (['formatBold', 'formatItalic', 'formatStrikeThrough'].includes(type)) this.command({ formatBold: 'bold', formatItalic: 'italic', formatStrikeThrough: 'strike' }[type]);
      else if (!['insertFromPaste', 'insertFromDrop'].includes(type)) this.message(translate("This input method is not supported: ") + type);
    }

    /** Reconcile native composition/autocorrection only within existing text rows.
     * Unexpected native structural changes roll back visibly, never import arbitrary HTML.
     */
    ingestNative() {
      const before = this.nativeBefore;
      if (!before) return;
      this.nativeBefore = null;
      const lines = Array.from(this.root.querySelectorAll('[data-line]'));
      try {
        if (lines.length !== this.rows.length) throw new M.EditorError(translate("The browser changed the document structure. Retry or use Markdown."));
        const afterRange = this.readSelection() ?? this.range;
        const rows = M.clone(before.rows);
        const plain = M.clone(before.rows);
        lines.forEach((line, index) => {
          const text = line.textContent.replaceAll('\0', '\ufffd');
          const old = rows[index];
          let left = 0, right = 0;
          while (left < old.text.length && left < text.length && old.text[left] === text[left]) left++;
          while (right < old.text.length - left && right < text.length - left && old.text.at(-1 - right) === text.at(-1 - right)) right++;
          const count = text.length - left - right;
          const links = M.spliceLinks(old, left, old.text.length - right, text.slice(left, text.length - right));
          if (links.length) { old.links = links; plain[index].links = M.clone(links); }
          else { delete old.links; delete plain[index].links; }
          const mask = before.pending ?? old.marks[Math.max(0, left - 1)] ?? 0;
          old.marks.splice(left, old.text.length - left - right, ...Array(count).fill(mask));
          plain[index].marks.splice(left, old.text.length - left - right, ...Array(count).fill(0));
          plain[index].text = text;
          old.text = text;
        });
        const admitted = this.admitInput(M.normalize(rows), M.normalize(plain));
        P.assertRows(admitted.rows, this.policy);
        this.rows = admitted.rows;
        this.clearInvalid();
        this.range = M.selection(this.rows, afterRange.start, afterRange.end);
        if (JSON.stringify(this.rows) === JSON.stringify(before.rows)) {
          this.render(); this.restoreSelection(); this.updateButtons(); return;
        }
        this.dirty = true;
        if (admitted.restricted) this.pending = 0;
        this.record(before);
        this.render();
        this.restoreSelection();
        this.message(admitted.restricted ? translate("Text inserted without new formatting: Markdown cannot represent this combination.") : translate("Text input completed."));
      } catch (error) {
        this.restore(before);
        this.message(error.message);
      }
    }

    clipboard(event, cut) {
      if (this.composing || !event.clipboardData) return;
      this.capture();
      if (collapsed(this.range)) return;
      event.preventDefault();
      const { start, end } = this.range;
      const text = this.rows.slice(start.row, end.row + 1).map((item, index, all) =>
        item.text.slice(index ? 0 : start.offset, index === all.length - 1 ? end.offset : undefined)).join('\n');
      event.clipboardData.setData('text/plain', text);
      if (cut) this.change((rows, range) => M.replace(rows, range, ''));
    }

    key(event) {
      if (event.isComposing || this.composing) return;
      const mod = event.metaKey || event.ctrlKey;
      const key = event.key.toLowerCase();
      // Physical T survives Option-produced characters and non-Latin layouts.
      const toolbarShortcut = event.altKey && !mod && (
        key === 'f10' && !event.shiftKey || event.shiftKey && (event.code === 'KeyT' || key === 't')
      );
      if (toolbarShortcut) {
        this.updateToolbarTabstop();
        if (this.toolbarButton) { event.preventDefault(); this.capture(); this.toolbarButton.focus(); }
      } else if (mod && !event.altKey && (key === 'z' || key === 'y' && event.ctrlKey)) {
        event.preventDefault(); this.history(event.shiftKey || key === 'y');
      } else if (this.mode === 'visual' && mod && !event.altKey && event.shiftKey && key === 'x') {
        event.preventDefault(); this.command('strike');
      } else if (this.mode === 'visual' && mod && !event.altKey && ['b', 'i', 'e', 'k'].includes(key)) {
        event.preventDefault(); this.command({ b: 'bold', i: 'italic', e: 'code', k: 'link' }[key]);
      } else if (this.mode === 'visual' && event.key === 'Escape') {
        this.tabExit = true;
        this.message(translate("The next Tab leaves the editor."));
      } else if (this.mode === 'visual' && event.key === 'Tab' && !mod && !event.altKey) {
        if (this.tabExit) { this.tabExit = false; return; }
        this.capture();
        if (this.rows[this.range.start.row].depth) { event.preventDefault(); this.command(event.shiftKey ? 'outdent' : 'indent'); }
      }
    }

    /** Switch atomically; rejected imports/exports preserve the active editing surface. */
    toggleMode() {
      if (this.composing || this.destroyed || this.policy.mode !== 'visual') return false;
      this.capture();
      const before = this.snapshot();
      try {
        if (this.mode === 'visual') {
          // Empty source must remain reachable so a blank comment can be written in Markdown.
          const exported = M.toCommentMarkdown(this.rows, true);
          P.assertMarkdown(exported, this.policy);
          this.sourceText = this.dirty ? exported : this.sourceText;
          this.visualSource = this.sourceText;
          this.source.value = this.sourceText;
          this.mode = 'source';
        } else {
          P.assertMarkdown(this.source.value, this.policy);
          const rows = this.source.value === this.visualSource ? this.rows : M.fromMarkdown(this.source.value);
          this.rows = rows;
          this.sourceText = this.source.value;
          this.dirty = false;
          this.mode = 'visual';
          this.range = M.selection(rows, this.range.start, this.range.end);
        }
        this.pending = null;
        this.clearInvalid();
        this.record(before);
        this.render();
        if (this.mode === 'source') this.source.focus(); else this.restoreSelection();
        this.message('');
        this.updateButtons();
        return true;
      } catch (error) {
        const recovery = this.mode === 'visual' ? translate(" Select text and use Clear formatting; Ctrl/Cmd+A selects the entire comment.") : '';
        this.message(error.message + recovery);
        return false;
      }
    }

    destroy() {
      if (this.destroyed) return;
      this.controller.abort();
      this.past.length = 0;
      this.future.length = 0;
      this.nativeBefore = null;
      this.sourceBefore = null;
      this.sourceCompositionBefore = null;
      this.destroyed = true;
      this.root.contentEditable = 'false';
    }
  }
  globalThis.CommentailVisualEditor = Object.freeze({ Editor });
})();
