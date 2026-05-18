# 카카오 비즈보드 소재봇 — 사용 가이드

> **버전**: v1 (auto-rembg)  
> **배포**: Railway (Python/FastAPI)  
> **슬랙 커맨드**: `/소재생성`

---

## 개요

슬랙에서 `/소재생성` 커맨드 하나로 카카오 비즈보드 광고 소재(1029×258px PNG)를 자동 생성합니다.  
텍스트·템플릿을 입력하면 배경 이미지 합성 → 상품 이미지 자동 누끼 처리 → 텍스트 렌더링이 순서대로 실행됩니다.

---

## 아키텍처

```
Slack 사용자
    │  /소재생성 입력
    ▼
FastAPI (Railway)
    ├─ /slack/command   → 모달 팝업 표시
    └─ /slack/interactive → 모달 제출 처리
            │
            ├─ rembg_utils.py  →  배경 제거 (rembg / ONNX)
            └─ composer.py     →  Pillow 이미지 합성
                    │
                    └─ assets/
                         ├─ backgrounds/  배경 PNG 파일
                         └─ fonts/        SpoqaHanSansNeo
```

---

## 디렉토리 구조

```
design-bot/
├─ app/
│   ├─ main.py          # FastAPI 서버, Slack 라우팅, 모달 로직
│   ├─ composer.py      # 이미지 합성 엔진 (Pillow)
│   ├─ rembg_utils.py   # 배경 제거 유틸 (rembg)
│   └─ config.py        # 환경변수 로딩
├─ assets/
│   ├─ backgrounds/     # 배경 PNG (bg_basic_2line.png 등)
│   └─ fonts/           # SpoqaHanSansNeo-Bold/Regular.ttf
├─ GUIDE.md             # 이 파일
└─ requirements.txt
```

---

## 환경변수 (Railway 설정)

| 변수명 | 설명 |
|--------|------|
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | Slack 앱 Signing Secret |
| `FIGMA_TOKEN` | Figma API 토큰 (현재 미사용, 설정만 필요) |
| `FIGMA_FILE_KEY` | Figma 파일 키 (기본값 있음) |

---

## 슬랙 앱 설정

### 필요 OAuth 스코프
- `chat:write` — 메시지 전송
- `files:write` — 소재 PNG 업로드
- `channels:history` — 직전 업로드 이미지 자동 감지
- `commands` — 슬래시 커맨드

### Slack 커맨드 등록
| 커맨드 | Request URL |
|--------|-------------|
| `/소재생성` | `https://[Railway도메인]/slack/command` |

### Interactivity URL
`https://[Railway도메인]/slack/interactive`

---

## 사용 방법

### 기본 흐름

1. 소재로 쓸 **상품 이미지를 채널에 먼저 업로드**
2. `/소재생성` 입력 → 모달 팝업
3. 템플릿 선택, 메인/서브 카피 입력
4. **생성하기** 클릭
5. 누끼 처리 후 PNG 소재가 스레드에 업로드됨

### 모달 입력 항목

| 항목 | 필수 | 설명 |
|------|------|------|
| 템플릿 | ✅ | 아래 템플릿 목록 참고 |
| 메인 카피 | ✅ | 48pt Bold, 최대 30자 |
| 서브 카피 | ✅ | 39pt Regular, 최대 30자 |
| 좌측 메인 카피 | ❌ | 비즈보드 전용 |
| 좌측 서브 카피 | ❌ | 비즈보드 전용 |
| 뱃지 텍스트 | ❌ | 최대 10자 |
| 상품 이미지 URL | ❌ | 빈칸이면 채널 직전 이미지 자동 사용 |

---

## 지원 템플릿

| 템플릿명 | 설명 | 이미지 | 뱃지 |
|---------|------|--------|------|
| `비즈보드` | 좌우 분리형, 중앙 오브젝트 | ✅ | ❌ |
| `기본_2줄형` | 좌측 카피 + 우측 오브젝트 | ✅ | ✅ 코너 |
| `기본_2줄형_좌측 오브제` | 좌측 오브젝트 + 우측 카피 | ✅ | ✅ 코너 |
| `기본_2줄형_좌측 오브제+뱃지` | 위와 동일 + 로고 | ✅ | ✅ 코너 |
| `썸네일형` | 로고 + 카피 + 우측 썸네일 박스 | ✅ | ❌ |
| `앱다운로드형` | 앱바 + 카피 | ❌ | ❌ |
| `앱다운로드+썸네일형` | 앱바 + 카피 + 썸네일 | ✅ | ❌ |
| `텍스트강조+썸네일형` | 로고 + 카피 + 인라인 pill 배지 + 썸네일 | ✅ | ✅ 인라인 pill |
| `텍스트강조형` | 로고(우) + 카피 + 인라인 pill 배지 | ❌ | ✅ 인라인 pill |
| `텍스트강조+썸네일형 v2` | 카피 + 오렌지 텍스트 + 썸네일 | ✅ | ✅ 컬러 프리픽스 |
| `텍스트강조형 v2` | 카피 + 오렌지 텍스트 | ❌ | ✅ 컬러 프리픽스 |

### 이미지 처리 방식

- **오브젝트형** (기본_2줄형 계열, 비즈보드): **자동 누끼 처리** (rembg)
  - 투명 PNG가 들어오면 바로 합성
  - 일반 JPG/PNG가 들어오면 rembg 배경 제거 후 합성
  - 누끼 실패 시 원본 이미지로 폴백
- **썸네일형** (썸네일, 앱다운로드+썸네일, 텍스트강조+썸네일): **사각 크롭** (누끼 없음)

---

## 렌더링 스펙 (카카오 비즈보드 가이드 기준)

| 항목 | 값 |
|------|-----|
| 캔버스 크기 | 1029 × 258 px |
| 메인 카피 | SpoqaHanSansNeo Bold, 48pt, #4C4C4C |
| 서브 카피 | SpoqaHanSansNeo Regular, 39pt, #777777 |
| Main-Sub 행간 | **21px** (PSD 실측: Main bottom=123px, Sub top=144px) |
| 텍스트 좌측 여백 | 48px |
| 오브젝트 좌측 여백 | 48px |
| 오브젝트-텍스트 간격 | 50px (좌측 오브제) / 33px (우측 오브제) |
| 오브젝트 최소 폭 | 219px |
| 오브젝트 최대 폭 | 315px |
| 텍스트 최소 폭 | 290px |

---

## 배경 파일 목록

| 파일명 | 용도 |
|--------|------|
| `bg_basic_2line.png` | 기본형·텍스트강조형·앱다운로드형 공용 배경 |
| `bg_basic_2line_left.png` | 좌측 오브제형 배경 |
| `bg_bizboard.png` | 비즈보드 배경 |
| `app_bar.png` | 앱다운로드형 앱 바 오버레이 |
| `logo.png` | 로고 (썸네일·텍스트강조형 배치용) |

---

## 알려진 제한사항

- **누끼 품질**: 자동 AI 누끼(rembg)는 복잡한 배경·반투명 소재에서 품질이 떨어질 수 있음
- **폰트**: SpoqaHanSansNeo 사용 중 (PSD 원본은 구버전 SpoqaHanSans)
- **자간(tracking)**: Pillow는 자간 미지원 — 현재 tracking=0 고정
- **파일 크기**: 출력 PNG가 300KB 초과 시 경고 로그 발생 (Slack 업로드는 정상 진행)

---

## 헬스체크

`GET https://[Railway도메인]/health`

```json
{
  "status": "ok",
  "missing_assets": []
}
```

---

# 소재봇 v2 — 대량 생성 가이드

> **슬랙 커맨드**: `/소재생성2`  
> v1과 같은 Railway 서비스에서 동작. 자동 누끼 없음.

## v1과의 차이

| | v1 `/소재생성` | v2 `/소재생성2` |
|---|---|---|
| 입력 방식 | 슬랙 모달 직접 입력 | 구글 시트 읽기 |
| 처리 건수 | 단건 | 대량 (시트 행 전체) |
| 이미지 누끼 | 자동 rembg 처리 | ❌ 없음 (디자이너 제공 PNG 그대로 사용) |
| 결과 저장 | 슬랙 스레드 | 슬랙 스레드 + Google Drive |

## 사전 준비

### 1. Google 서비스 계정 설정
1. [Google Cloud Console](https://console.cloud.google.com/) → 프로젝트 선택
2. **API 및 서비스 → 사용 설정**: Google Sheets API, Google Drive API
3. **서비스 계정 생성** → JSON 키 다운로드
4. Railway 환경변수 `GOOGLE_SA_JSON`에 JSON 파일 내용 전체를 문자열로 붙여넣기

### 2. 스프레드시트 설정
1. 구글 시트 생성
2. 서비스 계정 이메일(`...@....iam.gserviceaccount.com`)을 시트에 **편집자** 권한으로 공유
3. 시트 URL에서 ID 복사: `https://docs.google.com/spreadsheets/d/{SHEET_ID}/`
4. Railway 환경변수 `SHEET_ID`에 설정

### 3. Google Drive 폴더 설정
1. Drive에 결과물 저장용 폴더 생성
2. 서비스 계정 이메일을 해당 폴더에 **편집자** 권한으로 공유
3. 폴더 URL에서 ID 복사: `https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}`
4. Railway 환경변수 `DRIVE_FOLDER_ID`에 설정

### 4. Slack 앱에 커맨드 추가
| 커맨드 | Request URL |
|--------|-------------|
| `/소재생성2` | `https://[Railway도메인]/slack/command2` |

## 스프레드시트 구조

1행을 헤더로 사용. **정확히 이 순서**로 컬럼을 구성해야 합니다.

| 열 | 컬럼명 | 필수 | 예시 |
|----|--------|------|------|
| A | `template` | ✅ | `기본_2줄형_좌측 오브제` |
| B | `main_copy` | ✅ | `레드윙 UP TO 13%` |
| C | `sub_copy` | ✅ | `베스트템 재입고` |
| D | `badge` | ❌ | `32%` |
| E | `object_url` | ❌ | `https://...누끼PNG.png` |
| F | `status` | ✅ | `제작요청` / `제작완료` / `실패` |
| G | `result_note` | 봇 기입 | Drive URL 또는 에러 메시지 |

### 상태(status) 값
- `제작요청` → 봇이 처리 대상으로 선택
- `제작완료` → 처리 완료 (봇 기입, 재실행 시 건너뜀)
- `실패` → 처리 실패 (봇 기입, `제작요청`으로 변경하면 재실행)

## 사용 방법

1. 시트 A~E 열에 소재 정보 입력
2. F열(status)을 `제작요청`으로 설정
3. 오브젝트 이미지 URL을 E열에 입력 (누끼 처리된 투명 PNG 링크)
4. 슬랙에서 `/소재생성2` 입력
5. 확인 모달에서 제작요청 행 수 확인 후 **생성 시작** 클릭
6. 스레드에 행별 결과 PNG가 순서대로 올라옴
7. 완료 후 시트 F열 → `제작완료`, G열 → Drive URL 자동 기입

## Railway 추가 환경변수

| 변수명 | 설명 |
|--------|------|
| `GOOGLE_SA_JSON` | Google 서비스 계정 JSON 전체 (문자열) |
| `SHEET_ID` | 구글 스프레드시트 ID |
| `DRIVE_FOLDER_ID` | 결과물 저장 Drive 폴더 ID |

## 주의사항

- **오브젝트 이미지**: 반드시 투명 PNG (누끼 완료본). 일반 JPG 입력 시 경고 메시지와 함께 그대로 합성됨
- **처리 속도**: 행당 약 2~3초 소요. 50행이면 약 2~3분
- **재실행**: `실패` 상태 행을 `제작요청`으로 바꾸면 다음 실행 시 재처리됨
- **중복 방지**: `제작완료` 행은 자동으로 건너뜀
```
