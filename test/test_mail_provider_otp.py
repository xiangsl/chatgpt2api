from services.register.mail_provider import (
    _extract_code,
    _extract_openai_code_from_content,
    _is_openai_verification_message,
    _is_skipped_otp_message,
    _message_tracking_ref,
)


MICROSOFT_WELCOME_HTML = (
    '<a href="http://go.microsoft.com/fwlink/?LinkId=521839" style="color:#5a5a5a">Privacy Statement</a>'
)

OPENAI_HTML = (
    '<p style="font-size:28px; background-color:#F3F3F3; color:#5D5D5D; border-radius:16px; '
    'padding:28px 24px; margin:24px 0">530641 </p>'
)


def test_microsoft_welcome_does_not_extract_code():
    message = {
        "sender": "no-reply@microsoft.com",
        "subject": "Welcome to your new Outlook.com account",
        "text_content": "Welcome to your Outlook!",
        "html_content": MICROSOFT_WELCOME_HTML,
    }
    assert _extract_code(message) is None
    assert _extract_code(message, require_openai=True) is None
    assert not _is_openai_verification_message(message)


def test_openai_verification_extracts_code_with_sender_filter():
    message = {
        "sender": "noreply@tm.openai.com",
        "subject": "Your temporary OpenAI verification code",
        "text_content": "Enter this temporary verification code to continue:\n\n530641\n",
        "html_content": OPENAI_HTML,
    }
    assert _is_openai_verification_message(message)
    assert _extract_code(message, require_openai=True) == "530641"
    assert _extract_code(message) == "530641"


def test_openai_sender_domains_include_otp_mailbox():
    message = {
        "sender": "otp@tm1.openai.com",
        "subject": "任意语言主题",
        "text_content": "123456",
        "html_content": "",
    }
    assert _is_openai_verification_message(message)
    assert _extract_code(message, require_openai=True) == "123456"


def test_chinese_subject_openai_mail_is_recognized_without_english_keywords():
    message = {
        "sender": "noreply@tm.openai.com",
        "subject": "您的 OpenAI 临时验证码",
        "text_content": "请输入以下验证码继续：\n\n987654\n",
        "html_content": (
            '<p style="font-size:28px; background-color:#F3F3F3; color:#5D5D5D; '
            'border-radius:16px; padding:28px 24px; margin:24px 0">987654 </p>'
        ),
    }
    assert _is_openai_verification_message(message)
    assert _extract_code(message, require_openai=True) == "987654"


def test_openai_like_content_without_sender_is_ignored_in_strict_mode():
    message = {
        "sender": "no-reply@microsoft.com",
        "subject": "Security alert",
        "text_content": "Your verification code is 123456",
        "html_content": OPENAI_HTML,
    }
    assert _extract_code(message) == "530641"
    assert _extract_code(message, require_openai=True) is None


def test_plain_text_openai_code_after_url_strip():
    assert _extract_openai_code_from_content("", "Please continue with 442211 in this email.") == "442211"


def test_baseline_refs_skip_existing_messages():
    message = {
        "provider": "outlook_token",
        "mailbox": "user@outlook.com",
        "message_id": "abc-123",
        "sender": "noreply@tm.openai.com",
        "subject": "Your temporary OpenAI verification code",
        "text_content": "530641",
        "html_content": OPENAI_HTML,
    }
    ref = _message_tracking_ref(message)
    mailbox = {"_otp_baseline_refs": [ref]}
    assert _is_skipped_otp_message(mailbox, ref, set())
