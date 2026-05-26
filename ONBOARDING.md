# 카카오 비즈보드 소재봇 — AI TF 온보딩 가이드

> **이 파일을 먼저 읽으세요.**  
> Claude Code로 이 프로젝트에 기여하려는 TF 멤버를 위한 컨텍스트 문서입니다.  
> 코드를 열기 전에 이 파일을 읽으면 프로젝트 전체 그림이 잡힙니다.

---

## 이 봇이 뭘 하는가

**슬랙에서 카카오 비즈보드 광고 소재(1029×258px PNG)를 자동으로 만들어주는 봇**입니다.

- 텍스트와 상품 이미지를 입력하면 → 배경 합성 + 텍스트 렌더링 → PNG 생성 → 슬랙에 업로드
- 단건(모달 입력) 또는 대량(구글 시트 연동) 두 가지 방식 지원

```
슬랙 사용자
    │  /소재생성 또는 /소재생성2 입력
    ▼
Railway (FastAPI 서버)
    ├─ /slack/command    → 모달 팝업 (단건)
    ├─ /slack/command2   → 확인 모달 (대량)
    └─ /slack/interactive → 모달 제출 처리
            │
            ├─ rembg         → 자동 누끼 처리 (v1만 해당)
            ├─ composer.py   → Pillow 이미지 합성 (11종 템플릿)
            └─ Google Sheets → 대량 데이터 읽기/상태 업데이트 (v2)
```

---

## 두 가지 커맨드

| 커맨드 | 방식 | 특징 |
|--------|------|------|
| `/소재생성` | 슬랙 모달 직접 입력 | 단건, 자동 누끼(rembg) 포함 |
| `/소재생성2` | 구글 시트 읽기 | 대량, 누끼 없음 (디자이너 제공 PNG 사용) |

---

## 프로젝트 스택

| 항목 | 내용 |
|------|------|
| 서버 | Python FastAPI, Railway 배포 |
| 이미지 합성 | Pillow (PIL) |
| 누끼 제거 | rembg (ONNX 모델) |
| 슬랙 연동 | slack-sdk |
| 구글 시트 | gspread + Google Service Account |
| 배포 | Railway (GitHub main push → 자동 배포) |
| 레포 | `jsyoo-alt/design-bot` (public) |
| 서버 URL | `https://web-production-c38b0.up.railway.app` |

---

## 파일 구조 (핵심 파일 위주)

```
design-bot/
├── app/
│   ├── main.py         # FastAPI 서버, /소재생성 라우팅, Slack 서명 검증
│   ├── main_v2.py      # /소재생성2 라우터 (대량 생성)
│   ├── bulk.py         # 대량 생성 워커: 시트 읽기 → 합성 → 슬랙 업로드
│   ├── composer.py     # 핵심 합성 엔진 (11종 템플릿, ~900줄)
│   ├── sheets.py       # Google Sheets 읽기/상태 업데이트
│   ├── drive.py        # Google Drive 업로드 (현재 제한 있음, 아래 참조)
│   ├── rembg_utils.py  # 배경 제거 유틸
│   └── config.py       # 환경변수 로딩
├── assets/
│   ├── backgrounds/    # 배경 PNG 파일 (bg_bizboard.png 등 5종)
│   └── fonts/          # SpoqaHanSansNeo Bold/Regular .ttf
├── GUIDE.md            # 사용자/운영자 가이드 (v1·v2 설정 방법)
├── ONBOARDING.md       # 이 파일
└── requirements.txt
```

---

## 11종 템플릿

| 슬랙 표시명 | 이미지 | 뱃지 | 로고 | 비고 |
|-------------|--------|------|------|------|
| `비즈보드` | ✅ 중앙 오브젝트 | ❌ | ✅ 좌상단 | 좌/우 카피 분리. H·I열 = 좌측 카피 |
| `기본_2줄형` | ✅ 우측 오브젝트 | ✅ 코너 | ✅ 우상단 | 로고 safe zone(y=74) 적용 |
| `기본_2줄형_좌측 오브제` | ✅ 좌측 오브젝트 | ✅ 코너 | ✅ 좌상단 | 로고 safe zone(y=74) 적용 |
| `기본_2줄형_좌측 오브제+뱃지` | ✅ 좌측 오브젝트 | ✅ 코너 | ✅ | |
| `썸네일형` | ✅ 우측 썸네일 | ❌ | ❌ | |
| `앱다운로드형` | ❌ | ❌ | ❌ | 앱 바 오버레이 |
| `앱다운로드+썸네일형` | ✅ 우측 썸네일 | ❌ | ❌ | |
| `텍스트강조+썸네일형` | ✅ 우측 썸네일 | ✅ 오렌지 pill | ❌ | |
| `텍스트강조형` | ❌ | ✅ 오렌지 pill | ✅ 우상단 | |
| `텍스트강조+썸네일형 v2` | ✅ 우측 썸네일 | ✅ 오렌지 텍스트 | ❌ | |
| `텍스트강조형 v2` | ❌ | ✅ 오렌지 텍스트 | ✅ 우상단 | |

---

## 구글 시트 구조 (v2 `/소재생성2`)

1행 헤더, 2행부터 데이터. F열 상태를 `제작요청`으로 설정하면 봇이 처리.

| 열 | 컬럼 | 필수 | 설명 |
|----|------|------|------|
| A | template | ✅ | 위 템플릿명 중 하나 |
| B | main_copy | ✅ | 메인 카피 |
| C | sub_copy | ✅ | 서브 카피 |
| D | badge | ❌ | 뱃지 텍스트 |
| E | object_url | ❌ | 상품 이미지 URL (누끼 처리된 투명 PNG 권장) |
| F | status | ✅ | `제작요청` / `제작완료` / `실패` |
| G | result_note | 봇 기입 | 슬랙 업로드 완료 메모 |
| H | main_copy_l | ❌ | 비즈보드 좌측 메인 카피 |
| I | sub_copy_l | ❌ | 비즈보드 좌측 서브 카피 |

---

## 환경변수 (Railway에 설정됨)

| 변수 | 설명 | 필수 |
|------|------|------|
| `SLACK_BOT_TOKEN` | Slack Bot OAuth Token | ✅ |
| `SLACK_SIGNING_SECRET` | Slack 앱 Signing Secret | ✅ |
| `FIGMA_TOKEN` | Figma API 토큰 (현재 미사용) | ✅ (없으면 서버 시작 불가) |
| `GOOGLE_SA_JSON` | Google 서비스 계정 JSON 전체 문자열 | v2 필수 |
| `SHEET_ID` | 구글 스프레드시트 ID | v2 필수 |
| `DRIVE_FOLDER_ID` | Drive 결과물 폴더 ID | v2 선택 |

---

## 현재 상태 및 알려진 한계

### 잘 되는 것 ✅
- `/소재생성` 단건 생성 + 누끼 처리 + 슬랙 업로드
- `/소재생성2` 시트 읽기 → 대량 합성 → 슬랙 업로드 → 시트 상태 업데이트
- Drive URL의 오브젝트 이미지 자동 다운로드 (공개 링크 우선 → 서비스 계정 폴백)
- 11종 템플릿 모두 작동
- 기본_2줄형·좌측 오브제 브랜드 로고 합성 (safe zone y=74 적용, 오브젝트와 겹침 없음)
- 카카오 광고 검수 통과 확인 (기본_2줄형, 기본_2줄형_좌측 오브제)

### 한계 / 개선 필요 🟡

**1. Google Drive 업로드 불가 (서비스 계정 quota 없음)**  
서비스 계정은 개인 My Drive에 파일을 저장하는 quota가 없음.  
현재: Drive 업로드 실패 시 건너뛰고 "슬랙 업로드 완료"만 기록.  
해결책: Google Workspace의 Shared Drive 사용 or 개인 OAuth 인증으로 변경.

**2. 이미지 품질 (Pillow)**  
Pillow로 직접 렌더링하기 때문에 PSD 원본 대비 자간·행간·폰트 렌더링 품질 차이 존재.  
대안: HTML/CSS + Puppeteer 렌더러로 교체 (CLAUDE.md에 계획 있음).

**3. FIGMA_TOKEN 불필요한 의존성**  
v2에서 Figma를 전혀 사용하지 않지만, config.py에서 필수 환경변수로 선언되어 있음.  
없으면 서버 시작 자체가 안 됨.

**4. 오브젝트 이미지 자동 누끼 없음 (v2)**  
`/소재생성2`는 디자이너가 누끼 처리한 PNG를 사용한다는 전제. 일반 JPG 입력 시 배경 제거 없이 그대로 합성됨.

---

## 카카오 광고 검수 관련 주의사항

실제 운영 중 발생한 검수 이슈 기록. 소재 수정 시 참고할 것.

| 템플릿 | 검수 결과 | 비고 |
|--------|---------|------|
| `기본_2줄형` | ✅ 통과 | |
| `기본_2줄형_좌측 오브제` | ✅ 통과 | |
| `비즈보드` | ⚠️ 줄간격 보류 → 수정 완료 | 메인/서브 카피 줄간격 21px → 34px 조정 |

**비즈보드 줄간격 이슈 원인:**  
Pillow의 `textbbox()`는 **잉크 픽셀 기준 타이트 바운딩박스**를 반환함.  
카카오 PSD 기준(line-height 포함) 21px 간격을 그대로 쓰면 실제 렌더링이 훨씬 좁아 보임.  
→ `BIZBOARD_MAIN_SUB_GAP = 34` 상수로 분리하여 비즈보드만 별도 관리.

---

## 개선 아이디어 (TF 디벨롭 후보)

| 아이디어 | 난이도 | 임팩트 |
|---------|--------|--------|
| HTML/Puppeteer 렌더러로 교체 (품질 개선) | 상 | 상 |
| 소재 미리보기 → 슬랙에서 승인 후 최종 저장 | 중 | 상 |
| 생성된 소재 자동 카카오 광고 API 업로드 | 상 | 상 |
| 이미지 URL 없이 파일 첨부로 오브젝트 입력 | 중 | 중 |
| 생성 이력 시트 자동 집계 (월별 생성량 등) | 하 | 중 |
| 실패 행 자동 재시도 (일정 시간 후 재실행) | 중 | 중 |
| FIGMA_TOKEN 선택 환경변수로 변경 | 하 | 하 |
| 텍스트 길이 초과 시 슬랙 경고 메시지 | 하 | 하 |

---

## 기여 방법 (Claude Code 사용 시)

1. 이 레포를 클론하거나 열기  
2. Claude Code에서 이 파일(`ONBOARDING.md`)과 `GUIDE.md`를 먼저 읽기  
3. 작업 전 `app/composer.py`와 `app/bulk.py`의 구조 파악 권장  
4. `main` 브랜치 push → Railway 자동 배포 (약 2~3분 소요)  
5. 배포 확인: `GET https://web-production-c38b0.up.railway.app/health`

### 로컬 개발 환경
```bash
pip install -r requirements.txt
# 환경변수 설정 (.env 파일 또는 export)
uvicorn app.main:app --reload --port 8000
```
> 로컬에서 Slack 커맨드 테스트 시 ngrok 등으로 외부 노출 필요.

---

## 변경 이력

| 날짜 | 변경 내용 |
|------|---------|
| 2026-05-26 | 비즈보드 줄간격 수정 (21→34px), 카카오 검수 대응 |
| 2026-05-26 | 기본_2줄형·좌측 오브제 브랜드 로고 합성 추가 (safe zone y=74 적용) |
| 2026-05-26 | Drive 업로드 optional화 (서비스 계정 quota 없음 확인, 슬랙 업로드만으로 운영) |
| 2026-05-26 | Drive 오브젝트 이미지 자동 다운로드 개선 (공개 URL → 서비스 계정 폴백) |
| 2026-05-26 | GitHub 레포 public 전환, AI TF 공유 시작 |

---

## 참고 링크

- [카카오 비즈보드 소재 제작 가이드](https://kakaobusiness.gitbook.io/main/ad/moment/performance/talkboard/content-guide)
- [Slack API — files.upload v2](https://api.slack.com/methods/files.getUploadURLExternal)
- [Google Sheets API (gspread)](https://docs.gspread.org/)
- [Google Drive API — Shared Drives](https://developers.google.com/workspace/drive/api/guides/about-shareddrives)
- [rembg (배경 제거 라이브러리)](https://github.com/danielgatis/rembg)
