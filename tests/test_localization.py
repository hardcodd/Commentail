"""Exercise shipped locales at public, moderator and queued-mail boundaries."""

import gettext
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils.translation import get_language, override
from wagtail.models import Site

import commentail
from commentail.models import Discussion, MailJob, SiteCommentSettings
from commentail.outbox import process_mail
from commentail.services import (
    DomainError,
    confirm_email,
    moderate,
    moderate_revision,
    revise,
    submit,
)

# Independent expected copy catches English fallback and pt/pt-br confusion.
COPY = {
    "de": ("Kommentar senden", "Freigeben", "E-Mail-Adresse bestätigen",
           "Kommentar veröffentlicht", "Kommentar abgelehnt",
           "Ihr Kommentar wurde veröffentlicht", "Neue Antwort auf Ihren Kommentar"),
    "fr": ("Envoyer le commentaire", "Approuver", "Confirmez votre adresse e-mail",
           "Commentaire publié", "Commentaire rejeté",
           "Votre commentaire est publié", "Nouvelle réponse à votre commentaire"),
    "es": ("Enviar comentario", "Aprobar", "Confirme su correo electrónico",
           "Comentario publicado", "Comentario rechazado",
           "Su comentario está publicado", "Nueva respuesta a su comentario"),
    "pt-br": ("Enviar comentário", "Aprovar", "Confirme seu e-mail",
              "Comentário publicado", "Comentário rejeitado",
              "Seu comentário foi publicado", "Nova resposta ao seu comentário"),
}


class LocalizationTests(TestCase):
    def setUp(self) -> None:
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.options = SiteCommentSettings.objects.create(
            site=self.site, notify_publication=True, notify_rejection=True
        )
        self.admin = get_user_model().objects.create_superuser(
            "locale-admin", "admin@example.invalid", "synthetic"
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="127.0.0.1")
    def test_public_form_and_domain_errors_use_active_language(self) -> None:
        url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        for language, copy in COPY.items():
            with self.subTest(language=language), override(language):
                response = self.client.get(url)
                self.assertContains(response, copy[0])
                self.assertContains(response, f'lang="{language}"')
                self.assertNotContains(response, "Send comment")
                self.assertNotEqual(str(DomainError("Permission denied")), "Permission denied")
                self.assertNotIn("%(limit)s", response.content.decode())

    def test_admin_settings_rules_and_delivery_screens_are_localized(self) -> None:
        self.client.force_login(self.admin)
        headings = {
            "de": ("Moderationsfilter", "E-Mail-Versand", "Website-Einstellungen"),
            "fr": ("Règles de modération", "Envoi des e-mails", "Paramètres du site"),
            "es": ("Reglas de moderación", "Envío de correos", "Configuración del sitio"),
            "pt-br": ("Regras de moderação", "Envio de e-mails", "Configurações do site"),
        }
        for language, labels in headings.items():
            with self.subTest(language=language), override(language):
                for name, label, args in (
                    ("rules", labels[0], []),
                    ("mail", labels[1], []),
                    ("settings", labels[2], [self.site.pk]),
                ):
                    response = self.client.get(reverse(f"commentail_admin:{name}", args=args))
                    self.assertContains(response, label)

    def test_moderator_queue_and_decision_use_active_language(self) -> None:
        self.client.force_login(self.admin)
        for language, copy in COPY.items():
            with self.subTest(language=language), override(language):
                comment = submit(self.discussion.pk, text="Untranslated user text", user=self.admin)
                response = self.client.get(reverse("commentail_admin:detail", args=[comment.pk]))
                self.assertContains(response, copy[1])
                self.assertContains(response, comment.text)
                response = self.client.post(
                    reverse("commentail_admin:action", args=[comment.pk]),
                    {"action": "approve"}, follow=True,
                )
                self.assertEqual(response.status_code, 200)
                comment.refresh_from_db()
                self.assertEqual(comment.status, "published")

    def test_all_queued_mail_families_keep_recipient_language(self) -> None:
        for language, copy in COPY.items():
            with self.subTest(language=language):
                guest = submit(
                    self.discussion.pk, text="PRIVATE ORIGINAL TEXT",
                    guest_name="Guest", guest_email="guest@example.invalid",
                    language=language, subscribe=True,
                )
                self._send(guest.pk, "confirm", copy[2])
                confirm_email(guest.pk)
                moderate(guest.pk, "approve", actor=self.admin)
                self._send(guest.pk, "edit", copy[5], also=("published", copy[3]))
                from commentail.security import token_secret

                revision = revise(
                    guest.pk, "PRIVATE REVISION TEXT", site=self.site,
                    edit_token=token_secret(MailJob.objects.get(comment=guest, kind="edit").token),
                )
                moderate_revision(revision.pk, "approve", actor=self.admin)
                self._send(guest.pk, "published", copy[3])
                revision = revise(
                    guest.pk, "PRIVATE SECOND REVISION", site=self.site,
                    edit_token=token_secret(MailJob.objects.get(comment=guest, kind="edit").token),
                )
                moderate_revision(revision.pk, "reject", actor=self.admin, reason="Original reason — unchanged")
                self._send(guest.pk, "rejected", copy[4], body="Original reason — unchanged")
                reply = submit(
                    self.discussion.pk, text="PRIVATE REPLY TEXT", user=self.admin,
                    reply_to=guest.pk, language="en",
                )
                moderate(reply.pk, "approve", actor=self.admin)
                self._send(reply.pk, "reply", copy[6])
                rejected = submit(
                    self.discussion.pk, text="PRIVATE REJECTED TEXT", user=self.admin,
                    language=language,
                )
                moderate(rejected.pk, "reject", actor=self.admin)
                self._send(rejected.pk, "rejected", copy[4])

    def _send(
        self, comment_id: int, kind: str, subject: str, *,
        also: tuple[str, str] | None = None, body: str = "",
    ) -> None:
        pending = MailJob.objects.filter(status="pending")
        jobs = {job.kind: job for job in pending.filter(comment_id=comment_id)}
        job = jobs[kind]
        before = len(mail.outbox)
        with override("ru"):
            process_mail()
            self.assertEqual(get_language(), "ru")
        messages = mail.outbox[before:]
        by_id = {message.extra_headers["Message-ID"]: message for message in messages}
        for expected_kind, expected_subject in [(kind, subject), *([also] if also else [])]:
            expected = jobs[expected_kind]
            message = by_id[f"<commentail-{expected.pk}@{self.site.hostname}>"]
            self.assertEqual(message.subject, expected_subject)
            self.assertNotIn("PRIVATE", message.body)
            if expected_kind != "reply":
                self.assertIn(expected_subject, message.body)
            if body:
                self.assertIn(body, message.body)
        job.refresh_from_db()
        self.assertEqual(job.status, "sent")

    def test_reply_mail_localizes_generated_author_names_for_the_recipient(self) -> None:
        responder = get_user_model().objects.create_user("responder@example.invalid")
        for language, normal, deleted, subject in (
            ("en", "User", "Deleted user", "New reply to your comment"),
            ("ru", "Пользователь", "Удалённый пользователь", "Новый ответ на ваш комментарий"),
            ("de", "Benutzer", "Gelöschter Benutzer", COPY["de"][6]),
            ("fr", "Utilisateur", "Utilisateur supprimé", COPY["fr"][6]),
            ("es", "Usuario", "Usuario eliminado", COPY["es"][6]),
            ("pt-br", "Usuário", "Usuário excluído", COPY["pt-br"][6]),
        ):
            for account_deleted, label in ((False, normal), (True, deleted)):
                with self.subTest(language=language, account_deleted=account_deleted):
                    parent = submit(
                        self.discussion.pk, text="Parent", user=self.admin,
                        language=language, subscribe=True,
                    )
                    moderate(parent.pk, "approve", actor=self.admin)
                    reply = submit(
                        self.discussion.pk, text="PRIVATE REPLY TEXT", user=responder,
                        reply_to=parent.pk, language="en",
                    )
                    moderate(reply.pk, "approve", actor=self.admin)
                    if account_deleted:
                        reply.account_deleted = True
                        reply.user = None
                        reply.save(update_fields=["account_deleted", "user"])
                    self._send(reply.pk, "reply", subject, body=label)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="127.0.0.1")
    def test_untranslated_language_keeps_english_fallback(self) -> None:
        with override("ja"):
            response = self.client.get(reverse("commentail:discussion", args=[self.site.root_page.pk]))
            self.assertContains(response, "Send comment")


class CatalogMetadataTests(SimpleTestCase):
    def test_plural_rules_cover_zero_one_and_multiple(self) -> None:
        root = Path(commentail.__file__).parent / "locale"
        for locale, expected in (
            ("de", [1, 0, 1, 1]), ("es", [1, 0, 1, 1]),
            ("fr", [0, 0, 1, 1]), ("pt_BR", [0, 0, 1, 1]),
        ):
            with self.subTest(locale=locale):
                with (root / locale / "LC_MESSAGES/django.mo").open("rb") as stream:
                    catalog = gettext.GNUTranslations(stream)
                self.assertEqual([catalog.plural(n) for n in (0, 1, 2, 100)], expected)
