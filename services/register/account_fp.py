from __future__ import annotations

import uuid

# 注册成功后不立刻 refresh，避免新号刚入库就用另一套指纹打 backend-api
SKIP_IMMEDIATE_POST_REGISTER_REFRESH = True

# 与 openai_register.py 注册请求头保持一致，供 OpenAIBackendAPI 补全/复用
REGISTER_BACKEND_FP_DEFAULTS: dict[str, str] = {
    "impersonate": "chrome",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "accept-language": "en-US,en;q=0.9",
    "sec-ch-ua-arch": '"x86_64"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version": '"145.0.0.0"',
    "sec-ch-ua-full-version-list": (
        '"Chromium";v="145.0.0.0", "Not:A-Brand";v="99.0.0.0", "Google Chrome";v="145.0.0.0"'
    ),
    "sec-ch-ua-platform-version": '"10.0.0"',
    "oai-language": "en-US",
}


def build_register_account_extras(
    *,
    device_id: str,
    user_agent: str,
    sec_ch_ua: str,
) -> dict:
    """把注册时的浏览器指纹写入账号，供 OpenAIBackendAPI 入库后复用。"""
    did = str(device_id or "").strip()
    ua = str(user_agent or "").strip()
    ch = str(sec_ch_ua or "").strip()
    sid = str(uuid.uuid4())
    fp = {
        "user-agent": ua,
        "sec-ch-ua": ch,
        "oai-device-id": did,
        "oai-session-id": sid,
        **REGISTER_BACKEND_FP_DEFAULTS,
    }
    return {"fp": fp, "oai-device-id": did, "oai-session-id": sid}


def finalize_registered_account(index: int, result: dict, *, step) -> None:
    """入库后的刷新策略：默认跳过立刻 refresh，交给后台定时任务。"""
    access_token = str(result.get("access_token") or "").strip()
    if not access_token:
        return
    if SKIP_IMMEDIATE_POST_REGISTER_REFRESH:
        step(index, "账号已入库，跳过注册后立刻刷新（由定时任务稍后刷新）", "yellow")
        return
    from services.account_service import account_service

    refresh_result = account_service.refresh_accounts([access_token])
    if refresh_result.get("errors"):
        step(index, f"账号已保存，刷新状态暂未成功，稍后可重试: {refresh_result['errors']}", "yellow")
