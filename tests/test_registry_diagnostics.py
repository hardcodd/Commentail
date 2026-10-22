"""Configuration failures identify the fix without exposing import payloads."""

from unittest.mock import patch

from django.db import models
from django.test import SimpleTestCase

from commentail.objects import registry_errors
from tests.targets.models import Product
from tests.test_object_adapters import ProductAdapter


class RegistryDiagnosticTests(SimpleTestCase):
    path = "tests.test_object_adapters.ProductAdapter"

    def error(self, registry):
        errors = registry_errors(registry)
        self.assertEqual(len(errors), 1)
        return errors[0]

    def test_model_label_must_be_a_string(self):
        self.assertIn("model label must be a string", self.error({1: self.path}))

    def test_adapter_path_must_be_a_string(self):
        self.assertIn(
            "adapter path must be a string", self.error({Product._meta.label: 1})
        )

    def test_malformed_model_label_is_distinct(self):
        self.assertIn(
            "expected app_label.ModelName", self.error({"invalid": self.path})
        )

    def test_missing_model_is_distinct(self):
        self.assertIn("model not found", self.error({"missing.Model": self.path}))

    def test_page_models_are_rejected(self):
        self.assertIn("Page models", self.error({"wagtailcore.Page": self.path}))

    def test_internal_models_are_rejected(self):
        self.assertIn("internal models", self.error({"commentail.Comment": self.path}))

    def test_abstract_and_proxy_models_are_distinct(self):
        for attribute in ("abstract", "proxy"):
            with (
                self.subTest(attribute=attribute),
                patch.object(Product._meta, attribute, True),
            ):
                self.assertIn(
                    attribute + " models", self.error({Product._meta.label: self.path})
                )

    def test_unsupported_primary_key_is_distinct(self):
        with patch.object(Product._meta, "pk", models.BinaryField()):
            self.assertIn(
                "unsupported primary key", self.error({Product._meta.label: self.path})
            )

    def test_case_alias_is_a_duplicate(self):
        error = self.error(
            {Product._meta.label: self.path, Product._meta.label_lower: self.path}
        )
        self.assertIn("duplicate model registration", error)

    def test_import_failure_does_not_echo_arbitrary_exception(self):
        with patch(
            "commentail.objects.import_string",
            side_effect=ImportError("PRIVATE CREDENTIAL"),
        ):
            error = self.error({Product._meta.label: self.path})
        self.assertIn("adapter import failed", error)
        self.assertNotIn("PRIVATE CREDENTIAL", error)

    def test_adapter_must_be_a_class(self):
        self.assertIn(
            "adapter must be a class", self.error({Product._meta.label: "builtins.len"})
        )

    def test_missing_methods_are_named(self):
        with patch.object(ProductAdapter, "can_view", None):
            error = self.error({Product._meta.label: self.path})
        self.assertIn("missing callable methods: can_view", error)
        self.assertNotIn("get_site", error)

    def test_valid_adapter_is_not_instantiated(self):
        with patch.object(
            ProductAdapter, "__init__", side_effect=AssertionError("must not run")
        ):
            self.assertEqual(registry_errors({Product._meta.label: self.path}), [])
