(() => {
  'use strict';
  const M = globalThis.CommentailEditorModel;
  const core = globalThis.CommentailMarkdown;
  const FEATURES = Object.freeze(['bold', 'italic', 'strike', 'link', 'quote', 'orderedList', 'unorderedList', 'inlineCode', 'codeBlock']);
  const MODES = Object.freeze(['plain', 'markdown', 'visual']);
  const labels = Object.freeze({ bold: translate("Bold"), italic: translate("Italic"), strike: translate("Strikethrough"), link: translate("Links"), quote: translate("Quotes"), orderedList: translate("Ordered lists"), unorderedList: translate("Unordered lists"), inlineCode: translate("Inline code"), codeBlock: translate("Code blocks") });
  const commandFeatures = Object.freeze({ bold: 'bold', italic: 'italic', strike: 'strike', code: 'inlineCode', pre: 'codeBlock', link: 'link', quote: 'quote', ol: 'orderedList', ul: 'unorderedList' });

  class PolicyError extends M.EditorError {
    constructor(feature) {
      super(translate("This site disables formatting: \u201c") + labels[feature] + translate("\u201d. Remove it or put the example inside permitted code."));
      this.feature = feature;
    }
  }

  /** Validate one Site's capabilities and independent audience modes. Defaults
   * keep both audiences in plain text. Copies/freeze prevent settings mutation
   * from changing an editor halfway through a transaction or history operation.
   */
  function configure(input = {}) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('Expected site editor settings');
    if (Object.keys(input).some(key => !['guest', 'registered', 'features'].includes(key))) throw new TypeError('Unknown editor setting');
    const guest = input.guest === undefined ? 'plain' : input.guest;
    const registered = input.registered === undefined ? 'plain' : input.registered;
    const features = input.features === undefined ? [...FEATURES] : input.features;
    if (!MODES.includes(guest) || !MODES.includes(registered)) throw new TypeError('Unknown editor mode');
    if (!Array.isArray(features) || features.some(feature => !FEATURES.includes(feature)) || new Set(features).size !== features.length) {
      throw new TypeError('Expected unique supported editor features');
    }
    return Object.freeze({ guest, registered, features: Object.freeze([...features]) });
  }

  /** Select an immutable policy for the authenticated state supplied by the host.
   * This is a client UX boundary; the backend independently derives its own audience.
   */
  function forAudience(settings, audience) {
    if (!['guest', 'registered'].includes(audience)) throw new TypeError('Unknown editor audience');
    const site = configure(settings);
    return Object.freeze({ mode: site[audience], features: site.features });
  }

  function requireFeature(feature, policy) {
    if (!policy.features.includes(feature)) throw new PolicyError(feature);
  }

  /** Check the complete AST, never a parser with forbidden features suppressed.
   * Literal Markdown inside code remains literal. Throws without changing input.
   * Plain mode treats all syntax as text but retains the same source-size bound.
   */
  function assertMarkdown(source, policy) {
    if (typeof source !== 'string') throw new TypeError('Expected comment text');
    if (source.length > 100000) throw new M.EditorError(translate("Source is limited to 100,000 UTF-16 units."));
    if (policy.mode === 'plain') return;
    const nodes = [core.parseMarkdown(source)];
    while (nodes.length) {
      const node = nodes.pop();
      const feature = node.type === 'list' ? (node.ordered ? 'orderedList' : 'unorderedList') :
        ({ strong: 'bold', emphasis: 'italic', strike: 'strike', link: 'link', quote: 'quote', code: 'inlineCode', codeBlock: 'codeBlock' })[node.type];
      if (feature) requireFeature(feature, policy);
      if (node.children) nodes.push(...node.children);
    }
  }

  /** Gate model transactions as well as UI commands, including direct changes
   * supplied by extensions.
   */
  function assertRows(rows, policy) {
    for (const item of rows) {
      const feature = ({ ol: 'orderedList', ul: 'unorderedList', quote: 'quote', pre: 'codeBlock' })[item.kind];
      if (feature) requireFeature(feature, policy);
      if (item.links?.length) requireFeature('link', policy);
      for (const [bit, name] of [[M.BOLD, 'bold'], [M.ITALIC, 'italic'], [M.STRIKE, 'strike'], [M.CODE, 'inlineCode']]) {
        if (item.marks.some(mark => mark & bit)) requireFeature(name, policy);
      }
    }
  }

  function allowsCommand(command, policy) {
    if (command === 'undo' || command === 'redo') return true;
    if (policy.mode !== 'visual') return false;
    if (Object.hasOwn(commandFeatures, command)) return policy.features.includes(commandFeatures[command]);
    if (command === 'indent' || command === 'outdent') return policy.features.includes('orderedList') || policy.features.includes('unorderedList');
    return command === 'clear';
  }

  globalThis.CommentailEditorPolicy = Object.freeze({ FEATURES, MODES, labels, PolicyError, configure, forAudience, assertMarkdown, assertRows, allowsCommand });
})();
