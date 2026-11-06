/* Original, dependency-free editing model. UTF-16 offsets match DOM Selection. */
(() => {
  'use strict';
  /** @typedef {{start:number,end:number,href:string}} Link
   * @typedef {{text:string, kind:'p'|'ol'|'ul'|'pre'|'quote', depth:number, start:number, marks:number[], links?:Link[]}} Row
   * @typedef {{row:number, offset:number}} Point
   * @typedef {{start:Point, end:Point}} ModelRange
   */
  const core = globalThis.CommentailMarkdown;
  const BOLD = 1, ITALIC = 2, CODE = 4, STRIKE = 8;
  const LIMITS = Object.freeze({ text: 20000, rows: 1000, depth: 8 });
  class EditorError extends Error {}

  /** Create an editable block; marks are per UTF-16 unit, never HTML. */
  function row(text = '', kind = 'p', depth = 0, start = 1, marks = null) {
    return { text, kind, depth, start, marks: marks ?? Array(text.length).fill(0) };
  }
  const clone = value => structuredClone(value);

  /** Canonical link addresses use the same policy as Markdown rendering. */
  function linkURL(value) {
    const href = typeof value === 'string' && value.length <= 2048 ? core.safeURL(value) : null;
    if (!href || href.length > 2048) throw new EditorError(translate("Enter a full http://, https:// or mailto: address without spaces, credentials or controls (up to 2048 characters)."));
    return href;
  }

  /** Expand sparse spans only while editing/rendering; history stores each URL once. */
  function linkValues(item) {
    const values = Array(item.text.length).fill(null);
    for (const link of item.links ?? []) values.fill(link.href, link.start, link.end);
    return values;
  }

  function assignLinks(item, values) {
    const spans = [];
    for (let start = 0; start < values.length;) {
      let end = start + 1;
      while (end < values.length && values[end] === values[start]) end++;
      if (values[start]) spans.push({ start, end, href: values[start] });
      start = end;
    }
    if (spans.length) item.links = spans;
    else delete item.links;
    return item;
  }

  /** Insertions inherit only inside a link; edges and newlines start plain text. */
  function insertionLink(item, start, end, value) {
    if (value.includes('\n')) return null;
    return item.links?.find(link => start === end ? link.start < start && start < link.end :
      link.start <= start && end <= link.end)?.href ?? null;
  }

  /** Remap spans after a native single-row text edit without reading browser HTML. */
  function spliceLinks(item, start, end, value) {
    if (!item.links?.length) return [];
    const values = linkValues(item);
    return assignLinks({}, [...values.slice(0, start), ...Array(value.length).fill(insertionLink(item, start, end, value)), ...values.slice(end)]).links ?? [];
  }

  /** Validate/canonicalize a fresh model. Never mutate the caller's rows. */
  function normalize(input) {
    if (!Array.isArray(input) || input.length > LIMITS.rows) throw new EditorError(translate("Too many blocks (maximum 1000)."));
    let total = 0;
    for (const item of input) {
      if (!item || typeof item.text !== 'string') throw new EditorError(translate("Invalid editor model."));
      total += item.text.length;
      if (total > LIMITS.text) throw new EditorError(translate("The visual editor is limited to 20,000 UTF-16 units."));
    }
    const rows = clone(input.length ? input : [row()]);
    let length = 0, urlLength = 0;
    const levels = [];
    for (const item of rows) {
      if (!['p', 'ol', 'ul', 'pre', 'quote'].includes(item.kind) || typeof item.text !== 'string' ||
          !Array.isArray(item.marks) || item.marks.length !== item.text.length ||
          item.marks.some(mark => !Number.isInteger(mark) || mark < 0 || mark > 15) ||
          !Number.isInteger(item.depth) || item.depth < 0 || item.depth > LIMITS.depth ||
          !Number.isInteger(item.start) || item.start < 0 || item.start > 999999999) throw new EditorError(translate("Invalid editor model."));
      length += item.text.length;
      if (length > LIMITS.text) throw new EditorError(translate("The visual editor is limited to 20,000 UTF-16 units."));
      if (item.links !== undefined) {
        if (!Array.isArray(item.links) || item.links.length > 1000) throw new EditorError(translate("Invalid links."));
        let end = 0;
        for (const link of item.links) {
          if (!link || !Number.isInteger(link.start) || !Number.isInteger(link.end) || link.start < end ||
              link.start < 0 || link.end <= link.start || link.end > item.text.length || item.kind === 'pre' ||
              item.text.slice(link.start, link.end).includes('\n')) throw new EditorError(translate("A link must stay in one paragraph, without line breaks or block code."));
          link.href = linkURL(link.href);
          urlLength += link.href.length;
          if (urlLength > 100000) throw new EditorError(translate("Total link address length exceeds the editor limit."));
          end = link.end;
        }
        assignLinks(item, linkValues(item));
      }
      if (item.kind === 'p' || item.kind === 'pre' || item.kind === 'quote') {
        item.depth = 0;
        item.start = 1;
        levels.length = 0;
      } else {
        item.depth = Math.max(1, Math.min(item.depth, levels.length + 1));
        const previous = levels[item.depth - 1];
        if (item.kind === 'ul') item.start = 1;
        else if (previous?.kind === item.kind) item.start = previous.start + 1;
        if (item.start > 999999999) throw new EditorError(translate("List item number is too large."));
        levels.length = item.depth;
        levels[item.depth - 1] = item;
      }
      // A hard break is structure, not a styled glyph (including inline code).
      item.marks = item.marks.map((mark, index) => item.kind === 'pre' || item.text[index] === '\n' ? 0 : mark & CODE ? CODE : mark);
      // Markdown cannot emphasize boundary whitespace. Remove only that styling.
      for (const bit of [BOLD, ITALIC, STRIKE]) {
        for (let i = 0; i < item.text.length;) {
          if (!(item.marks[i] & bit)) { i++; continue; }
          let end = i;
          while (end < item.text.length && item.marks[end] & bit) end++;
          let left = i, right = end;
          while (left < right && /\s/u.test(item.text[left])) item.marks[left++] &= ~bit;
          while (right > left && /\s/u.test(item.text[right - 1])) item.marks[--right] &= ~bit;
          i = end;
        }
      }
    }
    return rows;
  }

  /** Import only the prototype's editable subset. Unsupported syntax stays in source. */
  function fromMarkdown(source) {
    const ast = core.parseMarkdown(source);
    const result = [];
    function inline(nodes, mask = 0, href = null) {
      let text = '', marks = [], links = [];
      for (const node of nodes) {
        let part;
        if (node.type === 'text' || node.type === 'code') {
          if (node.type === 'code' && mask) throw new EditorError(translate("Formatted inline code is available in Markdown source."));
          part = { text: node.value, marks: Array(node.value.length).fill(node.type === 'code' ? CODE : mask) };
        } else if (node.type === 'softBreak' || node.type === 'hardBreak') {
          part = { text: node.type === 'softBreak' ? ' ' : '\n', marks: [0] };
        } else if (['strong', 'emphasis', 'strike'].includes(node.type)) {
          part = inline(node.children, mask | (node.type === 'strong' ? BOLD : node.type === 'strike' ? STRIKE : ITALIC), href);
        } else if (node.type === 'link' && !href) {
          part = inline(node.children, mask, linkURL(node.href));
        } else throw new EditorError(translate("The visual editor supports bold, italic, strikethrough, code, links, quotes and lists. Other formatting stays in Markdown."));
        text += part.text;
        marks.push(...part.marks);
        links.push(...(part.links ?? Array(part.text.length).fill(href)));
      }
      return { text, marks, links };
    }
    function paragraph(node, kind = 'p', depth = 0, start = 1) {
      const value = inline(node?.children ?? []);
      result.push(assignLinks(row(value.text, kind, depth, start, value.marks), value.links));
    }
    function blocks(nodes, depth = 0) {
      for (const node of nodes) {
        if (node.type === 'paragraph' && depth === 0) paragraph(node);
        else if (node.type === 'quote' && depth === 0) {
          if (node.children.some(child => child.type !== 'paragraph')) {
            throw new EditorError(translate("Nested quotes and lists or block code inside quotes are available in Markdown source."));
          }
          if (!node.children.length) result.push(row('', 'quote'));
          else for (const child of node.children) paragraph(child, 'quote');
        } else if (node.type === 'codeBlock' && depth === 0 && !node.language) {
          result.push(row(node.value.replace(/\n$/, ''), 'pre'));
        } else if (node.type === 'list') {
          node.children.forEach((item, index) => {
            const paragraphs = item.children.filter(child => child.type === 'paragraph');
            if (paragraphs.length > 1 || item.children.some(child => !['paragraph', 'list'].includes(child.type)) ||
                (paragraphs.length && item.children[0].type !== 'paragraph')) throw new EditorError(translate("Complex list items are available in Markdown source."));
            paragraph(paragraphs[0], node.ordered ? 'ol' : 'ul', depth + 1, node.start + index);
            blocks(item.children.filter(child => child.type === 'list'), depth + 1);
          });
        } else throw new EditorError(translate("Complex quotes and code with a language are edited in Markdown source."));
      }
    }
    blocks(ast.children);
    const normalized = normalize(result);
    if (result.some((item, index) => item.kind === 'ol' && item.start !== normalized[index].start)) {
      throw new EditorError(translate("Separate adjacent ordered lists are available in Markdown source."));
    }
    return normalized;
  }

  const escape = text => text.replace(/[!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]/g, '\\$&');
  function codeSpan(text) {
    if (text.includes('\n')) throw new EditorError(translate("Use a code block for multiline code."));
    const fence = '`'.repeat(Math.max(0, ...Array.from(text.matchAll(/`+/g), match => match[0].length)) + 1);
    const pad = /^[` ]|[` ]$/.test(text) && !/^ +$/.test(text) ? ' ' : '';
    return fence + pad + text + pad + fence;
  }
  function inlineSource(item, bold, italic, stacked, italicFirst = false, linkFirst = true, strikeFirst = false) {
    let output = '', active = [];
    const symbols = { [BOLD]: bold, [ITALIC]: italic, [STRIKE]: '~~' };
    const links = item.links?.length ? linkValues(item) : null;
    const open = token => typeof token === 'number' ? symbols[token] : '[';
    const close = token => typeof token === 'number' ? symbols[token] : '](' + token.replace(/[\\()<>]/g, '\\$&') + ')';
    for (let i = 0; i < item.text.length;) {
      const mark = item.marks[i];
      let end = i + 1;
      while (end < item.text.length && item.marks[end] === mark && (!links || links[end] === links[i])) end++;
      const order = italicFirst ? [ITALIC, BOLD] : [BOLD, ITALIC];
      if (strikeFirst) order.unshift(STRIKE); else order.push(STRIKE);
      const desired = order.filter(bit => mark & bit);
      if (links?.[i]) { if (linkFirst) desired.unshift(links[i]); else desired.push(links[i]); }
      let shared = 0;
      if (stacked) while (shared < active.length && active[shared] === desired[shared]) shared++;
      for (let j = active.length - 1; j >= shared; j--) output += close(active[j]);
      for (let j = shared; j < desired.length; j++) output += open(desired[j]);
      active = desired;
      const text = item.text.slice(i, end);
      output += mark & CODE ? codeSpan(text) : escape(text).replaceAll('\n', '\\\n');
      i = end;
    }
    for (let j = active.length - 1; j >= 0; j--) output += close(active[j]);
    return output;
  }

  function signature(rows) {
    return JSON.stringify(normalize(rows).filter(item => item.kind !== 'p' || item.text).map(item =>
      [item.kind, item.depth, item.kind === 'ol' ? item.start : 1, item.text, item.marks, ...(item.links?.length ? [item.links] : [])]));
  }

  const encodingError = () => new EditorError(translate("Markdown cannot exactly represent this formatting combination. Text and previous formatting are kept."));

  /** Bounded fallback for short, densely formatted fragments. Keep the shortest
   * verified prefix for each closing delimiter spelling; later runs can merge
   * delimiter runs, so retaining only one prefix would discard valid solutions.
   * The normal linear strategies handle long text; this search has explicit caps.
   */
  function encodeRuns(item) {
    if (item.text.length > 256) return null;
    const runs = [];
    for (let start = 0; start < item.text.length;) {
      let end = start + 1;
      while (end < item.text.length && item.marks[end] === item.marks[start]) end++;
      runs.push({ start, end, mark: item.marks[start] });
      start = end;
    }
    if (runs.length > 32) return null;
    let candidates = [''];
    const wrappers = { 0: [['', '']], 1: [['**', '**'], ['__', '__']], 2: [['*', '*'], ['_', '_']],
      3: [['***', '***'], ['___', '___'], ['**_', '_**'], ['__*', '*__'], ['_**', '**_'], ['*__', '__*']] };
    for (const bit of [0, BOLD, ITALIC, BOLD | ITALIC]) {
      wrappers[bit | STRIKE] = wrappers[bit].flatMap(([open, close]) =>
        [['~~' + open, close + '~~'], [open + '~~', '~~' + close]]);
    }
    for (const run of runs) {
      const text = item.text.slice(run.start, run.end);
      const options = run.mark & CODE ? [['', codeSpan(text), '']] :
        wrappers[run.mark].map(([open, close]) => [open, escape(text).replaceAll('\n', '\\\n'), close]);
      const expected = signature([row(item.text.slice(0, run.end), 'p', 0, 1, item.marks.slice(0, run.end))]);
      const next = new Map();
      for (const prefix of candidates) {
        for (const [open, body, close] of options) {
          const source = prefix + open + body + close;
          try {
            if (signature(fromMarkdown(source)) !== expected) continue;
          } catch (error) { if (!(error instanceof EditorError)) throw error; continue; }
          const key = /[*_`~]+$/.exec(source)?.[0] ?? '';
          if (!next.has(key) || source.length < next.get(key).length) next.set(key, source);
        }
      }
      candidates = [...next.values()];
      if (!candidates.length) return null;
    }
    return candidates.sort((a, b) => a.length - b.length)[0] ?? null;
  }

  /** Choose delimiters locally: different words/blocks can require different nesting.
   * Whitespace with no mark separates independent spans. Never split styled spaces
   * or code, and always verify the combined source again before exporting it.
   */
  function encodeInline(item, split = true) {
    const expected = signature([{ ...item, kind: 'p', depth: 0, start: 1 }]);
    const matches = source => {
      try { return signature(fromMarkdown(source)) === expected; }
      catch (error) { if (!(error instanceof EditorError)) throw error; return false; }
    };
    for (const italicFirst of [false, true]) {
      for (const stacked of [true, false]) {
        for (const [bold, italic] of [['**', '*'], ['**', '_'], ['__', '*'], ['__', '_']]) {
          for (const linkFirst of item.links?.length ? [true, false] : [true]) {
            for (const strikeFirst of item.marks.some(mark => mark & STRIKE) ? [false, true] : [false]) {
              const source = inlineSource(item, bold, italic, stacked, italicFirst, linkFirst, strikeFirst);
              if (matches(source)) return source;
            }
          }
        }
      }
    }
    if (item.links?.length) throw encodingError();
    if (split) {
      let source = '', start = 0;
      try {
        for (let index = 0; index <= item.text.length; index++) {
          if (index !== item.text.length && !(item.marks[index] === 0 && /[ \t]/.test(item.text[index]))) continue;
          if (index > start) source += encodeInline(row(item.text.slice(start, index), 'p', 0, 1, item.marks.slice(start, index)), false);
          if (index < item.text.length) source += item.text[index];
          start = index + 1;
        }
        if (matches(source)) return source;
      } catch (error) { if (!(error instanceof EditorError)) throw error; }
    }
    const source = encodeRuns(item);
    if (source !== null && matches(source)) return source;
    throw encodingError();
  }

  /** Serialize semantically, with parser verification: fail rather than silently lose formatting. */
  function toMarkdown(input) {
    const rows = normalize(input);
    const expected = signature(rows);
    const indents = [''];
    const output = [];
    for (const item of rows) {
      if (item.kind === 'pre') {
        const fence = '~'.repeat(Math.max(2, ...Array.from(item.text.matchAll(/~+/g), match => match[0].length)) + 1);
        output.push(fence + '\n' + item.text + '\n' + fence);
      } else if (item.kind === 'p' || item.kind === 'quote') {
        indents.length = 1;
        const content = encodeInline(item);
        output.push(item.kind === 'quote' ? '> ' + content.replaceAll('\n', '\n> ') : content);
      } else {
        const indent = indents[item.depth - 1];
        const marker = item.kind === 'ol' ? item.start + '. ' : '- ';
        indents.length = item.depth + 1;
        indents[item.depth] = indent + ' '.repeat(marker.length);
        output.push(indent + marker + encodeInline(item).replaceAll('\n', '\n' + indents[item.depth]));
      }
    }
    const source = output.join('\n\n');
    try { if (signature(fromMarkdown(source)) === expected) return source; }
    catch (error) { if (!(error instanceof EditorError)) throw error; }
    throw encodingError();
  }

  /** Comment export policy on a copy, separate from live editing and strict
   * serialization. Trim only ordinary ASCII boundary whitespace; code is data.
   * @param {Row[]} input
   * @returns {Row[]} Fresh rows with aligned marks and unchanged list structure.
   */
  function normalizeForExport(input) {
    const rows = normalize(input);
    for (const item of rows) {
      if (item.kind === 'pre') continue;
      let left = 0, right = item.text.length;
      while (left < right && !(item.marks[left] & CODE) && /[ \t]/.test(item.text[left])) left++;
      while (right > left && !(item.marks[right - 1] & CODE) && /[ \t\n]/.test(item.text[right - 1])) right--;
      if (item.links?.length) assignLinks(item, linkValues(item).slice(left, right));
      item.text = item.text.slice(left, right);
      item.marks = item.marks.slice(left, right);
    }
    while (rows.length && rows[0].kind === 'p' && !rows[0].text) rows.shift();
    while (rows.length && rows.at(-1).kind === 'p' && !rows.at(-1).text) rows.pop();
    return rows.length ? rows : [row()];
  }

  /** Export the agreed comment policy without changing live rows. Empty input is
   * allowed only for intermediate formatting checks, never for final export.
   * @param {Row[]} input
   * @param {boolean} [allowEmpty=false]
   * @returns {string} Verified Markdown; throws EditorError on empty/unsupported input.
   */
  function toCommentMarkdown(input, allowEmpty = false) {
    const rows = normalizeForExport(input);
    const hasContent = rows.some(item => item.kind === 'pre' || /\S/u.test(item.text) ||
      item.marks.some(mark => mark & CODE));
    if (!allowEmpty && !hasContent) throw new EditorError(translate("Enter your comment."));
    return toMarkdown(rows);
  }

  /** Clear inline marks/links in a range, keeping block structure and exact text.
   * Fenced-code contents are data; a collapsed range does not change the model.
   * @param {Row[]} input
   * @param {ModelRange} range
   * @returns {Row[]} Independent rows; unsupported marks may remain outside the range.
   */
  function clearFormatting(input, range) {
    const rows = normalize(input);
    const { start, end } = selection(rows, range.start, range.end);
    for (let index = start.row; index <= end.row; index++) {
      const item = rows[index];
      if (item.kind === 'pre') continue;
      const left = index === start.row ? start.offset : 0;
      const right = index === end.row ? end.offset : item.text.length;
      item.marks.fill(0, left, right);
      if (item.links?.length) {
        const values = linkValues(item);
        values.fill(null, left, right);
        assignLinks(item, values);
      }
    }
    return rows;
  }

  /** Ordered, clamped selection; directional anchor/focus remain a controller concern. */
  function selection(rows, anchor, focus = anchor) {
    const point = value => {
      const r = Math.max(0, Math.min(rows.length - 1, value.row));
      return { row: r, offset: Math.max(0, Math.min(rows[r].text.length, value.offset)) };
    };
    const a = point(anchor), b = point(focus);
    return a.row < b.row || a.row === b.row && a.offset <= b.offset ? { start: a, end: b } : { start: b, end: a };
  }

  /** Replace a model range. Newlines create blocks, except within a code block. */
  function replace(input, range, value, mask = 0, soft = false) {
    if (typeof value !== 'string' || value.length > LIMITS.text + 2 * LIMITS.rows) throw new EditorError(translate("Pasted text exceeds the editor limit."));
    const rows = clone(input);
    const { start, end } = selection(rows, range.start, range.end);
    value = value.replace(/\r\n?/g, '\n').replaceAll('\0', '\ufffd');
    const first = rows[start.row], last = rows[end.row];
    const prefix = first.text.slice(0, start.offset), suffix = last.text.slice(end.offset);
    const leftMarks = first.marks.slice(0, start.offset), rightMarks = last.marks.slice(end.offset);
    const parts = soft || first.kind === 'pre' ? [value] : value.split('\n');
    if (parts.length + rows.length - (end.row - start.row + 1) > LIMITS.rows) throw new EditorError(translate("Too many blocks (maximum 1000)."));
    const replacement = parts.map((part, index) => ({ ...first, text: part, start: index ? 1 : first.start, marks: Array(part.length).fill(mask) }));
    if (first.links?.length || last.links?.length) {
      const inherited = start.row === end.row && parts.length === 1 ? insertionLink(first, start.offset, end.offset, value) : null;
      replacement.forEach((item, index) => assignLinks(item, [
        ...(index === 0 ? linkValues(first).slice(0, start.offset) : []),
        ...Array(parts[index].length).fill(inherited),
        ...(index === parts.length - 1 ? linkValues(last).slice(end.offset) : [])
      ]));
      // Joining into fenced code keeps the characters as literal code, not anchors.
      if (first.kind === 'pre') for (const item of replacement) delete item.links;
    }
    replacement[0].text = prefix + replacement[0].text;
    replacement[0].marks = leftMarks.concat(replacement[0].marks);
    const tail = replacement.at(-1);
    const offset = tail.text.length;
    tail.text += suffix;
    tail.marks.push(...rightMarks);
    rows.splice(start.row, end.row - start.row + 1, ...replacement);
    return { rows: normalize(rows), point: { row: start.row + parts.length - 1, offset } };
  }

  function format(input, range, bit) {
    if (![BOLD, ITALIC, CODE, STRIKE].includes(bit)) throw new EditorError(translate("Unknown format."));
    const rows = clone(input);
    const { start, end } = selection(rows, range.start, range.end);
    let all = true, count = 0;
    for (let r = start.row; r <= end.row; r++) {
      for (let i = r === start.row ? start.offset : 0; i < (r === end.row ? end.offset : rows[r].text.length); i++) {
        if (rows[r].kind === 'pre') continue;
        count++;
        all &&= Boolean(rows[r].marks[i] & bit);
      }
    }
    if (!count) return rows;
    for (let r = start.row; r <= end.row; r++) {
      for (let i = r === start.row ? start.offset : 0; i < (r === end.row ? end.offset : rows[r].text.length); i++) {
        if (rows[r].kind === 'pre') continue;
        rows[r].marks[i] = all ? rows[r].marks[i] & ~bit : bit === CODE ? CODE : (rows[r].marks[i] & ~CODE) | bit;
      }
    }
    return normalize(rows);
  }

  /** A cursor or contained selection edits the whole existing link. */
  function linkTarget(input, range) {
    const selected = selection(input, range.start, range.end);
    const { start, end } = selected;
    let link = null;
    if (start.row === end.row) {
      const spans = input[start.row].links ?? [];
      link = spans.find(item => item.start <= start.offset && start.offset < item.end && end.offset <= item.end) ??
        (start.offset === end.offset ? spans.find(item => item.end === start.offset) : null);
    }
    return { href: link?.href ?? null, range: link ? { start: { row: start.row, offset: link.start }, end: { row: start.row, offset: link.end } } : selected };
  }

  /** Apply/remove a single-row link atomically; unchanged labels retain all marks. */
  function applyLink(input, range, value, label) {
    let rows = normalize(input);
    const { start, end } = selection(rows, range.start, range.end);
    if (start.row !== end.row || rows[start.row].kind === 'pre') throw new EditorError(translate("Select text in one paragraph outside block code."));
    const href = value === null ? null : linkURL(value);
    const previous = rows[start.row].text.slice(start.offset, end.offset);
    const text = href ? (label ?? (previous || href)) : previous;
    if (typeof text !== 'string' || text.includes('\n') || text.includes('\r') || href && !text.trim()) throw new EditorError(translate("Enter link text without line breaks."));
    let finish = end.offset;
    if (text !== previous) {
      const mask = rows[start.row].marks[start.offset] ?? 0;
      rows = replace(rows, { start, end }, text, mask).rows;
      finish = start.offset + text.length;
    }
    const item = rows[start.row];
    const values = linkValues(item); values.fill(href, start.offset, finish);
    assignLinks(item, values);
    return { rows: normalize(rows), point: { row: start.row, offset: finish } };
  }

  /** Structural operations include descendants, so moving a parent preserves its subtree. */
  function structure(input, range, command) {
    const rows = clone(input);
    const { start, end } = selection(rows, range.start, range.end);
    if (end.row > start.row && end.offset === 0) end.row--;
    let last = end.row;
    while (rows[end.row].depth > 0 && last + 1 < rows.length && rows[last + 1].depth > rows[end.row].depth) last++;
    if (command === 'indent') {
      if (!rows[start.row].depth || start.row === 0 || rows[start.row - 1].depth < rows[start.row].depth) return rows;
      if (rows.slice(start.row, last + 1).some(item => item.depth >= LIMITS.depth)) throw new EditorError(translate("Lists support up to eight levels."));
      for (let i = start.row; i <= last; i++) rows[i].depth++;
      rows[start.row].start = 1;
    } else if (command === 'outdent') {
      for (let i = start.row; i <= last; i++) {
        if (!rows[i].depth) continue;
        rows[i].depth = Math.max(0, rows[i].depth - 1);
        if (!rows[i].depth) rows[i].kind = 'p';
      }
    } else if (['ol', 'ul', 'pre', 'quote'].includes(command)) {
      const remove = rows.slice(start.row, end.row + 1).every(item => item.kind === command);
      for (let i = start.row; i <= last; i++) {
        rows[i].kind = remove ? 'p' : command;
        rows[i].depth = remove || command === 'pre' || command === 'quote' ? 0 : Math.max(1, rows[i].depth);
        if (command === 'pre') rows[i].marks.fill(0);
        if (!remove && command === 'pre') delete rows[i].links;
      }
    } else throw new EditorError(translate("Unknown command."));
    return normalize(rows);
  }

  globalThis.CommentailEditorModel = Object.freeze({ BOLD, ITALIC, CODE, STRIKE, LIMITS, EditorError, row, normalize,
    fromMarkdown, toMarkdown, normalizeForExport, toCommentMarkdown, signature, selection, clearFormatting, replace, format, structure, clone,
    linkURL, linkValues, spliceLinks, linkTarget, applyLink });
})();
