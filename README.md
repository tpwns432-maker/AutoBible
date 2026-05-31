# BibleClip

클립보드의 성경 구절(예: `창 2:1`)을 자동으로 인식해 설정한 형식으로 변환·복사해 주는
한국어 데스크톱 앱입니다. 여러 역본 병렬 보기, 히브리어/헬라어 원어·사전 패널,
키워드 검색, GitHub 기반 자동 업데이트를 지원합니다.

> 저장소 이름은 역사적 이유로 `AutoBible` 이지만, 앱 이름은 **BibleClip** 입니다.

## 실행 (개발)

```bash
python -m bibleclip
# 또는
python bibleclip_app.py
```

Python 3.9+ 와 표준 라이브러리만 필요합니다(tkinter 포함). 자동 업데이트의 SSL
검증을 위해 `certifi` 가 있으면 사용합니다.

## 프로젝트 구조

```
bibleclip_app.py        진입점 슈팅 → bibleclip.ui.app:main
bibleclip/              애플리케이션 패키지
├─ _version.py          버전 단일 출처(ASCII 전용)
├─ config.py            플랫폼·폰트·경로·GitHub URL
├─ constants.py         자모/책이름 매핑
├─ text_utils.py        한글 조립·정제·검색 trigram
├─ theme.py             라이트/다크 팔레트
├─ update.py            릴리스 체크·플랫폼 자산 선택
├─ data/                bible_db.py · original_lang.py
├─ core/                engine.py(파서) · formatter.py
└─ ui/                  app.py + 믹스인(viewer·settings·lexicon·order·
                        viewer_ops·search·nav·monitor·theming·updater_ui)

bible_versions/         성경 SQLite DB (런타임 데이터)
original_lang/          원어/사전 데이터 (런타임 데이터)
icon.ico / icon.png     앱 아이콘
packaging/              build_mac.sh (macOS 로컬 빌드)
docs/                   CHANGELOG · BUILD_MAC · 리팩터링 파이프라인 문서
.github/workflows/      태그 푸시 시 Windows/macOS 자동 빌드·릴리스
```

UI 한 부분을 고칠 때 해당 믹스인 파일(`bibleclip/ui/*.py`)만 보면 되도록
관심사별로 분리돼 있습니다.

## 빌드 / 릴리스

- **자동(권장):** `v*` 태그를 push 하면 GitHub Actions가 Windows `.exe`(zip)와
  macOS `.app`(zip + dmg)을 빌드해 릴리스에 첨부합니다.
- **macOS 로컬:** `packaging/build_mac.sh` (자세한 내용은 `docs/BUILD_MAC.md`).

버전은 `bibleclip/_version.py` 한 곳에서 관리합니다. 변경 시 `docs/CHANGELOG.md` 도
함께 갱신하세요.

## 사용자 데이터

- 설정 파일: `bibleclip_settings.json` (예전 `autobible_settings.json` 은 최초 실행 시
  자동 승계됩니다).
- 성경/원어 데이터는 실행 파일 옆 또는 macOS `.app` 번들 안에서 로드됩니다.
