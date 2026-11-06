"""Self-reply rejection applies beyond the visible Reply control."""
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Site

from commentail.models import Comment, Discussion, SiteCommentSettings
from commentail.security import remember_guest
from commentail.services import DomainError, submit


class SelfReplyTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(site=self.site, page=self.site.root_page)
        SiteCommentSettings.objects.create(site=self.site, moderation="none")
        self.author = get_user_model().objects.create_user("self", email="self@example.invalid")
        self.other = get_user_model().objects.create_user("other", email="other@example.invalid")
        self.comment = submit(self.discussion.pk, text="Parent", user=self.author)
        self.url = reverse("commentail:discussion", args=[self.site.root_page.pk])

    def test_rejected_self_reply_does_not_lock_parent_or_create_comment(self):
        with self.assertRaisesMessage(DomainError, "You cannot reply to your own comment."):
            submit(self.discussion.pk, text="Self reply", user=self.author, reply_to=self.comment.pk)
        self.comment.refresh_from_db()
        self.assertFalse(self.comment.edit_locked)
        self.assertEqual(self.discussion.comments.count(), 1)
        reply = submit(self.discussion.pk, text="Other reply", user=self.other, reply_to=self.comment.pk)
        self.assertEqual(reply.reply_to_id, self.comment.pk)

    def test_guest_email_is_compared_without_case_or_surrounding_space(self):
        parent = Comment.objects.create(discussion=self.discussion, text="Guest parent", guest_name="Guest", email=" guest@example.invalid ", status="published", published_at=timezone.now())
        with self.assertRaisesMessage(DomainError, "You cannot reply to your own comment."):
            submit(self.discussion.pk, text="Self reply", guest_name="Another name", guest_email="GUEST@example.invalid", reply_to=parent.pk)
        parent.refresh_from_db()
        self.assertFalse(parent.edit_locked)

    def test_author_has_no_reply_link_or_forced_reply_form_but_other_reader_does(self):
        self.client.force_login(self.author)
        response = self.client.get(self.url, {"reply_to": self.comment.pk})
        markup = BeautifulSoup(response.content, "html.parser")
        self.assertIsNone(markup.select_one(f'[data-commentail-reply="{self.comment.pk}"]'))
        self.assertIsNone(markup.select_one(".commentail-form[data-reply-to]"))
        self.client.force_login(self.other)
        markup = BeautifulSoup(self.client.get(self.url, {"reply_to": self.comment.pk}).content, "html.parser")
        self.assertIsNotNone(markup.select_one(f'[data-commentail-reply="{self.comment.pk}"]'))
        self.assertIsNotNone(markup.select_one(".commentail-form[data-reply-to]"))

    def test_guest_proof_hides_self_reply_without_granting_edit_rights(self):
        parent = Comment.objects.create(discussion=self.discussion, text="Guest parent", guest_name="Guest", email="guest@example.invalid", status="published", published_at=timezone.now())
        self.client.cookies[f"commentail_guest_{self.site.pk}"] = remember_guest(self.site, "GUEST@example.invalid")
        markup = BeautifulSoup(self.client.get(self.url, {"reply_to": parent.pk}).content, "html.parser")
        self.assertIsNone(markup.select_one(f'[data-commentail-reply="{parent.pk}"]'))
        self.assertIsNone(markup.select_one(".commentail-form[data-reply-to]"))
        self.assertIsNone(markup.select_one(f'[data-commentail-edit="{parent.pk}"]'))

    def test_forged_post_rejects_self_reply_and_preserves_text(self):
        self.client.force_login(self.author)
        markup = BeautifulSoup(self.client.get(self.url).content, "html.parser")
        form = markup.select_one(".commentail-form")
        values = {node["name"]: node.get("value", "") for node in form.select("input[name]")}
        values.update(text="Preserve this rejected draft", reply_to=self.comment.pk)
        response = self.client.post(form["action"], values)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "You cannot reply to your own comment.", status_code=400)
        self.assertContains(response, "Preserve this rejected draft", status_code=400)
        self.assertEqual(self.discussion.comments.count(), 1)
