from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from wagtail.models import Site

from commentail.models import Comment, CommentRevision, Discussion, ModerationEvent
from commentail.services import (
    DomainError,
    moderate,
    moderate_revision,
    revise,
    submit,
    submit_once,
)


class SQLiteConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if "memory" in connection.settings_dict["NAME"]:
            self.skipTest("Use COMMENTAIL_TEST_SQLITE for a disposable file database")
        from wagtail.models import Locale, Page

        Locale.objects.get_or_create(language_code="en")
        root = Page.get_first_root_node()
        if root is None:
            root = Page.add_root(title="Synthetic root", slug="root")
        self.site = Site.objects.create(hostname="concurrency.invalid", root_page=root)
        self.discussion = Discussion.objects.create(site=self.site, page=root)
        self.author = get_user_model().objects.create_user("concurrent")
        self.admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )

    def race(self, left, right):
        barrier = Barrier(2)

        def run(callback):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return callback()
                except DomainError as exc:
                    return exc
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, left)
            second = pool.submit(run, right)
            return first.result(timeout=25), second.result(timeout=25)

    def published(self):
        comment = submit(self.discussion.pk, text="Original", user=self.author)
        return moderate(comment.pk, "approve", actor=self.admin)

    def test_reply_and_revision_cannot_lose_lock(self):
        comment = self.published()
        outcomes = self.race(
            lambda: revise(comment.pk, "New", user=self.author),
            lambda: submit(
                self.discussion.pk, text="Reply", user=self.author, reply_to=comment.pk
            ),
        )
        comment.refresh_from_db()
        self.assertTrue(comment.edit_locked)
        self.assertEqual(comment.direct_replies.count(), 1)
        self.assertLessEqual(comment.revisions.filter(status="pending").count(), 1)
        self.assertTrue(any(isinstance(item, Comment) for item in outcomes))
        with self.assertRaises(DomainError):
            revise(comment.pk, "Later", user=self.author)

    def test_duplicate_forms_create_one_comment(self):
        outcomes = self.race(
            lambda: submit_once(
                self.discussion.pk, "same", text="Message", user=self.author
            ),
            lambda: submit_once(
                self.discussion.pk, "same", text="Message", user=self.author
            ),
        )
        self.assertTrue(all(isinstance(item, Comment) for item in outcomes))
        self.assertEqual(outcomes[0].pk, outcomes[1].pk)
        self.assertEqual(Comment.objects.count(), 1)

    @override_settings(COMMENTAIL={"default": {"FORM_IP_LIMIT_PER_MINUTE": 1}})
    def test_form_issuance_budget_cannot_be_spent_twice_concurrently(self):
        from commentail.limits import consume
        from commentail.models import RateEvent

        outcomes = self.race(
            lambda: consume(self.site, "form", "", "192.0.2.1"),
            lambda: consume(self.site, "form", "", "192.0.2.1"),
        )
        self.assertEqual(sum(isinstance(item, DomainError) for item in outcomes), 1)
        self.assertEqual(RateEvent.objects.filter(kind="form_ip").count(), 1)

    def test_guest_duplicate_checks_serialize_across_discussions(self):
        from wagtail.models import Page

        page = self.site.root_page.add_child(instance=Page(title="Other", slug="other"))
        other = Discussion.objects.create(site=self.site, page=page)
        text = "A repeated guest message with enough useful context for readers. " * 2
        outcomes = self.race(
            lambda: submit_once(
                self.discussion.pk,
                "first",
                text=text,
                guest_name="First",
                guest_email="first@example.invalid",
            ),
            lambda: submit_once(
                other.pk,
                "second",
                text=text,
                guest_name="Second",
                guest_email="second@example.invalid",
            ),
        )
        self.assertTrue(all(isinstance(item, Comment) for item in outcomes))
        self.assertEqual(sum(item.suspicious for item in outcomes), 1)

    def test_competing_moderators_make_one_decision(self):
        comment = submit(self.discussion.pk, text="Message", user=self.author)
        outcomes = self.race(
            lambda: moderate(comment.pk, "approve", actor=self.admin),
            lambda: moderate(comment.pk, "reject", actor=self.admin),
        )
        comment.refresh_from_db()
        self.assertIn(comment.status, ["published", "rejected"])
        self.assertEqual(ModerationEvent.objects.count(), 1)
        self.assertEqual(sum(isinstance(item, DomainError) for item in outcomes), 1)

    def test_two_mail_workers_have_one_claim(self):
        from commentail.models import MailJob
        from commentail.outbox import claim_job

        submit(
            self.discussion.pk,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        job = MailJob.objects.get(kind="confirm")
        outcomes = self.race(lambda: claim_job(job.pk), lambda: claim_job(job.pk))
        self.assertEqual(sum(item is not None for item in outcomes), 1)
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1)

    def test_competing_author_revisions_preserve_one_pending_draft(self):
        comment = self.published()
        outcomes = self.race(
            lambda: revise(comment.pk, "First draft", user=self.author),
            lambda: revise(comment.pk, "Second draft", user=self.author),
        )
        self.assertEqual(sum(isinstance(item, CommentRevision) for item in outcomes), 1)
        self.assertEqual(sum(isinstance(item, DomainError) for item in outcomes), 1)
        revision = comment.revisions.get()
        self.assertEqual(revision.status, "pending")
        self.assertIn(revision.text, ["First draft", "Second draft"])
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Original")

    def test_competing_revision_decisions_apply_one_result_and_erase_draft(self):
        comment = self.published()
        revision = revise(comment.pk, "Private draft", user=self.author)
        outcomes = self.race(
            lambda: moderate_revision(revision.pk, "approve", actor=self.admin),
            lambda: moderate_revision(revision.pk, "reject", actor=self.admin),
        )
        self.assertEqual(sum(isinstance(item, DomainError) for item in outcomes), 1)
        revision.refresh_from_db()
        comment.refresh_from_db()
        self.assertIn(revision.status, ["approved", "rejected"])
        self.assertEqual(revision.text, "")
        self.assertEqual(
            comment.text,
            "Private draft" if revision.status == "approved" else "Original",
        )
        self.assertEqual(
            ModerationEvent.objects.filter(action__startswith="revision_").count(), 1
        )
