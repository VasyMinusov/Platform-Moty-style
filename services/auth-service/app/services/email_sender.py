"""
Отправка email-ов: абстракция + SMTP-реализация.

Контракт — `EmailSender` (Protocol). В тестах через FastAPI DI
подменяется на MockEmailSender (см. tests/conftest.py).

Если SMTP_HOST пуст — режим no-op: письмо логируется, но не отправляется.
Это удобно для local/dev, где SMTP обычно не поднят.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from string import Template
from typing import Any, Protocol

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Шаблоны (инлайн — чтобы не тянуть jinja2 и не возиться с путями)
# ═══════════════════════════════════════════════════════════════════════════

_TEMPLATES: dict[str, str] = {
    "verify_email.txt": (
        "Здравствуйте!\n\n"
        "Подтвердите ваш email для $service_name, перейдя по ссылке:\n"
        "$action_url\n\n"
        "Ссылка действительна $expires_hours ч.\n"
        "Если вы не регистрировались — просто проигнорируйте это письмо.\n"
    ),
    "verify_email.html": (
        "<p>Здравствуйте!</p>"
        "<p>Подтвердите ваш email для <b>$service_name</b>:</p>"
        '<p><a href="$action_url">Подтвердить email</a></p>'
        "<p>Ссылка действительна $expires_hours ч.</p>"
        "<p>Если вы не регистрировались — проигнорируйте письмо.</p>"
    ),
    "password_reset.txt": (
        "Здравствуйте!\n\n"
        "Для сброса пароля в $service_name перейдите по ссылке:\n"
        "$action_url\n\n"
        "Ссылка действительна $expires_hours ч.\n"
        "Если вы не запрашивали сброс — проигнорируйте письмо.\n"
    ),
    "password_reset.html": (
        "<p>Здравствуйте!</p>"
        "<p>Сброс пароля для <b>$service_name</b>:</p>"
        '<p><a href="$action_url">Установить новый пароль</a></p>'
        "<p>Ссылка действительна $expires_hours ч.</p>"
        "<p>Если вы не запрашивали сброс — проигнорируйте письмо.</p>"
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# Protocol
# ═══════════════════════════════════════════════════════════════════════════


class EmailSender(Protocol):
    """Интерфейс отправки email."""

    async def send(
        self,
        *,
        to: str,
        subject: str,
        text_template: str,
        html_template: str,
        context: dict[str, Any],
    ) -> None: ...


# ═══════════════════════════════════════════════════════════════════════════
# SMTP-реализация
# ═══════════════════════════════════════════════════════════════════════════


class SmtpEmailSender:
    """
    SMTP-отправитель.

    smtplib синхронный → оборачиваем в asyncio.to_thread, чтобы не блокировать
    event loop (SMTP-handshake + отправка могут занять сотни мс).
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    @staticmethod
    def _render(template_name: str, context: dict[str, Any]) -> str:
        raw = _TEMPLATES.get(template_name)
        if raw is None:
            raise ValueError(f"Unknown email template: {template_name}")
        # safe_substitute — чтобы не падать на неожиданных $ в данных
        return Template(raw).safe_substitute(**context)

    def _send_sync(
        self,
        *,
        to: str,
        subject: str,
        text_body: str,
        html_body: str,
    ) -> None:
        s = self._settings

        msg = EmailMessage()
        msg["From"] = s.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds) as smtp:
            smtp.ehlo()
            if s.smtp_start_tls:
                smtp.starttls()
                smtp.ehlo()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)

    async def send(
        self,
        *,
        to: str,
        subject: str,
        text_template: str,
        html_template: str,
        context: dict[str, Any],
    ) -> None:
        if not self._settings.smtp_host:
            log.warning(
                "email_not_sent_no_smtp",
                to=to,
                subject=subject,
                reason="SMTP_HOST is empty",
            )
            return

        text_body = self._render(text_template, context)
        html_body = self._render(html_template, context)

        try:
            await asyncio.to_thread(
                self._send_sync,
                to=to,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
            )
            log.info("email_sent", to=to, subject=subject)
        except Exception as exc:
            # Не глотаем — вызывающий код (роутер) должен знать,
            # что письмо не ушло (иначе пользователь будет ждать вечно).
            log.error("email_send_failed", to=to, subject=subject, error=str(exc))
            raise


# ═══════════════════════════════════════════════════════════════════════════
# Singleton / FastAPI dependency
# ═══════════════════════════════════════════════════════════════════════════

_email_sender: EmailSender | None = None


def get_email_sender() -> EmailSender:
    """FastAPI-dependency: singleton EmailSender."""
    global _email_sender
    if _email_sender is None:
        _email_sender = SmtpEmailSender()
    return _email_sender


def reset_email_sender() -> None:
    """Сбросить singleton (для тестов)."""
    global _email_sender
    _email_sender = None
