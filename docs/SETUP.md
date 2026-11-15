# 직접 설치하고 실행하기

**필요 환경:** Linux, NVIDIA GPU·CUDA 호환 드라이버, Python 3.11, Git, 인터넷 연결.

아래 명령을 서버 터미널에 순서대로 입력합니다.

## 1. 코드 다운로드

```bash
git clone https://github.com/ssonniee/hyundai-moaorder.git
cd hyundai-moaorder
```

이후 명령은 이 폴더에서 실행합니다.

## 2. 실행 환경 설치

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -c "import torch; print(torch.cuda.is_available())"
```

마지막 출력이 `True`인지 확인합니다.

## 3. 음원분리 환경 설치

아래 PyTorch 조합은 CUDA 12.8을 지원하는 드라이버가 필요합니다.

```bash
python3.11 -m venv .venv-separator
.venv-separator/bin/python -m pip install --upgrade pip
.venv-separator/bin/python -m pip install torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128
.venv-separator/bin/python -m pip install -r requirements-separator.txt
.venv-separator/bin/python -c "import torch; print(torch.cuda.is_available())"
```

이 환경에서도 `True`인지 확인합니다.

## 4. 모델 다운로드

```bash
python scripts/download_models.py
```

SepFormer 모델은 첫 음원분리 실행 때 자동 다운로드됩니다.

## 5. 서버 실행

```bash
source .venv/bin/activate
export DRIVE_ORDER_SEPARATOR_PYTHON="$PWD/.venv-separator/bin/python"
bash demo.sh
```

서버 PC의 브라우저에서 터미널에 출력된 `http://127.0.0.1:8765/#key=...` 링크를 엽니다. 녹음하려면 마이크 권한을 허용합니다.

종료는 `Ctrl+C`, 재실행은 위 세 명령을 사용합니다.

## 다른 기기에서 접속하기

HTTPS 터널·프록시를 서버의 **8765 포트**에 연결하고, 서버를 다음 명령으로 실행합니다.

```bash
bash demo.sh --public-host YOUR_HTTPS_HOST
```

- `YOUR_HTTPS_HOST`: 실제 도메인만 입력합니다. `https://`와 경로는 제외합니다.
- 접속 주소: `https://도메인/#key=서버에서_생성된_접속키`
- 휴대폰 녹음에는 HTTPS가 필요합니다.

## 설정·저장 위치

| 항목 | 경로 |
|---|---|
| 매장·메뉴·별칭 | `demo/stores.json` — 수정 후 서버 재시작 |
| 녹음·분석 결과 | `demo/sessions/` |
| 모델 | `models/` 및 Hugging Face 캐시 |

접속키와 녹음 결과는 공개하지 않습니다.
