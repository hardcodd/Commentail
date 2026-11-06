/* Markdown typing rules operate on text/model data, never browser HTML. */
(() => {
  'use strict';
  const M = globalThis.CommentailEditorModel;
  const P = globalThis.CommentailEditorPolicy;

  /** Called only after a single typed character, or before a fence-opening Enter.
   * Paste, replacement input and composition never enter this path. Failed or
   * disabled conversions return null and leave every literal character intact.
   * Inline candidates are bounded and must parse as one complete styled node.
   */
  function apply(rows, range, typed, policy) {
    if (policy.mode !== 'visual') return null;
    const { start, end } = M.selection(rows, range.start, range.end);
    if (start.row !== end.row || start.offset !== end.offset) return null;
    const item = rows[start.row], offset = start.offset;
    if (item.kind === 'pre' || item.marks[offset - 1] & M.CODE) return null;
    const prefix = item.text.slice(0, offset);
    let result = null;
    const block = typed === ' ' && /^(?:[-+*]|\d{1,9}[.)]|>) $/.test(prefix);
    const fence = typed === '\n' && /^(?:`{3}|~{3})$/.test(prefix) && offset === item.text.length;
    if (item.kind === 'p' && (block || fence) && item.marks.slice(0, offset).every(mark => !mark) && !item.links?.length) {
      const kind = fence ? 'pre' : prefix[0] === '>' ? 'quote' : /^\d/.test(prefix) ? 'ol' : 'ul';
      const feature = { pre: 'codeBlock', quote: 'quote', ol: 'orderedList', ul: 'unorderedList' }[kind];
      if (!policy.features.includes(feature)) return null;
      result = M.replace(rows, { start: { row: start.row, offset: 0 }, end: start }, '');
      Object.assign(result.rows[start.row], { kind, depth: ['ol', 'ul'].includes(kind) ? 1 : 0, start: kind === 'ol' ? Number.parseInt(prefix, 10) : 1 });
    } else if ('*_~`)'.includes(typed)) {
      // At most 512 UTF-16 units and 64 possible openings per keystroke.
      let attempts = 0;
      for (let left = Math.max(0, offset - 512); left < offset - 1 && attempts < 64; left++) {
        if (!'*_~`['.includes(prefix[left])) continue;
        attempts++;
        let escapes = 0;
        for (let index = left - 1; index >= 0 && prefix[index] === '\\'; index--) escapes++;
        if (escapes % 2 || item.marks.slice(left, offset).some(Boolean) ||
            item.links?.some(link => link.start < offset && link.end > left)) continue;
        // Intraword underscores and a suffix of a larger delimiter stay literal.
        if (prefix[left - 1] === prefix[left] || prefix[left] === '_' && /[\p{L}\p{N}]/u.test(prefix[left - 1] ?? '')) continue;
        const source = prefix.slice(left);
        if (source.includes('\n')) continue;
        try {
          const ast = globalThis.CommentailMarkdown.parseMarkdown(source);
          const nodes = ast.children[0]?.children;
          if (ast.children.length !== 1 || ast.children[0].type !== 'paragraph' || nodes?.length !== 1 ||
              !['strong', 'emphasis', 'strike', 'code', 'link'].includes(nodes[0].type)) continue;
          const imported = M.fromMarkdown(source);
          if (imported.length !== 1 || imported[0].text.includes('\n')) continue;
          P.assertRows(imported, policy);
          result = M.replace(rows, { start: { row: start.row, offset: left }, end: start }, imported[0].text);
          result.rows[start.row].marks.splice(left, imported[0].text.length, ...imported[0].marks);
          for (const link of imported[0].links ?? []) {
            result.rows = M.applyLink(result.rows, { start: { row: start.row, offset: left + link.start },
              end: { row: start.row, offset: left + link.end } }, link.href).rows;
          }
          break;
        } catch (error) {
          if (!(error instanceof M.EditorError) && !(error instanceof globalThis.CommentailMarkdown.MarkdownLimitError)) throw error;
        }
      }
    }
    if (!result) return null;
    try {
      result.rows = M.normalize(result.rows);
      P.assertRows(result.rows, policy);
      M.toCommentMarkdown(result.rows, true);
      return result;
    } catch (error) {
      if (!(error instanceof M.EditorError) && !(error instanceof globalThis.CommentailMarkdown.MarkdownLimitError)) throw error;
      return null;
    }
  }

  globalThis.CommentailEditorShortcuts = Object.freeze({ apply });
})();
