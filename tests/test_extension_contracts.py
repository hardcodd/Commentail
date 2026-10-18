"""Host extensions consume the public contract without importing internal models."""

from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from wagtail.models import PageViewRestriction, Site

from commentail.models import Discussion, MailJob
from commentail.outbox import GuestRecipient, process_mail
from commentail.services import moderate, revise, submit
from tests.test_release_gaps import templates


def author_name_callback(user, request):
    return user.username


def guest_mail_callback(recipient, target, site):
    return False


def host_templates(source):
    return templates(
        {
            "wagtailcore/page.html": "{% load commentail_tags %}{% commentail page %}",
            "commentail/block.html": source,
        }
    )


class ExtensionContractTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.author = get_user_model().objects.create_user("extension-author")
        self.admin = get_user_model().objects.create_superuser(
            "extension-admin", "", "test"
        )
        self.url = reverse("commentail:discussion", args=[self.site.root_page.pk])

    def published(self, text, **kwargs):
        return moderate(
            submit(self.discussion.pk, text=text, user=self.author, **kwargs).pk,
            "approve",
            actor=self.admin,
        )

    def test_host_override_consumes_public_thread_and_form_context(self):
        root = self.published("<script>public & root</script>")
        reply = self.published("Public reply", reply_to=root.pk)
        source = """{{ discussion_id }}|{{ page_id }}|{{ language_code }}
{% for item in rows %}<article id="commentail-{{ item.id }}">
{{ item.display_name }}|{{ item.body }}|{{ item.permalink }}|{{ item.reply_count }}
{% if item.opened %}{% for reply in item.replies %}
<aside>{{ reply.id }}|{{ reply.reply_to_id }}|{{ reply.reply_to_name }}|{{ reply.body }}</aside>
{% endfor %}{% endif %}</article>{% endfor %}
{% if can_post %}{% include 'commentail/form.html' %}{% endif %}"""
        self.client.force_login(self.author)
        with override_settings(TEMPLATES=host_templates(source)):
            response = self.client.get(
                self.url, {"reply_to": root.pk, "target": reply.pk}
            )
            self.assertContains(response, f'id="commentail-{root.pk}"')
            self.assertContains(
                response, "&lt;script&gt;public &amp; root&lt;/script&gt;"
            )
            self.assertContains(
                response,
                f"<aside>{reply.pk}|{root.pk}|extension-author|Public reply</aside>",
            )
            self.assertContains(response, f'name="reply_to" value="{root.pk}"')
            key = response.context["form_key"]
            response = self.client.post(
                reverse("commentail:submit", args=[self.site.root_page.pk]),
                {"key": key, "reply_to": root.pk, "text": "Override form reply"},
            )
            self.assertEqual(response.status_code, 302)
        accepted = self.discussion.comments.get(text="Override form reply")
        self.assertEqual(accepted.reply_to_id, root.pk)
        self.assertEqual(accepted.user_id, self.author.pk)

    def test_pending_revision_context_is_private_and_public_schema_keeps_old_text(self):
        root = self.published("Public original")
        revise(root.pk, "Private proposed revision", user=self.author)
        source = """{% for item in rows %}<p>{{ item.body }}|{{ item.schema.text }}</p>{% endfor %}
{% for item in own %}<aside>{{ item.body }}|{{ item.status }}|{{ item.schema }}</aside>{% endfor %}"""
        with override_settings(
            COMMENTAIL={"default": {"STRUCTURED_DATA": "json_ld"}},
            TEMPLATES=host_templates(source),
        ):
            public = self.client.get(self.url)
            self.assertContains(public, "Public original|Public original")
            self.assertNotContains(public, "Private proposed revision")
            self.client.force_login(self.author)
            owner = self.client.get(self.url)
            self.assertContains(
                owner, "<aside>Private proposed revision|published|None</aside>"
            )
            self.assertContains(owner, "Public original|Public original")

    def test_author_name_callback_receives_user_and_request_and_falls_back_safely(self):
        root = self.published("Public text")
        callback = Mock(return_value="  <Custom author>  ")
        config = {
            "default": {
                "GET_AUTHOR_NAME": "tests.test_extension_contracts.author_name_callback"
            }
        }
        with (
            override_settings(COMMENTAIL=config),
            patch("tests.test_extension_contracts.author_name_callback", callback),
        ):
            response = self.client.get(self.url)
            self.assertContains(response, "&lt;Custom author&gt;")
            user, request = callback.call_args.args
            self.assertEqual(user, self.author)
            self.assertEqual(request.path, self.url)
            for value in (None, " ", 7):
                callback.return_value = value
                self.assertContains(self.client.get(self.url), self.author.username)
            callback.side_effect = ValueError("PRIVATE CALLBACK FAILURE")
            with self.assertLogs("commentail", level="ERROR") as logs:
                response = self.client.get(self.url)
            self.assertContains(response, self.author.username)
            self.assertNotContains(response, "PRIVATE CALLBACK FAILURE")
            self.assertNotIn("PRIVATE CALLBACK FAILURE", " ".join(logs.output))
        root.refresh_from_db()
        self.assertEqual(root.text, "Public text")

    def test_guest_mail_callback_is_frozen_minimal_and_requires_explicit_true(self):
        comment = submit(
            self.discussion.pk,
            text="Private body",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        PageViewRestriction.objects.create(
            page=self.site.root_page, restriction_type="login"
        )
        config = {
            "default": {
                "CAN_SEND_GUEST_EMAIL": "tests.test_extension_contracts.guest_mail_callback"
            }
        }
        callback = Mock(return_value=True)
        with (
            override_settings(COMMENTAIL=config),
            patch("tests.test_extension_contracts.guest_mail_callback", callback),
        ):
            self.assertEqual(process_mail(), 1)
            recipient, target, site = callback.call_args.args
            self.assertIsInstance(recipient, GuestRecipient)
            self.assertEqual(recipient.email, comment.email)
            self.assertEqual(recipient.name, comment.guest_name)
            self.assertIsNone(recipient.confirmed_at)
            self.assertEqual(target.pk, self.site.root_page.pk)
            self.assertEqual(site, self.site)
            self.assertFalse(hasattr(recipient, "text"))
            self.assertFalse(hasattr(recipient, "discussion"))
            with self.assertRaises(FrozenInstanceError):
                recipient.name = "Changed"
            delivered = len(mail.outbox)
            for value in (False, None, "yes", 1):
                with self.subTest(value=value):
                    MailJob.objects.update(status="pending", attempts=0)
                    callback.return_value = value
                    self.assertEqual(process_mail(), 0)
                    self.assertEqual(MailJob.objects.get().status, "cancelled")
                    self.assertEqual(len(mail.outbox), delivered)
            MailJob.objects.update(status="pending", attempts=0)
            callback.side_effect = ValueError("Private handler details")
            self.assertEqual(process_mail(), 0)
            job = MailJob.objects.get()
            self.assertEqual(job.status, "failed")
            self.assertNotIn("Private handler details", job.error)
            self.assertEqual(len(mail.outbox), delivered)
