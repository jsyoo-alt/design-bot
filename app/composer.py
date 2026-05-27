"""
카카오 비즈보드 소재 합성 모듈
가이드 기준: 비즈보드 PSD 완화 제작 가이드 v2025.07.09
"""

import os
import io
import json
import logging
import subprocess
import requests
from PIL import Image, ImageDraw, ImageFont
from app.config import BACKGROUNDS_DIR, FONTS_DIR

log = logging.getLogger(__name__)

# 카카오 비즈보드 공식 스펙
CANVAS_SIZE = (1029, 258)

# Pretendard 폰트 경로 (카카오 완화 가이드 v2025.07.09 기준)
FONT_BOLD = os.path.join(FONTS_DIR, "Pretendard-Bold.ttf")
FONT_REGULAR = os.path.join(FONTS_DIR, "Pretendard-Regular.ttf")

# pt → px 변환 (72dpi 기준, 1pt = 1px)
def pt_to_px(pt: float) -> int:
    return round(pt)

# 공식 스펙 텍스트 크기 (pt → px)
MAIN_COPY_SIZE = pt_to_px(48)   # 48px
SUB_COPY_SIZE  = pt_to_px(39)   # 39px
BADGE_SIZE_1   = pt_to_px(30)   # 30px (한 줄)
BADGE_SIZE_2   = pt_to_px(25)   # 25px (두 줄)

# 공식 스펙 색상
COLOR_MAIN = "#4C4C4C"
COLOR_SUB  = "#777777"
COLOR_BADGE_TEXT = "#FFFFFF"

# 오브제 이미지 영역 (오브젝트형)
# 완화 가이드 최대값은 438px이나, 텍스트 가독성 확보를 위해 기존 315px 유지
OBJECT_AREA_W = 315
OBJECT_AREA_H = 258
# 비즈보드 전용 오브젝트 폭: 중앙 배치 + 좌우 텍스트 균형을 위해 별도 상수로 관리
# (장래 비즈보드 오브젝트 크기만 조정할 때 OBJECT_AREA_W에 영향 없이 변경 가능)
BIZBOARD_OBJECT_W = 315

# 썸네일 박스형 영역
THUMBNAIL_W = 315
THUMBNAIL_H = 186
THUMBNAIL_RADIUS = 8

# 로고 고정영역 (썸네일 우상단)
LOGO_PATH = os.path.join(BACKGROUNDS_DIR, "logo.png")
LOGO_MAX_W = 120
LOGO_MAX_H = 46
LOGO_MARGIN = 8
LOGO_Y = 20  # 배너 상단 로고 Y 위치
LOGO_SAFE_Y = LOGO_Y + LOGO_MAX_H + 8  # 74px: 로고와 겹치지 않는 오브젝트 배치 시작 Y

# 신규 썸네일 영역 스펙 (피그마 실측)
THUMB_FRAME_X = 652
THUMB_FRAME_Y = 36
THUMB_FRAME_W = 308
THUMB_FRAME_H = 186
THUMB_FRAME_R = 12

# 앱 바 스펙 (앱다운로드형)
APP_BAR_PATH   = os.path.join(BACKGROUNDS_DIR, "app_bar.png")
APP_BAR_X      = 49
APP_BAR_Y      = 43
APP_CONTENT_Y  = 90   # 앱 바 하단 이후 텍스트 배치 기준 Y

# 인라인 배지 스펙 (텍스트강조형)
INLINE_BADGE_W   = 77
INLINE_BADGE_H   = 42
INLINE_BADGE_R   = 8
INLINE_BADGE_GAP = 14
INLINE_BADGE_COL = "#FF6600"

# 좌측 텍스트 기준 X (PSD 가이드 실측)
TEXT_L_X = 48

# Main-Sub 텍스트 행간 간격
# 완화 가이드 PSD 실측 (01_기본형): Main bottom=123, Sub top=146 → 23px
MAIN_SUB_GAP = 23
BIZBOARD_MAIN_SUB_GAP = 23  # 비즈보드도 동일 PSD 기준 적용
# 우측 로고 기준 (캔버스 우측에서 52px 여백)
LOGO_RIGHT_MARGIN = 52

# 레이아웃 공통 규칙
MARGIN       = 48   # 양쪽 끝 투명 공백
OBJ_GAP      = 33   # 카피-오브젝트 최소 간격 (우측 정렬형)
OBJ_GAP_LEFT = 50   # 카피-오브젝트 최소 간격 (좌측 정렬형, 가이드 50px)
OBJ_MIN_W    = 219  # 오브젝트 실제 가로 최소 권장값 (가이드 Safe Zone)
TEXT_MIN_W   = 290  # 두 줄 중 최소 한 줄은 이 이상이어야 함 (가이드)
TEXT_MAX_W   = 585  # 텍스트 최대 길이


# ─────────────────────────────────────────────
# 누끼 제거 + 품질 체크
# ─────────────────────────────────────────────
def _is_removal_successful(img: Image.Image) -> bool:
    """
    알파채널 픽셀 비율로 배경 제거 품질 판단.
    투명 픽셀(alpha < 128)이 전체의 10~90% 범위일 때 성공으로 판단.
    - 10% 미만: 배경이 거의 안 지워진 경우
    - 90% 초과: 상품까지 같이 지워진 경우
    """
    if img.mode != "RGBA":
        return False
    import numpy as np
    alpha = np.array(img)[:, :, 3]
    total = alpha.size
    transparent = int(np.sum(alpha < 128))
    ratio = transparent / total
    return 0.10 <= ratio <= 0.90


def try_remove_background(img: Image.Image, timeout: int = 30) -> tuple[Image.Image, bool]:
    """
    rembg로 배경 제거 시도.
    성공 여부를 함께 반환: (결과 이미지, 성공 여부)
    실패하거나 timeout 초 초과하면 원본 이미지와 False 반환.
    """
    import concurrent.futures
    try:
        import numpy as np
        from rembg import remove as rembg_remove  # 무거운 import를 실제 사용 시점에만 로드

        buf_in = io.BytesIO()
        img.save(buf_in, format="PNG")
        data = buf_in.getvalue()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(rembg_remove, data)
            result_bytes = future.result(timeout=timeout)

        result = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
        if _is_removal_successful(result):
            return result, True
        return img, False
    except Exception:
        return img, False


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    if not os.path.exists(path):
        raise FileNotFoundError(f"폰트 파일 없음: {path} — assets/fonts/ 폴더에 파일을 넣고 git push 하세요.")
    return ImageFont.truetype(path, size)


def _download_image(url: str) -> Image.Image:
    # base64 data URL 지원 (rembg 전처리 결과물 수신용)
    if url.startswith("data:"):
        import base64
        _, encoded = url.split(",", 1)
        return Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGBA")

    headers: dict[str, str] = {}
    if "slack.com" in url:
        token = os.environ.get("SLACK_BOT_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, timeout=10, headers=headers)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type or not resp.content:
        raise ValueError(
            f"이미지 다운로드 실패 — Slack files:read 스코프가 없거나 URL이 유효하지 않습니다. "
            f"(Content-Type: {content_type}, URL: {url[:80]})"
        )
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


def _fit_image(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """박스 크기에 맞게 비율 유지하며 리사이즈 (cover)"""
    img_ratio = img.width / img.height
    box_ratio = box_w / box_h
    if img_ratio > box_ratio:
        new_h = box_h
        new_w = round(img_ratio * box_h)
    else:
        new_w = box_w
        new_h = round(box_w / img_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - box_w) // 2
    top = (new_h - box_h) // 2
    return img.crop((left, top, left + box_w, top + box_h))


def _paste_with_alpha(base: Image.Image, overlay: Image.Image, pos: tuple):
    if overlay.mode != "RGBA":
        overlay = overlay.convert("RGBA")
    base.paste(overlay, pos, overlay)


def _draw_text_centered(draw, text, font, color, canvas_w, y, x_start=0, x_end=None):
    """지정 영역 내 텍스트 수평 중앙 정렬"""
    if x_end is None:
        x_end = canvas_w
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    x = x_start + (x_end - x_start - text_w) // 2
    draw.text((x, y), text, font=font, fill=color)


def _draw_text_left(draw, text, font, color, x, y):
    draw.text((x, y), text, font=font, fill=color)


def _draw_text_right(draw, text, font, color, x_end, y):
    """텍스트를 x_end 기준 우측 정렬"""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    draw.text((x_end - text_w, y), text, font=font, fill=color)


def _fit_object_image(
    img: Image.Image,
    area_w: int = OBJECT_AREA_W,
    area_h: int = OBJECT_AREA_H,
    min_w: int = OBJ_MIN_W,
) -> Image.Image:
    """오브젝트형 이미지 리사이즈.

    규칙:
    - 박스(area_w × area_h) 안에 contain-fit (좌우 크롭 금지)
    - 결과 width < min_w 이면 min_w 기준으로 스케일 업 (세로 중앙 크롭 허용)
    """
    orig_w, orig_h = img.width, img.height

    # 1단계: contain fit — 전체가 박스 안에 들어오도록
    scale = min(area_w / orig_w, area_h / orig_h)
    new_w = round(orig_w * scale)
    new_h = round(orig_h * scale)

    # 2단계: width 가 min_w 미만이면 min_w 기준으로 스케일 업
    if new_w < min_w:
        scale = min_w / orig_w
        new_w = min_w
        new_h = round(orig_h * scale)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # 3단계: height 가 area_h 초과하면 상하 중앙 크롭
    if img.height > area_h:
        top = (img.height - area_h) // 2
        img = img.crop((0, top, img.width, top + area_h))

    return img


def _paste_object_image(
    canvas: Image.Image,
    img: Image.Image,
    area_x: int,
    area_y: int = 0,
) -> None:
    """오브젝트형(투명 PNG) 이미지를 캔버스에 배치.

    area_x: 오브젝트 영역 시작 X (폭 OBJECT_AREA_W)
    area_y: 오브젝트 배치 시작 Y (기본 0 = 캔버스 전체).
            로고 safe zone 확보 시 LOGO_SAFE_Y(74) 전달.
    - _fit_object_image() 로 최소 219px 보장
    - 영역 내 수평 중앙 + 지정 구간 세로 중앙 정렬
    """
    area_h = CANVAS_SIZE[1] - area_y
    fitted = _fit_object_image(img, area_h=area_h)
    x = area_x + (OBJECT_AREA_W - fitted.width) // 2
    y = area_y + (area_h - fitted.height) // 2
    _paste_with_alpha(canvas, fitted, (x, y))


def _check_text_min_width(
    draw: ImageDraw.ImageDraw,
    title: str,
    sub: str,
    font_m: ImageFont.FreeTypeFont,
    font_s: ImageFont.FreeTypeFont,
) -> None:
    """텍스트 최소 길이(290px) 가이드 미달 시 경고 로그."""
    main_w = draw.textlength(title, font=font_m)
    sub_w  = draw.textlength(sub,   font=font_s)
    if max(main_w, sub_w) < TEXT_MIN_W:
        log.warning(
            "텍스트 길이 가이드 미달 (최소 %dpx): main=%.0fpx '%s', sub=%.0fpx '%s'",
            TEXT_MIN_W, main_w, title, sub_w, sub,
        )


def _has_transparency(img: Image.Image, threshold: float = 0.05) -> bool:
    """투명 픽셀(alpha < 128)이 threshold 비율 이상이면 누끼 이미지로 판단"""
    if img.mode != "RGBA":
        return False
    alpha_data = img.getdata(band=3)
    transparent = sum(1 for a in alpha_data if a < 128)
    return transparent / len(alpha_data) >= threshold


def _paste_logo_on_thumbnail(canvas: Image.Image, thumb_x: int, thumb_y: int):
    """썸네일 박스 우상단에 로고 합성 (120x46 영역 내 contain fit, 여백 8px)"""
    if not os.path.exists(LOGO_PATH):
        return
    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo.thumbnail((LOGO_MAX_W, LOGO_MAX_H), Image.LANCZOS)
    x = thumb_x + THUMBNAIL_W - LOGO_MARGIN - logo.width
    y = thumb_y + LOGO_MARGIN
    _paste_with_alpha(canvas, logo, (x, y))


def _round_corners(img: Image.Image, radius: int) -> Image.Image:
    """이미지에 둥근 모서리 마스크 적용"""
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width, img.height], radius=radius, fill=255)
    img.putalpha(mask)
    return img


def _truncate_text(draw, text: str, font, max_width: int) -> str:
    """텍스트가 max_width를 초과하면 '...'을 붙여 잘라냄"""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "...", font=font) > max_width:
        text = text[:-1]
    return text + "..."


# ─────────────────────────────────────────────
# 1. 비즈보드 (좌우 분리형)
#    좌: sub_L + title_L  /  우: sub_R + title_R + 오브제 이미지
# ─────────────────────────────────────────────
def compose_bizboard(
    title_l: str,
    sub_l: str,
    title_r: str,
    sub_r: str,
    object_image_url: str | None = None,
) -> bytes:
    bg_path = os.path.join(BACKGROUNDS_DIR, "bg_bizboard.png")
    canvas = Image.open(bg_path).convert("RGBA").resize(CANVAS_SIZE)

    draw = ImageDraw.Draw(canvas)
    font_main = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_sub  = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    # 이미지 중앙 배치: 캔버스 정중앙 기준 (비즈보드는 BIZBOARD_OBJECT_W=315 고정)
    OBJ_X = (CANVAS_SIZE[0] - BIZBOARD_OBJECT_W) // 2  # (1029 - 315) // 2 = 357
    OBJ_X_END = OBJ_X + BIZBOARD_OBJECT_W              # 357 + 315 = 672

    # 좌측 텍스트: MARGIN(48) ~ 이미지 시작 - OBJ_GAP(33)
    LEFT_PADDING = MARGIN  # 48
    LEFT_TEXT_END = OBJ_X - OBJ_GAP                # 357 - 33 = 324
    left_max_w = LEFT_TEXT_END - LEFT_PADDING       # 324 - 48 = 276
    title_l = _truncate_text(draw, title_l, font_main, left_max_w)
    sub_l = _truncate_text(draw, sub_l, font_sub, left_max_w)

    title_bbox = draw.textbbox((0, 0), title_l, font=font_main)
    sub_bbox = draw.textbbox((0, 0), sub_l, font=font_sub)
    block_h = (title_bbox[3] - title_bbox[1]) + BIZBOARD_MAIN_SUB_GAP + (sub_bbox[3] - sub_bbox[1])
    y_start = (CANVAS_SIZE[1] - block_h) // 2

    # 좌측 텍스트: 오브젝트 쪽(LEFT_TEXT_END)에 붙여 우측 정렬
    _draw_text_right(draw, title_l, font_main, COLOR_MAIN, LEFT_TEXT_END, y_start)
    _draw_text_right(draw, sub_l, font_sub, COLOR_SUB, LEFT_TEXT_END, y_start + (title_bbox[3] - title_bbox[1]) + BIZBOARD_MAIN_SUB_GAP)

    # 우측 텍스트: 이미지 끝 + OBJ_GAP(33) ~ CANVAS - MARGIN(48)
    RIGHT_TEXT_START = OBJ_X_END + OBJ_GAP         # 672 + 33 = 705
    RIGHT_TEXT_END = CANVAS_SIZE[0] - MARGIN        # 1029 - 48 = 981
    right_max_w = RIGHT_TEXT_END - RIGHT_TEXT_START # 981 - 705 = 276
    title_r_t = _truncate_text(draw, title_r, font_main, right_max_w)
    sub_r_t = _truncate_text(draw, sub_r, font_sub, right_max_w)

    title_bbox_r = draw.textbbox((0, 0), title_r_t, font=font_main)
    sub_bbox_r = draw.textbbox((0, 0), sub_r_t, font=font_sub)
    block_h_r = (title_bbox_r[3] - title_bbox_r[1]) + BIZBOARD_MAIN_SUB_GAP + (sub_bbox_r[3] - sub_bbox_r[1])
    y_start_r = (CANVAS_SIZE[1] - block_h_r) // 2

    # 우측 텍스트: 오브젝트 쪽(RIGHT_TEXT_START)에 붙여 좌측 정렬
    _draw_text_left(draw, title_r_t, font_main, COLOR_MAIN, RIGHT_TEXT_START, y_start_r)
    _draw_text_left(draw, sub_r_t, font_sub, COLOR_SUB, RIGHT_TEXT_START, y_start_r + (title_bbox_r[3] - title_bbox_r[1]) + BIZBOARD_MAIN_SUB_GAP)

    # 오브제 이미지 — 캔버스 정중앙, 세로 중앙
    if object_image_url:
        obj_img = _download_image(object_image_url)
        if _has_transparency(obj_img):
            _paste_object_image(canvas, obj_img, OBJ_X)
        else:
            # 일반 이미지 → 썸네일 박스형 (315x186, 둥근 모서리, 세로 중앙)
            obj_img = _fit_image(obj_img, BIZBOARD_OBJECT_W, THUMBNAIL_H)
            obj_img = _round_corners(obj_img, THUMBNAIL_RADIUS)
            x = OBJ_X
            y = (CANVAS_SIZE[1] - THUMBNAIL_H) // 2
            _paste_with_alpha(canvas, obj_img, (x, y))

    _check_text_min_width(draw, title_l, sub_l, font_main, font_sub)
    _check_text_min_width(draw, title_r_t, sub_r_t, font_main, font_sub)
    return _export(canvas)


# ─────────────────────────────────────────────
# 2. 기본_2줄형
#    중앙 카피 (title + sub) + 배경 이미지 (전체)
# ─────────────────────────────────────────────
def compose_basic_2line(
    title: str,
    sub: str,
    object_image_url: str | None = None,
    badge_text: str | None = None,
) -> bytes:
    bg_path = os.path.join(BACKGROUNDS_DIR, "bg_basic_2line.png")
    canvas = Image.open(bg_path).convert("RGBA").resize(CANVAS_SIZE)

    # 오브제 이미지 (우측 MARGIN 여백 확보) — 로고 safe zone(y=74~) 내 배치
    OBJ_X = CANVAS_SIZE[0] - OBJECT_AREA_W - MARGIN  # 1029 - 315 - 48 = 666
    _SAFE_THUMB_H = CANVAS_SIZE[1] - LOGO_SAFE_Y     # 184px (로고 아래 가용 높이)
    if object_image_url:
        obj_img = _download_image(object_image_url)
        if _has_transparency(obj_img):
            _paste_object_image(canvas, obj_img, OBJ_X, area_y=LOGO_SAFE_Y)
        else:
            # 일반 이미지 → 썸네일 박스형 (315×184, 둥근 모서리, safe zone 내 세로 중앙)
            obj_img = _fit_image(obj_img, THUMBNAIL_W, _SAFE_THUMB_H)
            obj_img = _round_corners(obj_img, THUMBNAIL_RADIUS)
            x = OBJ_X
            y = LOGO_SAFE_Y + (_SAFE_THUMB_H - obj_img.height) // 2
            _paste_with_alpha(canvas, obj_img, (x, y))
            _paste_logo_on_thumbnail(canvas, x, y)

    # 로고: 우측 상단 고정 (이미지 위에 렌더링되도록 이미지 paste 이후 호출)
    _paste_banner_logo(canvas, right=True)

    draw = ImageDraw.Draw(canvas)
    font_main = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_sub  = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    TEXT_X = TEXT_L_X  # 48px (PSD 가이드 기준)
    text_max_w = (OBJ_X - OBJ_GAP - TEXT_X) if object_image_url else (CANVAS_SIZE[0] - MARGIN - TEXT_X)
    title = _truncate_text(draw, title, font_main, text_max_w)
    sub = _truncate_text(draw, sub, font_sub, text_max_w)

    title_bbox = draw.textbbox((0, 0), title, font=font_main)
    sub_bbox = draw.textbbox((0, 0), sub, font=font_sub)
    block_h = (title_bbox[3] - title_bbox[1]) + MAIN_SUB_GAP + (sub_bbox[3] - sub_bbox[1])
    y_start = (CANVAS_SIZE[1] - block_h) // 2

    _draw_text_left(draw, title, font_main, COLOR_MAIN, TEXT_X, y_start)
    _draw_text_left(draw, sub, font_sub, COLOR_SUB, TEXT_X, y_start + (title_bbox[3] - title_bbox[1]) + MAIN_SUB_GAP)

    if badge_text:
        _draw_badge(draw, badge_text, canvas)

    _check_text_min_width(draw, title, sub, font_main, font_sub)
    return _export(canvas)


# ─────────────────────────────────────────────
# 3. 기본_2줄형_좌측 오브제
#    좌측 오브제 이미지 + 우측 카피 (title + sub)
# ─────────────────────────────────────────────
def compose_basic_2line_left_obj(
    title: str,
    sub: str,
    object_image_url: str | None = None,
    badge_text: str | None = None,
) -> bytes:
    bg_path = os.path.join(BACKGROUNDS_DIR, "bg_basic_2line_left.png")
    canvas = Image.open(bg_path).convert("RGBA").resize(CANVAS_SIZE)

    # 좌측 오브제 이미지 — 로고 safe zone(y=74~) 내 배치
    OBJ_LEFT = MARGIN  # 48px
    _SAFE_THUMB_H = CANVAS_SIZE[1] - LOGO_SAFE_Y  # 184px (로고 아래 가용 높이)
    if object_image_url:
        obj_img = _download_image(object_image_url)
        if _has_transparency(obj_img):
            _paste_object_image(canvas, obj_img, OBJ_LEFT, area_y=LOGO_SAFE_Y)
        else:
            # 일반 이미지 → 썸네일 박스형 (315×184, 둥근 모서리, safe zone 내 세로 중앙)
            obj_img = _fit_image(obj_img, THUMBNAIL_W, _SAFE_THUMB_H)
            obj_img = _round_corners(obj_img, THUMBNAIL_RADIUS)
            x = OBJ_LEFT
            y = LOGO_SAFE_Y + (_SAFE_THUMB_H - obj_img.height) // 2
            _paste_with_alpha(canvas, obj_img, (x, y))
            _paste_logo_on_thumbnail(canvas, x, y)

    # 로고: 좌측 상단 고정 (비즈보드와 동일 위치, 이미지 paste 이후 호출)
    _paste_banner_logo(canvas, right=False)

    draw = ImageDraw.Draw(canvas)
    font_main = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_sub  = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    # 우측 텍스트: 이미지 우측 끝 + OBJ_GAP_LEFT(50px, 좌측형 가이드), 우측도 MARGIN(48) 확보
    TEXT_X = OBJ_LEFT + OBJECT_AREA_W + OBJ_GAP_LEFT  # 48 + 315 + 50 = 413
    text_max_w = CANVAS_SIZE[0] - MARGIN - TEXT_X      # 1029 - 48 - 413 = 568
    title = _truncate_text(draw, title, font_main, text_max_w)
    sub = _truncate_text(draw, sub, font_sub, text_max_w)

    title_bbox = draw.textbbox((0, 0), title, font=font_main)
    sub_bbox = draw.textbbox((0, 0), sub, font=font_sub)
    block_h = (title_bbox[3] - title_bbox[1]) + MAIN_SUB_GAP + (sub_bbox[3] - sub_bbox[1])
    y_start = (CANVAS_SIZE[1] - block_h) // 2

    _draw_text_left(draw, title, font_main, COLOR_MAIN, TEXT_X, y_start)
    _draw_text_left(draw, sub, font_sub, COLOR_SUB, TEXT_X, y_start + (title_bbox[3] - title_bbox[1]) + MAIN_SUB_GAP)

    if badge_text:
        _draw_badge(draw, badge_text, canvas)

    _check_text_min_width(draw, title, sub, font_main, font_sub)
    return _export(canvas)


# ─────────────────────────────────────────────
# 뱃지 그리기 (Flag-type, 우측 하단)
# ─────────────────────────────────────────────
BADGE_COLORS = {
    "red":    "#FF3B30",
    "orange": "#FF9500",
    "pink":   "#FF2D55",
    "blue":   "#007AFF",
    "green":  "#34C759",
    "purple": "#AF52DE",
    "black":  "#1C1C1E",
}

def _draw_badge(draw: ImageDraw.Draw, text: str, canvas: Image.Image, color: str = "red"):
    lines = text.split("\n")
    font_size = BADGE_SIZE_1 if len(lines) == 1 else BADGE_SIZE_2
    font = _load_font(FONT_BOLD, font_size)

    bg_color = BADGE_COLORS.get(color, BADGE_COLORS["red"])
    padding_x, padding_y = 12, 8

    line_heights = [(draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1]) for l in lines]
    max_w = max(draw.textbbox((0, 0), l, font=font)[2] - draw.textbbox((0, 0), l, font=font)[0] for l in lines)
    total_h = sum(line_heights) + (len(lines) - 1) * 4

    badge_w = max_w + padding_x * 2
    badge_h = total_h + padding_y * 2
    badge_x = canvas.width - badge_w - 10
    badge_y = canvas.height - badge_h - 10

    draw.rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], fill=bg_color)

    y_cursor = badge_y + padding_y
    for i, line in enumerate(lines):
        lw = draw.textbbox((0, 0), line, font=font)[2] - draw.textbbox((0, 0), line, font=font)[0]
        draw.text((badge_x + (badge_w - lw) // 2, y_cursor), line, font=font, fill=COLOR_BADGE_TEXT)
        y_cursor += line_heights[i] + 4


def _export(canvas: Image.Image) -> bytes:
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    size_kb = len(data) / 1024
    if size_kb > 300:
        log.warning("소재 PNG 용량 초과: %.1fKB (가이드 최대 300KB)", size_kb)
    return data


# ─────────────────────────────────────────────
# 신규 헬퍼 함수
# ─────────────────────────────────────────────

def _paste_banner_logo(canvas: Image.Image, right: bool = False):
    """배너 상단 좌측(기본) 또는 우측에 29CM 로고 배치"""
    if not os.path.exists(LOGO_PATH):
        return
    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo.thumbnail((LOGO_MAX_W, LOGO_MAX_H), Image.LANCZOS)
    x = (CANVAS_SIZE[0] - LOGO_RIGHT_MARGIN - logo.width) if right else TEXT_L_X
    _paste_with_alpha(canvas, logo, (x, LOGO_Y))


def _paste_thumb_area(canvas: Image.Image, img: Image.Image,
                      x: int, y: int, w: int, h: int):
    """지정 영역에 상품 이미지 배치 (누끼/일반 자동 분기, 로고 미포함)"""
    if _has_transparency(img):
        img = img.copy()  # thumbnail()은 in-place 변경 → 원본 보호
        img.thumbnail((w, h), Image.LANCZOS)
        px = x + (w - img.width) // 2
        py = y + (h - img.height) // 2
        _paste_with_alpha(canvas, img, (px, py))
    else:
        fitted = _fit_image(img, w, h)
        fitted = _round_corners(fitted, THUMB_FRAME_R)
        _paste_with_alpha(canvas, fitted, (x, y))


def _text_block_y(
    draw: ImageDraw.ImageDraw,
    main: str, sub: str,
    font_m: ImageFont.FreeTypeFont,
    font_s: ImageFont.FreeTypeFont,
    y_min: int = 0,
) -> tuple[int, int]:
    """(main_y, sub_y): y_min 아래 구간에서 텍스트 블록 세로 중앙 정렬"""
    m_h = draw.textbbox((0, 0), main, font=font_m)[3] - draw.textbbox((0, 0), main, font=font_m)[1]
    s_h = draw.textbbox((0, 0), sub,  font=font_s)[3] - draw.textbbox((0, 0), sub,  font=font_s)[1]
    block_h = m_h + MAIN_SUB_GAP + s_h
    y_start = y_min + (CANVAS_SIZE[1] - y_min - block_h) // 2
    return y_start, y_start + m_h + MAIN_SUB_GAP


def _draw_inline_badge_line(
    draw: ImageDraw.ImageDraw,
    badge_text: str | None,
    sub: str,
    font_b: ImageFont.FreeTypeFont,
    font_s: ImageFont.FreeTypeFont,
    text_x: int,
    line_y: int,
    pill: bool = True,
):
    """인라인 배지(pill 또는 컬러 텍스트) + 서브 카피 한 줄 렌더링
    pill=True  → 오렌지 pill 안에 badge_text, 우측에 sub_copy
    pill=False → badge_text를 오렌지 plain 텍스트로, 이어서 sub_copy
    """
    if not badge_text:
        draw.text((text_x, line_y), sub, font=font_s, fill=COLOR_SUB)
        return

    if pill:
        draw.rounded_rectangle(
            [text_x, line_y, text_x + INLINE_BADGE_W, line_y + INLINE_BADGE_H],
            radius=INLINE_BADGE_R,
            fill=INLINE_BADGE_COL,
        )
        b_bbox = draw.textbbox((0, 0), badge_text, font=font_b)
        b_w = b_bbox[2] - b_bbox[0]
        b_h = b_bbox[3] - b_bbox[1]
        bx = text_x + (INLINE_BADGE_W - b_w) // 2
        by = line_y + (INLINE_BADGE_H - b_h) // 2
        draw.text((bx, by), badge_text, font=font_b, fill=COLOR_BADGE_TEXT)

        sub_x = text_x + INLINE_BADGE_W + INLINE_BADGE_GAP
        s_h = draw.textbbox((0, 0), sub, font=font_s)[3] - draw.textbbox((0, 0), sub, font=font_s)[1]
        sub_y = line_y + (INLINE_BADGE_H - s_h) // 2
        draw.text((sub_x, sub_y), sub, font=font_s, fill=COLOR_SUB)
    else:
        b_w = int(draw.textlength(badge_text + " ", font=font_s))
        draw.text((text_x, line_y), badge_text, font=font_s, fill=INLINE_BADGE_COL)
        draw.text((text_x + b_w, line_y), sub, font=font_s, fill=COLOR_SUB)


# ─────────────────────────────────────────────
# 4. 썸네일형
#    로고(좌상단) + 좌측 카피 + 우측 썸네일 이미지
# ─────────────────────────────────────────────
def compose_thumbnail(
    title: str,
    sub: str,
    object_image_url: str | None = None,
) -> bytes:
    canvas = Image.open(os.path.join(BACKGROUNDS_DIR, "bg_basic_2line.png")).convert("RGBA").resize(CANVAS_SIZE)

    _paste_banner_logo(canvas)

    if object_image_url:
        obj_img = _download_image(object_image_url)
        _paste_thumb_area(canvas, obj_img, THUMB_FRAME_X, THUMB_FRAME_Y, THUMB_FRAME_W, THUMB_FRAME_H)

    draw = ImageDraw.Draw(canvas)
    font_m = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_s = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    max_w = (THUMB_FRAME_X - OBJ_GAP - TEXT_L_X) if object_image_url else (CANVAS_SIZE[0] - MARGIN - TEXT_L_X)
    title = _truncate_text(draw, title, font_m, max_w)
    sub   = _truncate_text(draw, sub,   font_s, max_w)

    main_y, sub_y = _text_block_y(draw, title, sub, font_m, font_s)
    _draw_text_left(draw, title, font_m, COLOR_MAIN, TEXT_L_X, main_y)
    _draw_text_left(draw, sub,   font_s, COLOR_SUB,  TEXT_L_X, sub_y)

    return _export(canvas)


# ─────────────────────────────────────────────
# 5. 기본_2줄형_좌측 오브제+뱃지
#    로고(좌상단) + 좌측 오브제 + 우측 카피 + 코너 배지
# ─────────────────────────────────────────────
def compose_basic_2line_left_badge(
    title: str,
    sub: str,
    object_image_url: str | None = None,
    badge_text: str | None = None,
) -> bytes:
    canvas = Image.open(os.path.join(BACKGROUNDS_DIR, "bg_basic_2line_left.png")).convert("RGBA").resize(CANVAS_SIZE)

    _paste_banner_logo(canvas)

    OBJ_LEFT = MARGIN
    if object_image_url:
        obj_img = _download_image(object_image_url)
        if _has_transparency(obj_img):
            _paste_object_image(canvas, obj_img, OBJ_LEFT)
        else:
            obj_img = _fit_image(obj_img, THUMBNAIL_W, THUMBNAIL_H)
            obj_img = _round_corners(obj_img, THUMBNAIL_RADIUS)
            x, y = OBJ_LEFT, (CANVAS_SIZE[1] - THUMBNAIL_H) // 2
            _paste_with_alpha(canvas, obj_img, (x, y))

    draw = ImageDraw.Draw(canvas)
    font_m = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_s = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    TEXT_X     = OBJ_LEFT + OBJECT_AREA_W + OBJ_GAP_LEFT  # 48 + 315 + 50 = 413
    text_max_w = CANVAS_SIZE[0] - MARGIN - TEXT_X          # 1029 - 48 - 413 = 568
    title = _truncate_text(draw, title, font_m, text_max_w)
    sub   = _truncate_text(draw, sub,   font_s, text_max_w)

    main_y, sub_y = _text_block_y(draw, title, sub, font_m, font_s)
    _draw_text_left(draw, title, font_m, COLOR_MAIN, TEXT_X, main_y)
    _draw_text_left(draw, sub,   font_s, COLOR_SUB,  TEXT_X, sub_y)

    if badge_text:
        _draw_badge(draw, badge_text, canvas)

    _check_text_min_width(draw, title, sub, font_m, font_s)
    return _export(canvas)


# ─────────────────────────────────────────────
# 6. 앱다운로드형
#    앱 바 + 카피 (이미지 없음)
# ─────────────────────────────────────────────
def compose_app_download(
    title: str,
    sub: str,
) -> bytes:
    canvas = Image.open(os.path.join(BACKGROUNDS_DIR, "bg_basic_2line.png")).convert("RGBA").resize(CANVAS_SIZE)

    if os.path.exists(APP_BAR_PATH):
        app_bar = Image.open(APP_BAR_PATH).convert("RGBA")
        _paste_with_alpha(canvas, app_bar, (APP_BAR_X, APP_BAR_Y))

    draw = ImageDraw.Draw(canvas)
    font_m = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_s = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    max_w = CANVAS_SIZE[0] - MARGIN * 2
    title = _truncate_text(draw, title, font_m, max_w)
    sub   = _truncate_text(draw, sub,   font_s, max_w)

    main_y, sub_y = _text_block_y(draw, title, sub, font_m, font_s, y_min=APP_CONTENT_Y)
    _draw_text_left(draw, title, font_m, COLOR_MAIN, MARGIN, main_y)
    _draw_text_left(draw, sub,   font_s, COLOR_SUB,  MARGIN, sub_y)

    return _export(canvas)


# ─────────────────────────────────────────────
# 7. 앱다운로드+썸네일형
#    앱 바 + 카피 + 우측 썸네일
# ─────────────────────────────────────────────
def compose_app_download_thumbnail(
    title: str,
    sub: str,
    object_image_url: str | None = None,
) -> bytes:
    canvas = Image.open(os.path.join(BACKGROUNDS_DIR, "bg_basic_2line.png")).convert("RGBA").resize(CANVAS_SIZE)

    if os.path.exists(APP_BAR_PATH):
        app_bar = Image.open(APP_BAR_PATH).convert("RGBA")
        _paste_with_alpha(canvas, app_bar, (APP_BAR_X, APP_BAR_Y))

    if object_image_url:
        obj_img = _download_image(object_image_url)
        _paste_thumb_area(canvas, obj_img, THUMB_FRAME_X, THUMB_FRAME_Y, THUMB_FRAME_W, THUMB_FRAME_H)

    draw = ImageDraw.Draw(canvas)
    font_m = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_s = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    max_w = (THUMB_FRAME_X - OBJ_GAP - MARGIN) if object_image_url else (CANVAS_SIZE[0] - MARGIN * 2)
    title = _truncate_text(draw, title, font_m, max_w)
    sub   = _truncate_text(draw, sub,   font_s, max_w)

    main_y, sub_y = _text_block_y(draw, title, sub, font_m, font_s, y_min=APP_CONTENT_Y)
    _draw_text_left(draw, title, font_m, COLOR_MAIN, MARGIN, main_y)
    _draw_text_left(draw, sub,   font_s, COLOR_SUB,  MARGIN, sub_y)

    return _export(canvas)


# ─────────────────────────────────────────────
# 8. 텍스트강조+썸네일형 (배지 pill)
#    로고(좌상단) + 메인 카피 + 오렌지 pill 배지 + 서브 카피 + 우측 썸네일
# ─────────────────────────────────────────────
def compose_text_highlight_thumbnail(
    title: str,
    sub: str,
    object_image_url: str | None = None,
    badge_text: str | None = None,
) -> bytes:
    canvas = Image.open(os.path.join(BACKGROUNDS_DIR, "bg_basic_2line.png")).convert("RGBA").resize(CANVAS_SIZE)

    _paste_banner_logo(canvas)

    if object_image_url:
        obj_img = _download_image(object_image_url)
        _paste_thumb_area(canvas, obj_img, THUMB_FRAME_X, THUMB_FRAME_Y, THUMB_FRAME_W, THUMB_FRAME_H)

    draw = ImageDraw.Draw(canvas)
    font_m = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_s = _load_font(FONT_REGULAR, SUB_COPY_SIZE)
    font_b = _load_font(FONT_BOLD, BADGE_SIZE_1)

    max_w_m = (THUMB_FRAME_X - OBJ_GAP - TEXT_L_X) if object_image_url else (CANVAS_SIZE[0] - MARGIN - TEXT_L_X)
    title = _truncate_text(draw, title, font_m, max_w_m)
    max_w_s = (max_w_m - INLINE_BADGE_W - INLINE_BADGE_GAP) if badge_text else max_w_m
    sub = _truncate_text(draw, sub, font_s, max_w_s)

    m_h = draw.textbbox((0, 0), title, font=font_m)[3] - draw.textbbox((0, 0), title, font=font_m)[1]
    badge_line_h = INLINE_BADGE_H if badge_text else (
        draw.textbbox((0, 0), sub, font=font_s)[3] - draw.textbbox((0, 0), sub, font=font_s)[1])
    block_h = m_h + MAIN_SUB_GAP + badge_line_h
    main_y  = (CANVAS_SIZE[1] - block_h) // 2
    badge_y = main_y + m_h + MAIN_SUB_GAP

    _draw_text_left(draw, title, font_m, COLOR_MAIN, TEXT_L_X, main_y)
    _draw_inline_badge_line(draw, badge_text, sub, font_b, font_s, TEXT_L_X, badge_y, pill=True)

    return _export(canvas)


# ─────────────────────────────────────────────
# 9. 텍스트강조형 (배지 pill, 이미지 없음)
#    로고(우상단) + 메인 카피 + 오렌지 pill 배지 + 서브 카피
# ─────────────────────────────────────────────
def compose_text_highlight(
    title: str,
    sub: str,
    badge_text: str | None = None,
) -> bytes:
    canvas = Image.open(os.path.join(BACKGROUNDS_DIR, "bg_basic_2line.png")).convert("RGBA").resize(CANVAS_SIZE)

    _paste_banner_logo(canvas, right=True)

    draw = ImageDraw.Draw(canvas)
    font_m = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_s = _load_font(FONT_REGULAR, SUB_COPY_SIZE)
    font_b = _load_font(FONT_BOLD, BADGE_SIZE_1)

    max_w = CANVAS_SIZE[0] - MARGIN - TEXT_L_X
    title = _truncate_text(draw, title, font_m, max_w)
    max_w_s = (max_w - INLINE_BADGE_W - INLINE_BADGE_GAP) if badge_text else max_w
    sub = _truncate_text(draw, sub, font_s, max_w_s)

    m_h = draw.textbbox((0, 0), title, font=font_m)[3] - draw.textbbox((0, 0), title, font=font_m)[1]
    badge_line_h = INLINE_BADGE_H if badge_text else (
        draw.textbbox((0, 0), sub, font=font_s)[3] - draw.textbbox((0, 0), sub, font=font_s)[1])
    block_h = m_h + MAIN_SUB_GAP + badge_line_h
    main_y  = (CANVAS_SIZE[1] - block_h) // 2
    badge_y = main_y + m_h + MAIN_SUB_GAP

    _draw_text_left(draw, title, font_m, COLOR_MAIN, TEXT_L_X, main_y)
    _draw_inline_badge_line(draw, badge_text, sub, font_b, font_s, TEXT_L_X, badge_y, pill=True)

    return _export(canvas)


# ─────────────────────────────────────────────
# 10. 텍스트강조+썸네일형 v2 (컬러 프리픽스)
#     로고(좌상단) + 메인 카피 + 오렌지 텍스트+서브 카피 + 우측 썸네일
# ─────────────────────────────────────────────
def compose_text_highlight_v2_thumbnail(
    title: str,
    sub: str,
    object_image_url: str | None = None,
    badge_text: str | None = None,
) -> bytes:
    canvas = Image.open(os.path.join(BACKGROUNDS_DIR, "bg_basic_2line.png")).convert("RGBA").resize(CANVAS_SIZE)

    _paste_banner_logo(canvas)

    if object_image_url:
        obj_img = _download_image(object_image_url)
        _paste_thumb_area(canvas, obj_img, THUMB_FRAME_X, THUMB_FRAME_Y, THUMB_FRAME_W, THUMB_FRAME_H)

    draw = ImageDraw.Draw(canvas)
    font_m = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_s = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    max_w = (THUMB_FRAME_X - OBJ_GAP - TEXT_L_X) if object_image_url else (CANVAS_SIZE[0] - MARGIN - TEXT_L_X)
    title = _truncate_text(draw, title, font_m, max_w)
    sub   = _truncate_text(draw, sub,   font_s, max_w)

    main_y, sub_y = _text_block_y(draw, title, sub, font_m, font_s)
    _draw_text_left(draw, title, font_m, COLOR_MAIN, TEXT_L_X, main_y)
    _draw_inline_badge_line(draw, badge_text, sub, font_s, font_s, TEXT_L_X, sub_y, pill=False)

    return _export(canvas)


# ─────────────────────────────────────────────
# 11. 텍스트강조형 v2 (컬러 프리픽스, 이미지 없음)
#     로고(우상단) + 메인 카피 + 오렌지 텍스트+서브 카피
# ─────────────────────────────────────────────
def compose_text_highlight_v2(
    title: str,
    sub: str,
    badge_text: str | None = None,
) -> bytes:
    canvas = Image.open(os.path.join(BACKGROUNDS_DIR, "bg_basic_2line.png")).convert("RGBA").resize(CANVAS_SIZE)

    _paste_banner_logo(canvas, right=True)

    draw = ImageDraw.Draw(canvas)
    font_m = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_s = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    max_w = CANVAS_SIZE[0] - MARGIN - TEXT_L_X
    title = _truncate_text(draw, title, font_m, max_w)
    sub   = _truncate_text(draw, sub,   font_s, max_w)

    main_y, sub_y = _text_block_y(draw, title, sub, font_m, font_s)
    _draw_text_left(draw, title, font_m, COLOR_MAIN, TEXT_L_X, main_y)
    _draw_inline_badge_line(draw, badge_text, sub, font_s, font_s, TEXT_L_X, sub_y, pill=False)

    return _export(canvas)


# ─────────────────────────────────────────────
# HTML/Puppeteer 렌더러 (폴백)
# ─────────────────────────────────────────────
_RENDERER_JS = os.path.join(os.path.dirname(__file__), "..", "renderer", "render.js")


def compose_html(template_key: str, **params) -> bytes:
    """Puppeteer로 HTML 템플릿을 렌더링해 PNG bytes 반환.

    template_key: render.html이 인식하는 영문 key (예: 'basic_2line')
    params: title, sub, title_l, sub_l, badge, image_url 등

    image_url이 있고 썸네일형이 아닌 템플릿이면 rembg로 누끼 처리 후
    base64 data URL로 변환해 render.js에 전달.
    """
    from app.rembg_utils import needs_rembg, remove_bg_to_data_url

    image_url = params.get("image_url")
    if image_url and needs_rembg(template_key):
        params["image_url"] = remove_bg_to_data_url(image_url)

    payload = json.dumps({"template": template_key, **{k: v for k, v in params.items() if v is not None}})

    result = subprocess.run(
        ["node", _RENDERER_JS, payload],
        capture_output=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Puppeteer 렌더링 실패: {result.stderr.decode(errors='replace')}")

    return result.stdout
