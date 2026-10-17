# Add comments to Django models outside Page

Register each supported model in the project-wide
`COMMENTAIL["default"]["OBJECT_ADAPTERS"]` dictionary:

```python
COMMENTAIL = {
    "default": {
        "OBJECT_ADAPTERS": {"shop.Product": "myproject.comments.ProductAdapter"},
    },
}
```

Adapters are stateless classes constructed without arguments:

```python
from django.http import HttpRequest
from wagtail.models import Site
from shop.models import Product


class ProductAdapter:
    def get_site(self, obj: Product, request: HttpRequest) -> Site:
        return obj.site

    def can_view(self, obj: Product, request: HttpRequest) -> bool:
        return obj.is_public or request.user.is_staff

    def get_url(self, obj: Product, site: Site) -> str:
        return obj.get_absolute_url()
```

Use the same `{% commentail product %}` tag and resource tags. Registration
supports concrete, non-proxy models with integer, UUID or string primary-key
fields; stored keys must be nonempty and at most 255 characters. Model, key and
Wagtail Site identify a discussion independently. Unregistered models are denied.
The adapter's saved Site must match the Site resolved for the current request.
Keep the host object's own view protected by the same access policy.

Every direct comment request rechecks registration, target existence, Site and
visitor access, including form replays and author edits. Adapter errors fail
closed with neutral visitor output and type-only server diagnostics; stored
comments/settings are retained. `CommentContext.target` is the actual object.
`get_url` must return an absolute HTTP(S) URL or a root-relative path.

The Comments section includes **Object discussions**, a searchable, paginated
list of existing discussions and a separate settings card with the same Site
inheritance choices as Pages. The Site settings grant authorizes this card;
no fields are injected into the host model editor. Rendering the tag creates
the discussion after access checks; Python integrations may also call
`commentail.objects.get_object_discussion(request, obj)`.

Account email delivery checks the adapter using a worker-created GET request
with the recipient's account, Site host, language and an empty session. Policies
requiring browser-only proof cannot authorize mail through this request. Guest
mail requires `CAN_SEND_GUEST_EMAIL` for registered objects; that callback proves
offline access. The adapter must still resolve the stored Site correctly.

Normal instance and queryset deletion through Django's runtime ORM removes all
related discussions, replies, revisions, subscriptions, tokens, form records,
mail and moderation events across Sites. Cleanup also works after removing the
adapter registration. Raw SQL and historical-model data migrations bypass this
runtime cleanup and must explicitly remove their discussions.

---

[← Callbacks](Callbacks.md) · [Documentation home](Home.md) · [Security and privacy →](Security-and-privacy.md)
