"""Default emails explain actions without exposing private comment content."""

from datetime import UTC, datetime
from html.parser import HTMLParser

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils.translation import override


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.urls.extend(value for key, value in attrs if key == "href" and value)


class EmailPresentationTests(SimpleTestCase):
    def test_action_labels_and_copy_describe_available_actions(self) -> None:
        context = {
            "site_name": "Example", "site_url": "https://example.invalid",
            "target_url": "https://example.invalid/discussion/",
            "action_url": "https://example.invalid/action/", "is_revision": False,
            "author_name": "Мария",
        }
        with override("ru"):
            for suffix in (".html", ".txt"):
                edit = render_to_string("commentail/emails/edit" + suffix, context)
                self.assertIn(">Редактировать комментарий</a>" if suffix == ".html"
                              else "\nРедактировать комментарий:\n", edit)
                self.assertIn("даже если он ещё ожидает модерации", edit)
            reply = render_to_string("commentail/emails/reply.html", context)
            self.assertIn(">Отписаться</a>", reply)
            self.assertNotIn("продолжить обсуждение", reply)
        with override("en"):
            for suffix in (".html", ".txt"):
                reply = render_to_string("commentail/emails/reply" + suffix, context)
                self.assertNotIn("continue the conversation", reply)
                edit = render_to_string("commentail/emails/edit" + suffix, context)
                self.assertIn("even if that reply is awaiting moderation", edit)

    def test_french_labels_and_author_names(self) -> None:
        context = {
            "site_name": "Example", "site_url": "https://example.invalid",
            "target_url": "https://example.invalid/discussion/",
            "action_url": "https://example.invalid/action/",
            "view_url": "https://example.invalid/status/", "author_name": "Alex",
        }
        with override("fr"):
            for kind in ("confirm", "edit", "published", "rejected"):
                text = render_to_string(f"commentail/emails/{kind}.txt", context)
                label = "Voir le commentaire" if kind == "published" else "Ouvrir la discussion"
                self.assertIn(label + " :\n", text)
            for suffix in (".html", ".txt"):
                reply = render_to_string("commentail/emails/reply" + suffix, context)
                self.assertIn("Auteur de la réponse : Alex", reply)

    def test_all_languages_actions_and_safe_metadata(self) -> None:
        context = {
            "author_name": '<script>alert("author")</script>',
            "site_name": '<img src=x onerror="site">',
            "site_url": "https://example.invalid",
            "target_url": "https://example.invalid/article/?target=1#commentail-1",
            "action_url": "https://example.invalid/comments/action/?token=synthetic&x=1",
            "view_url": "https://example.invalid/comments/view/?token=synthetic",
            "reason": '<script>alert("reason")</script>\nSecond line',
            "expires_at": datetime(2026, 10, 19, 12, tzinfo=UTC),
        }
        for language in ("en", "ru", "de", "fr", "es", "pt-br"):
            for kind in ("confirm", "edit", "published", "rejected", "reply"):
                for revision in (False, True) if kind in {"published", "rejected"} else (False,):
                    with self.subTest(language=language, kind=kind, revision=revision), override(language):
                        values = {**context, "kind": kind, "is_revision": revision}
                        prefix = f"commentail/emails/{kind}"
                        html = render_to_string(prefix + ".html", values)
                        text = render_to_string(prefix + ".txt", values)
                        parser = LinkParser()
                        parser.feed(html)
                        self.assertIn(context["target_url"], parser.urls)
                        self.assertIn(context["target_url"], text)
                        for field in ("action_url", "view_url") if kind == "confirm" else ("action_url",) if kind in {"edit", "reply"} else ():
                            self.assertIn(context[field], parser.urls)
                            self.assertIn(context[field], text)
                        self.assertIn("&lt;img", html)
                        self.assertNotIn("<script>", html)
                        self.assertNotIn("<img", html)
                        self.assertNotIn("<script src", html)
                        self.assertNotIn("url(", html)
                        self.assertIn(f'lang="{language}"', html)
                        self.assertNotIn("hardcodd", html + text)
                        if language != "en":
                            self.assertNotIn("Open discussion", html + text)
                            self.assertNotIn("This is an automatic", html + text)
                        if language == "ru" and kind == "reply":
                            self.assertIn("Автор ответа:", html + text)
                        if kind == "rejected":
                            self.assertIn("&lt;script&gt;", html)
                            self.assertIn(context["reason"], text)

    def test_revision_copy_differs_and_optional_links_are_omitted(self) -> None:
        context = {
            "site_name": "Example", "site_url": "https://example.invalid",
            "target_url": "https://example.invalid/article/", "action_url": "",
            "view_url": "", "reason": "", "is_revision": False,
        }
        with override("en"):
            for kind in ("published", "rejected"):
                for suffix in (".html", ".txt", "_subject.txt"):
                    path = f"commentail/emails/{kind}{suffix}"
                    original = render_to_string(path, context)
                    revision = render_to_string(path, {**context, "is_revision": True})
                    self.assertNotEqual(original, revision)
                    self.assertIn("changes", revision.lower())
            for kind in ("confirm", "edit"):
                html = render_to_string(f"commentail/emails/{kind}.html", context)
                self.assertNotIn('href=""', html)
