import os

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
FIGMA_TOKEN = os.environ.get("FIGMA_TOKEN", "")  # 선택 환경변수 (현재 미사용)
FIGMA_FILE_KEY = os.environ.get("FIGMA_FILE_KEY", "27WwR8ASEVErjzVZhq76XV")

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
BACKGROUNDS_DIR = os.path.join(ASSETS_DIR, "backgrounds")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")

# ── v2: Google Sheets / Drive 연동 ──────────────────────────────────────────
# Google 서비스 계정 JSON 키 (Railway 환경변수에 JSON 문자열로 저장)
GOOGLE_SA_JSON = os.environ.get("GOOGLE_SA_JSON", "")

# 고정 스프레드시트 ID (URL의 /d/{ID}/ 부분)
SHEET_ID = os.environ.get("SHEET_ID", "")

# 결과 PNG를 저장할 Google Drive 폴더 ID
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
