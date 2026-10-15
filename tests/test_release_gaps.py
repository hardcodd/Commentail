"""Public delivery and configuration contracts, independent of transport details."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Site

from commentail.admission import accept_request, issue_form
from commentail.config import configuration_errors, technical_settings
from commentail.models import Discussion, MailJob, SiteCommentSettings
from commentail.outbox import process_mail
from commentail.security import remember_guest
from commentail.services import moderate, submit


def templates(overrides):
    return [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "OPTIONS": {
                "loaders": [
                    ("django.template.loaders.locmem.Loader", overrides),
                    "django.template.loaders.app_directories.Loader",
                ]
            },
        }
    ]


class MailTemplateTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )

    def guest(self, **kwargs):
        return submit(
            self.discussion.pk,
            text="PRIVATE BODY",
            guest_name="A & B",
            guest_email="guest@example.invalid",
            **kwargs,
        )

    def test_confirmation_overrides_and_optional_html_have_only_metadata(self):
        comment = self.guest(language="en")
        with override_settings(
            TEMPLATES=templates(
                {
                    "commentail/emails/confirm_subject.txt": "  Custom {{ kind }}  \n",
                    "commentail/emails/confirm.txt": "{% autoescape off %}{{ author_name }} {{ action_url }} {{ view_url }} |{{ comment.text }}{{ text }}{{ recipient.email }}|{% endautoescape %}",
                    "commentail/emails/confirm.html": "<p>{{ author_name }}</p><a href='{{ action_url }}'>Confirm</a>{{ comment.text }}{{ text }}",
                }
            )
        ):
            self.assertEqual(process_mail(), 1)
        message = mail.outbox[-1]
        self.assertEqual(message.subject, "Custom confirm")
        self.assertIn("A & B", message.body)
        self.assertIn("/actions/confirm/?token=", message.body)
        self.assertIn("/actions/view/?token=", message.body)
        self.assertIn("A &amp; B", message.alternatives[0].content)
        self.assertNotIn(comment.text, str(message.message()))
        self.assertNotIn("guest@example.invalid", message.body)

    def test_bad_subject_or_template_fails_one_job_without_secret_diagnostics(self):
        self.guest()
        for source in [
            "Header\nBcc: private@example.invalid",
            "{% broken %}",
            "{% url 'missing-private-route' %}",
            "   ",
        ]:
            MailJob.objects.update(
                status="pending", attempts=0, next_attempt_at=timezone.now()
            )
            with (
                self.subTest(source=source),
                override_settings(
                    TEMPLATES=templates(
                        {
                            "commentail/emails/confirm_subject.txt": source,
                        }
                    )
                ),
            ):
                self.assertEqual(process_mail(), 0)
            job = MailJob.objects.get()
            self.assertEqual(job.status, "failed")
            self.assertNotIn("private", job.error)
            self.assertIsNone(job.lease_until)

    def test_saved_language_and_every_kind_use_templates_without_author_text(self):
        from commentail.services import confirm_email

        comment = self.guest(language="ru")
        self.assertEqual(process_mail(), 1)
        self.assertEqual(mail.outbox[-1].subject, "Подтвердите email")
        confirm_email(comment.pk)
        admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        moderate(comment.pk, "approve", actor=admin)
        edit = MailJob.objects.get(kind="edit")
        for kind in ["edit", "published", "rejected", "reply"]:
            with (
                self.subTest(kind=kind),
                override_settings(
                    TEMPLATES=templates(
                        {
                            f"commentail/emails/{kind}_subject.txt": "Custom {{ kind }}",
                            f"commentail/emails/{kind}.txt": "{{ kind }} {{ target_url }} {{ text }}{{ comment.text }}",
                        }
                    )
                ),
            ):
                # Rendering contract: lifecycle eligibility is tested separately.
                from commentail.outbox import deliver

                edit.kind = kind
                deliver(edit)
                self.assertEqual(mail.outbox[-1].subject, f"Custom {kind}")
                self.assertIn(f"target={comment.pk}", mail.outbox[-1].body)
                self.assertNotIn(comment.text, mail.outbox[-1].body)

    def test_broken_html_include_does_not_abort_other_jobs(self):
        from commentail.services import confirm_email

        self.guest()
        second = self.guest()
        confirm_email(second.pk)
        admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        moderate(second.pk, "approve", actor=admin)
        with override_settings(
            TEMPLATES=templates(
                {
                    "commentail/emails/confirm.html": '{% include "missing-private-template.html" %}',
                }
            )
        ):
            self.assertEqual(process_mail(), 1)
        self.assertEqual(
            MailJob.objects.filter(kind="confirm", status="failed").count(), 1
        )
        self.assertEqual(MailJob.objects.get(kind="edit").status, "sent")
        self.assertEqual(
            MailJob.objects.get(kind="confirm", status="failed").error,
            "TemplateDoesNotExist",
        )

    def test_reply_html_override_cannot_traverse_to_reply_or_parent_text(self):
        author = get_user_model().objects.create_user(
            "writer", email="writer@example.invalid"
        )
        admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        parent = submit(
            self.discussion.pk, text="SECRET PARENT", user=author, subscribe=True
        )
        moderate(parent.pk, "approve", actor=admin)
        reply = submit(
            self.discussion.pk, text="SECRET REPLY", user=admin, reply_to=parent.pk
        )
        moderate(reply.pk, "approve", actor=admin)
        with override_settings(
            TEMPLATES=templates(
                {
                    "commentail/emails/reply.html": "{{ author_name }} {{ target_url }} {{ action_url }} {{ text }}{{ comment.text }}{{ comment.reply_to.text }}{{ recipient.text }}{{ job.comment.text }}",
                }
            )
        ):
            self.assertEqual(process_mail(), 1)
        raw = str(mail.outbox[-1].message())
        self.assertNotIn("SECRET PARENT", raw)
        self.assertNotIn("SECRET REPLY", raw)
        self.assertIn(
            "/actions/unsubscribe/?token=", mail.outbox[-1].alternatives[0].content
        )


class GuestRequestSettingsTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        SiteCommentSettings.objects.create(site=self.site, moderation="none")

    def test_configuration_validation_and_hostname_inheritance(self):
        with override_settings(
            COMMENTAIL={
                "default": {"GUEST_REQUEST_CHECKS": ["missing_user_agent"]},
                self.site.hostname: {"GUEST_REQUEST_CHECKS": []},
            }
        ):
            self.assertEqual(configuration_errors(), [])
            self.assertEqual(technical_settings(self.site)["GUEST_REQUEST_CHECKS"], [])
            self.assertEqual(
                technical_settings(None)["GUEST_REQUEST_CHECKS"], ["missing_user_agent"]
            )
        for value in [
            True,
            "cross_site",
            ["unknown"],
            ["cross_site", "cross_site"],
            [1],
        ]:
            with (
                self.subTest(value=value),
                override_settings(
                    COMMENTAIL={"default": {"GUEST_REQUEST_CHECKS": value}}
                ),
            ):
                self.assertTrue(configuration_errors())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
    )
    def test_each_signal_can_be_enabled_or_disabled_independently(self):
        cases = [
            ([], {}, "published"),
            (["missing_user_agent"], {}, "pending"),
            (["cross_site"], {}, "published"),
            (["cross_site"], {"HTTP_SEC_FETCH_SITE": "cross-site"}, "pending"),
            (
                ["missing_user_agent"],
                {"HTTP_USER_AGENT": "Browser", "HTTP_SEC_FETCH_SITE": "cross-site"},
                "published",
            ),
        ]
        for index, (checks, headers, expected) in enumerate(cases):
            with (
                self.subTest(checks=checks, headers=headers),
                override_settings(
                    COMMENTAIL={"default": {"GUEST_REQUEST_CHECKS": checks}}
                ),
            ):
                request = RequestFactory().post(
                    "/", REMOTE_ADDR=f"127.0.0.{index + 1}", **headers
                )
                request.user = AnonymousUser()
                request.session = SessionStore()
                request.session.create()
                email = f"guest{index}@example.invalid"
                request.COOKIES[f"commentail_guest_{self.site.pk}"] = remember_guest(
                    self.site, email
                )
                comment = accept_request(
                    request,
                    self.discussion.pk,
                    issue_form(request, self.discussion),
                    text="Message",
                    guest_name="Guest",
                    guest_email=email,
                )
                self.assertEqual(comment.status, expected)

    @override_settings(
        EMAIL_HOST="smtp.invalid", COMMENTAIL={"default": {"GUEST_REQUEST_CHECKS": []}}
    )
    def test_disabled_signals_do_not_disable_csrf(self):
        from django.middleware.csrf import get_token

        browser = Client(enforce_csrf_checks=True)
        user = get_user_model().objects.create_user("writer")
        browser.force_login(user)
        url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        original = browser.get(url)
        response = browser.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {
                "key": original.context["form_key"],
                "text": "Attack",
                "csrfmiddlewaretoken": get_token(original.wsgi_request),
            },
            HTTP_ORIGIN="https://attacker.invalid",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.discussion.comments.exists())


class GuestDeliveryStatusTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.comment = submit(
            self.discussion.pk,
            text="PRIVATE COMMENT",
            guest_name="Guest",
            guest_email="private@example.invalid",
        )
        self.url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        session = self.client.session
        session["commentail_own"] = [self.comment.pk]
        session.save()

    def test_owner_sees_neutral_states_never_transport_data(self):
        cases = [
            ("pending", "", "Confirmation email is queued.", True),
            ("sending", "", "Confirmation email is being sent.", False),
            (
                "pending",
                "SMTP secret@example.invalid token=secret",
                "There was a problem sending the confirmation email. We will retry automatically.",
                True,
            ),
            (
                "failed",
                "SMTP secret@example.invalid token=secret",
                "There was a problem sending the confirmation email. You can request it again.",
                True,
            ),
            (
                "sent",
                "",
                "Confirmation email was sent. Check your inbox and spam folder.",
                True,
            ),
            ("cancelled", "", "Confirmation email is unavailable.", False),
        ]
        for status, error, message, resend in cases:
            MailJob.objects.update(status=status, error=error)
            with self.subTest(status=status, error=bool(error)):
                response = self.client.get(self.url)
                self.assertContains(response, message)
                self.assertNotContains(response, "secret@example.invalid")
                self.assertNotContains(response, "private@example.invalid")
                self.assertEqual(bool(response.context["own"][0]["resend_url"]), resend)
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertNotContains(Client().get(self.url), message)

    def test_expiry_and_retry_keep_original_deadline(self):
        job = MailJob.objects.get()
        expiry = job.expires_at
        MailJob.objects.update(status="failed", error="TimeoutError")
        self.assertEqual(
            self.client.post(
                reverse("commentail:resend", args=[self.comment.pk])
            ).status_code,
            302,
        )
        job.refresh_from_db()
        self.assertEqual(job.expires_at, expiry)
        self.assertContains(self.client.get(self.url), "Confirmation email is queued.")
        MailJob.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.get(self.url)
        self.assertContains(response, "The email confirmation deadline has passed.")
        self.assertFalse(response.context["own"][0]["resend_url"])

    def test_real_transport_failure_and_retry_change_owner_feedback(self):
        with patch("commentail.outbox.deliver", side_effect=TimeoutError("secret")):
            process_mail()
        self.assertContains(self.client.get(self.url), "We will retry automatically.")
        MailJob.objects.update(next_attempt_at=timezone.now())
        self.assertEqual(process_mail(), 1)
        self.assertContains(
            self.client.get(self.url), "Check your inbox and spam folder."
        )

    def test_owner_state_does_not_cross_sites_and_mail_is_loaded_in_bulk(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        other = Site.objects.create(
            hostname="other.invalid", root_page=self.site.root_page
        )
        Discussion.objects.create(site=other, page=self.site.root_page)
        self.assertNotContains(
            self.client.get(self.url, HTTP_HOST="other.invalid"),
            "Confirmation email is queued.",
        )
        identifiers = [self.comment.pk]
        for _ in range(5):
            identifiers.append(
                submit(
                    self.discussion.pk,
                    text="Owner",
                    guest_name="Guest",
                    guest_email="private@example.invalid",
                ).pk
            )
        session = self.client.session
        session["commentail_own"] = identifiers
        session.save()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)
        self.assertContains(response, "Confirmation email is queued.", count=6)
        mail_reads = [
            row["sql"] for row in queries if 'FROM "commentail_mailjob"' in row["sql"]
        ]
        self.assertEqual(len(mail_reads), 1)
