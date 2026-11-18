# Commentail 1.6.0 — editor themes and empty-field hints

English · [Русский](Release-1.6.0-ru.md)

Released 18 November 2026. [PyPI](https://pypi.org/project/commentail/1.6.0/) ·
[GitHub release](https://github.com/hardcodd/Commentail/releases/tag/v1.6.0).

## Changes

- The visual editor detects the containing surface's light or dark background.
  Theme switches update the toolbar, Markdown source, help and open link dialog
  without replacing the editor, losing its draft or moving focus.
- Seven optional CSS palette variables customize the editor and its external
  dialog together. Existing local palette overrides remain supported.
- Empty create/reply fields show the translated “Your comment” placeholder.
  Associated labels and accessible names remain; edit forms retain their visible
  contextual label. The hint is never included in saved text or Markdown.

## Upgrade from 1.5.0

1. Back up the current package, settings and template/style overrides; rehearse
   the update in your staging site.
2. Install `commentail==1.6.0`, run `check` and `collectstatic --noinput`, clear
   stale asset caches and restart the application through your deployment process.
   There are no new migrations or dependencies compared with 1.5.0.
3. Review `form.html` overrides: keep the associated label, native textarea
   placeholder and visual root's `data-placeholder`. Keep the editor asset hooks.
4. Test light/dark theme changes with an unsent draft, replies, editing, Markdown,
   link validation and the no-JavaScript fallback on your own theme.

Automatic detection composites ancestor background colors. Background images,
gradients and pseudo-elements are not sampled; provide a representative container
background color or explicit palette overrides for those designs. See the
[palette reference](Styling.md#visual-editor-palette).

For older upgrades, follow [1.5.0](Release-1.5.0.md) and the intervening migration notes.
No database or server-policy change is introduced by 1.6.0. Rolling back to 1.5.0
requires restoring matching package assets and templates, not a schema reversal.

## Compatibility

Unchanged: Python 3.12–3.14; Wagtail 7.4.3+ with Django 5.2/6.0 and Wagtail
8.0.x with Django 5.2/6.0/6.1; file SQLite and PostgreSQL 16. Host-specific theme
and assistive-technology behavior still require integration acceptance.
