# Comment editor (1.5.0)

[На русском](Comment-editor-ru.md). Available from Commentail 1.5.0.

## Site settings and existing content

Comments → Site settings → Comment editor selects **Plain text**, **Markdown**
or **Visual editor** independently for guests and registered users. The nine
formatting switches are shared by both audiences: bold, italic, strikethrough,
links, quotes, ordered/unordered lists, inline code and code blocks. These are
Site settings, without Page overrides or `COMMENTAIL` dictionary keys.

Migration `0020` defaults both modes and existing comments/revisions to plain
text. Existing `**markers**` remain literal, including when edited. New Markdown
comments and revisions store an explicit `text_format`; clients cannot override
it through a POST field. The server validates every nested construct against
the selected Site policy. Changing settings does not rewrite published content.
Editing existing Markdown after switching to plain mode opens its source; remove
disallowed formatting before submitting the revision.

The older **Clickable links** setting controls automatic linking in plain text.
Explicit Markdown links use the editor's **Links** capability.

## Dialect and fallback

The owned parser supports emphasis, strike, explicit HTTP/HTTPS/mailto links,
quotes, lists and fenced/inline code. HTML, entities, headings, images, tables,
link titles and automatic links are outside the dialect. Use inline or fenced
code to show literal Markdown examples. Containers require explicit quote/list
continuation indentation. Nested ordered lists display hierarchical numbering.
Links never fetch page titles or other remote data. Pasted web URLs use a short
hostname label, retaining the full destination; meaningful subdomains remain.

The visual subset includes strikethrough, simple quotes and lists. Nested quotes, code fences with language labels,
complex list items and cross-line links remain source-only. Unsupported visual
commands fail before changing the document. If later text edits make a mark
combination unexportable, **Clear formatting** removes selected inline styles
and links while retaining text and code. Export trims paragraph/list boundary
spaces and terminal blank paragraphs on a copy; code whitespace is preserved.
Typing `**bold**` / `__bold__`, `*italic*` / `_italic_`, `~~strike~~`, inline
backticks or `[label](https://example.com)` applies the supported formatting.
A paragraph-start `- `, `* `, `+ `, `1. ` / `1) ` or `> ` starts a list or quote;
three backticks or tildes followed by Enter starts a code block. One undo restores
the literal markers. Conversion requires unstyled markers outside code and links;
paste, composition and replacement input stay literal. Inline recognition examines
at most 512 UTF-16 units and 64 candidate openings. Disabled or unrepresentable
conversions stay literal; longer examples can use the toolbar or source mode.

Without JavaScript, or if the optional editor script fails to load, the native
textarea submits plain text or Markdown according to the same server policy.
Drafts are retained on validation/network errors; this is not persistent
autosaving. The editor JS/CSS and selected locale load only for visual forms. Keep the existing
`commentail_css` / `commentail_js` tags and collect static files after upgrading.
Custom replacements of create/edit/body templates must adopt their updated
contracts; rich bodies require a block container rather than a paragraph.

The parser rejects complete inputs beyond its limits: 100,000 UTF-16 units,
depth 32, 100,000 nodes or two million work units. Site text-length limits still
apply to the submitted source, and link destinations are limited to 2,048
characters. HTML output is escaped and restricted to parser-owned elements;
credentials, unsafe schemes and control characters are rejected in links.

## Keyboard, languages and verification

The toolbar is one Tab stop. Left/Right arrows choose a button; Home/End move to
its ends; Enter/Space applies it. Alt+Shift+T (Option+Shift+T on Mac) or Alt+F10
opens the toolbar from the text, and
Escape returns to the text. In lists, Escape then Tab exits the editor instead
of indenting. Both editing modes include collapsed localized keyboard help. Invalid
submission returns focus to the comment and exposes its error; correcting the
text clears the invalid state. The link dialog supports keyboard save, removal
and Escape cancellation with selection restored.

Editor runtime messages support English, Russian, German, French, Spanish and
Brazilian Portuguese. The server selects the active Django language; only that
locale asset is requested, and English needs none. Unknown languages use English.
If the locale or bundle fails to load, the native textarea stays usable.

Owned browser sources and build/test commands: [frontend/editor](../../frontend/editor/README.md).
See also [Configuration](Configuration.md), [Templates](Templates.md) and
[Replies and editing](Replies-and-editing.md).

Authors cannot reply to their own comments. Signed-in accounts use account identity;
guest authors use a normalized email address. Existing self-replies remain visible.
