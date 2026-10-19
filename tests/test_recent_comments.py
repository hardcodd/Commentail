from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection
from django.template import Context, Template, TemplateSyntaxError
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.safestring import mark_safe
from wagtail.models import Page, PageViewRestriction, Site

from commentail.middleware import CapabilityHeadersMiddleware
from commentail.models import Comment, Discussion, SiteCommentSettings
from tests.targets.models import Product
from tests.test_object_adapters import CONFIG


class RecentCommentsTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.page = self.site.root_page
        self.discussion = Discussion.objects.create(site=self.site, page=self.page)
        self.request = RequestFactory().get("/", HTTP_HOST=self.site.hostname)
        self.request.user = AnonymousUser()
        SessionMiddleware(lambda request: None).process_request(self.request)

    def comment(self, discussion=None, **kwargs):
        return Comment.objects.create(
            discussion=discussion or self.discussion,
            **{
                "text": "Public text", "guest_name": "Guest",
                "status": "published", "published_at": timezone.now(), **kwargs,
            },
        )

    def recent(self, arguments="", **values):
        context = Context({"request": self.request, **values})
        Template(
            "{% load commentail_tags %}{% commentail_recent "
            + arguments + " as comments %}"
        ).render(context)
        return context["comments"]

    def test_publication_order_ties_default_limit_and_no_writes(self):
        now = timezone.now()
        comments = [self.comment(published_at=now) for _ in range(7)]
        old = self.comment(published_at=now - timedelta(days=1))
        for status in Comment.Status.values:
            if status != "published":
                self.comment(status=status)
        self.comment(published_at=None)
        self.comment(published_at=now + timedelta(days=1))
        with CaptureQueriesContext(connection) as queries:
            rows = self.recent()
        self.assertFalse(any(
            q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}
            for q in queries
        ))
        self.assertEqual([row["id"] for row in rows], [c.pk for c in comments[::-1]][:5])
        self.assertEqual(self.recent("limit=1")[0]["id"], comments[-1].pk)
        self.assertEqual(self.recent("limit=8")[-1]["id"], old.pk)
        self.assertEqual(self.recent("limit=0"), [])

    def test_exact_page_filter_and_reply_toggle(self):
        child = self.page.add_child(instance=Page(title="Other", slug="other"))
        other = Discussion.objects.create(site=self.site, page=child)
        root = self.comment()
        reply = self.comment(root=root, reply_to=root)
        self.comment(other)
        self.assertEqual([r["id"] for r in self.recent("page=page", page=self.page)], [reply.pk, root.pk])
        self.assertEqual(
            [r["id"] for r in self.recent("page=page include_replies=False", page=self.page)],
            [root.pk],
        )
        for value in ("", 123, Page(title="Unsaved")):
            self.assertEqual(self.recent("page=page", page=value), [])

    def test_page_access_including_inherited_restrictions_and_live_state(self):
        child = self.page.add_child(instance=Page(title="Restricted", slug="restricted"))
        discussion = Discussion.objects.create(site=self.site, page=child)
        comment = self.comment(discussion)
        restriction = PageViewRestriction.objects.create(page=self.page, restriction_type="login")
        self.assertEqual(self.recent(), [])
        self.request.user = get_user_model().objects.create_user("reader")
        self.assertEqual(self.recent()[0]["id"], comment.pk)
        restriction.delete()
        child.live = False
        child.save()
        self.assertEqual(self.recent(), [])

    def test_hidden_settings_read_only_and_explicit_override(self):
        comment = self.comment()
        setting = SiteCommentSettings.objects.create(site=self.site, mode="hidden")
        self.assertEqual(self.recent(), [])
        self.discussion.mode = "read_only"
        self.discussion.save()
        self.assertEqual(self.recent()[0]["id"], comment.pk)
        setting.mode = "open"
        setting.save()
        self.discussion.mode = "hidden"
        self.discussion.save()
        self.assertEqual(self.recent(), [])

    def test_unavailable_candidates_do_not_consume_limit(self):
        visible = self.comment()
        child = self.page.add_child(instance=Page(title="Hidden", slug="hidden", live=False))
        discussion = Discussion.objects.create(site=self.site, page=child)
        for _ in range(105):
            self.comment(discussion)
        self.assertEqual([r["id"] for r in self.recent("limit=1")], [visible.pk])

    def test_site_isolation_and_missing_context(self):
        site = Site.objects.create(hostname="other.invalid", root_page=self.page)
        discussion = Discussion.objects.create(site=site, page=self.page)
        self.comment(discussion)
        self.assertEqual(self.recent(), [])
        self.assertEqual(self.recent(request=None), [])
        with patch("wagtail.models.Site.find_for_request", return_value=None):
            self.assertEqual(self.recent(), [])

    def test_page_without_widget_is_excluded(self):
        self.comment()
        with patch("commentail.detection.has_comments", return_value=False):
            self.assertEqual(self.recent(), [])

    def test_page_outside_site_root_is_excluded(self):
        outside = Page.get_first_root_node().add_child(
            instance=Page(title="Outside site", slug="outside-site"),
        )
        self.comment(Discussion.objects.create(site=self.site, page=outside))
        self.assertEqual(self.recent(), [])

    def test_unresolvable_template_fails_closed(self):
        from commentail.detection import DetectionError

        self.comment()
        with patch("commentail.detection.has_comments", side_effect=DetectionError):
            self.assertEqual(self.recent(), [])

    def test_access_decision_is_reused_only_within_one_selection(self):
        for _ in range(5):
            self.comment()
        with patch("commentail.recent._page_access", return_value={self.page.pk: True}) as check:
            self.assertEqual(len(self.recent()), 5)
            check.assert_called_once()
        with patch("commentail.recent._page_access", return_value={self.page.pk: False}):
            self.assertEqual(self.recent(), [])

    def test_password_restriction_uses_current_session(self):
        comment = self.comment()
        restriction = PageViewRestriction.objects.create(
            page=self.page, restriction_type="password", password="synthetic-password",
        )
        self.assertEqual(self.recent(), [])
        restriction.mark_as_passed(self.request)
        self.assertEqual(self.recent()[0]["id"], comment.pk)

    @override_settings(COMMENTAIL=CONFIG)
    def test_objects_recheck_access_site_registration_and_deleted_target(self):
        from django.contrib.contenttypes.models import ContentType

        product = Product.objects.create(site=self.site, title="Product")
        discussion = Discussion.objects.create(
            site=self.site, content_type=ContentType.objects.get_for_model(product),
            object_id=str(product.pk),
        )
        comment = self.comment(discussion)
        self.assertEqual(self.recent()[0]["target_title"], "Product")
        product.visible = False
        product.save()
        self.assertEqual(self.recent(), [])
        self.request.user = get_user_model().objects.create_user("staff", is_staff=True)
        self.assertEqual(self.recent()[0]["id"], comment.pk)
        with override_settings(COMMENTAIL={}):
            self.assertEqual(self.recent(), [])
        other = Site.objects.create(hostname="other.invalid", root_page=self.page)
        product.site = other
        product.save()
        self.assertEqual(self.recent(), [])
        product.delete()
        self.assertEqual(self.recent(), [])

    @override_settings(COMMENTAIL={"default": {"OBJECT_ADAPTERS": {
        "commentail_test_targets.Product": "tests.test_object_adapters.BrokenAdapter",
    }}})
    def test_broken_adapter_fails_closed(self):
        from django.contrib.contenttypes.models import ContentType

        product = Product.objects.create(site=self.site, title="Private")
        self.comment(Discussion.objects.create(
            site=self.site, content_type=ContentType.objects.get_for_model(product),
            object_id=str(product.pk),
        ))
        with self.assertLogs("commentail.objects", level="ERROR"):
            self.assertEqual(self.recent(), [])

    @override_settings(COMMENTAIL=CONFIG)
    def test_object_permalink_preserves_query_and_uses_existing_url_fallback(self):
        from django.contrib.contenttypes.models import ContentType
        from django.urls import reverse

        product = Product.objects.create(site=self.site, title="Product")
        discussion = Discussion.objects.create(
            site=self.site, content_type=ContentType.objects.get_for_model(product),
            object_id=str(product.pk),
        )
        comment = self.comment(discussion)
        def config(adapter):
            return {"default": {"OBJECT_ADAPTERS": {
                Product._meta.label: f"tests.test_object_adapters.{adapter}",
            }}}

        with override_settings(COMMENTAIL=config("QueryUrlAdapter")):
            self.assertEqual(
                self.recent()[0]["url"],
                f"/products/{product.pk}/?variant=blue&target={comment.pk}#commentail-{comment.pk}",
            )
        with override_settings(COMMENTAIL=config("BrokenUrlAdapter")):
            with self.assertLogs("commentail.objects", level="ERROR"):
                url = self.recent()[0]["url"]
            self.assertEqual(
                url, reverse("commentail:object_discussion", args=[discussion.pk])
                + f"?target={comment.pk}#commentail-{comment.pk}",
            )
        discussion.object_id = "999999999"
        discussion.save()
        self.assertEqual(self.recent(), [])

    def test_safe_fields_custom_markup_permalink_and_private_cache(self):
        from django.http import HttpResponse

        comment = self.comment(text='<script>alert("x")</script>', guest_name="<b>Guest</b>")
        rows = self.recent()
        self.assertEqual(set(rows[0]), {"id", "author_name", "text", "published_at", "target_title", "url"})
        self.assertIn(f"target={comment.pk}#commentail-{comment.pk}", rows[0]["url"])
        html = Template("{% for c in comments %}<p>{{ c.author_name }}: {{ c.text }}</p>{% endfor %}").render(Context({"comments": rows}))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;b&gt;Guest&lt;/b&gt;", html)
        response = CapabilityHeadersMiddleware(lambda request: HttpResponse(html))(self.request)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_name_hook_is_used(self):
        self.comment(user=get_user_model().objects.create_user("author"))
        with patch("commentail.avatars.author_name", return_value="Custom name"):
            self.assertEqual(self.recent()[0]["author_name"], "Custom name")

    def test_hook_html_is_still_plain_text(self):
        self.comment()
        with patch("commentail.avatars.author_name", return_value=mark_safe("<b>Name</b>")):
            rows = self.recent()
        self.assertIs(type(rows[0]["author_name"]), str)
        html = Template("{{ comments.0.author_name }}").render(Context({"comments": rows}))
        self.assertEqual(html, "&lt;b&gt;Name&lt;/b&gt;")

    def test_documented_markup_and_empty_state_render(self):
        from bs4 import BeautifulSoup

        template = Template(
            "{% load commentail_tags %}{% commentail_recent limit=1 as comments %}"
            '<ul>{% for c in comments %}<li><a href="{{ c.url }}">'
            '{{ c.author_name }}: {{ c.text|truncatechars:12 }}</a>'
            '<time datetime="{{ c.published_at|date:\'c\' }}">'
            '{{ c.published_at|date:"SHORT_DATETIME_FORMAT" }}</time></li>'
            "{% empty %}<li>No comments yet.</li>{% endfor %}</ul>"
        )
        context = Context({"request": self.request})
        self.assertIn("No comments yet.", template.render(context))
        comment = self.comment(text="Long published comment")
        document = BeautifulSoup(template.render(context), "html.parser")
        self.assertEqual(len(document.select("li")), 1)
        self.assertEqual(document.select_one("a").text, "Guest: Long publis…")
        self.assertIn(f"#commentail-{comment.pk}", document.select_one("a")["href"])
        self.assertTrue(document.select_one("time")["datetime"])

    def test_invalid_arguments_fail_explicitly(self):
        for arguments in ("limit=-1", "limit='5'", "limit=True", "limit=1.5", "include_replies='False'", "include_replies=0"):
            with self.subTest(arguments=arguments), self.assertRaises(TemplateSyntaxError):
                self.recent(arguments)
