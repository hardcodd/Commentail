"""Request-local Wagtail 7.4 create/edit integration; no cached handler mutation."""

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.panels import ObjectList, TabbedInterface
from wagtail.admin.views.pages.create import CreateView
from wagtail.admin.views.pages.edit import EditView
from wagtail.models import Page, Site

from .panels import CommentsPanel


class CommentsContextMixin:
    """Clone request-local panels and persist settings with a valid page action.

    Wagtail internal views are version-pinned and covered by integration tests.
    Editorial settings take effect immediately, independently of Page revisions.
    """

    def run_hook(self, hook_name: str, *args: object, **kwargs: object) -> object:
        # Earlier hooks already ran in the original view. Continue only after
        # this adapter, so project hooks execute exactly once and retain order.
        if hook_name in {"before_edit_page", "before_create_page"}:
            adapter = before_edit if hook_name == "before_edit_page" else before_create
            remaining = False
            for function in hooks.get_hooks(hook_name):
                if function is adapter:
                    remaining = True
                    continue
                if remaining:
                    result = function(*args, **kwargs)
                    if result is not None:
                        return result
            return None
        return super().run_hook(hook_name, *args, **kwargs)

    def prepare_comments(self) -> None:
        from . import detection
        from .forms import DiscussionSettingsForm
        from .models import Discussion
        from .permissions import can

        site = Site.find_for_request(self.request)
        if site is None or not can(self.request.user, site.pk, "settings"):
            return
        try:
            connected = detection.has_comments(self.page, self.request)
        except detection.DetectionError:
            messages.warning(
                self.request, _("Comment templates could not be resolved.")
            )
            return
        if not connected:
            return
        instance = (
            Discussion.objects.filter(site=site, page_id=self.page.pk).first()
            if self.page.pk
            else None
        )
        instance = instance or Discussion(site=site, page=self.page)
        bound = (
            self.request.method == "POST"
            and self.request.POST.get("commentail-enabled") == "1"
        )
        self.commentail_form = DiscussionSettingsForm(
            self.request.POST if bound else None, instance=instance, prefix="commentail"
        )
        self.request._commentail_editor_form = self.commentail_form
        original = self.edit_handler.clone()
        extra = ObjectList([CommentsPanel()], heading=_("Comments"))
        if isinstance(original, TabbedInterface):
            original.children = [*original.children, extra]
        else:
            original = TabbedInterface(
                [ObjectList([original], heading=_("Content")), extra]
            )
        self.edit_handler = original.bind_to_model(self.page_class)

    def get(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponse:
        self.prepare_comments()
        return super().get(request, *args, **kwargs)

    def post(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponse:
        self.prepare_comments()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form: object) -> HttpResponse:
        extra = getattr(self, "commentail_form", None)
        if extra is not None and extra.is_bound and not extra.is_valid():
            return self.form_invalid(form)
        with transaction.atomic():
            response = super().form_valid(form)
            if (
                extra is not None
                and extra.is_bound
                and self.page.pk
                and response.status_code < 400
            ):
                extra.instance.page = self.page
                extra.save()
            return response


class CommentsEditView(CommentsContextMixin, EditView):
    pass


class CommentsCreateView(CommentsContextMixin, CreateView):
    pass


def before_edit(request: HttpRequest, page: Page) -> HttpResponse | None:
    if getattr(request, "_commentail_library_view", False):
        return None
    request._commentail_library_view = True
    return CommentsEditView.as_view()(request, page_id=page.pk)


def before_create(
    request: HttpRequest, parent_page: Page, page_class: type[Page]
) -> HttpResponse | None:
    if getattr(request, "_commentail_library_view", False):
        return None
    request._commentail_library_view = True
    return CommentsCreateView.as_view()(
        request,
        content_type_app_name=page_class._meta.app_label,
        content_type_model_name=page_class._meta.model_name,
        parent_page_id=parent_page.pk,
    )
