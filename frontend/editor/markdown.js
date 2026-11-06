'use strict';
(() => {
const modules = Object.create(null);
modules["policy"] = (() => {
const FEATURES = Object.freeze([
  'bold', 'italic', 'strike', 'link', 'quote', 'unorderedList', 'orderedList', 'inlineCode', 'codeBlock',
]);

const DEFAULT_LIMITS = Object.freeze({
  maxLength: 100000, maxDepth: 32, maxNodes: 100000, maxWork: 2000000,
});

/** A rejected input is never silently truncated or partially rendered. */
class MarkdownLimitError extends RangeError {
  constructor(limit) {
    super(`Markdown limit exceeded: ${limit}`);
    this.name = 'MarkdownLimitError';
    this.limit = limit;
  }
}

/** Absolute web/mail links only; URL normalization is shared by all hosts.
 * Returns a canonical URL or null. Credentials, controls and backslashes fail.
 * @param {unknown} value
 * @returns {string|null}
 */
function safeURL(value) {
  if (typeof value !== 'string' || !value || /[\s\u0000-\u001f\u007f\\]/u.test(value)) return null;
  if (!/^(?:https?:\/\/|mailto:)/i.test(value)) return null;
  try {
    const url = new URL(value);
    if (url.username || url.password) return null;
    if (url.protocol === 'mailto:') {
      if (!url.pathname || /%0[ad]/i.test(value)) return null;
    } else if (!url.hostname) return null;
    return url.href;
  } catch {
    return null;
  }
}

/** Validate configuration once and keep resource accounting per invocation. */
function createContext(options = {}) {
  if (options === null || typeof options !== 'object' || Array.isArray(options)) {
    throw new TypeError('Expected an options object');
  }
  for (const key of Object.keys(options)) {
    if (!Object.hasOwn(DEFAULT_LIMITS, key) && key !== 'features') throw new TypeError(`Unknown option: ${key}`);
  }
  const limits = { ...DEFAULT_LIMITS };
  for (const key of Object.keys(limits)) {
    if (options[key] !== undefined) limits[key] = options[key];
    if (!Number.isSafeInteger(limits[key]) || limits[key] < 1 || limits[key] > DEFAULT_LIMITS[key]) {
      throw new TypeError(`Invalid ${key}: use a positive integer no greater than ${DEFAULT_LIMITS[key]}`);
    }
  }
  const values = options.features === undefined ? FEATURES : options.features;
  if (!Array.isArray(values) || values.some(value => !FEATURES.includes(value))) {
    throw new TypeError('Unknown or invalid features');
  }
  let work = 0;
  let nodes = 0;
  const heights = new WeakMap();
  return {
    limits, features: new Set(values),
    step(amount = 1) {
      work += amount;
      if (work > limits.maxWork) throw new MarkdownLimitError('maxWork');
    },
    depth(value) {
      if (value > limits.maxDepth) throw new MarkdownLimitError('maxDepth');
    },
    node(type, fields) {
      nodes += 1;
      if (nodes > limits.maxNodes) throw new MarkdownLimitError('maxNodes');
      // Reject deep inline trees during construction, before any recursive
      // consumer (including link validation) can visit an unsafe tree.
      let height = 0;
      for (const child of fields?.children || []) height = Math.max(height, heights.get(child) + 1);
      if (height > limits.maxDepth) throw new MarkdownLimitError('maxDepth');
      const node = { type, ...fields };
      heights.set(node, height);
      return node;
    },
  };
}

/** Escape every value emitted into HTML text or quoted attribute context. */
function escapeHTML(value) {
  return value.replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

return { FEATURES, DEFAULT_LIMITS, MarkdownLimitError, safeURL, createContext, escapeHTML };
})();
modules["inline"] = (() => {
const { safeURL } = modules["policy"];

const ASCII_PUNCTUATION = /^[!-/:-@\[-`{-~]$/;
const UNICODE_PUNCTUATION = /[\p{P}\p{S}]/u;
const isSpace = value => value === '' || /\s/u.test(value);
const isPunctuation = value => ASCII_PUNCTUATION.test(value) || UNICODE_PUNCTUATION.test(value);

/** Index code runs and balanced label brackets once, skipping literal code.
 * Same-length code delimiters bind before emphasis, escapes and links.
 */
function indexSyntax(source, context) {
  const runs = new Map();
  const positions = new Map();
  for (let index = 0; index < source.length;) {
    context.step();
    if (source[index] !== '`') { index += 1; continue; }
    let end = index + 1;
    while (source[end] === '`') end += 1;
    runs.set(index, end - index);
    if (!positions.has(end - index)) positions.set(end - index, []);
    positions.get(end - index).push(index);
    index = end;
  }
  function codeAt(index) {
    let length = runs.get(index);
    // An escaped first tick can leave a shorter opening run behind it.
    if (length === undefined) {
      let end = index + 1;
      while (source[end] === '`') end += 1;
      length = end - index;
    }
    const candidates = positions.get(length) || [];
    let low = 0;
    let high = candidates.length;
    while (low < high) {
      context.step();
      const middle = Math.floor((low + high) / 2);
      if (candidates[middle] <= index) low = middle + 1;
      else high = middle;
    }
    return { length, close: candidates[low] };
  }
  const brackets = new Map();
  const stack = [];
  for (let index = 0; index < source.length; index += 1) {
    context.step();
    if (source[index] === '\\' && ASCII_PUNCTUATION.test(source[index + 1] || '')) { index += 1; continue; }
    if (source[index] === '`') {
      const { length, close } = codeAt(index);
      index = close === undefined ? index + length - 1 : close + length - 1;
      continue;
    }
    if (source[index] === '[') stack.push(index);
    if (source[index] === ']' && stack.length) brackets.set(stack.pop(), index);
  }
  return { codeAt, brackets };
}

/** Parse a destination without interpreting HTML/entities or link titles. */
function destination(source, start, context) {
  if (source[start] !== '(') return null;
  let index = start + 1;
  let value = '';
  let depth = 0;
  const angled = source[index] === '<';
  if (angled) index += 1;
  for (; index < source.length; index += 1) {
    context.step();
    const character = source[index];
    if (character === '\\' && ASCII_PUNCTUATION.test(source[index + 1] || '')) {
      value += source[++index];
      continue;
    }
    if (angled) {
      if (character === '>' && source[index + 1] === ')') {
        return { value, end: index + 2 };
      }
      if (/[\s<>]/u.test(character)) return null;
    } else {
      if (character === '(') { depth += 1; context.depth(depth); }
      if (character === ')') {
        if (!depth) return { value, end: index + 1 };
        depth -= 1;
      }
      if (/\s/u.test(character)) return null;
    }
    value += character;
  }
  return null;
}

function flanking(source, start, end, marker) {
  const before = Array.from(source.slice(Math.max(0, start - 2), start)).at(-1) || '';
  const after = Array.from(source.slice(end, end + 2))[0] || '';
  const left = !isSpace(after) && (!isPunctuation(after) || isSpace(before) || isPunctuation(before));
  const right = !isSpace(before) && (!isPunctuation(before) || isSpace(after) || isPunctuation(after));
  return {
    open: left && (marker !== '_' || !right || isPunctuation(before)),
    close: right && (marker !== '_' || !left || isPunctuation(after)),
  };
}

/** Resolve marker runs with linked tokens so wrapping never slices the document.
 * Inactive delimiters cannot cross a completed pair; rule-of-three resolves
 * ambiguous emphasis. Work/depth budgets also cover adversarial arrangements.
 */
function resolveEmphasis(tokens, delimiters, context) {
  const head = { next: null };
  let tail = head;
  for (const node of tokens) {
    const item = { node, previous: tail, next: null };
    tail.next = item;
    tail = item;
    if (node.delimiter) node.delimiter.item = item;
  }
  function unlink(item) {
    item.previous.next = item.next;
    if (item.next) item.next.previous = item.previous;
  }
  for (let closerIndex = 0; closerIndex < delimiters.length; closerIndex += 1) {
    const closer = delimiters[closerIndex];
    while (closer.active && closer.close && closer.count > 0) {
      let openerIndex = closerIndex - 1;
      let opener;
      for (; openerIndex >= 0; openerIndex -= 1) {
        context.step();
        const candidate = delimiters[openerIndex];
        if (!candidate.active || !candidate.open || candidate.marker !== closer.marker || !candidate.count) continue;
        const ambiguous = (candidate.close || closer.open)
          && (candidate.original + closer.original) % 3 === 0
          && (candidate.original % 3 !== 0 || closer.original % 3 !== 0);
        if (candidate.marker !== '~' && ambiguous) continue;
        opener = candidate;
        break;
      }
      if (!opener) break;
      const amount = closer.marker === '~' ? 2 : Math.min(opener.count, closer.count) >= 2 ? 2 : 1;
      const children = [];
      let item = opener.item.next;
      while (item !== closer.item) {
        context.step();
        children.push(item.node);
        item = item.next;
      }
      if (!children.length) break;
      const type = closer.marker === '~' ? 'strike' : amount === 2 ? 'strong' : 'emphasis';
      const wrapped = { node: context.node(type, { children }), previous: opener.item, next: closer.item };
      opener.item.next = wrapped;
      closer.item.previous = wrapped;
      for (let index = openerIndex + 1; index < closerIndex; index += 1) delimiters[index].active = false;
      opener.count -= amount;
      closer.count -= amount;
      opener.item.node.value = opener.marker.repeat(opener.count);
      closer.item.node.value = closer.marker.repeat(closer.count);
      if (!opener.count) { unlink(opener.item); opener.active = false; }
      if (!closer.count) { unlink(closer.item); closer.active = false; }
    }
  }
  const result = [];
  for (let item = head.next; item; item = item.next) {
    delete item.node.delimiter;
    if (item.node.type === 'text' && !item.node.value) continue;
    const last = result.at(-1);
    if (last?.type === 'text' && item.node.type === 'text') last.value += item.node.value;
    else result.push(item.node);
  }
  // Delimiters nested inside a wrapper are internal metadata, never public AST.
  const stack = [...result];
  while (stack.length) {
    const node = stack.pop();
    delete node.delimiter;
    if (node.children) stack.push(...node.children);
  }
  return result;
}

/** Parse inline syntax into inert nodes. Raw HTML and entities remain text.
 * @param {string} source
 * @param {ReturnType<import('./policy.mjs').createContext>} context
 * @param {number} depth
 * @returns {Array<object>}
 */
function parseInline(source, context, depth) {
  context.depth(depth);
  const syntax = indexSyntax(source, context);
  const tokens = [];
  const delimiters = [];
  let text = '';
  const flush = () => {
    if (text) { tokens.push(context.node('text', { value: text })); text = ''; }
  };
  for (let index = 0; index < source.length;) {
    context.step();
    const character = source[index];
    if (character === '\\') {
      const after = source[index + 1];
      if (after === '\n') {
        flush(); tokens.push(context.node('hardBreak')); index += 2; continue;
      }
      if (ASCII_PUNCTUATION.test(after || '')) { text += after; index += 2; continue; }
    }
    if (character === '\n') {
      const trailing = / +$/.exec(text)?.[0].length || 0;
      if (trailing) text = text.slice(0, -trailing);
      flush();
      tokens.push(context.node(trailing >= 2 ? 'hardBreak' : 'softBreak'));
      index += 1;
      continue;
    }
    if (character === '`') {
      const { length, close } = syntax.codeAt(index);
      if (close !== undefined) {
        let value = source.slice(index + length, close).replaceAll('\n', ' ');
        if (value.startsWith(' ') && value.endsWith(' ') && /[^ ]/.test(value)) value = value.slice(1, -1);
        flush(); tokens.push(context.node('code', { value }));
        index = close + length;
        continue;
      }
      text += '`'.repeat(length);
      index += length;
      continue;
    }
    if (character === '[' && syntax.brackets.has(index)) {
      const close = syntax.brackets.get(index);
      const target = destination(source, close + 1, context);
      let slashes = 0;
      for (let before = index - 2; before >= 0 && source[before] === '\\'; before -= 1) slashes += 1;
      const image = index > 0 && source[index - 1] === '!' && slashes % 2 === 0;
      if (target && image) {
        text += source.slice(index, target.end);
        index = target.end;
        continue;
      }
      const href = target && safeURL(target.value);
      if (href && close > index + 1) {
        const children = parseInline(source.slice(index + 1, close), context, depth + 1);
        const containsLink = nodes => nodes.some(node => node.type === 'link' || (node.children && containsLink(node.children)));
        if (!containsLink(children)) {
          flush(); tokens.push(context.node('link', { href, children }));
          index = target.end;
          continue;
        }
      }
    }
    if (character === '*' || character === '_' || character === '~') {
      let end = index + 1;
      while (source[end] === character) end += 1;
      const count = end - index;
      if (character !== '~' || count === 2) {
        flush();
        const sides = flanking(source, index, end, character);
        const delimiter = { marker: character, count, original: count, ...sides, active: true };
        const node = context.node('text', { value: source.slice(index, end) });
        node.delimiter = delimiter;
        tokens.push(node);
        delimiters.push(delimiter);
      } else text += source.slice(index, end);
      index = end;
      continue;
    }
    text += character;
    index += 1;
  }
  flush();
  return resolveEmphasis(tokens, delimiters, context);
}

return { parseInline };
})();
modules["blocks"] = (() => {
const { parseInline } = modules["inline"];

const blank = line => /^[ \t]*$/.test(line);
const quote = line => /^ {0,3}>[ \t]?/.exec(line);
const fence = line => /^ {0,3}(`{3,}|~{3,})([^\n]*)$/.exec(line);

/** Only structural indentation expands tabs; code payload stays unchanged. */
function stripIndent(line, width) {
  let column = 0;
  let index = 0;
  while (column < width && (line[index] === ' ' || line[index] === '\t')) {
    column += line[index] === '\t' ? 4 - column % 4 : 1;
    index += 1;
  }
  return column < width ? null : ' '.repeat(column - width) + line.slice(index);
}

function listMarker(line) {
  const match = /^( {0,3})([-+*]|\d{1,9}[.)])(?:([ \t]+)(.*)|$)/.exec(line);
  if (!match) return null;
  const ordered = /^\d/.test(match[2]);
  const raw = match[3] || ' ';
  const prefix = match[1].length + match[2].length;
  let padding = 0;
  for (const character of raw) padding += character === '\t' ? 4 - (prefix + padding) % 4 : 1;
  // Large spacing belongs to item content, not an arbitrarily deep container.
  const width = padding > 4 ? 1 : padding;
  return {
    ordered, start: ordered ? Number(match[2].slice(0, -1)) : 1,
    marker: ordered ? match[2].at(-1) : match[2], indent: match[1].length,
    width: prefix + width,
    content: ' '.repeat(padding - width) + (match[4] || ''),
  };
}

function validFence(line) {
  const match = fence(line);
  return match && !(match[1][0] === '`' && match[2].includes('`')) ? match : null;
}

/** A deliberate explicit-container dialect: no lazy quote/list continuation.
 * Container recursion is bounded, and each child line retains its code payload.
 */
function parseBlocks(lines, context, depth = 1) {
  context.depth(depth);
  const children = [];
  let index = 0;
  while (index < lines.length) {
    context.step();
    const line = lines[index];
    if (blank(line)) { index += 1; continue; }
    const opening = validFence(line);
    if (opening) {
      const marker = opening[1][0];
      const width = opening[1].length;
      const indent = /^ */.exec(line)[0].length;
      const payload = [];
      index += 1;
      while (index < lines.length) {
        context.step();
        const closing = new RegExp(`^ {0,3}${marker}{${width},}[ \\t]*$`).test(lines[index]);
        if (closing) { index += 1; break; }
        let remove = 0;
        while (remove < indent && lines[index][remove] === ' ') remove += 1;
        payload.push(lines[index].slice(remove));
        index += 1;
      }
      const info = opening[2].trim();
      children.push(context.node('codeBlock', {
        value: payload.length ? payload.join('\n') + '\n' : '',
        language: /^[a-zA-Z0-9_+-]{1,30}$/.test(info) ? info : '',
      }));
      continue;
    }
    if (quote(line)) {
      const nested = [];
      while (index < lines.length) {
        context.step();
        const prefix = quote(lines[index]);
        if (!prefix) break;
        nested.push(lines[index].slice(prefix[0].length));
        index += 1;
      }
      children.push(context.node('quote', { children: parseBlocks(nested, context, depth + 1) }));
      continue;
    }
    const first = listMarker(line);
    if (first) {
      const items = [];
      let loose = false;
      while (index < lines.length) {
        const marker = listMarker(lines[index]);
        if (!marker || marker.ordered !== first.ordered || marker.marker !== first.marker || marker.indent !== first.indent) break;
        const nested = [marker.content];
        index += 1;
        let pendingBlank = false;
        while (index < lines.length) {
          context.step();
          if (blank(lines[index])) {
            pendingBlank = true;
            nested.push(''); index += 1;
            continue;
          }
          const content = stripIndent(lines[index], marker.width);
          if (content === null) break;
          if (pendingBlank) loose = true;
          pendingBlank = false;
          nested.push(content);
          index += 1;
        }
        const nextMarker = index < lines.length && listMarker(lines[index]);
        if (pendingBlank && nextMarker && nextMarker.ordered === first.ordered
          && nextMarker.marker === first.marker && nextMarker.indent === first.indent) loose = true;
        while (nested.length > 1 && blank(nested.at(-1))) nested.pop();
        items.push(context.node('listItem', { children: parseBlocks(nested, context, depth + 1) }));
      }
      children.push(context.node('list', { ordered: first.ordered, start: first.start, tight: !loose, children: items }));
      continue;
    }
    const paragraph = [line.replace(/^ {1,3}(?! )/, '')];
    index += 1;
    while (index < lines.length && !blank(lines[index])) {
      context.step();
      const marker = listMarker(lines[index]);
      if (validFence(lines[index]) || quote(lines[index]) || (marker && (!marker.ordered || marker.start === 1))) break;
      paragraph.push(lines[index].replace(/^ {1,3}(?! )/, ''));
      index += 1;
    }
    // Trailing spaces on the last line do not create a phantom hard break.
    const content = paragraph.join('\n').replace(/[ \t]+$/, '');
    children.push(context.node('paragraph', { children: parseInline(content, context, depth + 1) }));
  }
  return children;
}

return { parseBlocks };
})();
modules["index"] = (() => {
const { FEATURES, DEFAULT_LIMITS, MarkdownLimitError, createContext, escapeHTML, safeURL } = modules["policy"];
const { parseBlocks } = modules["blocks"];

/**
 * @typedef {{type:'text'|'code', value:string} |
 * {type:'softBreak'|'hardBreak'} |
 * {type:'strong'|'emphasis'|'strike', children:Inline[]} |
 * {type:'link', href:string, children:Inline[]}} Inline
 * @typedef {{type:'paragraph', children:Inline[]} |
 * {type:'codeBlock', value:string, language:string} |
 * {type:'quote', children:Block[]} |
 * {type:'list', ordered:boolean, start:number, tight:boolean, children:ListItem[]}} Block
 * @typedef {{type:'listItem', children:Block[]}} ListItem
 * @typedef {{type:'document', children:Block[]}} Document
 */

function parseWithContext(source, context) {
  if (typeof source !== 'string') throw new TypeError('Expected Markdown string');
  if (source.length > context.limits.maxLength) throw new MarkdownLimitError('maxLength');
  context.step(source.length);
  const normalized = source.replace(/\r\n?/g, '\n').replaceAll('\0', '\ufffd');
  const lines = normalized.split('\n');
  if (lines.at(-1) === '') lines.pop();
  const document = context.node('document', { children: parseBlocks(lines, context) });
  const stack = [{ node: document, depth: 0 }];
  while (stack.length) {
    context.step();
    const { node, depth } = stack.pop();
    context.depth(depth);
    if (node.children) for (const child of node.children) stack.push({ node: child, depth: depth + 1 });
  }
  return document;
}

/** Parse our documented Markdown subset into a fresh, inert document model.
 * LF/CRLF/CR normalize to LF; NUL becomes U+FFFD. No HTML/entities are decoded.
 * Unknown options/types throw TypeError; resource exhaustion throws
 * MarkdownLimitError, without partial output. Limits may only be lowered.
 * @param {string} source
 * @param {object} [options]
 * @returns {Document}
 */
function parseMarkdown(source, options = {}) {
  return parseWithContext(source, createContext(options));
}

function renderInlines(nodes, context, textOnly = false) {
  return nodes.map(node => {
    context.step();
    if (node.type === 'softBreak') return '\n';
    if (node.type === 'hardBreak') return textOnly ? '\n' : '<br>\n';
    if (node.type === 'text' || node.type === 'code') {
      const value = textOnly ? node.value : escapeHTML(node.value);
      return node.type === 'code' && !textOnly && context.features.has('inlineCode') ? `<code>${value}</code>` : value;
    }
    const value = renderInlines(node.children, context, textOnly);
    if (textOnly) return value;
    if (node.type === 'link') {
      return context.features.has('link')
        ? `<a href="${escapeHTML(node.href)}" rel="nofollow ugc noopener noreferrer">${value}</a>` : value;
    }
    const formats = { strong: ['bold', 'strong'], emphasis: ['italic', 'em'], strike: ['strike', 'del'] };
    const [feature, tag] = formats[node.type];
    return context.features.has(feature) ? `<${tag}>${value}</${tag}>` : value;
  }).join('');
}

function renderBlocks(nodes, context, textOnly = false) {
  return nodes.map(node => {
    context.step();
    if (node.type === 'paragraph') {
      const value = renderInlines(node.children, context, textOnly);
      return textOnly ? value : `<p>${value}</p>`;
    }
    if (node.type === 'codeBlock') {
      if (textOnly) return node.value.replace(/\n$/, '');
      const value = escapeHTML(node.value);
      if (!context.features.has('codeBlock')) return `<p>${value.replaceAll('\n', '<br>\n')}</p>`;
      const language = node.language ? ` class="language-${node.language}"` : '';
      return `<pre><code${language}>${value}</code></pre>`;
    }
    if (node.type === 'quote') {
      const value = renderBlocks(node.children, context, textOnly);
      return textOnly || !context.features.has('quote') ? value : `<blockquote>\n${value}\n</blockquote>`;
    }
    const feature = node.ordered ? 'orderedList' : 'unorderedList';
    const enabled = !textOnly && context.features.has(feature);
    const items = node.children.map((item, index) => {
      if (textOnly) {
        const marker = node.ordered ? `${node.start + index}. ` : '- ';
        return marker + renderBlocks(item.children, context, true).replaceAll('\n', '\n  ');
      }
      if (!enabled) return renderBlocks(item.children, context);
      if (!node.tight) return `<li>\n${renderBlocks(item.children, context)}\n</li>`;
      const value = item.children.map(child => child.type === 'paragraph'
        ? renderInlines(child.children, context) : renderBlocks([child], context)).join('\n');
      return `<li>${value}</li>`;
    }).join('\n');
    if (!enabled) return items;
    const tag = node.ordered ? 'ol' : 'ul';
    const start = node.ordered && node.start !== 1 ? ` start="${node.start}"` : '';
    return `<${tag}${start}>\n${items}\n</${tag}>`;
  }).join(textOnly ? '\n\n' : '\n');
}

/** Render only parser-owned nodes through a fixed HTML vocabulary and escaping.
 * Feature suppression removes presentation, never the underlying visible text.
 * Raw user HTML must not be passed to a different HTML sink alongside this output.
 * @param {string} source
 * @param {object} [options]
 * @returns {string}
 */
function renderMarkdown(source, options = {}) {
  const context = createContext(options);
  return renderBlocks(parseWithContext(source, context).children, context);
}

/** Plain presentation for diagnostics/mail experiments; no HTML escaping.
 * This is not a lossless source serializer or an approved email integration.
 * @param {string} source
 * @param {object} [options]
 * @returns {string}
 */
function renderText(source, options = {}) {
  const context = createContext(options);
  return renderBlocks(parseWithContext(source, context).children, context, true);
}



return { parseMarkdown, renderMarkdown, renderText, FEATURES, DEFAULT_LIMITS, MarkdownLimitError, safeURL };
})();
globalThis.CommentailMarkdown = Object.freeze({ ...modules.index, sourceId: "24979460c92f5135f91262119290dd79d5e62bc9e8403b91562bd1a3aa04bbda" });
})();
