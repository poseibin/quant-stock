"""推送：钉钉 / 企微 / 邮件"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
import os

import requests

from common.config import DINGTALK_WEBHOOK, WECHAT_WEBHOOK
from common.utils import get_logger

log = get_logger("notifier")


def send_dingtalk(text: str, webhook: str | None = None) -> bool:
    url = webhook or DINGTALK_WEBHOOK
    if not url:
        log.warning("钉钉 webhook 未配置")
        return False
    payload = {"msgtype": "markdown",
               "markdown": {"title": "量化选股", "text": text}}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        log.error(f"钉钉推送失败: {e}")
        return False


def send_wechat(text: str, webhook: str | None = None) -> bool:
    url = webhook or WECHAT_WEBHOOK
    if not url:
        log.warning("企微 webhook 未配置")
        return False
    payload = {"msgtype": "markdown", "markdown": {"content": text}}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        log.error(f"企微推送失败: {e}")
        return False


def send_email(subject: str, body: str) -> bool:
    host = os.getenv("EMAIL_SMTP_HOST")
    port = int(os.getenv("EMAIL_SMTP_PORT", "465") or "465")
    user = os.getenv("EMAIL_USER")
    pw = os.getenv("EMAIL_PASSWORD")
    to = os.getenv("EMAIL_TO")
    if not all([host, user, pw, to]):
        log.warning("邮件配置不全")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("量化选股", user))
    msg["To"] = to
    try:
        with smtplib.SMTP_SSL(host, port) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        return True
    except Exception as e:
        log.error(f"邮件推送失败: {e}")
        return False


def broadcast(subject: str, body: str) -> dict:
    """同时推送多个渠道，返回每个渠道的成功状态。"""
    return {
        "dingtalk": send_dingtalk(body),
        "wechat":   send_wechat(body),
        "email":    send_email(subject, body),
    }
