from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from wagtail.models import Site

from commentail.detection import DetectionError, has_comments


def dynamic_templates(page, request):
    return ["dynamic.html", "included.html"]


def broken_templates(page, request):
    raise RuntimeError("Synthetic resolver failure")


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "OPTIONS": {
            "loaders": [
                (
                    "django.template.loaders.locmem.Loader",
                    {
                        "direct.html": "{% load commentail_tags %}{% commentail page %}",
                        "included.html": "{% include 'direct.html' %}",
                        "inherited.html": "{% extends 'included.html' %}",
                        "conditional.html": "{% load commentail_tags %}{% if False %}{% commentail page %}{% endif %}",
                        "resources.html": "{% load commentail_tags %}{% commentail_css %}{% commentail_js %}",
                        "dynamic.html": "{% include selected_template %}",
                        "cycle.html": "{% include 'cycle.html' %}{% load commentail_tags %}{% commentail page %}",
                    },
                )
            ]
        },
    }
]


@override_settings(TEMPLATES=TEMPLATES)
class DetectionTests(TestCase):
    def setUp(self):
        self.page = Site.objects.get(is_default_site=True).root_page
        self.request = RequestFactory().get("/")

    def test_compiled_chains_conditions_and_cycles(self):
        for name in ("direct", "included", "inherited", "conditional", "cycle"):
            with (
                self.subTest(name=name),
                patch.object(self.page, "get_template", return_value=name + ".html"),
            ):
                self.assertTrue(has_comments(self.page, self.request))

    def test_resources_do_not_enable_discussion(self):
        with patch.object(self.page, "get_template", return_value="resources.html"):
            self.assertFalse(has_comments(self.page, self.request))

    def test_dynamic_requires_explicit_handler(self):
        with (
            patch.object(self.page, "get_template", return_value="dynamic.html"),
            self.assertRaises(DetectionError),
        ):
            has_comments(self.page, self.request)

    @override_settings(
        COMMENTAIL={
            "default": {
                "GET_COMMENT_TEMPLATES": "tests.test_detection.dynamic_templates"
            }
        }
    )
    def test_dynamic_handler_enumerates_dependencies(self):
        self.assertTrue(has_comments(self.page, self.request))

    @override_settings(
        COMMENTAIL={
            "default": {
                "GET_COMMENT_TEMPLATES": "tests.test_detection.broken_templates"
            }
        }
    )
    def test_handler_failure_is_a_diagnostic_not_a_page_editor_crash(self):
        with self.assertRaises(DetectionError):
            has_comments(self.page, self.request)
