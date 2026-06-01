# Bundled fonts — Pretendard

UI + 본문 폰트로 **Pretendard v1.3.9** 사용 (한국어 산세리프, 모던, 라틴 포함).

- **라이선스**: SIL Open Font License 1.1 (`OFL.txt`). 임베드·재배포 자유.
- **출처**: https://github.com/orioncactus/pretendard/releases/tag/v1.3.9
- **포함 형식** (weight 400/600/700/800):
  - `*.woff2` — 웹뷰 렌더용(가장 작음). `@font-face` src 1순위.
  - `*.otf` — macOS 배포용.
  - `*.ttf` — Windows 배포용.
- `@font-face` 정의는 `../css/fonts.css`. 셋 다 두어 어떤 환경에서도 로드되게 함.

## 재생성 (다른 weight/형식이 필요할 때)
릴리스 zip(`Pretendard-1.3.9.zip`)에서 복사:
- woff2: `web/static/woff2/Pretendard-<weight>.woff2`
- otf:   `public/static/Pretendard-<weight>.otf`
- ttf:   `public/static/alternative/Pretendard-<weight>.ttf`
