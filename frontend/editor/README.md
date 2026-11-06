# Owned comment editor sources

These modules implement Commentail's limited Markdown core, reversible visual
model, Site capability policy, link dialog, URL paste and native form lifecycle.
They have no added runtime/build dependencies. The supported dialect and current
integration limits are documented in [Comment editor](../../docs/wiki/Comment-editor.md).

From the repository root:

```sh
node tools/build_editor.mjs
node tools/build_editor.mjs --check
node --test tests/test_*.js
python -m django test --settings=tests.settings
```

The build concatenates the ordered modules into
`commentail/static/commentail/editor.js` and generates separate `editor-<locale>.js`
assets from `locales/*.json`. Only the active non-English locale loads, before
the editor bundle. Edit sources here, regenerate the
bundle, and check the actual bundled runtime with the Node tests. Styles live
in `commentail/static/commentail/editor.css`. No minifier is required.

`mount.js` preserves the native textarea as the POST contract. Each visual
instance owns its event abort controller and dialog; destroy it before replacing
its form. Synchronize the latest draft before replacing a discussion and export
validated Markdown before submission. The independent server implementation in
`commentail/markdown.py` remains the admission/rendering authority; the shared
2,064-case corpus checks HTML and plain-text parity. Expand regression coverage
on both sides when changing the dialect. Parser resource limits are intentional
whole-input rejections, never partial rendering.

Create/reply/edit templates keep the toolbar before both editable fields and
associate the native label with its textarea explicitly. Both modes share the
toolbar's horizontal edges; showing source must not move the toolbar below it.

Keyboard access uses one Tab stop per toolbar, Left/Right (wrapping), Home/End
and native Enter/Space activation. Alt+Shift+T (Option+Shift+T on Mac) or
Alt+F10 moves from either editing surface to
the last available toolbar control; Escape returns to the editing surface.
In a list, Escape followed by Tab exits instead of changing indentation. A collapsed, localized keyboard-help disclosure describes these keys and is associated with both editing surfaces.
Submission marks both surfaces invalid and focuses the first invalid instance;
editing clears that state. The textarea's required semantics are retained through
ARIA while client validation handles the hidden source. Identical status messages
do not rewrite the live region. These are regression-tested contracts, not a claim
of complete screen-reader or WCAG acceptance.

Runtime messages use English source keys with Russian, German, French, Spanish
and Brazilian Portuguese catalogs. The server selects the active Django language;
English needs no catalog request. Keep user text outside chrome translation.
Catalog/message completeness and locale load order/failure recovery have Node tests.

`shortcuts.js` recognizes supported typed markers using the existing parser, with
a 512-unit/64-candidate bound. A separate controller transaction makes conversion
undoable back to literal markers. Paste, replacements, composition and code are
excluded. Disabled or unencodable conversions remain literal. Strikethrough uses
its own model bit; inline code remains exclusive. Physical-device and
assistive-technology acceptance is a separate check.
