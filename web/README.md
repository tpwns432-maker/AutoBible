# BibleClip web frontend (High redesign)

웹(pywebview) 리라이트의 프론트엔드. **현재 Phase 1 = 정적 디자인 시스템**입니다.

## 구조
- `css/tokens.css` — 디자인 토큰 단일 출처(색·타입·간격·라운드·그림자). 라이트 기본, `<html data-theme="dark">`로 다크 전환. 액센트(보라/인디고)와 좌측 레일은 테마 무관.
- `css/styles.css` — 레이아웃·컴포넌트(레일·상단바·세그먼트·필·카드 3분할·세리프 본문·원어·사전). 토큰만 소비.
- `index.html` — 앱 레이아웃 + **하드코딩 샘플(여호수아 1)**. 실제 데이터 연결은 Phase 2.
- `app.js` — 미리보기용 최소 인터랙션(테마 토글·세그먼트·상태 배지)만. **데이터 배선 없음.**

## 보기
`web/index.html`를 브라우저로 열면 됨. 좌측 레일의 달 아이콘으로 라이트/다크 전환.

## 다음 (Phase 2~)
- pywebview 창에서 `bibleclip.core.library.Library` API(`get_chapter`/`interlinear`/`lookup_strong`/`build_output`/`start_monitoring`)를 JS에 노출해 실제 본문 렌더.
- 사전 원시 마크업(`lookup_strong`) → 실제 HTML 변환기.
- 폰트 번들링(오프라인), PyInstaller 자산 포함 위치 결정.
