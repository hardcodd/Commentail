from django import forms
from wagtail.admin.panels import Panel

from .assets import asset_url


class CommentsPanel(Panel):
    class BoundPanel(Panel.BoundPanel):
        template_name = "commentail/admin/page_panel.html"

        @property
        def media(self) -> forms.Media:
            return super().media + forms.Media(css={"all": [asset_url("admin.css")]})

        def get_context_data(
            self, parent_context: dict[str, object] | None = None
        ) -> dict[str, object]:
            context = super().get_context_data(parent_context)
            context["commentail_form"] = getattr(
                self.request, "_commentail_editor_form", None
            )
            return context
