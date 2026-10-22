"""Boundary regressions for the widget and moderation refactor."""

from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import signing
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from wagtail.models import Site

from commentail.admin_views import _diff
from commentail.models import Comment, Discussion, FormTicket, SiteCommentSettings
from commentail.public import _next, _url, _window, block_context, render_text
from commentail.services import submit


class ReadingValueTests(SimpleTestCase):
    def test_plain_and_linked_text_escape_markup_and_keep_trailing_punctuation(self):
        text = "<b>Read</b> https://example.invalid/a?q=1&x=2)."
        plain = render_text(text, False)
        linked = render_text(text, True)
        self.assertNotIn("<a ", plain)
        self.assertIn("&lt;b&gt;Read&lt;/b&gt;", plain)
        self.assertIn("&lt;b&gt;Read&lt;/b&gt;", linked)
        self.assertIn('href="https://example.invalid/a?q=1&amp;x=2"', linked)
        self.assertTrue(linked.endswith("</a>)."))
        self.assertIn('rel="nofollow ugc noopener noreferrer"', linked)

    def test_reading_url_keeps_host_query_and_all_independent_thread_values(self):
        request = RequestFactory().get(
            "/fragment/?thread=4&thread=8&replies=a&replies=b&target=5"
        )
        request.META["COMMENTAIL_WIDGET_PATH"] = "/host/?category=books#commentail"
        parts = urlsplit(_url(request, target=None, window="next"))
        self.assertEqual(parts.path, "/host/")
        self.assertEqual(parts.fragment, "commentail")
        self.assertEqual(
            parse_qs(parts.query),
            {
                "category": ["books"],
                "thread": ["4", "8"],
                "replies": ["a", "b"],
                "window": ["next"],
            },
        )

    def test_revision_diff_escapes_both_sides_and_marks_changed_lines(self):
        old, new = _diff("same\n<script>old</script>", "same\n<img src=x>")
        self.assertTrue(old.startswith("same\n<del>"))
        self.assertTrue(new.startswith("same\n<ins>"))
        self.assertIn("&lt;script&gt;", old)
        self.assertIn("&lt;img src=x&gt;", new)
        self.assertNotIn("<script>", old)
        self.assertNotIn("<img ", new)


@override_settings(ALLOWED_HOSTS=["localhost"])
class WidgetBoundaryTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.options = SiteCommentSettings.objects.create(
            site=self.site, mode="read_only"
        )
        self.request = RequestFactory().get("/", HTTP_HOST=self.site.hostname)
        self.request.user = AnonymousUser()
        self.request._wagtail_site = self.site
        SessionMiddleware(lambda request: None).process_request(self.request)

    def test_windows_are_bound_to_discussion_and_exact_thread(self):
        snapshot = timezone.now().isoformat()
        self.request.GET = self.request.GET.copy()
        self.request.GET.setlist(
            "replies",
            [
                _next(self.discussion, snapshot, 40, 7),
                _next(self.discussion, snapshot, 20, 9),
            ],
        )
        self.assertEqual(
            _window(self.request, self.discussion, "replies", 9), (snapshot, 40)
        )
        with patch("django.utils.timezone.now", return_value=timezone.now()) as now:
            self.assertEqual(
                _window(self.request, self.discussion, "replies", 8),
                (now.return_value.isoformat(), 20),
            )
        other = Discussion(pk=self.discussion.pk + 1)
        self.assertEqual(_window(self.request, other, "replies", 9)[1], 20)

    def test_invalid_window_limits_do_not_change_default_batch(self):
        for value in (True, 0, -1, "40", None):
            with self.subTest(limit=value):
                token = signing.dumps(
                    {
                        "discussion": self.discussion.pk,
                        "thread": 0,
                        "snapshot": timezone.now().isoformat(),
                        "limit": value,
                    },
                    salt="commentail.window",
                )
                self.request.GET = self.request.GET.copy()
                self.request.GET["window"] = token
                self.assertEqual(
                    _window(self.request, self.discussion, "window")[1], 20
                )

    def test_hidden_widget_does_not_issue_forms_or_consume_mail_notice(self):
        self.options.mode = "hidden"
        self.options.save()
        self.request.session["commentail_mail_notice"] = self.discussion.pk
        context = block_context(self.request, self.discussion)
        self.assertTrue(context["hidden"])
        self.assertNotIn("rows", context)
        self.assertNotIn("captcha", context)
        self.assertEqual(FormTicket.objects.count(), 0)
        self.assertEqual(
            self.request.session["commentail_mail_notice"], self.discussion.pk
        )

    def test_guest_private_rows_require_browser_proof_and_exclude_deleted_accounts(
        self,
    ):
        self.options.mode = "open"
        self.options.save()
        own = submit(
            self.discussion.pk,
            text="own",
            guest_name="Own",
            guest_email="own@example.invalid",
        )
        foreign = submit(
            self.discussion.pk,
            text="foreign",
            guest_name="Other",
            guest_email="other@example.invalid",
        )
        self.options.mode = "read_only"
        self.options.save()
        Comment.objects.filter(pk=foreign.pk).update(account_deleted=True)
        self.assertEqual(block_context(self.request, self.discussion)["own"], [])
        self.request.session["commentail_own"] = [own.pk, foreign.pk]
        rows = block_context(self.request, self.discussion)["own"]
        self.assertEqual([row["id"] for row in rows], [own.pk])
        self.assertNotIn("email", rows[0])

    def test_expired_confirmation_has_no_resend_link(self):
        self.options.mode = "open"
        self.options.save()
        comment = submit(
            self.discussion.pk,
            text="waiting",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        self.options.mode = "read_only"
        self.options.save()
        self.request.session["commentail_own"] = [comment.pk]
        job = comment.mail_events.get(kind="confirm")
        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["expires_at"])
        row = block_context(self.request, self.discussion)["own"][0]
        self.assertEqual(row["resend_url"], "")
        self.assertEqual(
            row["delivery_message"], "The email confirmation deadline has passed."
        )
