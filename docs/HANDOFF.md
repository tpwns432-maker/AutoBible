# BibleClip — 작업 인계 노트 (HANDOFF)

> 대화를 `/clear` 한 뒤 다음 세션이 빠르게 이어받기 위한 문서.
> 최종 업데이트: **v1.5.3 릴리스 완료** (2026-06-01) — main 머지·태그·CI 배포 모두 끝. CI green, Win zip + Mac zip + dmg 게시 완료.

---

## 1. 프로젝트 한 줄 요약
- **BibleClip** — 클립보드의 성경 구절(예: `창 2:1`)을 자동 인식·변환·복사하는 한국어 데스크톱 앱.
- Python + tkinter + **CustomTkinter**. 여러 역본 병렬 보기, 히브리어/헬라어 원어·사전, 키워드 검색, GitHub 자동 업데이트.
- **GitHub 저장소 이름은 역사적 이유로 `AutoBible` 유지** (앱 이름만 BibleClip). 저장소: `tpwns432-maker/AutoBible`.

## 2. 현재 상태
- **최신 릴리스: v1.5.3** (CI green, Windows zip + macOS zip + dmg 배포 완료 — 2026-06-01 게시).
  설정 탭 CTk화 + 사전 팝업 z-order 수정 포함. main 머지·태그·CI 배포 모두 완료, 작업 브랜치 삭제됨.
- `main` 브랜치가 곧 배포본. 작업용 브랜치는 머지 후 삭제함.
- **진행 중: High(pywebview 웹) 리라이트 — 리디자인 리포트의 ③단계.** 브랜치 `feat/web-engine-facade`(병행 전략: CTk 앱은 계속 배포, 웹 UI는 기능 동등 도달 시 전환).
  **Phase 0(엔진 파사드) 완료** — 아래 §9 참고. 미커밋 상태일 수 있음.
- 그동안의 큰 작업:
  - **v1.5.1** — 단일 파일 `autobible.py`(3,764줄)를 `bibleclip/` 패키지로 모듈화 + 네이밍 정리.
  - **v1.5.2** — UI 현대화(리디자인 "Medium" 단계, CustomTkinter) — 설정 탭 제외.
  - **v1.5.3** — 설정 탭도 CTk(세그먼트 버튼)로 통일 + 사전 팝업 z-order를 Win32 조회로 재구현.

## 3. 구조 (모듈화 후)
```
bibleclip_app.py            진입점 슈팅 → bibleclip.ui.app:main   (PyInstaller/CI 엔트리)
bibleclip/
├─ __main__.py              python -m bibleclip
├─ _version.py              버전 단일 출처 (ASCII 전용! 빌드가 인코딩 무관하게 읽음)
├─ config.py                플랫폼·폰트(UI_FONT/SERIF_FONT)·경로(BASE_DIR)·GitHub URL
├─ constants.py             자모/책이름 맵
├─ text_utils.py            한글 조립·정제·검색 trigram
├─ theme.py                 LIGHT_THEME/DARK_THEME(tk용 dict) + CTK(CTk용 (light,dark) 튜플)
├─ update.py                릴리스 체크·플랫폼 자산 선택
├─ data/   bible_db.py · original_lang.py
├─ core/   engine.py(파서) · formatter.py
└─ ui/
   ├─ app.py                BibleClipApp = 믹스인 10개 다중상속 + __init__/_build_ui + main()
   ├─ widgets.py            ScrollDropdown (휠 스크롤 커스텀 드롭다운)
   └─ (믹스인) viewer_tab · settings_tab · lexicon · order · viewer_ops ·
              search · nav · monitor · theming · updater_ui
bible_versions/  original_lang/   런타임 데이터 (루트 고정 — 절대 옮기지 말 것)
assets? (없음)  icon.ico/png       아이콘은 루트
packaging/build_mac.sh             macOS 로컬 빌드
docs/  CHANGELOG.md · BUILD_MAC.md · HANDOFF.md(이 파일) · pipelines/*.html
.github/workflows/build.yml        태그 vX.Y.Z 푸시 시 Win+Mac 자동 빌드/릴리스
```

## 4. UI 리디자인(CTk) — 완료 vs 남음
**완료 (v1.5.2):**
- 상단바: CTkButton(pill) + 컬러 상태 배지 + 탭은 CTkSegmentedButton.
- 본문/원어/사전/로그 = CTkFrame **카드**(라운드+테두리) + CTkScrollbar. 안의 텍스트는 **tk.Text 유지**(태그·스크롤동기·hover 보존).
- nav 컨트롤 = CTk(버튼·CTkEntry·세그먼트 사전토글). 책/장 = `ScrollDropdown`(휠 스크롤·UI폰트·토글 닫기).
- 버전 칩 줄 = 카드, 칩 드래그는 place 기반 **라이브 reorder + 트윈 애니메이션**(좌우 대칭 중간점 기준).
- 팔레트: 보라/인디고 (accent `#6D4DFF`/`#9A86FF`). 라이트/다크는 `ctk.set_appearance_mode` + (light,dark) 튜플로 자동 전환.

**완료 (v1.5.3):**
- [x] **설정(출력 설정) 탭 CTk화** — viewer와 동일한 카드 레이아웃. 표기 설정 라디오 그룹 7개를
  `CTkSegmentedButton`으로(값 매핑은 `settings_tab.py` `_seg_row`의 (value,label) 튜플), 우측은
  `CTkScrollableFrame`(단, `PanedWindow`에 직접 못 넣어 tk.Frame 홀더로 감쌈). `StringVar`/`BooleanVar`
  배선 유지로 `order.py` 콜백은 무수정. `theming.py` settings 구간 축소 + 세그먼트 선택색 재적용.
- [x] **사전 팝업 z-order** — `lexicon.py`에서 Windows는 닫는 시점에 `EnumWindows`로 실제 z-order를 읽어
  (destroy 전) 메인보다 앞이던 팝업만 재부상. 비-Windows는 기존 `<Activate>` 방식 fallback.

**남은 일 (다음 버전 후보):**
- [ ] 드롭다운 팝업 위치 미세조정(이미 화면 아래면 위로 flip함).
- [ ] (참고) 세그먼트 버튼 텍스트색은 CTk가 상태별 분리를 못 해 `_restyle_segmented`로 직접 칠함 —
  `_apply_theme`에서 `_settings_segs`/`tab_bar`/`lex_lang_seg`를 다시 칠하도록 해둠.

## 5. 빌드 / 릴리스 절차
1. 작업용 브랜치에서 진행, **단계마다 커밋**.
2. `bibleclip/_version.py` 버전 올리고 **`docs/CHANGELOG.md` 같이 갱신**(메모리 규칙).
3. **프리즈 빌드로 직접 테스트** (CTk는 PyInstaller에서 자산 누락 잦음):
   ```
   python -m PyInstaller --onedir --windowed --noconfirm --clean \
     --collect-submodules bibleclip --collect-all customtkinter \
     --icon=icon.ico --name BibleClip --distpath dist_test --workpath build_test bibleclip_app.py
   # 그 뒤 dist_test/BibleClip/ 에 bible_versions, original_lang, icon.ico, autobible_settings.json 복사 후 실행
   ```
4. `main`에 **fast-forward 머지** → `git push origin main`.
5. `git tag -a vX.Y.Z -m ...` → `git push origin vX.Y.Z` → CI가 Win+Mac+dmg 빌드/릴리스.
6. CI 확인은 **GitHub REST API 폴링**(이 환경엔 `gh` CLI 없음):
   `https://api.github.com/repos/tpwns432-maker/AutoBible/actions/runs` 및 `/releases/latest`.

## 6. ⚠️ 반드시 지킬 것 (호된 교훈 포함)
- **헤드리스 테스트 시 설정 저장 메서드 호출 금지.** `_commit_drag`/`_save_settings`/`_on_close`는 `_save_settings`가 `root.geometry()`를 저장하는데, 창을 `withdraw()`하면 200x200 같은 값이 저장돼 **사용자의 `bibleclip_settings.json`이 오염됨**. 실제로 한 번 망가뜨려 창 크기를 손으로 복원했음. 테스트는 빌드/렌더만:
  ```python
  import customtkinter as ctk
  from bibleclip.ui.app import BibleClipApp
  root = ctk.CTk(); root.withdraw()
  app = BibleClipApp(root); root.update_idletasks()
  # ... 검사 ...
  import os, sys; sys.stdout.flush(); os._exit(0)   # 저장 메서드 호출 X
  ```
- 한글 콘솔 출력은 **`python -X utf8`** 로 실행.
- **설정 파일명**: `bibleclip_settings.json` (예전 `autobible_settings.json`을 최초 실행 시 1회 승계). 두 이름 다 gitignore. 둘 다 절대 다른 이름으로 바꾸지 말 것.
- **데이터 폴더**(`bible_versions/`, `original_lang/`)·**엔트리 파일명**(`bibleclip_app.py`)·**GitHub repo "AutoBible"**는 고정.
- 의도적으로 남긴 "autobible" 흔적: `config.GITHUB_REPO="AutoBible"`, `config.LEGACY_SETTINGS_FILE`, CHANGELOG 과거 기록, macOS 옛-번들 호환. 그 외엔 전부 정리됨.

## 7. CTk 관련 메모(재발 방지)
- **CTkOptionMenu/Combobox는 `['values']` 문법 불가** → `.configure(values=)` / `.cget('values')`. (책/장은 아예 `ScrollDropdown`으로 교체함.)
- **CTkSegmentedButton은 선택/비선택 텍스트색 분리 불가** → `app._restyle_segmented(seg)`가 내부 `_buttons_dict`를 직접 칠함(선택=흰색). `tab_bar`, `lex_lang_seg`에 적용 중.
- **CTkFrame을 tk.PanedWindow 안에 둘 때** 둥근 코너 노치가 부모 배경을 못 따라감 → 카드에 `bg_color=CTK['app_bg']` 지정.
- 다크 토글: `theming.py` `_toggle_dark_mode`가 `ctk.set_appearance_mode(...)` + `_apply_theme()` 호출. CTk 위젯은 (light,dark) 튜플로 자동, tk 위젯만 `_apply_theme`에서 색 지정.

## 8. 참고 문서
- 리디자인 원본: `docs/redesign-report.html` (Low/Medium/High 3단계 목업·워크플로우). v1.5.2 = **Medium** 구현.
- 리팩터링 파이프라인: `docs/pipelines/통합_파이프라인.html` 등.
- macOS 빌드: `docs/BUILD_MAC.md`.

## 9. High(pywebview 웹) 리라이트 — 진행 상황 (브랜치 `feat/web-engine-facade`)
리포트 ③단계. **전략: 별도 브랜치 병행** — CTk(main)는 계속 배포본, 웹 UI가 기능 동등 도달 시 전환.

**Phase 0 — 엔진 파사드 추출 (✅ 완료, 동작 변경 없음):**
- 신규 `bibleclip/core/library.py` `class Library` — **모든 비-UI 상태/로직의 단일 출처**(DB·원어·사전·`settings`·참조→출력 파이프라인·검색·모니터링). tkinter 비의존(`import bibleclip.core.library`가 tkinter를 끌어오지 않음 — 검증됨). 웹 UI가 그대로 import해서 쓸 API: `parse_reference / get_chapter(s) / search / lookup_strong(원시 마크업 반환) / interlinear / build_output(text)→{kind:reference|keyword,…} / start_monitoring / stop_monitoring / notify_clipboard_written`.
- 신규 `bibleclip/core/clipboard_monitor.py` `class ClipboardMonitor` — 주입식 read/write 콜백 기반 감시 루프(`last`로 자기출력 재감지 방지).
- `ui/app.py`: `self.core=Library()` 후 **별칭 배선**(`self.bible_dbs=self.core.dbs`, `self.settings=self.core.settings`, `bethlehem_*`, `lexicon_*` — 공유 참조라 믹스인 전부 무수정). `_load_*`/`_save_settings`/`_process_clipboard`/`_monitor_loop` 로직은 코어로 이동, 앱엔 얇은 위임만(`_bethlehem_ready`,`_refresh_databases`,`_save_settings`는 geometry 스탬프용). `DEFAULT_SETTINGS`는 `Library`로 이동(+클래스 별칭).
- 수동 복사(`viewer_ops`/`search`)·종료(`updater_ui` `_on_close`/`_quit_for_update`)는 `core.notify_clipboard_written` / `core.stop_monitoring`로 라우팅.
- `data/original_lang.py`: 모듈 상단 `import tkinter`를 `render_dict_html` 내부 지연 import로(코어 tk-free화).
- **검증**: `python -X utf8 tests/test_core.py`(헤드리스 코어 스모크 — parse/get_chapter/build_output/search/lexicon/interlinear, **save_settings 호출 X**). + 헤드리스 CTk 렌더·별칭 배선 확인. + 가짜 클립보드로 모니터 통합(재처리 방지·키워드·수동복사 가드) 확인. 전부 통과.

**남은 Phase (다음 세션):** 1 디자인 시스템(CSS 토큰) · 2 pywebview 브리지+실제 장 렌더(웹 클립보드 백엔드 결정 지점) · 3 3패널+사전 마크업→HTML 변환기 · 4 폴리싱·상태 · 5 패키징·서명. (WebView2는 Win11 기본 탑재.)
