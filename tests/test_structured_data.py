"""Public metadata follows visible content, access and script safety contracts."""

import json
from datetime import timedelta

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import PageViewRestriction, Site

from commentail.config import configuration_errors
from commentail.models import Comment, Discussion, SiteCommentSettings


class StructuredDataTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.user = get_user_model().objects.create_user(
            "writer", first_name="Current name"
        )
        self.url = reverse("commentail:discussion", args=[self.site.root_page.pk])

    def comment(self, text="Published text", **values):
        return Comment.objects.create(
            discussion=self.discussion,
            guest_name="Guest",
            text=text,
            published_at=timezone.now() - timedelta(minutes=1),
            **{"status": "published", **values},
        )

    def read(self, **query):
        response = self.client.get(self.url, query)
        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.content, "html.parser")
        scripts = soup.select('script[type="application/ld+json"]')
        self.assertLessEqual(len(scripts), 1)
        graph = json.loads(scripts[0].string)["@graph"] if scripts else []
        return soup, graph

    def test_default_formats_describe_same_published_content(self):
        row = self.comment(user=self.user, edited_at=timezone.now())
        soup, graph = self.read()
        self.assertEqual(len(graph), 1)
        entity = graph[0]
        article = soup.select_one(f"#commentail-{row.pk}")
        self.assertEqual(entity["@type"], "Comment")
        self.assertEqual(article["itemid"], entity["@id"])
        self.assertTrue(entity["@id"].endswith(f"/#commentail-{row.pk}"))
        self.assertNotIn("/commentail/", entity["@id"])
        self.assertEqual(entity["text"], row.text)
        self.assertEqual(
            entity["author"]["name"], article.select_one('[itemprop="name"]').text
        )
        self.assertEqual(entity["datePublished"], row.published_at.isoformat())
        self.assertEqual(entity["dateModified"], row.edited_at.isoformat())
        self.assertEqual(article.select_one('[itemprop="text"]').text, row.text)
        self.assertEqual(
            article.select_one('[itemprop="datePublished"]')["datetime"],
            entity["datePublished"],
        )
        self.assertEqual(entity["about"]["@id"], "http://testserver/")
        self.user.first_name = "Updated name"
        self.user.save()
        _, updated = self.read()
        self.assertEqual(updated[0]["author"]["name"], "Updated name")

    def test_only_rendered_replies_and_direct_parent_are_described(self):
        root = self.comment("Root")
        reply = self.comment("Reply", root=root, reply_to=root)
        nested = self.comment("Direct reply", root=root, reply_to=reply)
        _, graph = self.read()
        self.assertEqual([item["text"] for item in graph], ["Root"])
        soup, graph = self.read(thread=root.pk)
        entities = {item["text"]: item for item in graph}
        self.assertEqual(len(entities), 3)
        self.assertEqual(
            entities["Direct reply"]["parentItem"]["@id"], entities["Reply"]["@id"]
        )
        self.assertEqual(
            soup.select_one(f'#commentail-{nested.pk} [itemprop="parentItem"]')[
                "itemid"
            ],
            entities["Reply"]["@id"],
        )

    def test_metadata_excludes_private_and_removed_content(self):
        self.client.force_login(self.user)
        published = self.comment(
            "Old approved body", user=self.user, email="secret@example.invalid"
        )
        published.revisions.create(text="PRIVATE REVISION", status="pending")
        for status in ("pending", "awaiting_email", "rejected", "hidden", "deleted"):
            self.comment(f"PRIVATE {status}", status=status, user=self.user)
        hidden = self.comment("HIDDEN ROOT TEXT", status="hidden")
        self.comment("Visible child", root=hidden, reply_to=hidden)
        soup, graph = self.read(thread=hidden.pk)
        payload = json.dumps(graph)
        self.assertEqual(
            {item["text"] for item in graph}, {"Old approved body", "Visible child"}
        )
        self.assertNotIn("PRIVATE", payload)
        self.assertNotIn("secret@", payload)
        self.assertNotIn("HIDDEN ROOT", payload)
        self.assertFalse(
            soup.select_one(f"#commentail-{hidden.pk}").has_attr("itemscope")
        )
        self.assertFalse(soup.select(".commentail-pending [itemprop]"))

    def test_script_and_attribute_injection_are_inert(self):
        text = '</script><script>alert("x")</script> & <b>plain</b>'
        name = '"><img src=x onerror=alert(1)>'
        row = self.comment(text)
        row.guest_name = name
        row.save()
        soup, graph = self.read()
        self.assertEqual(graph[0]["text"], text)
        self.assertEqual(graph[0]["author"]["name"], name)
        self.assertEqual(len(soup.select("script")), 1)
        self.assertFalse(soup.select("script[src], img[onerror]"))
        raw = str(soup.select_one('script[type="application/ld+json"]'))
        self.assertIn("\\u003C/script\\u003E", raw)

    def test_modes_and_hostname_inheritance(self):
        self.comment()
        for mode, scripts, microdata in (
            ("both", True, True),
            ("json_ld", True, False),
            ("microdata", False, True),
            ("off", False, False),
        ):
            with (
                self.subTest(mode=mode),
                override_settings(COMMENTAIL={"default": {"STRUCTURED_DATA": mode}}),
            ):
                soup, graph = self.read()
                self.assertEqual(bool(graph), scripts)
                self.assertEqual(
                    bool(soup.select('[itemtype="https://schema.org/Comment"]')),
                    microdata,
                )
        with override_settings(
            COMMENTAIL={
                "default": {"STRUCTURED_DATA": "off"},
                self.site.hostname: {"STRUCTURED_DATA": "both"},
            }
        ):
            self.assertTrue(self.read()[1])

    def test_invalid_modes_fail_configuration_checks(self):
        for mode in (True, None, [], {}, "invalid"):
            with (
                self.subTest(mode=mode),
                override_settings(COMMENTAIL={"default": {"STRUCTURED_DATA": mode}}),
            ):
                self.assertTrue(
                    any("STRUCTURED_DATA" in error for error in configuration_errors())
                )
        with override_settings(COMMENTAIL={"default": {"STRUCTURED_DATA": "both"}}):
            self.assertEqual(configuration_errors(), [])

    def test_empty_hidden_and_restricted_discussions_emit_nothing(self):
        self.assertEqual(self.read()[1], [])
        self.comment()
        settings = SiteCommentSettings.for_site(self.site)
        settings.mode = "hidden"
        settings.save()
        self.assertEqual(self.read()[1], [])
        settings.mode = "open"
        settings.save()
        PageViewRestriction.objects.create(
            page=self.site.root_page, restriction_type="login"
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"application/ld+json", response.content)

    def test_pagination_metadata_matches_rendered_rows(self):
        for index in range(23):
            self.comment(f"Row {index}")
        soup, graph = self.read()
        self.assertEqual(len(graph), 20)
        self.assertEqual(
            {item["@id"] for item in graph},
            {row["itemid"] for row in soup.select(".commentail-comment[itemscope]")},
        )
        target = self.discussion.comments.order_by("pk").first()
        _, graph = self.read(target=target.pk)
        self.assertIn(target.text, {item["text"] for item in graph})

    def test_native_document_and_fragment_share_metadata(self):
        row = self.comment()
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.template import Context, Template
        from django.test import RequestFactory

        request = RequestFactory().get("/?thread=1&edit_token=PRIVATE_TOKEN")
        request.user = AnonymousUser()
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        rendered = Template("{% load commentail_tags %}{% commentail page %}").render(
            Context({"request": request, "page": self.site.root_page})
        )
        soup = BeautifulSoup(rendered, "html.parser")
        script = soup.select_one('script[type="application/ld+json"]')
        entity = json.loads(script.string)["@graph"][0]
        self.assertEqual(entity, self.read()[1][0])
        self.assertNotIn("PRIVATE_TOKEN", script.string)
        self.assertTrue(entity["@id"].endswith(f"#commentail-{row.pk}"))

    def test_object_adapter_urls_and_failure_are_safe(self):
        from django.contrib.contenttypes.models import ContentType

        from tests.targets.models import Product

        product = Product.objects.create(site=self.site, title="Synthetic")
        discussion = Discussion.objects.create(
            site=self.site,
            content_type=ContentType.objects.get_for_model(product),
            object_id=str(product.pk),
        )
        Comment.objects.create(
            discussion=discussion,
            guest_name="Guest",
            text="Object body",
            status="published",
            published_at=timezone.now(),
        )
        url = reverse("commentail:object_discussion", args=[discussion.pk])
        for adapter in ("QueryUrlAdapter", "BrokenUrlAdapter"):
            config = {
                "default": {
                    "OBJECT_ADAPTERS": {
                        Product._meta.label: f"tests.test_object_adapters.{adapter}"
                    }
                }
            }
            with self.subTest(adapter=adapter), override_settings(COMMENTAIL=config):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                soup = BeautifulSoup(response.content, "html.parser")
                script = soup.select_one('script[type="application/ld+json"]')
                if adapter == "QueryUrlAdapter":
                    entity = json.loads(script.string)["@graph"][0]
                    self.assertEqual(
                        entity["about"]["@id"],
                        f"http://testserver/products/{product.pk}/?variant=blue&target=old",
                    )
                    self.assertTrue(entity["@id"].startswith(entity["about"]["@id"]))
                else:
                    self.assertIsNone(script)
                    self.assertFalse(soup.select("[itemprop]"))
        product.visible = False
        product.save()
        with override_settings(
            COMMENTAIL={
                "default": {
                    "OBJECT_ADAPTERS": {
                        Product._meta.label: "tests.test_object_adapters.ProductAdapter"
                    }
                }
            }
        ):
            self.assertEqual(self.client.get(url).status_code, 404)
