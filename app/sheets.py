"""
Google Sheets 연동 모듈 (v2)

시트 구조 (1행: 헤더):
  A: template      - 템플릿명
  B: main_copy     - 메인 카피 (비즈보드: 우측)
  C: sub_copy      - 서브 카피 (비즈보드: 우측)
  D: badge         - 뱃지 텍스트 (선택)
  E: object_url    - 오브젝트 PNG URL (선택)
  F: status        - 상태: 제작요청 / 제작완료 / 실패
  G: result_note   - 결과 메모 (봇 기입: Drive URL 또는 에러 메시지)
  H: main_copy_l   - 비즈보드 좌측 메인 카피 (비즈보드 전용, 나머지 템플릿은 비워둠)
  I: sub_copy_l    - 비즈보드 좌측 서브 카피 (비즈보드 전용, 나머지 템플릿은 비워둠)
"""

import json
import logging
from dataclasses import dataclass

import gspread
from google.oauth2.service_account import Credentials

from app.config import GOOGLE_SA_JSON, SHEET_ID

log = logging.getLogger(__name__)

# Google API 스코프
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 시트 컬럼 인덱스 (0-based)
COL_TEMPLATE    = 0  # A
COL_MAIN_COPY   = 1  # B
COL_SUB_COPY    = 2  # C
COL_BADGE       = 3  # D
COL_OBJECT_URL  = 4  # E
COL_STATUS      = 5  # F
COL_RESULT_NOTE = 6  # G
COL_MAIN_COPY_L = 7  # H (비즈보드 좌측 메인)
COL_SUB_COPY_L  = 8  # I (비즈보드 좌측 서브)

STATUS_REQUEST  = "제작요청"
STATUS_DONE     = "제작완료"
STATUS_FAIL     = "실패"

# 헤더 행 인덱스 (0-based, 실제 시트 1행)
HEADER_ROW = 0


@dataclass
class SheetRow:
    """시트 한 행을 표현하는 데이터 클래스."""
    row_index: int      # 시트 행 번호 (1-based, 헤더 포함)
    template: str
    main_copy: str      # 메인 카피 (비즈보드: 우측)
    sub_copy: str       # 서브 카피 (비즈보드: 우측)
    badge: str | None
    object_url: str | None
    status: str
    main_copy_l: str | None  # 비즈보드 좌측 메인 카피
    sub_copy_l: str | None   # 비즈보드 좌측 서브 카피


def _get_credentials() -> Credentials:
    """환경변수 GOOGLE_SA_JSON에서 서비스 계정 인증 생성."""
    if not GOOGLE_SA_JSON:
        raise RuntimeError(
            "GOOGLE_SA_JSON 환경변수가 비어 있습니다. "
            "Google 서비스 계정 JSON을 Railway 환경변수에 설정해 주세요."
        )
    info = json.loads(GOOGLE_SA_JSON)
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def _get_worksheet() -> gspread.Worksheet:
    """고정 스프레드시트의 첫 번째 시트 반환."""
    if not SHEET_ID:
        raise RuntimeError(
            "SHEET_ID 환경변수가 비어 있습니다. "
            "Railway 환경변수에 구글 스프레드시트 ID를 설정해 주세요."
        )
    creds = _get_credentials()
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).sheet1


def fetch_pending_rows() -> list[SheetRow]:
    """
    시트에서 status == '제작요청' 인 행만 읽어 반환.
    헤더 행(1행)은 건너뜀.
    """
    ws = _get_worksheet()
    all_rows = ws.get_all_values()

    pending: list[SheetRow] = []
    for i, row in enumerate(all_rows):
        if i == HEADER_ROW:
            continue  # 헤더 스킵

        # 컬럼 수 부족한 행 패딩 (I열까지)
        padded = row + [""] * (COL_SUB_COPY_L + 1 - len(row))

        status = padded[COL_STATUS].strip()
        if status != STATUS_REQUEST:
            continue

        template = padded[COL_TEMPLATE].strip()
        main_copy = padded[COL_MAIN_COPY].strip()
        sub_copy  = padded[COL_SUB_COPY].strip()

        if not template or not main_copy or not sub_copy:
            log.warning("행 %d: template/main_copy/sub_copy 중 빈 값 있음 — 스킵", i + 1)
            continue

        pending.append(SheetRow(
            row_index   = i + 1,   # 1-based (시트 실제 행번호)
            template    = template,
            main_copy   = main_copy,
            sub_copy    = sub_copy,
            badge       = padded[COL_BADGE].strip() or None,
            object_url  = padded[COL_OBJECT_URL].strip() or None,
            status      = status,
            main_copy_l = padded[COL_MAIN_COPY_L].strip() or None,
            sub_copy_l  = padded[COL_SUB_COPY_L].strip() or None,
        ))

    log.info("제작요청 행 %d개 발견", len(pending))
    return pending


def update_row_status(row_index: int, status: str, note: str = "") -> None:
    """
    시트의 특정 행 status(F열)와 result_note(G열)를 업데이트.

    Args:
        row_index: 1-based 시트 행번호
        status:    STATUS_DONE 또는 STATUS_FAIL
        note:      Drive 공유 URL 또는 에러 메시지
    """
    ws = _get_worksheet()
    # gspread는 1-based row, 1-based col
    status_cell = gspread.utils.rowcol_to_a1(row_index, COL_STATUS + 1)
    note_cell   = gspread.utils.rowcol_to_a1(row_index, COL_RESULT_NOTE + 1)
    ws.update(status_cell, [[status]])
    ws.update(note_cell,   [[note]])
    log.info("행 %d 업데이트: %s | %s", row_index, status, note[:60])


def count_pending() -> int:
    """제작요청 상태인 행 수 반환 (모달 미리보기용)."""
    try:
        return len(fetch_pending_rows())
    except Exception as e:
        log.warning("제작요청 카운트 실패: %s", e)
        return -1
