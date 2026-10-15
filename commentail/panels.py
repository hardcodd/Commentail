from wagtail.admin.panels import Panel


class CommentsPanel(Panel):
    class BoundPanel(Panel.BoundPanel):
        template_name = "commentail/admin/page_panel.html"

        def get_context_data(
            self, parent_context: dict[str, object] | None = None
        ) -> dict[str, object]:
            context = super().get_context_data(parent_context)
            context["commentail_form"] = getattr(
                self.request, "_commentail_editor_form", None
            )
            return context
