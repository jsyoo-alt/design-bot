"""
카카오 비즈보드 소재 합성 모듈
가이드 기준: https://kakaobusiness.gitbook.io/main/ad/moment/performance/talkboard/content-guide
"""

import os
import io
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from rembg import remove as rembg_remove
from config import BACKGROUNDS_DIR, FONTS_DIR

# 카카오 비즈보드 공식 스펙
CANVAS_SIZE = (1029, 258)

# Spoqa Han Sans 폰트 경로
FONT_BOLD = os.path.join(FONTS_DIR, "SpoqaHanSansNeo-Bold.ttf")
FONT_REGULAR = os.path.join(FONTS_DIR, "SpoqaHanSansNeo-Regular.ttf")

# pt → px 변환 (96dpi 기준)
def pt_to_px(pt: float) -> int:
    return round(pt * 96 / 72)

# 공식 스펙 텍스트 크기 (pt → px)
MAIN_COPY_SIZE = pt_to_px(48)   # 64px
SUB_COPY_SIZE  = pt_to_px(39)   # 52px
BADGE_SIZE_1   = pt_to_px(30)   # 40px (한 줄)
BADGE_SIZE_2   = pt_to_px(25)   # 33px (두 줄)

# 공식 스펙 색상
COLOR_MAIN = "#4C4C4C"
COLOR_SUB  = "#777777"
COLOR_BADGE_TEXT = "#FFFFFF"

# 오브제 이미지 영역
OBJECT_AREA_W = 315
OBJECT_AREA_H = 258


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
    alpha = np.array(img)[:, :, 3]
    total = alpha.size
    transparent = int(np.sum(alpha < 128))
    ratio = transparent / total
    return 0.10 <= ratio <= 0.90


def try_remove_background(img: Image.Image) -> tuple[Image.Image, bool]:
    """
    rembg로 배경 제거 시도.
    성공 여부를 함께 반환: (결과 이미지, 성공 여부)
    실패하면 원본 이미지와 False 반환.
    """
    try:
        buf_in = io.BytesIO()
        img.save(buf_in, format="PNG")
        buf_in.seek(0)
        result_bytes = rembg_remove(buf_in.read())
        result = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
        if _is_removal_successful(result):
            return result, True
        return img, False
    except Exception:
        return img, False


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _download_image(url: str) -> Image.Image:
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
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

    # 좌측 영역 (0 ~ 514px)
    LEFT_END = 514
    LEFT_PADDING = 40

    sub_bbox = draw.textbbox((0, 0), sub_l, font=font_sub)
    title_bbox = draw.textbbox((0, 0), title_l, font=font_main)
    block_h = (sub_bbox[3] - sub_bbox[1]) + 8 + (title_bbox[3] - title_bbox[1])
    y_start = (CANVAS_SIZE[1] - block_h) // 2

    _draw_text_left(draw, sub_l, font_sub, COLOR_SUB, LEFT_PADDING, y_start)
    _draw_text_left(draw, title_l, font_main, COLOR_MAIN, LEFT_PADDING, y_start + (sub_bbox[3] - sub_bbox[1]) + 8)

    # 우측 텍스트 영역 (514 ~ 714px, 오브제 이미지 315px는 우측에 배치)
    RIGHT_TEXT_START = 514
    RIGHT_TEXT_END = CANVAS_SIZE[0] - OBJECT_AREA_W - 10

    sub_bbox_r = draw.textbbox((0, 0), sub_r, font=font_sub)
    title_bbox_r = draw.textbbox((0, 0), title_r, font=font_main)
    block_h_r = (sub_bbox_r[3] - sub_bbox_r[1]) + 8 + (title_bbox_r[3] - title_bbox_r[1])
    y_start_r = (CANVAS_SIZE[1] - block_h_r) // 2

    _draw_text_centered(draw, sub_r, font_sub, COLOR_SUB, CANVAS_SIZE[0], y_start_r, RIGHT_TEXT_START, RIGHT_TEXT_END)
    _draw_text_centered(draw, title_r, font_main, COLOR_MAIN, CANVAS_SIZE[0], y_start_r + (sub_bbox_r[3] - sub_bbox_r[1]) + 8, RIGHT_TEXT_START, RIGHT_TEXT_END)

    # 오브제 이미지 (우측 315x258) — 누끼 시도 후 실패 시 썸네일로 폴백
    if object_image_url:
        obj_img = _download_image(object_image_url)
        obj_img, removed = try_remove_background(obj_img)
        if removed:
            # 누끼 성공: 투명 배경 유지하며 비율 맞춰 배치
            obj_img.thumbnail((OBJECT_AREA_W, OBJECT_AREA_H), Image.LANCZOS)
            x_offset = CANVAS_SIZE[0] - OBJECT_AREA_W + (OBJECT_AREA_W - obj_img.width) // 2
            y_offset = (OBJECT_AREA_H - obj_img.height) // 2
            _paste_with_alpha(canvas, obj_img, (x_offset, y_offset))
        else:
            # 누끼 실패: 썸네일 방식(cover)으로 폴백
            obj_img = _fit_image(obj_img, OBJECT_AREA_W, OBJECT_AREA_H)
            _paste_with_alpha(canvas, obj_img, (CANVAS_SIZE[0] - OBJECT_AREA_W, 0))

    return _export(canvas)


# ─────────────────────────────────────────────
# 2. 기본_2줄형
#    중앙 카피 (title + sub) + 배경 이미지 (전체)
# ─────────────────────────────────────────────
def compose_basic_2line(
    title: str,
    sub: str,
    bg_image_url: str | None = None,
    badge_text: str | None = None,
) -> bytes:
    bg_path = os.path.join(BACKGROUNDS_DIR, "bg_basic_2line.png")
    canvas = Image.open(bg_path).convert("RGBA").resize(CANVAS_SIZE)

    # 배경 상품 이미지가 있으면 전체 배경에 합성
    if bg_image_url:
        prod_img = _download_image(bg_image_url)
        prod_img = _fit_image(prod_img, CANVAS_SIZE[0], CANVAS_SIZE[1])
        _paste_with_alpha(canvas, prod_img, (0, 0))

    draw = ImageDraw.Draw(canvas)
    font_main = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_sub  = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    TEXT_X = 40
    sub_bbox = draw.textbbox((0, 0), sub, font=font_sub)
    title_bbox = draw.textbbox((0, 0), title, font=font_main)
    block_h = (sub_bbox[3] - sub_bbox[1]) + 8 + (title_bbox[3] - title_bbox[1])
    y_start = (CANVAS_SIZE[1] - block_h) // 2

    _draw_text_left(draw, sub, font_sub, COLOR_SUB, TEXT_X, y_start)
    _draw_text_left(draw, title, font_main, COLOR_MAIN, TEXT_X, y_start + (sub_bbox[3] - sub_bbox[1]) + 8)

    if badge_text:
        _draw_badge(draw, badge_text, canvas)

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

    # 좌측 오브제 이미지 (315x258) — 누끼 시도 후 실패 시 썸네일로 폴백
    if object_image_url:
        obj_img = _download_image(object_image_url)
        obj_img, removed = try_remove_background(obj_img)
        if removed:
            # 누끼 성공: 투명 배경 유지하며 비율 맞춰 배치
            obj_img.thumbnail((OBJECT_AREA_W, OBJECT_AREA_H), Image.LANCZOS)
            x_offset = (OBJECT_AREA_W - obj_img.width) // 2
            y_offset = (OBJECT_AREA_H - obj_img.height) // 2
            _paste_with_alpha(canvas, obj_img, (x_offset, y_offset))
        else:
            # 누끼 실패: 썸네일 방식(cover)으로 폴백
            obj_img = _fit_image(obj_img, OBJECT_AREA_W, OBJECT_AREA_H)
            _paste_with_alpha(canvas, obj_img, (0, 0))

    draw = ImageDraw.Draw(canvas)
    font_main = _load_font(FONT_BOLD, MAIN_COPY_SIZE)
    font_sub  = _load_font(FONT_REGULAR, SUB_COPY_SIZE)

    # 우측 텍스트 영역: 가이드 기준 오브제-텍스트 간격 50px
    TEXT_X = OBJECT_AREA_W + 50
    sub_bbox = draw.textbbox((0, 0), sub, font=font_sub)
    title_bbox = draw.textbbox((0, 0), title, font=font_main)
    block_h = (sub_bbox[3] - sub_bbox[1]) + 8 + (title_bbox[3] - title_bbox[1])
    y_start = (CANVAS_SIZE[1] - block_h) // 2

    _draw_text_left(draw, sub, font_sub, COLOR_SUB, TEXT_X, y_start)
    _draw_text_left(draw, title, font_main, COLOR_MAIN, TEXT_X, y_start + (sub_bbox[3] - sub_bbox[1]) + 8)

    if badge_text:
        _draw_badge(draw, badge_text, canvas)

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
    canvas_rgb = canvas.convert("RGB")
    buf = io.BytesIO()
    canvas_rgb.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
