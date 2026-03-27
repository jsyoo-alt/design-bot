"""
슬랙 소재봇 서버 (FastAPI)
"""

import hashlib
import hmac
import time
import json
import io

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import composer
from config import SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET

app = FastAPI()
slack = WebClient(token=SLACK_BOT_TOKEN)

TEMPLATES = {
    "비즈보드": "bizboard",
    "기본_2줄형": "basic_2line",
    "기본_2줄형_좌측": "basic_2line_left_obj",
}


# ─────────────────────────────────────────────
# Slack 서명 검증
# ─────────────────────────────────────────────
def verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False
    sig_base = f"v0:{timestamp}:{request_body.decode()}"
    computed = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(), sig_base.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


# ─────────────────────────────────────────────
# /소재생성 슬래시 커맨드 수신
# ─────────────────────────────────────────────
@app.post("/slack/command")
async def slash_command(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    form = await request.form()
    trigger_id = form.get("trigger_id")
    channel_id = form.get("channel_id")

    # 모달 열기
    background_tasks.add_task(open_modal, trigger_id, channel_id)
    return JSONResponse({"response_type": "ephemeral", "text": "소재 옵션을 선택해 주세요 ✏️"})


def open_modal(trigger_id: str, channel_id: str):
    slack.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "create_material",
            "private_metadata": channel_id,
            "title": {"type": "plain_text", "text": "카카오 소재 생성"},
            "submit": {"type": "plain_text", "text": "생성하기"},
            "close": {"type": "plain_text", "text": "취소"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "template",
                    "label": {"type": "plain_text", "text": "템플릿"},
                    "element": {
                        "type": "static_select",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "템플릿 선택"},
                        "options": [
                            {"text": {"type": "plain_text", "text": k}, "value": k}
                            for k in TEMPLATES
                        ],
                    },
                },
                {
                    "type": "input",
                    "block_id": "title",
                    "label": {"type": "plain_text", "text": "메인 카피"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "예: 레드윙 UP TO 13%"},
                        "max_length": 30,
                    },
                },
                {
                    "type": "input",
                    "block_id": "sub",
                    "label": {"type": "plain_text", "text": "서브 카피"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "예: 베스트템 재입고"},
                        "max_length": 30,
                    },
                },
                {
                    "type": "input",
                    "block_id": "title_l",
                    "label": {"type": "plain_text", "text": "좌측 메인 카피 (비즈보드 전용)"},
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "예: 푸마"},
                    },
                },
                {
                    "type": "input",
                    "block_id": "sub_l",
                    "label": {"type": "plain_text", "text": "좌측 서브 카피 (비즈보드 전용)"},
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "예: 신규 발매"},
                    },
                },
                {
                    "type": "input",
                    "block_id": "badge",
                    "label": {"type": "plain_text", "text": "뱃지 텍스트 (선택)"},
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "예: 32% / 15%\\n세일"},
                        "max_length": 10,
                    },
                },
                {
                    "type": "input",
                    "block_id": "image_url",
                    "label": {"type": "plain_text", "text": "상품 이미지 URL"},
                    "optional": True,
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "value",
                        "placeholder": {"type": "plain_text", "text": "https://..."},
                    },
                },
            ],
        },
    )


# ─────────────────────────────────────────────
# 모달 제출 처리
# ─────────────────────────────────────────────
@app.post("/slack/interactive")
async def interactive(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))

    if payload.get("type") == "view_submission":
        background_tasks.add_task(handle_submission, payload)
        return JSONResponse({})  # 모달 즉시 닫기

    return JSONResponse({})


def _get_val(values: dict, block_id: str) -> str | None:
    return values.get(block_id, {}).get("value", {}).get("value") or None


def handle_submission(payload: dict):
    values = payload["view"]["state"]["values"]
    channel_id = payload["view"]["private_metadata"]

    template  = _get_val(values, "template")
    title     = _get_val(values, "title") or ""
    sub       = _get_val(values, "sub") or ""
    title_l   = _get_val(values, "title_l")
    sub_l     = _get_val(values, "sub_l")
    badge     = _get_val(values, "badge")
    image_url = _get_val(values, "image_url")

    slack.chat_postMessage(channel=channel_id, text=f"⏳ *{template}* 소재 생성 중...")

    try:
        template_key = TEMPLATES.get(template)

        if template_key == "bizboard":
            img_bytes = composer.compose_bizboard(
                title_l=title_l or title,
                sub_l=sub_l or sub,
                title_r=title,
                sub_r=sub,
                object_image_url=image_url,
            )
        elif template_key == "basic_2line":
            img_bytes = composer.compose_basic_2line(
                title=title,
                sub=sub,
                bg_image_url=image_url,
                badge_text=badge,
            )
        elif template_key == "basic_2line_left_obj":
            img_bytes = composer.compose_basic_2line_left_obj(
                title=title,
                sub=sub,
                object_image_url=image_url,
                badge_text=badge,
            )
        else:
            slack.chat_postMessage(channel=channel_id, text="❌ 알 수 없는 템플릿입니다.")
            return

        slack.files_upload_v2(
            channel=channel_id,
            file=io.BytesIO(img_bytes),
            filename=f"{template}.png",
            title=f"{template} | {title}",
        )

    except Exception as e:
        slack.chat_postMessage(channel=channel_id, text=f"❌ 생성 실패: {e}")


@app.get("/health")
def health():
    return {"status": "ok"}
