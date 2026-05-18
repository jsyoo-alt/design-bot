"""
대량 소재 생성 워커 (v2)

sheets.py에서 '제작요청' 행을 읽어 순서대로 합성 → Drive 업로드 → Slack 전송 → 시트 상태 업데이트.
각 행은 독립적으로 에러 격리됨 (한 행 실패해도 다음 행 계속 진행).
"""

import io
import logging
import time

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import base64

import requests

from app import composer
from app.sheets import (
    SheetRow,
    fetch_pending_rows,
    update_row_status,
    STATUS_DONE,
    STATUS_FAIL,
)
from app.drive import upload_png, extract_drive_file_id, download_file as drive_download

log = logging.getLogger(__name__)

# 템플릿명 → composer 함수 매핑 (main.py TEMPLATES와 동기화)
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

# Slack API rate limit 대응: 행 간 대기 시간 (초)
ROW_DELAY_SEC = 1.5


def _resolve_object_url(url: str | None) -> str | None:
    """
    오브젝트 이미지 URL 전처리.
    Google Drive URL이면:
      1) 공개 다운로드 URL (uc?export=download&id=...) 로 먼저 시도
      2) 실패 시 서비스 계정 API로 폴백
    일반 URL이면 그대로 반환.
    """
    if not url:
        return None
    file_id = extract_drive_file_id(url)
    if not file_id:
        return url

    # 1) 공개 다운로드 시도 (링크 공유된 파일)
    public_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        resp = requests.get(public_url, timeout=30)
        resp.raise_for_status()
        raw = resp.content
        log.info("Drive 공개 URL 다운로드 성공: id=%s (%d bytes)", file_id, len(raw))
        b64 = base64.b64encode(raw).decode()
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        log.warning("Drive 공개 URL 실패, 서비스 계정으로 재시도: id=%s, error=%s", file_id, e)

    # 2) 서비스 계정 API 폴백 (서비스 계정과 공유된 파일)
    raw = drive_download(file_id)
    b64 = base64.b64encode(raw).decode()
    log.info("Drive 서비스 계정 다운로드 성공: id=%s (%d bytes)", file_id, len(raw))
    return f"data:image/png;base64,{b64}"


def _compose(row: SheetRow) -> bytes:
    """SheetRow → composer 호출 → PNG bytes 반환."""
    template_key = TEMPLATES.get(row.template)
    if template_key is None:
        raise ValueError(f"알 수 없는 템플릿: '{row.template}'")

    obj_url = _resolve_object_url(row.object_url)

    if template_key == "bizboard":
        return composer.compose_bizboard(
            title_l=row.main_copy_l or row.main_copy,
            sub_l=row.sub_copy_l or row.sub_copy,
            title_r=row.main_copy,
            sub_r=row.sub_copy,
            object_image_url=obj_url,
        )
    elif template_key == "thumbnail":
        return composer.compose_thumbnail(
            title=row.main_copy, sub=row.sub_copy, object_image_url=obj_url,
        )
    elif template_key == "basic_2line":
        return composer.compose_basic_2line(
            title=row.main_copy, sub=row.sub_copy,
            object_image_url=obj_url, badge_text=row.badge,
        )
    elif template_key == "basic_2line_left":
        return composer.compose_basic_2line_left_obj(
            title=row.main_copy, sub=row.sub_copy,
            object_image_url=obj_url, badge_text=row.badge,
        )
    elif template_key == "basic_2line_left_badge":
        return composer.compose_basic_2line_left_badge(
            title=row.main_copy, sub=row.sub_copy,
            object_image_url=obj_url, badge_text=row.badge,
        )
    elif template_key == "app_download":
        return composer.compose_app_download(title=row.main_copy, sub=row.sub_copy)
    elif template_key == "app_download_thumb":
        return composer.compose_app_download_thumbnail(
            title=row.main_copy, sub=row.sub_copy, object_image_url=obj_url,
        )
    elif template_key == "text_highlight_thumb":
        return composer.compose_text_highlight_thumbnail(
            title=row.main_copy, sub=row.sub_copy,
            object_image_url=obj_url, badge_text=row.badge,
        )
    elif template_key == "text_highlight":
        return composer.compose_text_highlight(
            title=row.main_copy, sub=row.sub_copy, badge_text=row.badge,
        )
    elif template_key == "text_highlight_v2_thumb":
        return composer.compose_text_highlight_v2_thumbnail(
            title=row.main_copy, sub=row.sub_copy,
            object_image_url=obj_url, badge_text=row.badge,
        )
    elif template_key == "text_highlight_v2":
        return composer.compose_text_highlight_v2(
            title=row.main_copy, sub=row.sub_copy, badge_text=row.badge,
        )
    else:
        raise ValueError(f"처리되지 않은 템플릿 키: '{template_key}'")


def _safe_filename(row: SheetRow) -> str:
    """Drive 저장용 파일명 생성. 특수문자 제거."""
    safe_title = "".join(c for c in row.main_copy if c.isalnum() or c in " _-")[:20].strip()
    return f"{row.template}_{safe_title}_{row.row_index}.png"


def run_bulk(
    slack: WebClient,
    channel_id: str,
    thread_ts: str | None,
) -> None:
    """
    대량 소재 생성 메인 워커.
    백그라운드 태스크로 실행됨.

    흐름:
      1. 시트에서 '제작요청' 행 조회
      2. 시작 메시지 전송
      3. 각 행: 합성 → Drive 업로드 → Slack 업로드 → 시트 상태 업데이트
      4. 완료 요약 메시지
    """
    def post(text: str):
        try:
            slack.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text)
        except SlackApiError as e:
            log.warning("Slack 메시지 전송 실패: %s", e)

    # 1. 제작요청 행 조회
    try:
        rows = fetch_pending_rows()
    except Exception as e:
        post(f"❌ 시트 읽기 실패: {e}")
        return

    if not rows:
        post("ℹ️ 제작요청 상태인 행이 없습니다. 시트의 F열을 '제작요청'으로 설정해 주세요.")
        return

    post(f"⏳ 총 *{len(rows)}개* 소재 생성 시작합니다...")

    success_count = 0
    fail_count = 0

    for idx, row in enumerate(rows, start=1):
        row_label = f"[{idx}/{len(rows)}] 행{row.row_index} `{row.template}` — {row.main_copy}"
        log.info("처리 시작: %s", row_label)

        try:
            # 2. 합성
            png_bytes = _compose(row)

            # 3. Drive 업로드
            filename = _safe_filename(row)
            drive_url = upload_png(png_bytes, filename)

            # 4. Slack 스레드에 파일 업로드
            slack.files_upload_v2(
                channel=channel_id,
                thread_ts=thread_ts,
                file=io.BytesIO(png_bytes),
                filename=filename,
                title=f"{row.template} | {row.main_copy}",
                initial_comment=f"✅ {row_label}\n📎 Drive: {drive_url}",
            )

            # 5. 시트 상태 업데이트 → 제작완료
            update_row_status(row.row_index, STATUS_DONE, drive_url)
            success_count += 1

        except Exception as e:
            log.error("행 %d 처리 실패: %s", row.row_index, e, exc_info=True)
            error_msg = f"{type(e).__name__}: {str(e)[:120]}"
            try:
                update_row_status(row.row_index, STATUS_FAIL, error_msg)
            except Exception as sheet_err:
                log.warning("시트 실패 상태 기록도 실패: %s", sheet_err)
            post(f"⚠️ {row_label}\n실패: {error_msg}")
            fail_count += 1

        # Slack rate limit 대응
        if idx < len(rows):
            time.sleep(ROW_DELAY_SEC)

    # 6. 완료 요약
    summary = f"🎉 소재 생성 완료 — 성공 *{success_count}개* / 실패 *{fail_count}개*"
    if fail_count > 0:
        summary += "\n실패 행은 시트 F열이 '실패'로 표시됩니다. 수정 후 '제작요청'으로 변경하면 재실행됩니다."
    post(summary)
    log.info("대량 생성 완료: 성공=%d 실패=%d", success_count, fail_count)
