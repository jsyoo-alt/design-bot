"""
소재봇 v2 — Slack 라우터

/소재생성2 커맨드 수신 → 확인 모달 표시 → 대량 생성 워커(bulk.py) 실행.

v1과의 차이:
  - 자동 누끼(rembg) 없음 — 디자이너 제작 투명 PNG 그대로 사용
  - 입력은 Google Sheets에서 읽음 (시트 고정)
  - 결과를 Slack 스레드 + Google Drive 양쪽에 저장
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.bulk import run_bulk
from app.config import SLACK_BOT_TOKEN
from app.sheets import count_pending

log = logging.getLogger(__name__)
router = APIRouter()
slack = WebClient(token=SLACK_BOT_TOKEN)


# ─────────────────────────────────────────────
# /소재생성2 슬래시 커맨드
# ─────────────────────────────────────────────
@router.post("/slack/command2")
async def slash_command_v2(request: Request, background_tasks: BackgroundTasks):
    """
    /소재생성2 커맨드 수신.
    trigger_id로 확인 모달 오픈.
    """
    from app.main import verify_slack_signature  # v1 서명 검증 재사용

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

    background_tasks.add_task(_open_confirm_modal, trigger_id, channel_id)
    return JSONResponse({"response_type": "ephemeral", "text": "📊 시트를 확인하는 중..."})


def _open_confirm_modal(trigger_id: str, channel_id: str):
    """제작 시작 전 확인 모달 표시. 제작요청 행 수를 미리 보여줌."""
    pending_count = count_pending()

    if pending_count == 0:
        # 제작요청 행이 없으면 모달 대신 ephemeral 메시지
        try:
            slack.chat_postEphemeral(
                channel=channel_id,
                user="",  # trigger_id 방식에서는 user 불필요
                text="ℹ️ 시트에 '제작요청' 상태인 행이 없습니다.",
            )
        except Exception:
            pass
        return

    count_text = (
        f"*{pending_count}개* 행이 제작요청 상태입니다."
        if pending_count > 0
        else "시트 연결을 확인할 수 없습니다. 그래도 실행하려면 생성 시작을 누르세요."
    )

    metadata = json.dumps({"channel_id": channel_id})

    try:
        slack.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "bulk_material_v2",
                "private_metadata": metadata,
                "title": {"type": "plain_text", "text": "대량 소재 생성 v2"},
                "submit": {"type": "plain_text", "text": "생성 시작"},
                "close":  {"type": "plain_text", "text": "취소"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f":bar_chart: *구글 시트 현황*\n{count_text}\n\n"
                                ":white_check_mark: *처리 조건*\n"
                                "• F열(status)이 `제작요청`인 행만 처리\n"
                                "• 이미 `제작완료`인 행은 건너뜀\n"
                                "• 오브젝트 이미지는 누끼 처리 없이 그대로 합성\n\n"
                                ":floppy_disk: *결과물*\n"
                                "• 이 채널 스레드에 PNG 업로드\n"
                                "• Google Drive 지정 폴더에도 저장\n"
                                "• 시트 F열 → `제작완료`, G열 → Drive URL"
                            ),
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": (
                                    "⚠️ 오브젝트 이미지는 *투명 PNG(누끼 처리 완료본)*이어야 합니다. "
                                    "일반 JPG를 입력하면 경고와 함께 그대로 합성됩니다."
                                ),
                            }
                        ],
                    },
                ],
            },
        )
    except SlackApiError as e:
        log.error("v2 모달 열기 실패: %s", e.response.get("error"))


# ─────────────────────────────────────────────
# 모달 제출 처리 (interactive endpoint는 main.py 공유)
# ─────────────────────────────────────────────
def handle_bulk_submission(payload: dict):
    """
    callback_id == 'bulk_material_v2' 인 모달 제출 처리.
    main.py의 /slack/interactive 에서 분기되어 호출됨.
    """
    raw_meta = payload["view"]["private_metadata"]
    try:
        metadata = json.loads(raw_meta)
        channel_id = metadata["channel_id"]
    except (json.JSONDecodeError, KeyError):
        log.error("v2 모달 메타데이터 파싱 실패: %s", raw_meta)
        return

    # 시작 메시지 전송
    try:
        result = slack.chat_postMessage(
            channel=channel_id,
            text="🚀 대량 소재 생성을 시작합니다. 완료되면 이 스레드에 결과가 올라옵니다.",
        )
        thread_ts = result["ts"]
    except SlackApiError as e:
        log.error("v2 시작 메시지 전송 실패: %s", e)
        thread_ts = None

    # 대량 생성 워커 실행 (동기 — BackgroundTasks 안에서 호출됨)
    run_bulk(slack=slack, channel_id=channel_id, thread_ts=thread_ts)
