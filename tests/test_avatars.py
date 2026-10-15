from dataclasses import FrozenInstanceError

from django.test import RequestFactory, TestCase, override_settings
from wagtail.models import Site

from commentail.models import Discussion
from commentail.services import submit


def custom_avatar(context, request):
    assert not hasattr(context, "email")
    assert not hasattr(context, "text")
    try:
        context.display_name = "Attack"
    except FrozenInstanceError:
        return "/static/account-avatar.png"
    raise AssertionError("Context is mutable")


def failing_avatar(context, request):
    raise ValueError("Synthetic failure")


class AvatarTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.comment = submit(
            self.discussion.pk,
            text="Guest",
            guest_name="Марина Анна Иванова",
            guest_email="private@example.invalid",
        )
        self.request = RequestFactory().get("/")

    def test_initials_use_first_and_last_word_and_two_characters_for_single_word(self):
        from commentail.avatars import default_avatar

        self.assertEqual(default_avatar("Марина Анна Иванова")[0], "МИ")
        self.assertEqual(default_avatar("Марина")[0], "МА")
        self.assertEqual(
            default_avatar("")[1],
            "linear-gradient(135deg, hsl(220 85% 56%), hsl(265 85% 60%))",
        )

    @override_settings(
        COMMENTAIL={"default": {"GET_AVATAR": "tests.test_avatars.custom_avatar"}}
    )
    def test_handler_gets_frozen_context_without_guest_email(self):
        from commentail.avatars import avatar_url

        self.assertEqual(
            avatar_url(self.comment, self.request, self.comment.display_name),
            "/static/account-avatar.png",
        )

    @override_settings(
        COMMENTAIL={"default": {"GET_AVATAR": "tests.test_avatars.failing_avatar"}}
    )
    def test_callback_failure_falls_back(self):
        from commentail.avatars import avatar_url

        with self.assertLogs("commentail", level="ERROR"):
            self.assertIsNone(
                avatar_url(self.comment, self.request, self.comment.display_name)
            )
