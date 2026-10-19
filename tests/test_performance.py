"""Query-growth regressions; elapsed-time capacity belongs in the benchmark."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from wagtail.models import Page, PageViewRestriction, Site

from commentail.models import (
    Comment,
    CommentRevision,
    Discussion,
    MailJob,
    ModerationRule,
    SiteCommentSettings,
)
from commentail.public import block_context
from commentail.recent import recent_comments
from tests.targets.models import Product
from tests.test_object_adapters import CONFIG


@override_settings(ALLOWED_HOSTS=["localhost"])
class PerformanceTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.page = self.site.root_page
        self.page.get_url(current_site=self.site)
        self.discussion = Discussion.objects.create(site=self.site, page=self.page)
        SiteCommentSettings.objects.create(site=self.site, mode="read_only")
        self.request = RequestFactory().get("/", HTTP_HOST=self.site.hostname)
        self.request.user = AnonymousUser()
        self.request._wagtail_site = self.site
        SessionMiddleware(lambda r: None).process_request(self.request)

    def comments(self, count, discussion=None, **values):
        return Comment.objects.bulk_create([
            Comment(discussion=discussion or self.discussion, text="Synthetic",
                    guest_name="Reader", status="published", published_at=timezone.now(),
                    **values) for _ in range(count)
        ])

    def recent(self, limit=5):
        return recent_comments(self.request, limit=limit, page=None, include_replies=True)

    @override_settings(COMMENTAIL=CONFIG)
    def test_object_resolution_does_not_grow_with_comments(self):
        product = Product.objects.create(site=self.site, title="Target")
        discussion = Discussion.objects.create(
            site=self.site, content_type=ContentType.objects.get_for_model(product),
            object_id=str(product.pk),
        )
        self.comments(25, discussion)
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(len(self.recent(20)), 20)
        lookups = [q for q in queries if 'FROM "commentail_test_targets_product"' in q["sql"]]
        self.assertEqual(len(lookups), 1)

    def test_many_pages_have_batched_access_checks(self):
        for n in range(25):
            page = self.page.add_child(instance=Page(title=str(n), slug=f"p{n}"))
            self.comments(1, Discussion.objects.create(site=self.site, page=page))
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(len(self.recent(20)), 20)
        self.assertLessEqual(len(queries), 9)

    def test_recent_queries_are_limited_and_skip_unpublished_comments_in_sql(self):
        expected = self.comments(1)[0]
        page = self.page.add_child(instance=Page(title="Draft", slug="draft", live=False))
        self.comments(250, Discussion.objects.create(site=self.site, page=page))
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.recent(1)[0]["id"], expected.pk)
        candidates = [q["sql"] for q in queries if 'FROM "commentail_comment"' in q["sql"]]
        self.assertTrue(candidates)
        self.assertTrue(all("LIMIT" in sql for sql in candidates))
        self.assertTrue(all('"live"' in sql for sql in candidates))

    def test_sqlite_recent_order_uses_index_with_collected_statistics(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite planner regression; PostgreSQL plans are in the benchmark")
        self.comments(1000)
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE")
        with CaptureQueriesContext(connection) as queries:
            self.recent()
        sql = next(q["sql"] for q in queries if 'FROM "commentail_comment"' in q["sql"])
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN QUERY PLAN " + sql)
            plan = " ".join(str(row) for row in cursor.fetchall())
        self.assertIn("commentail_publication_order", plan)
        self.assertNotIn("TEMP B-TREE", plan)

    def test_closed_threads_do_not_add_queries_per_root(self):
        self.comments(1)
        with CaptureQueriesContext(connection) as small:
            block_context(self.request, self.discussion)
        self.comments(19)
        with CaptureQueriesContext(connection) as large:
            context = block_context(self.request, self.discussion)
        self.assertEqual(len(context["rows"]), 20)
        self.assertLessEqual(len(large), len(small) + 1)

    def test_recent_alias_keeps_source_restrictions(self):
        source = self.page.add_child(instance=Page(title="Private", slug="private"))
        PageViewRestriction.objects.create(page=source, restriction_type="login")
        alias = source.create_alias(parent=self.page, update_slug="alias")
        self.comments(1, Discussion.objects.create(site=self.site, page=alias))
        self.assertEqual(self.recent(), [])

    def test_groups_are_batched_and_membership_is_rechecked(self):
        group = Group.objects.create(name="Readers")
        self.request.user = get_user_model().objects.create_user("member")
        self.request.user.groups.add(group)
        for n in range(12):
            page = self.page.add_child(instance=Page(title=str(n), slug=f"group{n}"))
            restriction = PageViewRestriction.objects.create(page=page, restriction_type="groups")
            restriction.groups.add(group)
            self.comments(1, Discussion.objects.create(site=self.site, page=page))
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(len(self.recent(12)), 12)
        self.assertLessEqual(len(queries), 9)
        self.request.user.groups.clear()
        self.assertEqual(self.recent(), [])

    def test_native_group_acceptance_is_preserved(self):
        group = Group.objects.create(name="Readers")
        self.request.user = get_user_model().objects.create_user("member")
        self.request.user.groups.add(group)
        restriction = PageViewRestriction.objects.create(page=self.page, restriction_type="groups")
        restriction.groups.add(group)
        self.comments(1)
        with patch.object(PageViewRestriction, "accept_request", return_value=False):
            self.assertEqual(self.recent(), [])

    def test_custom_page_restrictions_use_native_resolution(self):
        from commentail.recent import _page_access

        class CustomPage(SimpleNamespace):
            def get_view_restrictions(self):
                return [SimpleNamespace(accept_request=lambda request: False)]

        page = CustomPage(path=self.page.path)
        self.assertFalse(_page_access(self.request, {self.page.pk: page})[self.page.pk])

    def test_page_unpublished_during_selection_is_excluded(self):
        self.comments(1)

        def check(request, pages):
            for page in pages.values():
                page.live = False
            return dict.fromkeys(pages, True)

        with patch("commentail.recent._page_access", side_effect=check):
            self.assertEqual(self.recent(), [])

    def test_open_replies_do_not_add_queries_per_reply(self):
        root = self.comments(1)[0]
        self.comments(1, root=root, reply_to=root)
        self.request.GET = self.request.GET.copy()
        self.request.GET["thread"] = str(root.pk)
        with CaptureQueriesContext(connection) as small:
            block_context(self.request, self.discussion)
        self.comments(19, root=root, reply_to=root)
        with CaptureQueriesContext(connection) as large:
            result = block_context(self.request, self.discussion)
        self.assertEqual(len(result["rows"][0]["replies"]), 20)
        self.assertLessEqual(len(large), len(small) + 1)

    def test_cleanup_does_not_lock_fresh_unconfirmed_discussions(self):
        from commentail.services import cleanup_unconfirmed

        fresh = Comment.objects.create(discussion=self.discussion, text="Fresh")
        old = Comment.objects.create(discussion=self.discussion, text="Expired")
        Comment.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=7))
        with patch("commentail.services._comment", wraps=__import__(
            "commentail.services", fromlist=["_comment"]
        )._comment) as lock:
            self.assertEqual(cleanup_unconfirmed(), 1)
        self.assertEqual([call.args[0] for call in lock.call_args_list], [old.pk])
        self.assertTrue(Comment.objects.filter(pk=fresh.pk).exists())

    def test_rule_prefixes_duplicates_and_disabled_entries_keep_priority(self):
        from commentail.policies import policy_result

        ModerationRule.objects.bulk_create([
            ModerationRule(phrase="one two", action="review"),
            ModerationRule(phrase="two three", action="reject"),
            ModerationRule(phrase="one", action="review"),
            ModerationRule(phrase="one two three", action="reject"),
            ModerationRule(phrase="one two", action="reject", enabled=False),
            ModerationRule(phrase="duplicate", action="reject"),
            ModerationRule(phrase="duplicate", action="review"),
            ModerationRule(phrase="!!!", action="reject"),
        ])
        for text, expected in [
            ("one two", "pending"), ("one two three", "rejected"),
            ("other two three", "rejected"), ("someone", "published"),
            ("DUPLICATE", "rejected"), ("one. unmatched", "pending"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(policy_result(text, "rules", guest=False, suspicious=False), expected)

    def test_claim_loads_mail_author_and_revision_without_followup_queries(self):
        from commentail.outbox import claim_job

        user = get_user_model().objects.create_user("author")
        comment = Comment.objects.create(discussion=self.discussion, user=user, text="Source")
        revision = CommentRevision.objects.create(comment=comment, text="Revision", reason="Reason")
        job = MailJob.objects.create(
            comment=comment, recipient=comment, revision=revision, event_key="performance",
            kind="rejected", expires_at=timezone.now() + timedelta(hours=1),
        )
        claimed = claim_job(job.pk)
        with self.assertNumQueries(0):
            self.assertEqual(claimed.comment.display_name, "author")
            self.assertEqual(claimed.revision.reason, "Reason")
