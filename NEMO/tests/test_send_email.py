from smtplib import SMTPConnectError, SMTPDataError, SMTPServerDisconnected, SMTPHeloError
from unittest.mock import patch, MagicMock

from django.http import QueryDict
from django.test import TestCase

from NEMO.forms import EmailBroadcastForm
from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.utilities import send_mail


class TestSendMailRetries(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.subject = "Retry Test"
        self.content = "<p>Testing retry logic</p>"
        self.from_email = "test@example.com"
        self.to = ["recipient@example.com"]
        self.fail_silently = True

    @patch("NEMO.utilities.EmailMessage.send", side_effect=[SMTPServerDisconnected(), 1])
    def test_send_mail_retries_on_disconnection(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    @patch("NEMO.utilities.EmailMessage.send", side_effect=[SMTPConnectError(451, "Temporary error"), 1])
    def test_send_mail_retries_on_connect_error(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    @patch("NEMO.utilities.EmailMessage.send", side_effect=[SMTPHeloError(451, "Helo error"), 1])
    def test_send_mail_retries_on_helo_error(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    @patch("NEMO.utilities.EmailMessage.send", side_effect=[SMTPDataError(451, "Data error"), 1])
    def test_send_mail_retries_on_data_error(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    @patch(
        "NEMO.utilities.EmailMessage.send",
        side_effect=[SMTPServerDisconnected(), SMTPConnectError(451, "Temporary error")],
    )
    def test_send_mail_fails_after_max_retries(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 0)
        self.assertEqual(mock_send.call_count, 2)


class TestEmailBroadcastFormFields(NEMOTestCaseMixin, TestCase):
    """Tests for the reply_to and cc fields on EmailBroadcastForm."""

    def _form_data(self, **overrides):
        qd = QueryDict(mutable=True)
        defaults = {
            "subject": "Test Subject",
            "color": "#5bc0de",
            "contents": "Hello",
            "copy_me": "on",
            "audience": "tool",
            "reply_to": "",
            "cc": "",
        }
        defaults.update(overrides)
        for key, value in defaults.items():
            qd[key] = value
        return qd

    def test_reply_to_valid_email(self):
        form = EmailBroadcastForm(data=self._form_data(reply_to="admin@example.com"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["reply_to"], "admin@example.com")

    def test_reply_to_empty_is_valid(self):
        form = EmailBroadcastForm(data=self._form_data(reply_to=""))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["reply_to"], "")

    def test_reply_to_invalid_email(self):
        form = EmailBroadcastForm(data=self._form_data(reply_to="not-an-email"))
        self.assertFalse(form.is_valid())
        self.assertIn("reply_to", form.errors)

    def test_cc_single_valid_email(self):
        form = EmailBroadcastForm(data=self._form_data(cc="user@example.com"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cc"], ["user@example.com"])

    def test_cc_multiple_valid_emails(self):
        form = EmailBroadcastForm(data=self._form_data(cc="a@example.com, b@example.com"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cc"], ["a@example.com", "b@example.com"])

    def test_cc_semicolon_delimiter(self):
        form = EmailBroadcastForm(data=self._form_data(cc="a@example.com; b@example.com"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cc"], ["a@example.com", "b@example.com"])

    def test_cc_empty_is_valid(self):
        form = EmailBroadcastForm(data=self._form_data(cc=""))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cc"], [])

    def test_cc_invalid_email(self):
        form = EmailBroadcastForm(data=self._form_data(cc="good@example.com, bad-email"))
        self.assertFalse(form.is_valid())
        self.assertIn("cc", form.errors)


class TestSendMailReplyToAndCc(NEMOTestCaseMixin, TestCase):
    """Tests for the reply_to and cc parameters in send_mail."""

    @patch("NEMO.utilities.EmailMessage.send", return_value=1)
    def test_send_mail_with_reply_to(self, mock_send):
        send_mail(
            subject="Test",
            content="<p>Hello</p>",
            from_email="sender@example.com",
            to=["recipient@example.com"],
            reply_to=["replyto@example.com"],
        )
        self.assertEqual(mock_send.call_count, 1)

    @patch("NEMO.utilities.EmailMessage.send", return_value=1)
    def test_send_mail_with_cc(self, mock_send):
        send_mail(
            subject="Test",
            content="<p>Hello</p>",
            from_email="sender@example.com",
            to=["recipient@example.com"],
            cc=["cc1@example.com", "cc2@example.com"],
        )
        self.assertEqual(mock_send.call_count, 1)

    @patch("NEMO.utilities.EmailMessage.send", return_value=1)
    def test_send_mail_without_reply_to_or_cc(self, mock_send):
        result = send_mail(
            subject="Backward compat",
            content="<p>Hello</p>",
            from_email="sender@example.com",
            to=["recipient@example.com"],
        )
        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 1)
