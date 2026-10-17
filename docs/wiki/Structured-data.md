# Comment structured data: microdata and JSON-LD

Commentail describes the published comments currently rendered in the widget as
[Schema.org Comment](https://schema.org/Comment) entities. Both HTML microdata and
JSON-LD are enabled by default. No extra template tag or JavaScript is required
when using the supplied templates.

## Choose the output

```python
COMMENTAIL = {
    "default": {"STRUCTURED_DATA": "both"},
    "www.example.org": {"STRUCTURED_DATA": "json_ld"},
}
```

| Value | Output |
| --- | --- |
| `both` | Microdata and JSON-LD with matching entity IDs (default). |
| `json_ld` | Only a passive `application/ld+json` script inside the widget. |
| `microdata` | Only `itemscope`, `itemtype`, `itemid` and `itemprop` attributes. |
| `off` | No built-in structured data; useful when the host generates its own. |

The setting follows the normal default/hostname inheritance and is checked by
`python manage.py check`. It is a Python integration option, not an editorial field.

## What is described

Each entity contains its published plain text, current visible author name,
publication date, approved modification date when present, and a link to the
comment in the host article/object. `about` identifies the host URL;
`parentItem` identifies the direct addressee of a reply. IDs are stable host URLs
with `#commentail-<id>` fragments, shared by both formats. Reading controls,
protected action tokens and request query parameters are not copied into them.
Trusted query parameters supplied by an object adapter's `get_url` are preserved.

Only the comments actually rendered in this response are described. Collapsed
or unloaded replies appear after expansion/loading. Pagination and progressive
updates replace the widget's graph together with its visible rows; no duplicate
scripts accumulate. Native HTML responses contain the same metadata without JS.

Excluded: pending/rejected/unconfirmed comments, private author status cards,
pending revisions, hidden/deleted placeholder bodies, email, rejection reasons,
account identifiers, avatars and protected action links. A pending revision keeps
the old approved text in metadata. Empty/hidden discussions emit no graph; target
access restrictions continue to apply. A failed object URL handler omits metadata.
A reference to a removed parent identifies the relationship without publishing its text.

## Integrate with your page graph

Commentail does not invent an Article, Product, Review, rating or aggregate score.
Keep your site's Article/WebPage schema and canonical URL implementation. `about`
references the host target URL; if your graph uses another ID such as `#article`,
adapt the templates or generate one combined graph with `STRUCTURED_DATA="off"`.
Use a consistent public URL in `Page.get_url` or the object adapter; redirects and
canonical aliases remain the host site's responsibility.

When overriding `commentail/comment.html`, preserve conditional metadata around
`comment.schema` and `structured_microdata`. When overriding `block.html`, keep
`{% load commentail_tags %}` and `{% commentail_json_ld structured_comments %}`
inside the replaced section. The supplied serializer uses Django's script-safe
JSON escaping; never replace it with unescaped user text plus `safe`.

## Verify on your site

1. View article source: find `https://schema.org/Comment` and `application/ld+json`.
2. Confirm names, text, dates and links match the visible published rows.
3. Expand a thread or follow a comment permalink and inspect the updated graph.
4. Check a private/restricted discussion and an awaiting-moderation message.
5. Validate the rendered HTML with the [Schema.org validator](https://validator.schema.org/).

Valid structured data helps machines interpret content; it does not guarantee
indexing, ranking or a Google rich result. Follow Google's
[structured-data policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies)
and do not label ordinary comments as product reviews for search appearance.

---

[← Templates](Templates.md) · [Documentation home](Home.md) · [Configuration →](Configuration.md)
