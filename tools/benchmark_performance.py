"""Reproducible synthetic server benchmark on a newly created disposable test DB.

Run from the checkout with the project's test dependencies installed. PostgreSQL
uses the same PG* environment variables as tests.settings. Never uses the host's
application database, external SMTP or a live HTTP server. Timings include ORM,
permissions, template rendering and middleware where noted, not a browser/network.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

# Support direct invocation without requiring an editable package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comments", type=int, default=100_000)
    parser.add_argument("--roots", type=int, default=100)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--load-seconds", type=int, default=0)
    parser.add_argument("--migration-cycle", action="store_true", help="Reverse/reapply migration 0014 on the synthetic comments")
    args = parser.parse_args()
    if min(args.comments, args.roots, args.samples, args.workers) < 1:
        parser.error("comments, roots, samples and workers must be positive")
    if args.load_seconds < 0:
        parser.error("load-seconds must be nonnegative")

    import django
    import wagtail

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import AnonymousUser
    from django.contrib.sessions.middleware import SessionMiddleware
    from django.db import close_old_connections, connection, connections
    from django.test import Client, RequestFactory, override_settings
    from django.test.runner import DiscoverRunner
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone
    from wagtail.models import Page, PageViewRestriction, Site

    from commentail.admin_views import index
    from commentail.models import (
        CaptchaChallenge,
        Comment,
        Discussion,
        MailJob,
        ModerationRule,
        SiteCommentSettings,
    )
    from commentail.outbox import process_mail
    from commentail.policies import policy_result
    from commentail.recent import recent_comments
    from commentail.services import cleanup_unconfirmed

    run_id = uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="commentail-performance-") as directory:
        test_name = (
            f"commentail_perf_{run_id}" if connection.vendor == "postgresql"
            else str(Path(directory) / "benchmark.sqlite3")
        )
        settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = test_name
        runner = DiscoverRunner(verbosity=0, interactive=False)
        previous = runner.setup_databases()
        try:
            with override_settings(
                ALLOWED_HOSTS=["localhost", "testserver"],
                EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            ):
                site = Site.objects.get(is_default_site=True)
                page = site.root_page
                page.get_url(current_site=site)
                discussion = Discussion.objects.create(site=site, page=page)
                SiteCommentSettings.objects.create(site=site, mode="read_only")
                now = timezone.now()
                roots = Comment.objects.bulk_create([
                    Comment(discussion=discussion, text=f"Root {n}", guest_name="Synthetic",
                            status="published", published_at=now)
                    for n in range(args.roots)
                ], batch_size=1000)
                for start in range(0, args.comments, 1000):
                    Comment.objects.bulk_create([
                        Comment(discussion=discussion, text="Synthetic reply " * 20,
                                guest_name="Synthetic", root=roots[n % len(roots)],
                                reply_to=roots[n % len(roots)], status="published", published_at=now)
                        for n in range(start, min(start + 1000, args.comments))
                    ])
                admin = get_user_model().objects.create_superuser("benchmark", "", "synthetic-only")
                client = Client()
                from django.urls import reverse

                fragment = reverse("commentail:discussion", args=[page.pk])

                def request():
                    value = RequestFactory().get("/", HTTP_HOST=site.hostname)
                    value.user = AnonymousUser()
                    value._wagtail_site = site
                    SessionMiddleware(lambda r: None).process_request(value)
                    return value

                def recent():
                    return recent_comments(request(), limit=5, page=None, include_replies=True)

                def read(opened=False):
                    response = client.get(fragment, {"thread": roots[-1].pk} if opened else {})
                    if response.status_code != 200:
                        raise RuntimeError(f"Fragment HTTP {response.status_code}")
                    return response

                def administration():
                    value = request()
                    value.user = admin
                    return index(value).render()

                results = {}
                if args.migration_cycle:
                    from django.db.migrations.executor import MigrationExecutor

                    def fingerprint():
                        digest = hashlib.sha256()
                        for row in Comment.objects.order_by("pk").values_list().iterator(chunk_size=1000):
                            digest.update(repr(row).encode())
                        return digest.hexdigest()

                    expected = fingerprint()
                    timings = {}
                    for migration in ("0013_sitecommentsettings_email_enabled", "0014_reading_indexes"):
                        started = time.perf_counter()
                        MigrationExecutor(connection).migrate([("commentail", migration)])
                        timings[migration] = round((time.perf_counter() - started) * 1000, 2)
                        if fingerprint() != expected:
                            raise RuntimeError("Migration cycle changed comment data")
                    results["migration_cycle"] = {"data_preserved": True, "elapsed_ms": timings}

                def measure(name, operation):
                    operation()  # Exclude first template/import/cache initialization.
                    samples = []
                    counts = []
                    for _ in range(args.samples):
                        connection.queries_log.clear()
                        with CaptureQueriesContext(connection) as queries:
                            started = time.perf_counter()
                            operation()
                            samples.append((time.perf_counter() - started) * 1000)
                        counts.append(len(queries))
                    results[name] = {
                        "p50_ms": round(statistics.median(samples), 2),
                        "p95_ms": round(sorted(samples)[math.ceil(len(samples) * .95) - 1], 2),
                        "max_queries": max(counts),
                    }

                with connection.cursor() as cursor:
                    cursor.execute("ANALYZE")
                with CaptureQueriesContext(connection) as captured:
                    recent()
                candidate_sql = next(q["sql"] for q in captured if 'FROM "commentail_comment"' in q["sql"])
                with connection.cursor() as cursor:
                    cursor.execute(("EXPLAIN (ANALYZE, BUFFERS) " if connection.vendor == "postgresql"
                                    else "EXPLAIN QUERY PLAN ") + candidate_sql)
                    candidate_plan = [list(row) for row in cursor.fetchall()]
                measure("recent_5", recent)
                measure("fragment_20_roots", read)
                measure("fragment_open_thread", lambda: read(True))
                measure("admin_pending", administration)
                # Keep mail transport local even if an environment sets SMTP options.
                sample = roots[0]
                MailJob.objects.bulk_create([
                    MailJob(comment=sample, recipient=sample, kind="published", status="sent",
                            event_key=f"synthetic:{n}", expires_at=now)
                    for n in range(min(args.comments, 100_000))
                ], batch_size=1000)
                measure("worker_idle_with_history", process_mail)
                MailJob.objects.filter(event_key__startswith="synthetic:").update(
                    status="pending", next_attempt_at=now + timedelta(days=1),
                    expires_at=now + timedelta(days=1),
                )
                measure("worker_idle_with_future_queue", process_mail)
                admin.email = "synthetic@example.invalid"
                admin.save(update_fields=["email"])
                mail_comment = Comment.objects.create(
                    discussion=discussion, user=admin, text="Synthetic mail source",
                    status="published", published_at=now,
                )

                def local_delivery():
                    batch = uuid.uuid4().hex
                    MailJob.objects.bulk_create([
                        MailJob(comment=mail_comment, recipient=mail_comment, kind="published",
                                event_key=f"local:{batch}:{n}", expires_at=now + timedelta(hours=1))
                        for n in range(25)
                    ])
                    if process_mail(limit=25) != 25:
                        raise RuntimeError("Local mail batch did not complete")

                measure("worker_25_local_messages", local_delivery)
                Comment.objects.bulk_create([
                    Comment(discussion=discussion, text="Fresh unconfirmed")
                    for _ in range(min(args.comments, 10_000))
                ], batch_size=1000)
                measure("cleanup_fresh_unconfirmed", cleanup_unconfirmed)
                CaptchaChallenge.objects.bulk_create([
                    CaptchaChallenge(site=site, session_digest=f"synthetic-{n}", answer=0,
                                     expires_at=now + timedelta(minutes=5))
                    for n in range(min(args.comments, 100_000))
                ], batch_size=1000)
                measure("captcha_session_invalidation", lambda: CaptchaChallenge.objects.filter(
                    site=site, session_digest="new-synthetic-session", used=False,
                ).update(used=True))

                # Anonymous-denied Pages precede the original accessible comments.
                for n in range(50):
                    restricted = page.add_child(instance=Page(title=f"Restricted {n}", slug=f"r{n}"))
                    PageViewRestriction.objects.create(page=restricted, restriction_type="login")
                    target = Discussion.objects.create(site=site, page=restricted)
                    Comment.objects.create(discussion=target, text="Restricted", status="published",
                                           published_at=timezone.now())
                measure("recent_after_50_denied_pages", recent)
                ModerationRule.objects.bulk_create([
                    ModerationRule(phrase=f"unmatched rule {n}", action="reject")
                    for n in range(20_000)
                ], batch_size=1000)
                measure("moderation_20000_rules", lambda: policy_result(
                    "ordinary words " * 300, "rules", guest=False, suspicious=False,
                ))
                # Constructing the SMTP backend checks availability without sending.
                SiteCommentSettings.objects.filter(site=site).update(mode="open")
                guest_number = 0

                def guest_form():
                    nonlocal guest_number
                    guest_number += 1
                    response = Client().get(
                        fragment, REMOTE_ADDR=f"10.0.{guest_number // 250}.{guest_number % 250 + 1}",
                    )
                    if response.status_code != 200 or b"commentail-form" not in response.content:
                        raise RuntimeError("Open guest form did not render")

                with override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                                       EMAIL_HOST="localhost"):
                    measure("open_guest_form", guest_form)
                SiteCommentSettings.objects.filter(site=site).update(mode="read_only")

                def concurrent_read(_):
                    close_old_connections()
                    try:
                        response = Client().get(fragment)
                        if response.status_code != 200:
                            raise RuntimeError(f"Concurrent HTTP {response.status_code}")
                    finally:
                        connections.close_all()

                started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    list(pool.map(concurrent_read, range(args.samples)))
                results["concurrent_fragments"] = {
                    "workers": args.workers, "requests": args.samples,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                }

                def sustained(guest):
                    deadline = time.perf_counter() + args.load_seconds

                    def worker(worker_number):
                        close_old_connections()
                        durations = []
                        client = Client()
                        try:
                            while time.perf_counter() < deadline:
                                started = time.perf_counter()
                                response = client.get(
                                    fragment, REMOTE_ADDR=f"10.1.0.{worker_number + 1}",
                                )
                                if response.status_code != 200 or (
                                    guest and b"commentail-form" not in response.content
                                ):
                                    raise RuntimeError("Sustained request failed")
                                durations.append((time.perf_counter() - started) * 1000)
                        finally:
                            connections.close_all()
                        return durations

                    started = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=args.workers) as pool:
                        durations = [value for batch in pool.map(worker, range(args.workers)) for value in batch]
                    elapsed = time.perf_counter() - started
                    if not durations:
                        raise RuntimeError("No sustained requests completed")
                    return {
                        "workers": args.workers, "requests": len(durations),
                        "elapsed_seconds": round(elapsed, 2),
                        "p50_ms": round(statistics.median(durations), 2),
                        "p95_ms": round(sorted(durations)[math.ceil(len(durations) * .95) - 1], 2),
                    }

                if args.load_seconds:
                    results["sustained_read_only"] = sustained(False)
                    SiteCommentSettings.objects.filter(site=site).update(mode="open")
                    # Exercise issuance continuously instead of measuring quota rejection.
                    with override_settings(
                        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                        EMAIL_HOST="localhost", COMMENTAIL={"default": {
                            "CAPTCHA_IP_LIMIT_PER_HOUR": 1_000_000,
                            "CAPTCHA_IP_LIMIT_PER_MINUTE": 1_000_000,
                        }},
                    ):
                        results["sustained_open_guest"] = sustained(True)
                    SiteCommentSettings.objects.filter(site=site).update(mode="read_only")
                from commentail.admission import accept_request, issue_form

                SiteCommentSettings.objects.filter(site=site).update(
                    mode="open", moderation="none", email_enabled=False,
                )
                users = get_user_model().objects.bulk_create([
                    get_user_model()(username=f"writer{n}", password="!")
                    for n in range(args.samples * 2 + 1)
                ])
                submissions = []
                for user in users:
                    value = request()
                    value.user = user
                    submissions.append((value, issue_form(value, discussion)))

                def submit(pair):
                    value, key = pair
                    return accept_request(value, discussion.pk, key, text="Synthetic submission").pk

                serial = iter(submissions[:args.samples + 1])
                with override_settings(COMMENTAIL={"default": {
                    "IP_LIMIT_PER_HOUR": args.samples * 3 + 1,
                }}):
                    measure("submission", lambda: submit(next(serial)))

                    def concurrent_submit(pair):
                        close_old_connections()
                        try:
                            return submit(pair)
                        finally:
                            connections.close_all()

                    started = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=args.workers) as pool:
                        identifiers = list(pool.map(concurrent_submit, submissions[args.samples + 1:]))
                    if len(set(identifiers)) != args.samples:
                        raise RuntimeError("Concurrent submissions did not produce distinct comments")
                    results["concurrent_submissions"] = {
                        "workers": args.workers, "accepted": len(identifiers),
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                plans = {}
                for name, query in {
                    "publication_order": Comment.objects.filter(status="published", published_at__lte=now)
                    .order_by("-published_at", "-pk")[:5],
                    "thread_replies": Comment.objects.filter(root=sample, status="published")
                    .order_by("published_at", "pk")[:20],
                }.items():
                    plans[name] = query.explain()
                print(json.dumps({
                    "database": connection.vendor,
                    "database_version": connection.Database.sqlite_version if connection.vendor == "sqlite" else connection.pg_version,
                    "python": platform.python_version(), "platform": platform.platform(),
                    "django": django.get_version(), "wagtail": wagtail.__version__,
                    "comments": args.comments + len(roots), "samples": args.samples,
                    "results": results, "plans": plans, "recent_candidate_plan": candidate_plan,
                }, indent=2))
        finally:
            runner.teardown_databases(previous)


if __name__ == "__main__":
    main()
