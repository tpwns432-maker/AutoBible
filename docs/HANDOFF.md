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

**Phase 1 — 디자인 시스템(정적 CSS) (✅ 완료):** `web/` 폴더.
- `css/tokens.css` — 토큰 단일 출처(색·타입·간격·라운드·그림자). 라이트 기본 + `<html data-theme="dark">` 다크. 액센트/레일은 테마 무관. `--accent-text`는 다크에서 밝은 보라(`#9A86FF`)로 분리(가시성).
- `css/styles.css` — 레일·상단바·세그먼트·필·카드 3분할·본문·원어·사전. 토큰만 소비.
- `css/fonts.css` + `web/fonts/` — **Pretendard v1.3.9 번들**(OFL). weight 400/600/700/800 × woff2(렌더)+otf(맥)+ttf(윈도우), ~19MB. `--font-ui` 한 곳으로 본문·UI 통일.
- `index.html` — 앱 레이아웃 + 하드코딩 샘플(여호수아 1). `app.js`는 미리보기 인터랙션만(테마/세그먼트/배지), **데이터 배선 없음**.
- 사용자 결정 사항(반영됨): 본문 **산세리프**(세리프 X) · 본문에 **원어코드(H####) 숨김**(원어 패널엔 유지) · 역본 칩은 **사용 중인 것만** + 점선 "＋" 추가버튼 · 사전 히브리어 헤드워드 **48px**.

**Phase 2 — pywebview 브리지 + 실데이터 렌더 (✅ 완료, 본문+원어+사전):**
- 새 의존성 `pywebview`(requirements.txt). Windows=EdgeChromium(WebView2)+pythonnet 자동.
- 신규 `bibleclip/webui/` (정적 `web/`와 구분되는 파이썬 브리지):
  - `api.py` `class Api` — JS-facing(`pywebview.api.*`), **`webview` import 안 함**(헤드리스 테스트 가능). `Library`를 감싸 JSON 반환: `get_initial / get_books / get_chapters / get_chapter / get_interlinear / lookup_strong`. `markup_to_html()`로 사전 원시 마크업→HTML(`^`→공백, `<num>`→`span.lex-num`; `<b>/<br>/<sup>/<font>`는 보존).
  - `app.py` `main()` — `Library`+`Api`로 `webview.create_window(url=get_resource_dir()/web/index.html, js_api=...)`+`start()`. 진입점: `bibleclip_web.py`, `python -m bibleclip.webui`.
- `Library` 추가(읽기 접근자): `versions()`/`books(version)`/`primary_version()`.
- `web/app.js`: **라이브 모드**(`window.pywebview` 있으면 실데이터, 없으면 정적 샘플 폴백). `pywebviewready`→`get_initial`→책/장/버전 드롭다운·본문·원어 렌더. 스트롱 칩 클릭→`lookup_strong`→사전. ‹›/책/장/버전 전환. `index.html`에 id 부여, `styles.css`에 `.menu`/`.lex-num`/`.panel-loading` 추가.
- **검증**: `tests/test_webui_api.py`(헤드리스 — get_initial/get_chapter('태초')/get_interlinear/lookup_strong('여호와'), webview 불필요). + 실제 `bibleclip_web.py` 창에서 책/장/버전 전환·원어·사전 클릭 동작 확인(사용자 OK). CTk 회귀 없음.
- 알려진 정교화 후보: 라이브 사전의 히브리어 헤드워드를 48px로 크게 뽑는 건 미적용(정적 디자인엔 있음). 사전 마크업 파서 강건화.

**Phase 3a — 클립보드 모니터링 (✅ 완료, 사용자 실창 검증):**
- **백엔드 결정: `pyperclip`**(크로스플랫폼, requirements.txt 추가). CTk 앱은 tkinter/pbcopy 직접 사용 — 웹만 pyperclip.
- `webui/api.py`: `start_monitoring()`/`stop_monitoring()` 추가. `Library.start_monitoring`에 `pyperclip.paste/copy`를 read/write로 주입. **Python→JS 푸시 채널**: `set_window(window)`로 주입받은 pywebview 창의 `evaluate_js`로 `window.bibleclip.onReference(result)` / `onKeyword(kw)` 호출 — **여전히 `webview` import 안 함**(window 객체만 보유, 헤드리스 시 None→no-op). 모니터 워커 스레드에서 호출해도 pywebview가 UI 스레드로 마샬, `onReference`는 비동기 작업을 await 없이 킥오프해 즉시 반환→evaluate_js 블로킹 짧음(데드락 없음).
- `webui/app.py`: `create_window` 반환 창을 `api.set_window(window)`로 연결.
- `web/`: 모니터 버튼(`#monitor-btn`) 토글+배지 상태, **캡처 시 뷰어 자동이동+절 하이라이트**(`.v.hl` flash), **토스트**(하단 `#toast-wrap`), **활동 로그 드로어**(우측 슬라이드, 레일 클립보드 아이콘 토글, unread 점, 로그행 클릭→재이동). 키워드(`#…`)는 토스트+로그만(검색 패널 미구현).
  - ⚠️ 교훈: `.drawer{display:flex}`가 UA `[hidden]`을 이겨 드로어가 안 숨겨짐 → `.drawer[hidden]{display:none}` 명시 필요(고침). 같은 패턴 주의.
- **검증**: `tests/test_webui_api.py` 확장(`FakeClipboard`+`FakeWindow`로 `start_monitoring`→`창 1:1` 인플레이스 변환·`onReference` 푸시·`#사랑`→`onKeyword` 검증, 실 클립보드/webview 불필요). + 사용자 실창 검증(모니터 토글·`요 1:1-3` 변환·자동이동·드로어 OK).
- **다음 후보(사용자 합의로 보류)**: 로그행 클릭 시 **재복사**(현재 이동만 — CTk도 이동만이라 동작 일치).

**Phase 3b — 다역본 병렬 보기 (✅ 완료, 사용자 실창 검증):**
- 모델: `settings['viewer_versions']`(체크된 역본, `viewer_version_order` 기준 정렬). 첫 역본=primary(책/장 드롭다운·원어 패널 구동). CTk와 동일 모델.
- `webui/api.py`: `get_initial`에 `'viewer'`(체크 리스트) 추가. 신규 `set_viewer_versions(names)` — dbs로 필터+`viewer_version_order`로 재정렬+`save_settings`, 최소 1개 유지, 정리된 리스트 반환.
- `web/`: 단일 `#ver-chip`→`#ver-chips`(체크된 역본 칩 라이브 렌더, 첫 칩 primary 점 표시, 칩 `✕`로 제거·마지막 1개는 불가). `＋` 버튼=**다중선택 메뉴**(`openMenu`에 `multi` 옵션 추가 — 토글 시 안 닫힘, `onPick` 반환값으로 체크상태 반영). 본문 패널: 체크된 역본 **병렬 fetch**(`Promise.all`로 각 `get_chapter`) 후 JS에서 절번호 합집합 병합, 절마다 역본별 줄(`.vline`+`.vver` 배지). 단일 역본이면 배지 숨김. primary 변경 시 책/장 목록 갱신.
- **검증**: `tests/test_webui_api.py` — `get_initial.viewer` + `set_viewer_versions`(검증·정렬·빈 거부, **save_settings 스텁**으로 사용자 설정 미오염). 사용자 실창 OK.
- 칩 **드래그&드롭 순서 조정**: ✅ 완료(Phase 3d) — 아래.

**Phase 3c — 출력 설정 탭 (✅ 완료, 사용자 실창 검증):**
- `webui/api.py`: `get_settings`(format 10키+output_order+versions), `set_setting(key,value)`(화이트리스트 `_FORMAT_KEYS`: enum 값검증/bool 강제, save), `set_output_order(names)`(dbs 필터·dedup·순서 유지, save), `get_preview()`(`build_output('요 1:1-3')` 결과 텍스트 = 실제 복사물).
- `web/`: 상단 탭 `#tab-seg`(성경 보기/출력 설정)이 `#viewer-view`↔`#settings-view` 전환 + `#viewer-controls` 숨김. 설정뷰는 lazy 로드. **표기 설정**(7개 세그 + 토글 3개), **출력 순서**(↑↓✕ + ＋역본추가 메뉴), **미리보기**(요 1:1-3, 변경 즉시 갱신). 포맷 행은 JS config(`FORMAT_ROWS`/`TOGGLE_ROWS`)로 렌더(구분기호 `' '` 값이 HTML 속성 인코딩에 안 깨지게).
- ⚠️ CSS: 전역 `[hidden]{display:none !important}` 추가 — `.panels`/`.drawer` 등 display 규칙이 `[hidden]`을 이기던 문제 일괄 해결.
- **검증**: `tests/test_webui_api.py` — get_settings/set_setting(enum·bool·미지키)/set_output_order(필터·dedup)/get_preview(실데이터·빈순서 플레이스홀더), **save_settings 스텁**. 사용자 실창 OK(탭 전환·미리보기·순서·모니터 반영).
- **출력 순서 FLIP 애니메이션 (✅ 완료, 사용자 OK)**: ↑↓/제거 시 행이 자리를 미끄러져 바뀜. `commitOrder`를 낙관적(즉시 재렌더+`flipReorder`)으로 전환하고 백엔드 저장은 백그라운드 reconcile. `rowTops()`로 이전 top 기록→재렌더→이전위치 transform→rAF에서 transition으로 복귀(.22s). 행에 `data-ver`.

**Phase 3d — 검색·사전 강화·재복사·칩 드래그·UX 패치 (✅ 완료, 사용자 실창 검증):**
- **Library 리팩터**: `build_output`의 포맷 코어를 `format_reference(book,chapter,verses)->(text,n_parts)`로 추출(재복사·미리보기와 공유). `morphology(code,book,ch,verse)` 추가(원전분해.sdb→형태소; 현재 사용자 환경엔 데이터 없어 빈 리스트로 graceful).
- **검색 패널**: `api.search(keyword,version,limit)`(기본=primary/한국어, hits=book/chapter/verse/short/text), `api.copy_reference(book,ch,verses)`(format_reference→pyperclip 복사+notify). 프론트: 좌측 레일 검색뷰(입력+Enter/버튼, 결과 클릭→복사 토스트). 모니터 `#키워드` 캡처→검색뷰 자동 표시.
- **사전 정교화**: `parse_entry(markup)`로 `headword`(`^` 앞)·`reading`(첫 `<font>`)·`html`(나머지) 분리 → 사전 패널에 히브리어 48px 헤드워드+음역. `lookup_strong(code,lang,book,ch,verse)`에 `morph` 포함. 한글/영어 토글 배선(`lexLang`).
- **hover/우클릭**: 원어 칩 hover→0.4s 후 툴팁(`hover_summary`: 헤드워드 30px+음역+요약줄). 우클릭→`open_dict_window`(app.py가 `set_popup_factory`로 `webview.create_window(html=...)` 주입; `_dict_page_html` 자가완결 인라인 CSS, 폰트는 시스템 폴백). api.py는 여전히 webview 비의존(window/factory 주입식).
- **클립보드 로그 재복사**: 로그행 클릭 시 이동 + `copy_reference`로 다시 복사(토스트).
- **칩 드래그 순서조정 + 라이브 갭**: `api.set_viewer_order(names)`(주어진 순서 신뢰+`viewer_version_order` 앞으로). 프론트는 박스 위임 HTML5 DnD; `dragover` 때 DOM 재렌더 없이 다른 칩에 `translateX` 트랜지션으로 삽입 갭을 실시간 표시(`layoutDragGap`), 드롭 시 `reorderViewer`+`flipChips` 안착. (칩 add/remove에도 `flipChips`.)
- **UX 패치**: ① 출력설정을 상단 탭→**좌측 레일 아이콘**(`#nav-settings`, 본문·검색 사이)로 이동, `#tab-seg` 제거, `showView('viewer'|'settings'|'search')`로 통합. ② 모니터가 **참조** 캡처 시 `showView('viewer')`로 본문 복귀. ③ hover 헤드워드 30px. ④ 역본 칩 라이브 드래그.
- ⚠️ 편집 중 `web/app.js`에 NUL 바이트 2개 혼입된 적 있음(`join(" ")`가 `join("\x00")`로) → 제거함. 커밋/실행 전 `python -c "open('web/app.js','rb').read().count(b'\x00')"`로 점검 권장.
- **검증**: `tests/test_webui_api.py` 대폭 확장(lookup_strong headword/reading/morph, hover_summary, search+copy_reference[clipboard 스텁], set_viewer_order, open_dict_window 무팩토리 no-op; **save_settings 스텁**). 사용자 실창 OK 전 항목.

**Phase 4 — 상태 지속·폴리싱 (✅ 완료, 사용자 OK):**
- `api`: `get_initial`에 `dark_mode`/`font_size` 추가. `set_dark_mode(on)`·`set_font_size(size)`(8~30 클램프)·`note_position(book,chapter)`(메모리만; 종료 시 저장).
- `app.py`: 시작 시 `settings['web_geometry']`(웹 전용 키 — CTk tk `geometry`와 분리)로 창 크기·위치 복원, `window.events.closing`에서 `web_geometry` 스탬프 + `library.save_settings()`(마지막 위치 등 일괄 저장).
- `web/`: A−/A+ → `--reading-scale`(=`font_size/11`)로 본문·원어·사전 글자 크기, persist. 달 아이콘 테마 토글이 `dark_mode` 저장. 마지막 위치는 `loadChapter`마다 `note_position`. 부팅 시 테마/글자크기 복원.
- **달 아이콘 패치**: 다크 모드일 때 달이 노란색(`#FFD66B`)으로 채워지고 라이트일 때 외곽선만 — 상태 직관화(`[data-theme="dark"] #theme-toggle svg path{fill}`).
- **검증**: `tests/test_webui_api.py`(set_font_size 클램프·set_dark_mode·note_position, save 스텁). 사용자 실창 + 설정 파일로 지속 확인(web_geometry/dark/font/last 모두 기록됨).

**Phase 3→웹 이관 누락 기능:**
- ✅ **뷰어 수동 복사**(완료): 본문 절 클릭=단일 복사, 드래그 선택=범위 복사(`copy_reference(...,versions=state.viewer)`로 보고 있는 역본 형식). ⚠️ **pywebview는 `text_select` 기본 False** — `create_window(text_select=True)` 안 켜면 드래그 선택 자체가 안 됨(블럭도 안 보임). CSS로 읽기 패널만 `user-select:text`, 나머지 chrome은 `none`.
- ✅ **키보드 장 이동**(완료): 본문 화면에서 ←/→ → 이전/다음 장(`chapStep`, 입력 포커스/비뷰어 시 무시).
- ✅ **DB 새로고침**(완료): 출력설정 "출력 순서" 카드의 "DB 새로고침" → `api.refresh_databases()`(lib.refresh_databases + 버전목록 반환).
- ◐ **업데이트 확인**(체크 완료, 설치 미구현): `api.check_update`(update.py `fetch_latest_release`+`parse_version`)/`open_releases_page`/`skip_update`, get_initial에 `auto_update_check`. 상단 버튼=수동 체크(최신이면 토스트, 새 버전이면 보라 배너+릴리스 페이지/건너뛰기), 시작 시 조용한 자동 체크(skip 존중). **인앱 다운로드·설치(.bat/.sh 교체+재시작)는 frozen 레이아웃 의존 → Phase 5에서.** 토스트는 테마 반전색(`--toast-bg/fg`)으로 가시성↑.
- ⬜ **스크롤 동기화**: CTk 본문↔원어 패널 스크롤 동기(`_on_viewer_yscroll`). 웹 미구현(폴리시 후보).

**남은 Phase:** 5 패키징·서명(`--add-data web`, 폰트 포함; WebView2는 Win11 기본). + 위 이관 누락 기능들(우선순위는 사용자와 협의).
