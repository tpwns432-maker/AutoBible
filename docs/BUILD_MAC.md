# BibleClip — macOS 빌드 안내

Windows에서 만든 BibleClip을 Mac에서 빌드해 실행하는 방법입니다.
(PyInstaller는 크로스 컴파일이 안 되므로 **반드시 Mac에서** 빌드해야 합니다.)

## 1. 폴더 구성 확인

받은 폴더 안에 아래가 모두 있어야 합니다:

```
bibleclip_app.py      ← 실행 진입점 (python -m bibleclip 도 가능)
bibleclip/            ← 프로그램 소스 패키지 (config·data·core·ui)
packaging/build_mac.sh ← Mac 빌드 스크립트
bible_versions/       ← 성경 DB (최소 KRV.SQLite3)
original_lang/        ← 원어/사전 데이터 (개역한글S.sdb, HebGrkKo.dct, HebGrkEn.dct)
icon.icns             ← (선택) 앱 아이콘. 없으면 기본 아이콘으로 빌드됨
```

## 2. 사전 준비 (Python)

Mac에 Python 3가 필요합니다. 터미널에서:

```bash
python3 --version
```

3.9 이상이면 됩니다. 없으면 https://www.python.org 에서 설치하거나
`brew install python` (Homebrew)으로 설치하세요.

## 3. 빌드

터미널에서 이 폴더로 이동한 뒤:

```bash
cd /받은/폴더/경로
chmod +x packaging/build_mac.sh
./packaging/build_mac.sh
```

스크립트가 자동으로:
1. PyInstaller 설치
2. `BibleClip.app` 빌드
3. `dist/BibleClip-mac/` 폴더에 앱 + 데이터 폴더를 함께 배치

## 4. 실행

```
dist/BibleClip-mac/BibleClip.app   ← 더블클릭
```

성경/원어 데이터는 `BibleClip.app` **번들 안에** 들어있어, 앱을 어디로 옮기든
함께 따라갑니다. (추가 성경을 넣고 싶으면 `.app`과 같은 폴더에 `bible_versions`
폴더를 두면 인식됩니다.)

### 처음 실행 시 Gatekeeper 경고

서명되지 않은 앱이라 macOS가 "확인되지 않은 개발자" 경고를 띄울 수 있습니다.

- `BibleClip.app` 우클릭 → **열기** → **열기**, 또는
- 터미널에서:
  ```bash
  xattr -cr /Applications/BibleClip.app    # 경로는 실제 위치에 맞게
  ```
  ("손상되어 열 수 없음(damaged)" 경고가 나올 때도 위 명령으로 해결됩니다.)

## 참고 / 동작 차이

- **자동 업데이트**: Mac에서는 자동 설치가 안 되고, 새 버전이 있으면
  배너의 "지금 업데이트" 클릭 시 GitHub 다운로드 페이지가 열립니다.
- **폰트**: Mac에서는 Apple SD Gothic Neo / Menlo로 자동 표시됩니다.
- **클립보드 모니터링 / 성경·원어·사전 보기**: Windows와 동일하게 동작합니다.

## 아이콘을 넣고 싶다면 (선택)

`.ico` 대신 `.icns`가 필요합니다. Windows에서 받은 `icon.ico`를 Mac에서
변환하거나, 아이콘 없이 빌드해도 기능엔 문제 없습니다.
