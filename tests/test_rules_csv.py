import csv
import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from wagtail.models import Site

from commentail.models import ModerationRule, SiteGroupPermission


class RuleCsvTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            "csv-admin", "", "synthetic"
        )
        self.client.force_login(self.admin)
        self.import_url = reverse("commentail_admin:rules_import")
        self.export_url = reverse("commentail_admin:rules_export")
        self.old = ModerationRule.objects.create(phrase="Old phrase", action="review")
        self.untouched = ModerationRule.objects.create(
            phrase="Keep me", action="reject"
        )

    def upload(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        return self.client.post(
            self.import_url, {"file": SimpleUploadedFile("rules.csv", data, "text/csv")}
        )

    def test_merge_and_repeated_import_are_idempotent(self):
        data = "\ufeffphrase;action;enabled\nOld phrase;reject;0\nНовое правило;review;true\n"
        self.assertRedirects(self.upload(data), reverse("commentail_admin:rules"))
        self.old.refresh_from_db()
        self.assertEqual(self.old.action, "reject")
        self.assertFalse(self.old.enabled)
        self.untouched.refresh_from_db()
        self.assertEqual(self.untouched.action, "reject")
        self.assertTrue(ModerationRule.objects.get(phrase="Новое правило").enabled)
        self.assertRedirects(self.upload(data), reverse("commentail_admin:rules"))
        self.assertEqual(ModerationRule.objects.count(), 3)

    def test_optional_reason_column_and_legacy_import_preserve_existing_reason(self):
        self.old.reason = "Keep this explanation"
        self.old.save()
        self.upload("phrase,action,enabled\nOld phrase,reject,1\n")
        self.old.refresh_from_db()
        self.assertEqual(self.old.reason, "Keep this explanation")
        data = "reason;enabled;action;phrase\nNew explanation;1;reject;Old phrase\n"
        self.assertEqual(self.upload(data).status_code, 302)
        self.old.refresh_from_db()
        self.assertEqual(self.old.reason, "New explanation")
        self.assertEqual(
            self.upload(
                "phrase,action,enabled,reason\nOld phrase,reject,1,\n"
            ).status_code,
            302,
        )
        self.old.refresh_from_db()
        self.assertEqual(self.old.reason, "")

    def test_reason_roundtrip_and_formula_escaping(self):
        self.old.reason = '=HYPERLINK("https://example.invalid")\nExplanation'
        self.old.save()
        content = b"".join(self.client.get(self.export_url).streaming_content)
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        self.assertTrue(
            next(
                row["reason"] for row in rows if row["phrase"] == self.old.phrase
            ).startswith("'=")
        )
        self.old.reason = "changed"
        self.old.save()
        self.assertEqual(self.upload(content).status_code, 302)
        self.old.refresh_from_db()
        self.assertEqual(
            self.old.reason, '=HYPERLINK("https://example.invalid")\nExplanation'
        )

    def test_invalid_reason_rolls_back_whole_import(self):
        for reason in ("x" * 2001, "null\x00byte"):
            data = (
                "phrase,action,enabled,reason\nNew,reject,1,Valid\nOld phrase,reject,1,"
                + reason
                + "\n"
            )
            self.assertEqual(self.upload(data).status_code, 200)
            self.assertFalse(ModerationRule.objects.filter(phrase="New").exists())

    def test_invalid_row_never_partially_updates_or_adds(self):
        response = self.upload(
            "phrase,action,enabled\nOld phrase,reject,0\nNew,review,1\nBad,unknown,1\n"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4")
        self.old.refresh_from_db()
        self.assertEqual(self.old.action, "review")
        self.assertEqual(ModerationRule.objects.count(), 2)

    def test_invalid_import_exposes_focusable_error_summary_and_field_link(self):
        response = self.upload("phrase,action,enabled\nBad,unknown,1\n")
        self.assertContains(response, "data-commentail-error-focus")
        self.assertContains(response, 'tabindex="-1"')
        self.assertContains(response, 'href="#id_file"')
        self.assertContains(response, 'id="id_file_error"', count=1)
        self.assertContains(response, response.context["form"].errors["file"][0])
        self.assertContains(response, "/static/commentail/admin.js")
        initial = self.client.get(self.import_url)
        self.assertNotContains(initial, "data-commentail-error-focus")

    def test_invalid_encoding_headers_and_duplicate_rows(self):
        for data in (
            b"\xff",
            "phrase,action\nA,review\n",
            "phrase,action,enabled\nA,review,1\nA,reject,0\n",
            "phrase,action,enabled\nA,review,maybe\n",
            'phrase,action,enabled\n"unterminated,review,1',
            "phrase,action,enabled\n,,\n",
            "phrase,action,enabled\n" + "x" * 256 + ",review,1\n",
        ):
            with self.subTest(data=data):
                response = self.upload(data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertEqual(ModerationRule.objects.count(), 2)

    def test_ambiguous_existing_phrase_rolls_back(self):
        ModerationRule.objects.create(phrase="Old phrase", action="reject")
        response = self.upload(
            "phrase,action,enabled\nNew,review,1\nOld phrase,review,0\n"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ModerationRule.objects.filter(phrase="New").exists())

    def test_export_roundtrip_unicode_quoting_and_formula_escaping(self):
        phrases = [
            'Фраза, "кавычки"\nвторая строка',
            '=HYPERLINK("https://example.invalid")',
            "'literal",
            "\tformula",
            "+sum",
            "@name",
            " =formula",
        ]
        for phrase in phrases:
            ModerationRule.objects.create(phrase=phrase, action="reject", enabled=False)
        response = self.client.get(self.export_url, {"q": "no matches"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        content = b"".join(response.streaming_content)
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 9)
        self.assertTrue(
            next(r["phrase"] for r in rows if "HYPERLINK" in r["phrase"]).startswith(
                "'="
            )
        )
        self.assertRedirects(self.upload(content), reverse("commentail_admin:rules"))
        self.assertEqual(ModerationRule.objects.count(), 9)
        for phrase in phrases:
            self.assertFalse(ModerationRule.objects.get(phrase=phrase).enabled)

    @override_settings(
        COMMENTAIL={"default": {"RULES_CSV_MAX_BYTES": 40, "RULES_CSV_MAX_ROWS": 1}}
    )
    def test_upload_and_row_limits(self):
        self.assertTrue(self.upload("x" * 41).context["form"].errors)
        with override_settings(
            COMMENTAIL={
                "default": {"RULES_CSV_MAX_BYTES": 1000, "RULES_CSV_MAX_ROWS": 1}
            }
        ):
            self.assertTrue(
                self.upload("phrase,action,enabled\nA,review,1\nB,review,1\n")
                .context["form"]
                .errors
            )

    def test_large_import_and_project_wide_configuration(self):
        rows = "phrase,action,enabled\n" + "".join(
            f"Bulk {i},review,1\n" for i in range(1500)
        )
        self.assertRedirects(self.upload(rows), reverse("commentail_admin:rules"))
        self.assertEqual(ModerationRule.objects.count(), 1502)
        from commentail.config import configuration_errors

        with override_settings(
            COMMENTAIL={"example.invalid": {"RULES_CSV_MAX_ROWS": 10}}
        ):
            self.assertTrue(configuration_errors())

    def test_access_and_csrf(self):
        user = get_user_model().objects.create_user("csv-viewer", is_staff=True)
        group = Group.objects.create(name="CSV viewers")
        group.permissions.add(Permission.objects.get(codename="access_admin"))
        user.groups.add(group)
        SiteGroupPermission.objects.create(
            group=group, site=Site.objects.get(is_default_site=True), view=True
        )
        self.client.force_login(user)
        self.client.defaults["HTTP_X_REQUESTED_WITH"] = "XMLHttpRequest"
        self.assertEqual(self.client.get(self.export_url).status_code, 403)
        self.assertEqual(self.client.get(self.import_url).status_code, 403)
        self.assertEqual(
            self.upload("phrase,action,enabled\nNew,review,1\n").status_code, 403
        )
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(
            csrf.post(
                self.import_url,
                {
                    "file": SimpleUploadedFile(
                        "rules.csv", b"phrase,action,enabled\nNew,review,1"
                    )
                },
            ).status_code,
            403,
        )
        self.assertEqual(ModerationRule.objects.count(), 2)
