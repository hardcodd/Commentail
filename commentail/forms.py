"""Editorial forms validate values without exposing author text to moderators."""

from typing import ClassVar

from django import forms
from django.utils.translation import gettext_lazy as _

from .config import technical_settings
from .models import Discussion, ModerationRule, SiteCommentSettings, SiteGroupPermission
from .rules_csv import RuleRow, parse_rules

EDITORIAL_FIELDS = (
    "mode",
    "moderation",
    "access",
    "max_length",
    "clickable_links",
    "notify_publication",
    "notify_rejection",
)

EDITORIAL_LABELS = {
    "mode": _("Discussion mode"),
    "moderation": _("Moderation policy"),
    "access": _("Who can comment"),
    "max_length": _("Maximum comment length"),
    "clickable_links": _("Clickable links"),
    "notify_publication": _("Publication emails"),
    "notify_rejection": _("Rejection emails"),
}


class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteCommentSettings
        fields = ("email_enabled", *EDITORIAL_FIELDS)
        labels: ClassVar[dict[str, object]] = {"email_enabled": _("Send emails"), **EDITORIAL_LABELS}

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["email_enabled"].help_text = _(
            "Disables all comment emails, including guest verification. Guests cannot comment while email is disabled."
        )

    def clean_max_length(self) -> int:
        value = self.cleaned_data["max_length"]
        if value < 1:
            raise forms.ValidationError(_("Length must be positive"))
        return value


class DiscussionSettingsForm(forms.ModelForm):
    class Meta:
        model = Discussion
        fields = EDITORIAL_FIELDS
        labels = EDITORIAL_LABELS

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        for name in ("mode", "moderation", "access"):
            self.fields[name].choices = [
                ("", _("Use site setting")),
                *self.fields[name].choices[1:],
            ]
        for name in ("clickable_links", "notify_publication", "notify_rejection"):
            self.fields[name].widget = forms.Select(
                choices=[
                    ("", _("Use site setting")),
                    (True, _("Yes")),
                    (False, _("No")),
                ]
            )

    def clean_max_length(self) -> int | None:
        value = self.cleaned_data["max_length"]
        if value is not None and value < 1:
            raise forms.ValidationError(_("Length must be positive"))
        return value


class RuleForm(forms.ModelForm):
    class Meta:
        model = ModerationRule
        fields = ("phrase", "action", "enabled")
        labels: ClassVar[dict[str, object]] = {
            "phrase": _("Word or phrase"),
            "action": _("Action"),
            "enabled": _("Enabled"),
        }


class SitePermissionForm(forms.ModelForm):
    class Meta:
        model = SiteGroupPermission
        fields = (
            "group",
            "site",
            "view",
            "moderate",
            "hide",
            "delete",
            "settings",
            "rules",
        )
        labels: ClassVar[dict[str, object]] = {
            "group": _("Group"),
            "site": _("Site"),
            "view": _("View comments"),
            "moderate": _("Moderate comments"),
            "hide": _("Hide and restore comments"),
            "delete": _("Erase comment text"),
            "settings": _("Manage settings"),
            "rules": _("Manage project-wide rules"),
        }


class RuleCsvImportForm(forms.Form):
    file = forms.FileField(
        label=_("CSV file"),
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    def clean_file(self) -> list[RuleRow]:
        upload = self.cleaned_data["file"]
        limits = technical_settings(None)
        max_bytes = limits["RULES_CSV_MAX_BYTES"]
        if upload.size > max_bytes:
            raise forms.ValidationError(
                _("The CSV file exceeds the limit of %(limit)s bytes."),
                params={"limit": max_bytes},
            )
        data = upload.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise forms.ValidationError(
                _("The CSV file exceeds the limit of %(limit)s bytes."),
                params={"limit": max_bytes},
            )
        return parse_rules(data, limits["RULES_CSV_MAX_ROWS"])
