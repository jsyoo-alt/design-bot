"""
누끼(배경 제거) 유틸리티

썸네일형 4종은 사각 크롭 유지, 나머지 이미지 있는 템플릿은 rembg 처리.
"""

import io
import base64
import logging

import requests
import rembg

log = logging.getLogger(__name__)

# 사각 크롭(썸네일) 유지 템플릿 — 이 외 템플릿은 rembg 적용
THUMBNAIL_TEMPLATES: frozenset[str] = frozenset({
    "thumbnail",
    "app_download_thumb",
    "text_highlight_thumb",
    "text_highlight_v2_thumb",
})


def needs_rembg(template_key: str) -> bool:
    """이 템플릿에 이미지가 들어갈 경우 누끼 처리가 필요한지 여부."""
    return template_key not in THUMBNAIL_TEMPLATES


def remove_bg(image_url: str, bot_token: str | None = None) -> bytes:
    """이미지 URL → rembg → 투명 PNG bytes 반환.

    Args:
        image_url: 공개 URL 또는 Slack private URL
        bot_token: Slack private URL일 때 Bearer 인증에 사용
    """
    headers: dict[str, str] = {}
    if bot_token and "slack.com" in image_url:
        headers["Authorization"] = f"Bearer {bot_token}"

    log.info("이미지 다운로드 중: %s", image_url[:80])
    resp = requests.get(image_url, headers=headers, timeout=15)
    resp.raise_for_status()

    log.info("rembg 처리 중 (%d bytes)...", len(resp.content))
    result: bytes = rembg.remove(resp.content)
    log.info("rembg 완료 → %d bytes", len(result))
    return result


def remove_bg_to_data_url(image_url: str, bot_token: str | None = None) -> str:
    """이미지 URL → rembg → base64 data URL 반환.

    HTML/Puppeteer 경로와 Pillow 경로 모두에서 사용.
    반환값은 `_download_image()` 및 render.js 의 <img src="..."> 에 직접 전달 가능.
    """
    png_bytes = remove_bg(image_url, bot_token)
    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def warmup() -> None:
    """서버 시작 시 rembg 모델을 미리 로드해 첫 요청 지연을 줄인다."""
    try:
        # 1×1 투명 PNG (최소 유효 PNG)
        minimal_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        rembg.remove(minimal_png)
        log.info("[STARTUP] rembg 모델 워밍업 완료")
    except Exception as exc:
        log.warning("[STARTUP] rembg 워밍업 실패 (첫 요청에서 로드됨): %s", exc)
