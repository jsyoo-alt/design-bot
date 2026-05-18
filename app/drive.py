"""
Google Drive 업로드 모듈 (v2)

생성된 소재 PNG를 지정 폴더에 업로드하고 공유 가능한 URL을 반환.
"""

import io
import json
import logging

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from app.config import GOOGLE_SA_JSON, DRIVE_FOLDER_ID

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

MIME_PNG = "image/png"

# Google Drive URL에서 파일 ID를 추출하는 패턴
import re
_DRIVE_ID_PATTERNS = [
    re.compile(r"/file/d/([a-zA-Z0-9_-]+)"),   # /file/d/{ID}/view
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"),     # ?id={ID} or &id={ID}
]


def extract_drive_file_id(url: str) -> str | None:
    """Google Drive URL에서 파일 ID 추출. Drive URL이 아니면 None."""
    for pattern in _DRIVE_ID_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def _get_drive_service():
    """Google Drive API 서비스 객체 반환."""
    if not GOOGLE_SA_JSON:
        raise RuntimeError(
            "GOOGLE_SA_JSON 환경변수가 비어 있습니다."
        )
    info = json.loads(GOOGLE_SA_JSON)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def download_file(file_id: str) -> bytes:
    """
    서비스 계정 인증으로 Google Drive 파일 다운로드.

    Args:
        file_id: Drive 파일 ID

    Returns:
        파일 바이트
    """
    service = _get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    from googleapiclient.http import MediaIoBaseDownload
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    log.info("Drive 파일 다운로드 완료: id=%s (%d bytes)", file_id, buf.tell())
    return buf.getvalue()


def upload_png(
    png_bytes: bytes,
    filename: str,
    folder_id: str | None = None,
) -> str:
    """
    PNG bytes를 Google Drive에 업로드하고 공유 URL 반환.

    Args:
        png_bytes: 업로드할 PNG 데이터
        filename:  저장 파일명 (확장자 포함, 예: "레드윙_기본형.png")
        folder_id: 업로드 대상 폴더 ID. None이면 DRIVE_FOLDER_ID 사용

    Returns:
        "anyone" 공유 링크 URL (https://drive.google.com/file/d/{id}/view)
    """
    target_folder = folder_id or DRIVE_FOLDER_ID
    if not target_folder:
        raise RuntimeError(
            "DRIVE_FOLDER_ID 환경변수가 비어 있습니다. "
            "Railway 환경변수에 Drive 폴더 ID를 설정해 주세요."
        )

    service = _get_drive_service()

    # 파일 메타데이터
    file_metadata: dict = {"name": filename}
    if target_folder:
        file_metadata["parents"] = [target_folder]

    # 업로드
    media = MediaIoBaseUpload(io.BytesIO(png_bytes), mimetype=MIME_PNG, resumable=False)
    file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id")
        .execute()
    )
    file_id = file.get("id")
    log.info("Drive 업로드 완료: %s → id=%s", filename, file_id)

    # 링크 공유 권한 설정 (anyone with link can view)
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    url = f"https://drive.google.com/file/d/{file_id}/view"
    log.info("Drive 공유 URL: %s", url)
    return url
