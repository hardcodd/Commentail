from django.contrib.auth import get_user_model
from django.test import TestCase
from wagtail.models import Site

from commentail.models import Comment, Discussion
from commentail.services import DomainError, submit_once


class SubmissionTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.user = get_user_model().objects.create_user("writer")

    def test_duplicate_returns_same_record(self):
        first = submit_once(
            self.discussion.pk, "form-key", text="Message", user=self.user
        )
        second = submit_once(
            self.discussion.pk, "form-key", text="Message", user=self.user
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Comment.objects.count(), 1)

    def test_duplicate_changed_payload_fails(self):
        submit_once(self.discussion.pk, "key", text="Message", user=self.user)
        with self.assertRaises(DomainError):
            submit_once(self.discussion.pk, "key", text="Changed", user=self.user)

    def test_new_key_same_text_is_new_comment(self):
        submit_once(self.discussion.pk, "one", text="Message", user=self.user)
        submit_once(self.discussion.pk, "two", text="Message", user=self.user)
        self.assertEqual(Comment.objects.count(), 2)

    def test_actor_and_discussion_scope(self):
        submit_once(self.discussion.pk, "key", text="Message", user=self.user)
        other = get_user_model().objects.create_user("other")
        submit_once(self.discussion.pk, "key", text="Message", user=other)
        second = Site.objects.create(
            hostname="other.invalid", root_page=self.site.root_page
        )
        discussion = Discussion.objects.create(site=second, page=self.site.root_page)
        submit_once(discussion.pk, "key", text="Message", user=self.user)
        self.assertEqual(Comment.objects.count(), 3)
