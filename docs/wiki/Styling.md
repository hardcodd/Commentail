# Theme and CSS customization

The widget inherits the containing element's text color, font, font size and
line height. Its background is transparent; fields, buttons and separators use
subtle translucent tones of the current text color. This follows the site's own
light/dark switch and decorative backgrounds without JavaScript or an OS-theme
guess. Without `color-mix()` support, controls retain transparent backgrounds and
solid current-color borders. Generated avatar colors remain independent.

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
| `color-button-text` | Accent or inherited text color |
| `color-button-surface`, `color-button-hover` | 8% / 15% button-text tint |
| `color-control-surface`, `color-control-hover` | Quiet actions: transparent / 8% text-color tint |
| `color-menu-surface`, `color-menu-text` | Action popup: browser canvas with a subtle tint / canvas text |
| `border-radius`, `avatar-size` | `.75rem` / `2.5rem` |
| `spacing`, `max-width` | `1rem` form spacing unit / `48rem` widget limit |
| `input-min-height`, `input-max-height` | `6rem` / `24rem` |

The host must provide readable foreground/background contrast. A busy photograph
or conflicting global `!important` rules can require explicit overrides; the
widget cannot safely infer a brand palette or repair the host's contrast.
For a filled accent button, set both `color-button-surface` and
`color-button-text` to a contrasting pair, and set `color-button-hover` as needed.
Standalone email-action documents need the same host theme via
overridden page templates; they cannot inherit CSS from a different document.

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
