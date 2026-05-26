"""
슬랙 소재봇 서버 (FastAPI)
"""

import hashlib
import hmac
import time
import json
import io
import logging
import os

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app import composer
from app.config import SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, BACKGROUNDS_DIR, FONTS_DIR
from app.rembg_utils import needs_rembg, remove_bg_to_data_url
from app.main_v2 import router as v2_router, handle_bulk_submission

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

TEMPLATES = {
    "비즈보드":                    "bizboard",
    "썸네일형":                    "thumbnail",
    "기본_2줄형":                  "basic_2line",
    "기본_2줄형_좌측 오브제":      "basic_2line_left",
    "기본_2줄형_좌측 오브제+뱃지": "basic_2line_left_badge",
    "앱다운로드형":                "app_download",
    "앱다운로드+썸네일형":         "app_download_thumb",
    "텍스트강조+썸네일형":         "text_highlight_thumb",
    "텍스트강조형":                "text_highlight",
    "텍스트강조+썸네일형 v2":      "text_highlight_v2_thumb",
    "텍스트강조형 v2":             "text_highlight_v2",
}

REQUIRED_BACKGROUNDS = [
    "bg_bizboard.png", "bg_basic_2line.png", "bg_basic_2line_left.png", "app_bar.png",
]
REQUIRED_FONTS = ["SpoqaHanSansNeo-Bold.ttf", "SpoqaHanSansNeo-Regular.ttf"]


# ─────────────────────────────────────────────
# 시작 시 필수 파일 / 환경변수 검증
# ─────────────────────────────────────────────
def _check_assets() -> list[str]:
    """누락된 파일 목록 반환. 빈 리스트면 정상."""
    missing = []
    for fname in REQUIRED_BACKGROUNDS:
        path = os.path.join(BACKGROUNDS_DIR, fname)
        if not os.path.exists(path):
            missing.append(f"배경 이미지 없음: assets/backgrounds/{fname}")
    for fname in REQUIRED_FONTS:
        path = os.path.join(FONTS_DIR, fname)
        if not os.path.exists(path):
            missing.append(f"폰트 파일 없음: assets/fonts/{fname}")
    return missing


@asynccontextmanager
async def lifespan(application: FastAPI):
    missing = _check_assets()
    if missing:
        for m in missing:
            log.error("[STARTUP] %s", m)
        log.error("[STARTUP] 위 파일들이 없습니다. git에 추가했는지 확인하세요.")
    else:
        log.info("[STARTUP] 모든 필수 파일 확인 완료")

    # rembg 모델 워밍업 — 백그라운드에서 실행해 서버 시작을 차단하지 않음
    import threading
    from app.rembg_utils import warmup
    threading.Thread(target=warmup, daemon=True).start()

    yield


app = FastAPI(lifespan=lifespan)
app.include_router(v2_router)   # v2: /소재생성2 라우트 마운트
slack = WebClient(token=SLACK_BOT_TOKEN)


# ─────────────────────────────────────────────
# Slack 서명 검증
# ─────────────────────────────────────────────
def verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    try:
        if not timestamp or not signature:
            return False
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
        sig_base = f"v0:{timestamp}:{request_body.decode()}"
        computed = "v0=" + hmac.new(
            SLACK_SIGNING_SECRET.encode(), sig_base.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed, signature)
    except (ValueError, Exception) as e:
        log.warning("서명 검증 실패: %s", e)
        return False


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
    trigger_id = form.get("trigger_id", "")
    channel_id = form.get("channel_id", "")

    if not trigger_id or not channel_id:
        raise HTTPException(status_code=400, detail="trigger_id or channel_id missing")

    background_tasks.add_task(open_modal, trigger_id, channel_id)
    return JSONResponse({"response_type": "ephemeral", "text": "소재 옵션을 선택해 주세요 ✏️"})


def open_modal(trigger_id: str, channel_id: str):
    # 채널 최근 메시지에서 이미지 자동 감지
    auto_image_url = None
    thread_ts = None
    try:
        history = slack.conversations_history(channel=channel_id, limit=10)
        for msg in history.get("messages", []):
            for f in msg.get("files", []):
                if f.get("mimetype", "").startswith("image/"):
                    auto_image_url = f.get("url_private_download")
                    thread_ts = msg.get("ts")
                    break
            if auto_image_url:
                break
    except SlackApiError as e:
        # channels:history 스코프 없으면 무시하고 계속 진행
        log.warning("채널 히스토리 조회 실패 (스코프 확인 필요): %s", e.response.get("error"))

    found_hint = (
        "✅ 직전 이미지 자동 감지됨 — URL 비워도 됩니다"
        if auto_image_url
        else "이미지를 채널에 먼저 올린 후 /소재생성 을 입력하면 자동으로 가져옵니다"
    )

    metadata = json.dumps({
        "channel_id": channel_id,
        "image_url": auto_image_url,
        "thread_ts": thread_ts,
    })

    try:
        slack.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "create_material",
                "private_metadata": metadata,
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
                        "hint": {
                            "type": "plain_text",
                            "text": "기본형: 우측 하단 코너 배지 | 텍스트강조형: 서브 카피 앞 인라인 배지(pill) | v2: 서브 카피 앞 오렌지 텍스트",
                        },
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "value",
                            "placeholder": {"type": "plain_text", "text": "예: 32%  /  29day"},
                            "max_length": 10,
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "image_url",
                        "label": {"type": "plain_text", "text": "상품 이미지 URL (선택)"},
                        "optional": True,
                        "hint": {"type": "plain_text", "text": found_hint},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "value",
                            "placeholder": {"type": "plain_text", "text": "https://..."},
                        },
                    },
                ],
            },
        )
    except SlackApiError as e:
        log.error("모달 열기 실패: %s", e.response.get("error"))


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
        callback_id = payload.get("view", {}).get("callback_id", "")
        if callback_id == "bulk_material_v2":
            # v2: 대량 생성 워커
            background_tasks.add_task(handle_bulk_submission, payload)
        else:
            # v1: 단건 생성 (기본)
            background_tasks.add_task(handle_submission, payload)
        return JSONResponse({})

    return JSONResponse({})


def _get_val(values: dict, block_id: str) -> str | None:
    """block_id로 모달 입력값 추출. static_select / plain_text_input 모두 처리."""
    element = values.get(block_id, {}).get("value")
    if not isinstance(element, dict):
        return None
    if element.get("type") == "static_select":
        return (element.get("selected_option") or {}).get("value") or None
    return element.get("value") or None


def handle_submission(payload: dict):
    # private_metadata 파싱 — 구 버전(문자열) 호환 처리 포함
    raw_meta = payload["view"]["private_metadata"]
    try:
        metadata = json.loads(raw_meta)
        channel_id = metadata["channel_id"]
        auto_image_url = metadata.get("image_url")
        thread_ts = metadata.get("thread_ts")
    except (json.JSONDecodeError, KeyError):
        channel_id = raw_meta  # 구 포맷 폴백
        auto_image_url = None
        thread_ts = None

    values = payload["view"]["state"]["values"]
    template  = _get_val(values, "template")
    title     = _get_val(values, "title") or ""
    sub       = _get_val(values, "sub") or ""
    title_l   = _get_val(values, "title_l")
    sub_l     = _get_val(values, "sub_l")
    badge     = _get_val(values, "badge")
    image_url = _get_val(values, "image_url") or auto_image_url

    log.info("소재 생성 요청 — template=%s title=%s image_url=%s", template, title, image_url)

    slack.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f"⏳ *{template}* 소재 생성 중...",
    )

    try:
        template_key = TEMPLATES.get(template)
        if template_key is None:
            raise ValueError(f"알 수 없는 템플릿: '{template}' — 선택 가능: {list(TEMPLATES.keys())}")

        # 누끼 전처리: 썸네일형이 아닌 템플릿에 이미지가 있으면 rembg 적용
        # Pillow·HTML 양 경로 모두 data URL을 수신할 수 있도록 _download_image에 data URL 지원 추가됨
        if image_url and needs_rembg(template_key):
            log.info("누끼 처리 시작 — template=%s", template_key)
            slack.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="🔪 누끼 처리 중... (5~10초 소요)",
            )
            try:
                image_url = remove_bg_to_data_url(image_url, bot_token=SLACK_BOT_TOKEN)
                log.info("누끼 처리 완료")
                slack.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text="✅ 누끼 완료 — 소재 합성 중...",
                )
            except Exception as rembg_err:
                log.warning("누끼 처리 실패, 원본 이미지 사용: %s", rembg_err)
                slack.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text="⚠️ 누끼 실패 — 원본 이미지로 대체합니다",
                )
                # image_url은 원본 그대로 유지
        if template_key == "bizboard":
            img_bytes = composer.compose_bizboard(
                title_l=title_l or title,
                sub_l=sub_l or sub,
                title_r=title,
                sub_r=sub,
                object_image_url=image_url,
            )
        elif template_key == "thumbnail":
            img_bytes = composer.compose_thumbnail(
                title=title, sub=sub, object_image_url=image_url,
            )
        elif template_key == "basic_2line":
            img_bytes = composer.compose_basic_2line(
                title=title, sub=sub, object_image_url=image_url, badge_text=badge,
            )
        elif template_key == "basic_2line_left":
            img_bytes = composer.compose_basic_2line_left_obj(
                title=title, sub=sub, object_image_url=image_url, badge_text=badge,
            )
        elif template_key == "basic_2line_left_badge":
            img_bytes = composer.compose_basic_2line_left_badge(
                title=title, sub=sub, object_image_url=image_url, badge_text=badge,
            )
        elif template_key == "app_download":
            img_bytes = composer.compose_app_download(title=title, sub=sub)
        elif template_key == "app_download_thumb":
            img_bytes = composer.compose_app_download_thumbnail(
                title=title, sub=sub, object_image_url=image_url,
            )
        elif template_key == "text_highlight_thumb":
            img_bytes = composer.compose_text_highlight_thumbnail(
                title=title, sub=sub, object_image_url=image_url, badge_text=badge,
            )
        elif template_key == "text_highlight":
            img_bytes = composer.compose_text_highlight(
                title=title, sub=sub, badge_text=badge,
            )
        elif template_key == "text_highlight_v2_thumb":
            img_bytes = composer.compose_text_highlight_v2_thumbnail(
                title=title, sub=sub, object_image_url=image_url, badge_text=badge,
            )
        elif template_key == "text_highlight_v2":
            img_bytes = composer.compose_text_highlight_v2(
                title=title, sub=sub, badge_text=badge,
            )

        # 300KB 초과 시 사용자에게 경고 (카카오 비즈보드 가이드 최대 300KB)
        size_kb = len(img_bytes) / 1024
        if size_kb > 300:
            slack.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"⚠️ 소재 용량이 {size_kb:.0f}KB로 카카오 가이드 최대치(300KB)를 초과합니다. 업로드는 정상 진행됩니다.",
            )

        slack.files_upload_v2(
            channel=channel_id,
            thread_ts=thread_ts,
            file=io.BytesIO(img_bytes),
            filename=f"{template}.png",
            title=f"{template} | {title}",
        )
        log.info("소재 생성 완료 — template=%s", template)

    except Exception as e:
        log.error("소재 생성 실패: %s", e, exc_info=True)
        slack.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"❌ 생성 실패: {type(e).__name__}: {e}",
        )


# ─────────────────────────────────────────────
# 헬스체크 — 필수 파일 상태도 함께 반환
# ─────────────────────────────────────────────
@app.get("/health")
def health():
    missing = _check_assets()
    if missing:
        return JSONResponse(status_code=500, content={"status": "error", "missing": missing})
    return {"status": "ok"}
