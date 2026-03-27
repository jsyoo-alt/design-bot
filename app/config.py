import os

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
FIGMA_TOKEN = os.environ["FIGMA_TOKEN"]
FIGMA_FILE_KEY = os.environ.get("FIGMA_FILE_KEY", "27WwR8ASEVErjzVZhq76XV")

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
BACKGROUNDS_DIR = os.path.join(ASSETS_DIR, "backgrounds")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")
