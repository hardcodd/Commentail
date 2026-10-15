from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Site

from commentail.models import Discussion, MailJob, SiteGroupPermission
from commentail.services import moderate, submit
from tests.targets.models import Product, StringTarget, UUIDTarget


class ProductAdapter:
    def get_site(self, obj, request):
        return obj.site

    def can_view(self, obj, request):
        return obj.visible or request.user.is_staff

    def get_url(self, obj, site):
        return f"/products/{obj.pk}/"


class BrokenAdapter(ProductAdapter):
    def can_view(self, obj, request):
        raise RuntimeError("PRIVATE FAILURE")


class QueryUrlAdapter(ProductAdapter):
    def get_url(self, obj, site):
        return f"/products/{obj.pk}/?variant=blue&target=old#details"


class BrokenUrlAdapter(ProductAdapter):
    def get_url(self, obj, site):
        raise RuntimeError("PRIVATE URL FAILURE")


REGISTRY = {
    model._meta.label: "tests.test_object_adapters.ProductAdapter"
    for model in (Product, StringTarget, UUIDTarget)
}
CONFIG = {"default": {"OBJECT_ADAPTERS": REGISTRY}}


@override_settings(COMMENTAIL=CONFIG)
class ObjectAdapterTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.product = Product.objects.create(site=self.site, title="Synthetic product")
        self.user = get_user_model().objects.create_user(
            "object-author", email="author@example.invalid"
        )
        self.client.force_login(self.user)
        self.request = RequestFactory().get("/")
        self.request.user = self.user
        from django.contrib.sessions.middleware import SessionMiddleware

        SessionMiddleware(lambda request: None).process_request(self.request)
        self.request.session.save()

    def discussion(self, obj=None, request=None):
        from commentail.objects import get_object_discussion

        return get_object_discussion(request or self.request, obj or self.product)

    def test_tag_and_key_types_have_isolated_stable_discussions(self):
        objects = [
            self.product,
            StringTarget.objects.create(
                site=self.site, title="String", key="a/b привет"
            ),
            UUIDTarget.objects.create(site=self.site, title="UUID"),
        ]
        discussions = [self.discussion(obj) for obj in objects]
        self.assertEqual(len({d.pk for d in discussions}), 3)
        for obj, discussion in zip(objects, discussions):
            self.assertEqual(self.discussion(obj).pk, discussion.pk)
            html = Template("{% load commentail_tags %}{% commentail obj %}").render(
                Context({"obj": obj, "request": self.request})
            )
            self.assertIn(f'data-discussion="{discussion.pk}"', html)
            self.assertIsNone(discussion.page_id)

    def test_direct_requests_recheck_access_and_form_replay(self):
        discussion = self.discussion()
        url = reverse("commentail:object_discussion", args=[discussion.pk])
        submit_url = reverse("commentail:object_submit", args=[discussion.pk])
        response = self.client.get(url)
        key = response.context["form_key"]
        payload = {"key": key, "text": "Object comment"}
        self.assertEqual(self.client.post(submit_url, payload).status_code, 302)
        self.assertEqual(discussion.comments.count(), 1)
        self.product.visible = False
        self.product.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(submit_url, payload).status_code, 404)
        self.assertEqual(discussion.comments.count(), 1)

    def test_host_navigation_preserves_adapter_query_and_survives_url_failure(self):
        discussion = self.discussion()
        url = reverse("commentail:object_discussion", args=[discussion.pk])
        submit_url = reverse("commentail:object_submit", args=[discussion.pk])
        for adapter in ("QueryUrlAdapter", "BrokenUrlAdapter"):
            config = {"default": {"OBJECT_ADAPTERS": {
                Product._meta.label: f"tests.test_object_adapters.{adapter}"
            }}}
            with self.subTest(adapter=adapter), override_settings(COMMENTAIL=config):
                self.client.force_login(get_user_model().objects.create_user(adapter))
                response = self.client.get(url)
                self.assertTemplateUsed(response, "commentail/block.html")
                self.assertNotContains(response, "<!doctype")
                document = self.client.get(url, HTTP_ACCEPT="text/html")
                self.assertEqual(document.status_code, 302 if adapter == "QueryUrlAdapter" else 404)
                response = self.client.post(submit_url, {
                    "key": response.context["form_key"], "text": adapter
                })
                comment = discussion.comments.get(text=adapter)
                expected = (
                    f"/products/{self.product.pk}/?variant=blue&target={comment.pk}#commentail-{comment.pk}"
                    if adapter == "QueryUrlAdapter"
                    else f"{url}?target={comment.pk}#commentail-{comment.pk}"
                )
                self.assertEqual(response["Location"], expected)
                self.assertNotContains(self.client.get(url), "PRIVATE URL FAILURE")
    def test_unregistered_and_adapter_failure_never_disclose_content(self):
        discussion = self.discussion()
        submit(discussion.pk, text="PRIVATE CONTENT", user=self.user)
        url = reverse("commentail:object_discussion", args=[discussion.pk])
        for config in (
            {},
            {
                "default": {
                    "OBJECT_ADAPTERS": {
                        Product._meta.label: "tests.test_object_adapters.BrokenAdapter"
                    }
                }
            },
        ):
            with override_settings(COMMENTAIL=config):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, "PRIVATE CONTENT", status_code=404)
        self.assertTrue(Discussion.objects.filter(pk=discussion.pk).exists())

    def test_site_resolution_cannot_cross_site_boundary(self):
        other = Site.objects.create(
            hostname="foreign.invalid", root_page=self.site.root_page
        )
        self.product.site = other
        self.product.save()
        from commentail.objects import ObjectAccessError

        with self.assertRaises(ObjectAccessError):
            self.discussion()

    def test_bulk_deletion_cleans_data_but_preserves_other_targets(self):
        discussion = self.discussion()
        comment = submit(discussion.pk, text="Synthetic", user=self.user)
        MailJob.objects.create(
            event_key="object-mail",
            comment=comment,
            recipient=comment,
            kind="published",
            expires_at=timezone.now() + timedelta(days=1),
        )
        unrelated = self.discussion(
            Product.objects.create(site=self.site, title="Keep")
        )
        Product.objects.filter(pk=self.product.pk).delete()
        self.assertFalse(Discussion.objects.filter(pk=discussion.pk).exists())
        self.assertFalse(MailJob.objects.filter(event_key="object-mail").exists())
        self.assertTrue(Discussion.objects.filter(pk=unrelated.pk).exists())

    def test_settings_card_requires_site_settings_permission(self):
        discussion = self.discussion()
        url = reverse("commentail_admin:object_settings", args=[discussion.pk])
        self.user.is_staff = True
        self.user.save()
        group = Group.objects.create(name="Object editors")
        group.permissions.add(Permission.objects.get(codename="access_admin"))
        self.user.groups.add(group)
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403, getattr(response, "url", ""))
        SiteGroupPermission.objects.create(group=group, site=self.site, settings=True)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Synthetic product")
        data = {
            "mode": "read_only",
            "moderation": "",
            "access": "",
            "max_length": "",
            "clickable_links": "unknown",
            "notify_publication": "unknown",
            "notify_rejection": "unknown",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        discussion.refresh_from_db()
        self.assertEqual(discussion.mode, "read_only")

    def test_account_edit_and_mail_use_the_object_target(self):
        from django.core import mail

        from commentail.outbox import _can_receive, deliver

        discussion = self.discussion()
        self.user.is_superuser = True
        self.user.save()
        comment = submit(discussion.pk, text="Original", user=self.user)
        moderate(comment.pk, "approve", actor=self.user)
        response = self.client.post(
            reverse("commentail:edit", args=[comment.pk]), {"text": "Changed"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            f"/products/{self.product.pk}/?target={comment.pk}#commentail-{comment.pk}",
            response.url,
        )
        self.assertTrue(_can_receive(comment))
        job = MailJob.objects.create(
            event_key="object-published",
            comment=comment,
            recipient=comment,
            kind="published",
            expires_at=timezone.now() + timedelta(days=1),
        )
        deliver(job)
        self.assertIn("/products/", mail.outbox[-1].body)
        self.product.visible = False
        self.product.save()
        self.user.is_superuser = False
        self.user.save()
        self.assertFalse(_can_receive(comment))

    def test_model_site_uniqueness_and_database_target_invariants(self):
        from django.contrib.contenttypes.models import ContentType
        from django.db import IntegrityError, transaction

        discussion = self.discussion()
        other = Site.objects.create(
            hostname="second.invalid", root_page=self.site.root_page
        )
        second = Discussion.objects.create(
            site=other,
            content_type=discussion.content_type,
            object_id=discussion.object_id,
        )
        self.assertNotEqual(second.pk, discussion.pk)
        uuid_target = UUIDTarget.objects.create(
            site=self.site,
            title="Same numeric string",
            pk="00000000-0000-0000-0000-000000000001",
        )
        self.assertNotEqual(self.discussion(uuid_target).pk, discussion.pk)
        for fields in (
            {
                "content_type": discussion.content_type,
                "object_id": discussion.object_id,
            },
            {},
            {
                "page": self.site.root_page,
                "content_type": ContentType.objects.get_for_model(Product),
                "object_id": "1",
            },
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Discussion.objects.create(site=self.site, **fields)

    def test_invalid_registry_and_key_limit_are_explicit(self):
        from commentail.config import configuration_errors
        from commentail.objects import ObjectAccessError

        for registry in (
            [],
            {"missing.Model": "bad.path"},
            {"wagtailcore.Page": "tests.test_object_adapters.ProductAdapter"},
            {"commentail.Comment": "tests.test_object_adapters.ProductAdapter"},
            {Product._meta.label: "builtins.str"},
        ):
            with override_settings(
                COMMENTAIL={"default": {"OBJECT_ADAPTERS": registry}}
            ):
                self.assertTrue(configuration_errors())
        with override_settings(
            COMMENTAIL={"example.invalid": {"OBJECT_ADAPTERS": REGISTRY}}
        ):
            self.assertTrue(configuration_errors())
        from unittest.mock import patch

        with (
            patch.object(
                ProductAdapter, "get_site", return_value=Site(pk=self.site.pk)
            ),
            self.assertRaises(ObjectAccessError),
        ):
            self.discussion()
        with self.assertRaises(ObjectAccessError):
            self.discussion(Product(site=self.site, title="Unsaved"))
        obj = StringTarget(site=self.site, title="Oversized", key="x" * 256)
        obj._state.adding = False
        with self.assertRaises(ObjectAccessError):
            self.discussion(obj)

    def test_cleanup_removes_all_related_records_across_sites(self):
        from commentail.admission import issue_form
        from commentail.models import (
            CommentRevision,
            FormTicket,
            ModerationEvent,
            ReplySubscription,
        )
        from commentail.security import issue_token

        discussion = self.discussion()
        other = Site.objects.create(
            hostname="cleanup.invalid", root_page=self.site.root_page
        )
        second = Discussion.objects.create(
            site=other,
            content_type=discussion.content_type,
            object_id=discussion.object_id,
        )
        self.user.is_superuser = True
        self.user.save()
        for item in (discussion, second):
            comment = submit(item.pk, text="Purge", user=self.user)
            CommentRevision.objects.create(comment=comment, text="Revision")
            ReplySubscription.objects.create(comment=comment)
            ModerationEvent.objects.create(
                comment=comment, actor=self.user, action="approve"
            )
            issue_token(comment, "view", timezone.now() + timedelta(hours=1))
        issue_form(self.request, discussion)
        with override_settings(COMMENTAIL={}):
            self.product.delete()
        for model in (CommentRevision, ReplySubscription, ModerationEvent, FormTicket):
            self.assertFalse(model.objects.exists())
        self.assertFalse(
            Discussion.objects.filter(pk__in=[discussion.pk, second.pk]).exists()
        )

    def test_guest_mail_requires_explicit_offline_access_callback(self):
        from commentail.outbox import _can_receive

        discussion = self.discussion()
        comment = submit(
            discussion.pk,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        self.assertFalse(_can_receive(comment))
        with override_settings(
            COMMENTAIL={
                "default": {
                    "OBJECT_ADAPTERS": REGISTRY,
                    "CAN_SEND_GUEST_EMAIL": "tests.test_object_adapters.allow_guest_mail",
                }
            }
        ):
            self.assertTrue(_can_receive(comment))
            self.product.site = Site.objects.create(
                hostname="moved.invalid", root_page=self.site.root_page
            )
            self.product.save()
            self.assertFalse(_can_receive(comment))

    def test_avatar_callback_gets_registered_object_without_guest_email(self):
        from commentail.avatars import avatar_url

        comment = submit(self.discussion().pk, text="Avatar", user=self.user)
        with override_settings(
            COMMENTAIL={
                "default": {
                    "OBJECT_ADAPTERS": REGISTRY,
                    "GET_AVATAR": "tests.test_object_adapters.object_avatar",
                }
            }
        ):
            self.assertEqual(
                avatar_url(comment, self.request, "Name"), "/synthetic-avatar.png"
            )


def allow_guest_mail(recipient, target, site):
    return (
        isinstance(target, Product)
        and target.site_id == site.pk
        and recipient.email == "guest@example.invalid"
    )


def object_avatar(context, request):
    assert isinstance(context.target, Product)
    assert not hasattr(context, "email")
    return "/synthetic-avatar.png"
