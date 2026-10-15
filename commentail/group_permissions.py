"""Site grants edited with Wagtail's normal group permission panels."""

from django import forms
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.http import QueryDict
from django.template.loader import render_to_string
from django.utils.datastructures import MultiValueDict
from django.utils.translation import gettext_lazy as _
from wagtail.admin.forms.formsets import BaseFormSetMixin
from wagtail.models import Site

from .assets import asset_url
from .forms import SitePermissionForm
from .models import SiteGroupPermission

CAPABILITIES = ("view", "moderate", "hide", "delete", "settings", "rules")


class SiteGrantForm(forms.ModelForm):
    class Meta:
        model = SiteGroupPermission
        fields = ("site", *CAPABILITIES)
        labels = SitePermissionForm.Meta.labels

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = Site.objects.order_by("hostname", "port")


class BaseGroupCommentPermissionFormSet(BaseFormSetMixin, forms.BaseFormSet):
    """Replace only this group's grants after all panels validate.

    Wagtail enforces group create/change permissions before constructing this
    panel. Existing grants are loaded on GET; no permission records are written
    until Wagtail saves the group and calls save(). Duplicate Sites are invalid.
    """

    def __init__(
        self,
        data: QueryDict | None = None,
        files: MultiValueDict[str, UploadedFile] | None = None,
        instance: Group | None = None,
        prefix: str | None = None,
    ) -> None:
        self.instance = instance if instance is not None else Group()
        initial = (
            list(
                SiteGroupPermission.objects.filter(group=self.instance).values(
                    "site", *CAPABILITIES
                )
            )
            if self.instance.pk
            else []
        )
        super().__init__(
            data, files, initial=initial, prefix=prefix or "commentail_permissions"
        )

    def clean(self) -> None:
        super().clean()
        if any(self.errors):
            return
        sites = [
            form.cleaned_data["site"].pk
            for form in self.forms
            if not self._should_delete_form(form) and "site" in form.cleaned_data
        ]
        if len(sites) != len(set(sites)):
            raise forms.ValidationError(_("Each site may appear only once."))

    @transaction.atomic
    def save(self) -> None:
        if not self.instance.pk or not self.is_valid():
            raise ValueError("A saved group and valid permission panel are required")
        retained: list[int] = []
        for form in self.forms:
            if self._should_delete_form(form) or "site" not in form.cleaned_data:
                continue
            values = {name: form.cleaned_data[name] for name in CAPABILITIES}
            if not any(values.values()):
                continue
            grant, _created = SiteGroupPermission.objects.update_or_create(
                group=self.instance, site=form.cleaned_data["site"], defaults=values
            )
            retained.append(grant.pk)
        SiteGroupPermission.objects.filter(group=self.instance).exclude(
            pk__in=retained
        ).delete()

    def as_admin_panel(self) -> str:
        return render_to_string(
            "commentail/admin/group_permissions.html", {"formset": self}
        )

    @property
    def media(self) -> forms.Media:
        return super().media + forms.Media(css={"all": [asset_url("admin.css")]})


GroupCommentPermissionFormSet = forms.formset_factory(
    SiteGrantForm,
    formset=BaseGroupCommentPermissionFormSet,
    extra=0,
    can_delete=True,
    max_num=1000,
    validate_max=True,
    absolute_max=1000,
)
