"""Guest HTTP actions driven by messages actually accepted over loopback SMTP."""

import re
import socketserver
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from threading import Thread
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from wagtail.models import Site

from commentail.models import CaptchaChallenge, Discussion, MailJob, ReplySubscription
from commentail.outbox import process_mail
from commentail.services import moderate, moderate_revision, submit


@contextmanager
def smtp_receiver():
    """Accept mail locally on an OS-assigned port; never forward to a recipient."""
    messages = []

    class Receiver(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 localhost ESMTP\r\n")
            while line := self.rfile.readline():
                command = line.upper()
                if command.startswith((b"EHLO", b"HELO", b"MAIL", b"RCPT", b"RSET")):
                    self.wfile.write(b"250 OK\r\n")
                elif command.startswith(b"DATA"):
                    self.wfile.write(b"354 Send message\r\n")
                    chunks = []
                    while (chunk := self.rfile.readline()) not in (b".\r\n", b""):
                        chunks.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                    messages.append(
                        BytesParser(policy=policy.default).parsebytes(b"".join(chunks))
                    )
                    self.wfile.write(b"250 Accepted\r\n")
                elif command.startswith(b"QUIT"):
                    self.wfile.write(b"221 Bye\r\n")
                    return
                else:
                    self.wfile.write(b"502 Unsupported\r\n")

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Receiver) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with override_settings(
                EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                EMAIL_HOST="127.0.0.1",
                EMAIL_PORT=server.server_address[1],
                EMAIL_USE_TLS=False,
                EMAIL_USE_SSL=False,
                EMAIL_HOST_USER="",
                EMAIL_HOST_PASSWORD="",
            ):
                yield messages
        finally:
            server.shutdown()
            worker.join(timeout=5)


class SMTPGuestChainTests(TestCase):
    def test_received_mail_drives_confirmation_revision_and_unsubscribe(self):
        site = Site.objects.get(is_default_site=True)
        discussion = Discussion.objects.create(site=site, page=site.root_page)
        admin = get_user_model().objects.create_superuser("smtp-admin", "", "synthetic")
        browser = Client(enforce_csrf_checks=True)
        visitor = Client()
        url = reverse("commentail:discussion", args=[site.root_page.pk])

        def post_action(action_url, **data):
            page = browser.get(action_url)
            self.assertEqual(page.status_code, 200)
            return browser.post(
                urlsplit(action_url).path,
                {
                    "token": page.context["token"],
                    "csrfmiddlewaretoken": browser.cookies["csrftoken"].value,
                    **data,
                },
            )

        def mail_link(message, purpose):
            body = message.get_content()
            matches = re.findall(
                r"http[^\s]+/actions/" + purpose + r"/\?token=[^\s]+", body
            )
            self.assertEqual(len(matches), 1)
            return matches[0]

        with smtp_receiver() as messages:
            form = browser.get(url)
            task = form.context["captcha"]
            response = browser.post(
                reverse("commentail:submit", args=[site.root_page.pk]),
                {
                    "key": form.context["form_key"],
                    "text": "Guest original, never in mail",
                    "name": "Guest",
                    "email": "guest@example.invalid",
                    "subscribe": "on",
                    "challenge": str(task.id),
                    "answer": str(CaptchaChallenge.objects.get(pk=task.id).answer),
                    "csrfmiddlewaretoken": browser.cookies["csrftoken"].value,
                },
                HTTP_USER_AGENT="Synthetic acceptance browser",
            )
            self.assertEqual(response.status_code, 302)
            comment = discussion.comments.get()
            self.assertEqual(comment.status, "awaiting_email")
            self.assertEqual(process_mail(), 1)
            confirmation = messages[-1]
            self.assertEqual(confirmation["To"], "guest@example.invalid")
            confirm_url = mail_link(confirmation, "confirm")
            browser.get(confirm_url)
            comment.refresh_from_db()
            self.assertEqual(comment.status, "awaiting_email")
            self.assertEqual(post_action(confirm_url).status_code, 200)
            comment.refresh_from_db()
            self.assertEqual(comment.status, "pending")
            self.assertIsNone(browser.get(url).context["captcha"])
            self.assertNotContains(visitor.get(url), comment.text)

            moderate(comment.pk, "approve", actor=admin)
            self.assertEqual(process_mail(), 1)
            edit_url = mail_link(messages[-1], "edit")
            self.assertEqual(
                post_action(edit_url, text="Guest revised").status_code, 200
            )
            revision = comment.revisions.get()
            self.assertEqual(revision.status, "pending")
            self.assertContains(visitor.get(url), comment.text)
            self.assertNotContains(visitor.get(url), revision.text)
            moderate_revision(revision.pk, "approve", actor=admin)
            self.assertContains(visitor.get(url), revision.text)
            self.assertNotContains(visitor.get(url), comment.text)

            reply = submit(
                discussion.pk,
                text="PRIVATE REPLY BODY",
                user=admin,
                reply_to=comment.pk,
            )
            self.assertEqual(process_mail(), 0)
            moderate(reply.pk, "approve", actor=admin)
            self.assertEqual(process_mail(), 1)
            notification = messages[-1]
            self.assertIn(
                f"?target={reply.pk}#commentail-{reply.pk}", notification.get_content()
            )
            unsubscribe_url = mail_link(notification, "unsubscribe")
            browser.get(unsubscribe_url)
            self.assertTrue(ReplySubscription.objects.get(comment=comment).enabled)
            self.assertEqual(post_action(unsubscribe_url).status_code, 200)
            self.assertFalse(ReplySubscription.objects.get(comment=comment).enabled)
            another = submit(
                discussion.pk, text="Second reply", user=admin, reply_to=comment.pk
            )
            moderate(another.pk, "approve", actor=admin)
            self.assertEqual(process_mail(), 0)
            self.assertEqual(len(messages), 3)
            self.assertFalse(MailJob.objects.exclude(status="sent").exists())
            for message in messages:
                for text in (comment.text, revision.text, reply.text, another.text):
                    self.assertNotIn(
                        text, str(message["Subject"]) + message.get_content()
                    )
