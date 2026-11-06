"""Server contracts for the deliberately small comment Markdown dialect."""

import json
from pathlib import Path

from django.test import SimpleTestCase

from commentail.markdown import MarkdownError, parse, render, render_plain


class MarkdownTests(SimpleTestCase):
    def test_browser_core_parity_corpus(self):
        corpus = json.loads(
            Path(__file__).with_name("markdown-corpus.json").read_text()
        )
        for case in corpus:
            with self.subTest(case=case["name"]):
                self.assertEqual(render(case["source"]), case["html"])
                self.assertEqual(render_plain(case["source"]), case["plain"])

    def test_inline_and_literal_code(self):
        self.assertEqual(
            render("***both*** ~~gone~~ `**literal**`"),
            "<p><em><strong>both</strong></em> <del>gone</del> <code>**literal**</code></p>",
        )

    def test_nested_numbering_structure(self):
        self.assertEqual(
            render("1. First\n   1. Nested\n   2. Next\n2. Second"),
            "<ol>\n<li>First\n<ol>\n<li>Nested</li>\n<li>Next</li>\n</ol></li>\n<li>Second</li>\n</ol>",
        )

    def test_untrusted_html_and_unsafe_links_stay_inert(self):
        value = render("<img src=x onerror=alert(1)> [x](javascript:alert(1))")
        self.assertNotIn("<img", value)
        self.assertNotIn("<a ", value)
        self.assertIn("&lt;img", value)

    def test_code_whitespace_is_preserved(self):
        self.assertEqual(
            render("```\n \tx  \n\n```"), "<pre><code> \tx  \n\n</code></pre>"
        )

    def test_plain_presentation(self):
        self.assertEqual(
            render_plain("**hello** [site](https://example.com)"), "hello site"
        )

    def test_limits_fail_without_partial_output(self):
        for text in ("x" * 100001, "> " * 40 + "x", "*" * 80 + "x" + "*" * 80):
            with self.subTest(text=text[:50]), self.assertRaises(MarkdownError):
                parse(text)
