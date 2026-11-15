# Self-hosting Guide

자신의 GPU 서버에서 MoaOrder를 실행하는 방법입니다. 웹 체험만 원한다면 [공개 데모](https://udder-purify-retract.ngrok-free.dev/)를 이용하세요.

## 준비 사항

| 항목 | 필요 환경 |
|---|---|
| 서버 | NVIDIA GPU와 CUDA 호환 드라이버가 설치된 Linux |
| 도구 | Git, Python 3.11, Python venv |
| 네트워크 | 모델 다운로드를 위한 인터넷 연결 |
| 저장 공간 | 모델 가중치와 녹음 결과를 저장할 여유 공간 |

개발에는 RTX 5090 32GB를 사용했습니다. 다른 GPU의 최소 메모리는 검증하지 않았습니다. 아래 명령은 **서버의 터미널**에 순서대로 입력합니다.

## 1. 코드 내려받기

```bash
git clone https://github.com/ssonniee/hyundai-moaorder.git
cd hyundai-moaorder
```

이후 모든 명령은 이 폴더에서 실행합니다.

## 2. 기본 실행 환경 만들기

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

GPU가 인식되는지 확인합니다.

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

`True`가 나오면 다음 단계로 진행합니다. `False`라면 NVIDIA 드라이버와 설치한 PyTorch의 CUDA 호환성을 먼저 확인하세요. 음성 변환에는 시스템 ffmpeg를 사용하며, 없으면 함께 설치되는 imageio-ffmpeg를 사용합니다.

## 3. 음원분리 환경 만들기

SepFormer는 별도 Python 환경에서 실행합니다. 아래는 개발 환경에서 사용한 CUDA 12.8 조합이며, 서버 드라이버가 이를 지원해야 합니다.

```bash
python3.11 -m venv .venv-separator
.venv-separator/bin/python -m pip install --upgrade pip
.venv-separator/bin/python -m pip install torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128
.venv-separator/bin/python -m pip install -r requirements-separator.txt
.venv-separator/bin/python -c "import torch; print(torch.cuda.is_available())"
```

이 환경에서도 `True`가 나오는지 확인합니다.

## 4. 모델 다운로드

기본 환경이 활성화된 상태에서 실행합니다.

```bash
python scripts/download_models.py
```

Qwen3-4B, Whisper, Nemotron 화자분리 모델을 준비합니다. SepFormer는 처음 음원분리가 필요한 녹음을 처리할 때 다운로드하므로 첫 분석은 더 오래 걸릴 수 있습니다.

## 5. 서버 시작

```bash
source .venv/bin/activate
export DRIVE_ORDER_SEPARATOR_PYTHON="$PWD/.venv-separator/bin/python"
bash demo.sh
```

**서버 PC의 브라우저**에서 터미널에 표시되는 다음 형식의 링크를 엽니다.

```text
http://127.0.0.1:8765/#key=서버에서_생성된_접속키
```

매장을 선택하고 마이크 권한을 허용한 뒤 짧게 녹음해 보세요. 서버를 종료하려면 실행 중인 터미널에서 `Ctrl+C`를 누릅니다. 다음에 다시 실행할 때는 이 단계의 세 명령만 입력하면 됩니다.

> 이 저장소의 기본 실행은 접속키를 사용하는 개인 서버입니다. 운영 중인 키 없는 공개 데모와 접속 방식이 다릅니다.

## 다른 PC나 휴대폰에서 접속하기

HTTPS 터널 또는 역방향 프록시를 서버의 **8765 포트**에 연결합니다. 서비스를 통해 도메인을 준비한 뒤, 서버를 종료하고 해당 도메인을 허용해 다시 실행합니다.

```bash
bash demo.sh --public-host YOUR_HTTPS_HOST
```

`YOUR_HTTPS_HOST`를 실제 도메인으로 바꾸세요. `https://`, 포트, 경로는 넣지 않습니다.

브라우저에서는 `https://도메인/#key=서버에서_생성된_접속키`로 접속합니다. 휴대폰의 마이크 사용에는 HTTPS가 필요합니다. 터널·프록시 구성은 별도로 해야 하며, 다른 기기의 `localhost` 주소로는 서버에 연결되지 않습니다.

## 메뉴와 저장 위치

- **매장·메뉴:** `demo/stores.json` — 메뉴의 `aliases`에 별칭을 추가하고 서버를 재시작합니다.
- **녹음·분석 결과:** `demo/sessions/` — 최종 주문, 발화 원문, 변경 이력과 메뉴 후보 기록을 저장합니다.
- **모델:** `models/` 및 Hugging Face 캐시 — 가중치는 Git에 포함되지 않습니다.

접속키와 녹음 결과는 공개하지 마세요. 분석 결과는 주문 초안이므로 메뉴·수량을 확인한 뒤 사용하세요.
