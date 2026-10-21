# Theme and CSS customization

When upgrading an existing form override, see [upgrade guidance](Release-1.2.0.md).

The widget inherits the containing element's text color, font, font size and
line height. Its background is transparent; fields, buttons and separators use
subtle translucent tones of the current text color. The comment submit button
uses a stronger border, weight and tint without imposing a fixed palette. This follows the site's own
light/dark switch and decorative backgrounds without JavaScript or an OS-theme
guess. Without `color-mix()` support, controls retain transparent backgrounds and
solid current-color borders.
Generated avatar colors remain independent.

No host CSS variables are required for the default widget. The library reads
`currentColor` from its container; it does not discover arbitrary site tokens
such as `--brand-link`. Map those explicitly only when customizing.

Classes use `commentail-*`; custom properties use `--commentail-*`. Set properties
on the widget or an ancestor such as `:root`; load class overrides after the
package stylesheet. For example, map the site's own accent token explicitly:

```css
:root {
  --commentail-color-accent: var(--site-link-color, #245a86);
  --commentail-border-radius: .4rem;
  --commentail-avatar-size: 2.25rem;
}
```

| Property suffix (after `--commentail-`) | Default |
| --- | --- |
| `color-text`, `font-family`, `font-size`, `line-height` | Inherited from the container |
| `color-accent`, `color-muted`, `color-error` | Current/inherited text color |
| `color-surface` | Transparent widget background |
| `color-border` | Text-color tint; stronger on controls |
| `color-input-surface` | 3% text-color tint |
| `color-button-text` | Inherited text for comment submission; accent or inherited text for other buttons |
| `color-button-surface`, `color-button-hover` | 12% / 18% text-color tint for comment submission; 8% / 15% for other buttons |
| `color-control-surface`, `color-control-hover` | Quiet actions: transparent / 8% text-color tint |
| `color-menu-surface`, `color-menu-text` | Action popup: browser canvas with a subtle tint / canvas text |
| `color-staff-text`, `color-staff-surface` | Staff name: accent/inherited text and a 12% tint; blue foreground/pale blue background without `color-mix()` |
| `color-superuser-text`, `color-superuser-surface` | Super administrator name: dark amber (`#795400`) / pale gold (`#ffedb5`) |
| `border-radius`, `avatar-size` | `.75rem` / `2.5rem` |
| `spacing`, `max-width` | `1rem` form spacing unit / `48rem` widget limit |
| `input-min-height`, `input-max-height` | `6rem` / `24rem` |

The `.commentail-staff-name` class styles the name badge, with
`.commentail-superuser-name` adding the distinct gold palette for super
administrators. The `.commentail-crown` class positions the golden SVG on the upper-right edge of the avatar.
The `.commentail-avatar-wrap` wrapper keeps the crown outside the clipped
`.commentail-avatar`, so uploaded photos stay circular. The name badge and crown
are controlled by the Site setting described in [Configuration](Configuration.md#staff-name-highlighting).

The host must provide readable foreground/background contrast. A busy photograph
or conflicting global `!important` rules can require explicit overrides; the
widget cannot safely infer a brand palette or repair the host's contrast.
When customizing a filled button, set both `color-button-surface` and
`color-button-text` to a contrasting pair, and set `color-button-hover` as needed.
Standalone email-action documents need the same host theme via
overridden page templates; they cannot inherit CSS from a different document.
Their bundled `.commentail-document` styles have their own light/dark palette,
selected by the browser's `prefers-color-scheme`. Override
`--commentail-document-background` and the shared text/surface properties there
to match a site-managed theme; `--commentail-document-shadow` controls the card shadow.

## Scoped theme recipe

Load overrides after the package stylesheet:

```css
.commentail {
  --commentail-color-accent: var(--brand-link, #245a86);
  --commentail-max-width: 100%;
  --commentail-border-radius: .5rem;
  --commentail-avatar-size: 2.25rem;
  --commentail-input-max-height: 20rem;
}
.commentail .commentail-date { font-size: .875em; }
```

Adapt host tokens, test actual light/dark themes, keep visible focus and readable
error contrast. Avoid fixed widths on narrow screens and broad selectors affecting
Wagtail. Textareas grow vertically; horizontal resizing is disabled. Prefer CSS to
markup replacement; use [Templates](Templates.md) only when structure must change.

---

[← Email and worker](Email-and-worker.md) · [Documentation home](Home.md) · [Templates →](Templates.md)
