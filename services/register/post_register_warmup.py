from __future__ import annotations

import random
import time
from typing import Callable

from services.account_service import account_service
from services.openai_backend_api import OpenAIBackendAPI

StepFn = Callable[[int, str, str], None]

DEFAULT_MODEL = "auto"

WARMUP_PROMPTS = (
    # 通用寒暄
    "Hi",
    "Hello",
    "Hey there",
    "How are you?",
    "What can you help me with?",
    # 教育 / 通识
    "What's 2 plus 2?",
    "What is the capital of France?",
    "Explain photosynthesis in one sentence",
    "Can you recommend a good book?",
    "How do I prepare for a job interview?",
    # 科技 / IT
    "What is an API in simple terms?",
    "What's the difference between RAM and storage?",
    "What are basic principles of good UI design?",
    "How do I write a good commit message?",
    # 商业 / 金融
    "What are the key parts of a business plan?",
    "How do I write a professional email?",
    "What does ROI mean?",
    "What is compound interest?",
    "How should I start budgeting?",
    "What is the difference between revenue and profit?",
    # 法律
    "What is a non-disclosure agreement?",
    "What should I know before signing a lease?",
    # 市场营销
    "What makes a good product tagline?",
    "How do I measure customer satisfaction?",
    "What makes a product description effective?",
    # 医疗健康
    "What are signs I should drink more water?",
    "How much sleep do adults typically need?",
    "How does a vaccine work in simple terms?",
    # 餐饮
    "Suggest a healthy meal idea",
    "What herbs go well with chicken?",
    # 旅游
    "What should I pack for a weekend trip?",
    "How do I overcome jet lag?",
    # 运动 / 健身
    "Give me a tip for staying focused",
    "What's a simple warm-up exercise?",
    # 房地产
    "What should I look for when renting an apartment?",
    # 人力资源
    "What questions should I ask in a job interview?",
    # 心理学
    "How can I manage stress at work?",
    # 制造业
    "What is lean manufacturing?",
    # 农业
    "What is crop rotation?",
    # 新闻 / 传媒
    "How do I write a clear news headline?",
    # 建筑 / 室内设计
    "What makes a room feel spacious?",
    # 环保
    "How can I reduce plastic waste at home?",
    # 客服
    "How do I handle an upset customer politely?",
    # 摄影
    "What is the rule of thirds in photography?",
    # 汽车
    "How often should tire pressure be checked?",
    # 项目管理
    "What skills are useful for project management?",
    # 科学
    "Tell me a fun fact about space",
    "Why is the sky blue?",
    # 创意 / 写作
    "Give me an idea for a short story title",
    # 供应链
    "What is supply chain management?",
)


def _pick_warmup_prompt() -> str:
    return random.choice(WARMUP_PROMPTS)


def _consume_warmup_stream(backend: OpenAIBackendAPI, message: str, model: str) -> None:
    messages = [{"role": "user", "content": message}]
    got_payload = False
    for payload in backend.stream_conversation(messages=messages, model=model):
        if not payload:
            continue
        if payload == "[DONE]":
            break
        got_payload = True
    if not got_payload:
        raise RuntimeError("预热对话未收到上游响应")


def run_post_register_warmup(
    access_token: str,
    *,
    index: int = 0,
    step_fn: StepFn | None = None,
) -> dict:
    """注册成功后立刻发送一条简单对话，标记账号已被使用。"""
    token = str(access_token or "").strip()
    if not token:
        return {"ok": False, "error": "access_token 为空"}

    message = _pick_warmup_prompt()
    model = DEFAULT_MODEL

    def step(text: str, color: str = "") -> None:
        if step_fn is not None:
            step_fn(index, text, color)

    step(f"开始预热对话: {message!r} (model={model})")
    try:
        rest_seconds = random.uniform(5, 10)
        step(f"对话前随机休息 {rest_seconds:.1f}s")
        time.sleep(rest_seconds)

        backend = OpenAIBackendAPI(access_token=token)
        _consume_warmup_stream(backend, message, model)
        account_service.mark_text_used(token)
        step("预热对话完成", "green")
        return {"ok": True, "message": message, "model": model}
    except Exception as error:
        error_msg = str(error)
        step(f"预热对话失败: {error_msg}", "yellow")
        return {"ok": False, "error": error_msg, "message": message, "model": model}
