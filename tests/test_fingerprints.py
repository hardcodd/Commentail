"""Private fingerprints preserve quotas/replays across key rotation and upgrade."""

import importlib
import json
from datetime import timedelta
from types import SimpleNamespace

from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase, override_settings
from django.utils import timezone
from wagtail.models import Site

from commentail.fingerprints import fingerprint, fingerprint_candidates
from commentail.limits import consume
from commentail.models import Comment, Discussion, RateEvent, SubmissionRecord
from commentail.security import (
    digest,
    issue_token,
    remember_guest,
    remembered_guest,
    verify_token,
)
from commentail.services import DomainError, submit, submit_once


class FingerprintTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )

    def test_fingerprints_require_key_and_purpose(self):
        value = "guest:guest@example.invalid"
        hashed = fingerprint(value, "actor")
        self.assertNotEqual(hashed, digest(value))
        self.assertNotEqual(hashed, fingerprint(value, "address"))
        with override_settings(SECRET_KEY="synthetic-other-key"):
            self.assertNotEqual(hashed, fingerprint(value, "actor"))

    def test_new_rate_records_are_keyed_and_site_scoped(self):
        consume(self.site, "comment", "guest:guest@example.invalid", "192.0.2.1")
        event = RateEvent.objects.get(kind="comment_author")
        self.assertEqual(
            event.subject_digest,
            fingerprint(
                "guest:guest@example.invalid", f"rate.{self.site.pk}.comment_author"
            ),
        )
        self.assertNotEqual(event.subject_digest, digest("guest:guest@example.invalid"))
        other = Site.objects.create(
            hostname="fingerprint.invalid", root_page=self.site.root_page
        )
        consume(other, "comment", "guest:guest@example.invalid", "192.0.2.1")
        self.assertNotEqual(
            event.subject_digest,
            RateEvent.objects.get(site=other, kind="comment_author").subject_digest,
        )

    def test_rotation_preserves_quota_without_writing_legacy_hashes(self):
        with override_settings(SECRET_KEY="synthetic-old-key"):
            consume(self.site, "comment", "guest:guest@example.invalid", "192.0.2.1")
        with override_settings(
            SECRET_KEY="synthetic-new-key", SECRET_KEY_FALLBACKS=["synthetic-old-key"]
        ):
            with self.assertRaises(DomainError):
                consume(
                    self.site, "comment", "guest:guest@example.invalid", "192.0.2.2"
                )
            self.assertEqual(
                len(fingerprint_candidates("guest:guest@example.invalid", "actor")), 2
            )

    def test_rotation_preserves_replay_and_changed_payload_rejection(self):
        kwargs = {
            "text": "Message",
            "guest_name": "Guest",
            "guest_email": "guest@example.invalid",
        }
        with override_settings(SECRET_KEY="synthetic-old-key"):
            first = submit_once(self.discussion.pk, "synthetic-form-key", **kwargs)
        with override_settings(
            SECRET_KEY="synthetic-new-key", SECRET_KEY_FALLBACKS=["synthetic-old-key"]
        ):
            self.assertEqual(
                submit_once(self.discussion.pk, "synthetic-form-key", **kwargs).pk,
                first.pk,
            )
            with self.assertRaisesMessage(DomainError, "different content"):
                submit_once(
                    self.discussion.pk,
                    "synthetic-form-key",
                    **{**kwargs, "text": "Changed"},
                )
        self.assertEqual(SubmissionRecord.objects.count(), 1)

    def test_upgrade_protects_legacy_rows_without_resetting_replays_or_quotas(self):
        actor = "guest:guest@example.invalid"
        key = "synthetic-legacy-form-key"
        kwargs = {
            "text": "Legacy message",
            "guest_name": "Guest",
            "guest_email": "guest@example.invalid",
        }
        comment = submit(self.discussion.pk, **kwargs)
        record = SubmissionRecord.objects.create(
            discussion=self.discussion,
            comment=comment,
            actor_digest=digest(actor),
            key_digest=digest(key),
            payload_digest=digest(
                json.dumps(
                    [
                        kwargs["text"],
                        kwargs["guest_name"],
                        kwargs["guest_email"],
                        None,
                        "en",
                        False,
                    ],
                    ensure_ascii=False,
                )
            ),
        )
        rate = RateEvent.objects.create(
            site=self.site, kind="comment_author", subject_digest=digest(actor)
        )
        content = RateEvent.objects.create(
            site=self.site, kind="content", subject_digest="a" * 64
        )
        secret = issue_token(comment, "view", timezone.now() + timedelta(hours=1))
        grant = remember_guest(self.site, kwargs["guest_email"])
        migration = importlib.import_module(
            "commentail.migrations.0018_private_fingerprints"
        )
        historical = (
            MigrationLoader(connection)
            .project_state([("commentail", "0017_revision_spam_signals")])
            .apps
        )
        migration.protect_fingerprints(
            historical, SimpleNamespace(connection=connection)
        )
        record.refresh_from_db()
        rate.refresh_from_db()
        content.refresh_from_db()
        self.assertNotEqual(record.actor_digest, digest(actor))
        self.assertNotEqual(rate.subject_digest, digest(actor))
        self.assertEqual(content.subject_digest, "a" * 64)
        self.assertEqual(submit_once(self.discussion.pk, key, **kwargs).pk, comment.pk)
        with self.assertRaises(DomainError):
            consume(self.site, "comment", actor, "192.0.2.1")
        self.assertEqual(verify_token(secret, "view", self.site).comment_id, comment.pk)
        self.assertEqual(
            remembered_guest(grant, self.site).email, kwargs["guest_email"]
        )

    def test_attempt_budget_uses_keyed_ip_and_survives_rotation(self):
        from django.contrib.sessions.backends.db import SessionStore
        from django.test import RequestFactory

        from commentail.antispam import consume_attempt

        request = RequestFactory().post("/")
        request.session = SessionStore()
        request.session.create()
        with override_settings(SECRET_KEY="synthetic-old-key"):
            consume_attempt(request, self.site, "192.0.2.1")

            event = RateEvent.objects.get(kind="attempt_ip")
            self.assertNotEqual(event.subject_digest, digest("192.0.2.1"))
        with (
            override_settings(
                SECRET_KEY="synthetic-new-key",
                SECRET_KEY_FALLBACKS=["synthetic-old-key"],
                COMMENTAIL={"default": {"GUEST_IP_ATTEMPTS_PER_MINUTE": 1}},
            ),
            self.assertRaisesMessage(DomainError, "Too many attempts"),
        ):
            consume_attempt(request, self.site, "192.0.2.1")

    def test_migration_protects_all_rows_across_batch_boundaries(self):
        comments = Comment.objects.bulk_create(
            [Comment(discussion=self.discussion, text="Retained") for _ in range(501)]
        )
        RateEvent.objects.bulk_create(
            [
                RateEvent(
                    site=self.site,
                    kind="attempt_ip",
                    subject_digest=digest(str(index)),
                )
                for index in range(501)
            ]
        )
        SubmissionRecord.objects.bulk_create(
            [
                SubmissionRecord(
                    discussion=self.discussion,
                    comment=comments[index],
                    actor_digest=digest("actor"),
                    key_digest=digest(str(index)),
                    payload_digest=digest("payload"),
                )
                for index in range(501)
            ]
        )
        migration = importlib.import_module(
            "commentail.migrations.0018_private_fingerprints"
        )
        historical = (
            MigrationLoader(connection)
            .project_state([("commentail", "0017_revision_spam_signals")])
            .apps
        )
        migration.protect_fingerprints(
            historical, SimpleNamespace(connection=connection)
        )
        for index, event in enumerate(RateEvent.objects.order_by("pk")):
            self.assertEqual(
                event.subject_digest,
                fingerprint(str(index), f"rate.{self.site.pk}.attempt_ip"),
            )
        self.assertEqual(
            SubmissionRecord.objects.filter(
                actor_digest=fingerprint(
                    "actor", f"submission.actor.{self.discussion.pk}"
                ),
                payload_digest=fingerprint(
                    "payload", f"submission.payload.{self.discussion.pk}"
                ),
            ).count(),
            501,
        )

    def test_admission_retry_after_rotation_needs_no_new_quota(self):
        from django.contrib.auth import get_user_model
        from django.contrib.sessions.backends.db import SessionStore
        from django.test import RequestFactory

        from commentail.admission import accept_request, issue_form

        request = RequestFactory().post("/", REMOTE_ADDR="192.0.2.1")
        request.user = get_user_model().objects.create_user("fingerprint-author")
        request.session = SessionStore()
        request.session.create()
        with override_settings(SECRET_KEY="synthetic-old-key"):
            key = issue_form(request, self.discussion)
            first = accept_request(request, self.discussion.pk, key, text="Message")
        with override_settings(
            SECRET_KEY="synthetic-new-key", SECRET_KEY_FALLBACKS=["synthetic-old-key"]
        ):
            self.assertEqual(
                accept_request(request, self.discussion.pk, key, text="Message").pk,
                first.pk,
            )
