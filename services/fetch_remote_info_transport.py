"""fetch_remote_info 的三种独立出口：本地直连、清障、注册代理。"""

from __future__ import annotations

from typing import Any

from curl_cffi import requests

from services.proxy_service import ClearanceBundle, proxy_settings
from services.register import openai_register
from utils.helper import anonymize_token
from utils.log import logger


def is_http_403_error(exc: BaseException) -> bool:
    message = str(exc or "")
    return "HTTP 403" in message or "failed: HTTP 403" in message


def fetch_user_info_local(access_token: str) -> dict[str, Any]:
    from services.openai_backend_api import OpenAIBackendAPI

    api = OpenAIBackendAPI(access_token)
    try:
        return api.get_user_info()
    finally:
        api.close()


def _apply_clearance_bundle(session: requests.Session, bundle: ClearanceBundle | None) -> None:
    if bundle is None:
        return
    if bundle.user_agent:
        session.headers["User-Agent"] = bundle.user_agent
    target_host = str(bundle.target_host or "chatgpt.com").strip()
    for name, value in bundle.cookies.items():
        try:
            session.cookies.set(name, value, domain=f".{target_host}")
            session.cookies.set(name, value, domain=target_host)
        except Exception:
            continue


def _rebuild_backend_session(api: Any, *, proxy: str = "", upstream: bool = False) -> requests.Session:
    account = api.account if isinstance(api.account, dict) else {}
    impersonate = str(api.fp.get("impersonate") or "chrome110")
    api.session.close()
    session = requests.Session(
        **proxy_settings.build_session_kwargs(
            account=account,
            proxy=proxy,
            upstream=upstream,
            impersonate=impersonate,
            verify=True,
        )
    )
    session.headers.update(api._build_session_headers())
    token = str(api.access_token or "").strip()
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    api.session = session
    return session


def fetch_user_info_clearance(access_token: str) -> dict[str, Any]:
    from services.openai_backend_api import OpenAIBackendAPI

    api = OpenAIBackendAPI(access_token)
    _rebuild_backend_session(api, upstream=True)
    bundle = proxy_settings.refresh_clearance(
        target_url="https://chatgpt.com",
        account=api.account if isinstance(api.account, dict) else None,
        upstream=True,
        force=True,
    )
    _apply_clearance_bundle(api.session, bundle)
    headers = proxy_settings.build_headers(
        headers=dict(api.session.headers),
        target_url="https://chatgpt.com",
        account=api.account if isinstance(api.account, dict) else None,
        upstream=True,
    )
    api.session.headers.update({str(k): str(v) for k, v in headers.items()})
    try:
        return api.get_user_info()
    finally:
        api.close()


def fetch_user_info_proxy(access_token: str, proxy: str) -> dict[str, Any]:
    from services.openai_backend_api import OpenAIBackendAPI

    api = OpenAIBackendAPI(access_token)
    _rebuild_backend_session(api, proxy=str(proxy or "").strip(), upstream=True)
    try:
        return api.get_user_info()
    finally:
        api.close()


def _log_egress_success(*, egress: str, token_hint: str, proxy: str = "") -> None:
    payload: dict[str, Any] = {
        "event": "fetch_remote_info_egress",
        "egress": egress,
        "token": token_hint,
    }
    if proxy:
        payload["proxy"] = proxy
    logger.info(payload)


def _resolve_fetch_remote_info_proxy() -> str:
    return str(openai_register.config.get("proxy") or "").strip()


def _always_use_fetch_remote_info_proxy() -> bool:
    return bool(openai_register.config.get("always_use_fetch_remote_info_proxy"))


def fetch_user_info_with_403_fallback(access_token: str) -> dict[str, Any]:
    token_hint = anonymize_token(access_token)

    if _always_use_fetch_remote_info_proxy():
        proxy = _resolve_fetch_remote_info_proxy()
        if proxy:
            result = fetch_user_info_proxy(access_token, proxy)
            _log_egress_success(egress="proxy", token_hint=token_hint, proxy=proxy)
            return result

    try:
        result = fetch_user_info_local(access_token)
        _log_egress_success(egress="local", token_hint=token_hint)
        return result
    except RuntimeError as exc:
        if not is_http_403_error(exc):
            raise
        local_error = exc

    try:
        result = fetch_user_info_clearance(access_token)
        _log_egress_success(egress="clearance", token_hint=token_hint)
        return result
    except RuntimeError as exc:
        if not is_http_403_error(exc):
            raise
        clearance_error = exc

    proxy = _resolve_fetch_remote_info_proxy()
    if not proxy:
        raise clearance_error from local_error

    result = fetch_user_info_proxy(access_token, proxy)
    _log_egress_success(egress="proxy", token_hint=token_hint, proxy=proxy)
    return result
