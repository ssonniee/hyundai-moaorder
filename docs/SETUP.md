# 서버 설치 및 실행

CUDA 사용이 가능한 Linux GPU 서버와 Python 3.11 환경을 기준으로 합니다. 개발 시 RTX 5090 32GB를 사용했습니다. 다른 GPU에서의 최소 메모리는 검증하지 않았습니다. 모델을 처음 받을 때 인터넷과 충분한 디스크 공간이 필요합니다.

모든 명령은 저장소 루트에서 터미널에 입력합니다. CUDA 드라이버와 호환되는 PyTorch를 먼저 준비하세요.

## 1. 기본 Python 환경

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/download_models.py
```

모델 다운로드는 Qwen3-4B, Whisper, Nemotron 화자분리를 준비합니다. 다운로드 오류가 발생하면 정상 완료한 뒤 서버를 시작하세요. 기본 환경에서 GPU를 확인합니다.

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

`True`가 나와야 기본 CUDA 실행이 가능합니다. 음성 변환은 시스템 ffmpeg를 사용하며, 없으면 설치된 imageio-ffmpeg를 사용합니다.

## 2. 음원분리 환경

주 처리 환경과 SpeechBrain의 의존성을 분리합니다. 아래 PyTorch 조합은 개발 서버에서 사용한 CUDA 12.8 조합이며, 서버 드라이버가 이를 지원해야 합니다.

```bash
python3.11 -m venv .venv-separator
.venv-separator/bin/python -m pip install --upgrade pip
.venv-separator/bin/python -m pip install torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128
.venv-separator/bin/python -m pip install -r requirements-separator.txt
export DRIVE_ORDER_SEPARATOR_PYTHON="$PWD/.venv-separator/bin/python"
```

SepFormer 가중치는 첫 음원분리 실행 때 다운로드됩니다. 새 터미널에서는 기본 환경 활성화와 위 환경변수 설정을 다시 해주세요.

## 3. 웹 서버 시작

```bash
source .venv/bin/activate
export DRIVE_ORDER_SEPARATOR_PYTHON="$PWD/.venv-separator/bin/python"
bash demo.sh
```

서버 PC의 브라우저에서 터미널에 출력되는 `http://127.0.0.1:8765/#key=...` 링크를 엽니다. 다른 Python 환경을 쓰려면 `DRIVE_ORDER_PYTHON`에 실행 파일 경로를 지정합니다.

다른 기기에서 접속하려면 HTTPS 역방향 프록시 또는 터널을 8765 포트에 연결합니다. 할당받은 호스트를 서버에 허용하세요.

```bash
bash demo.sh --public-host YOUR_HTTPS_HOST
```

`YOUR_HTTPS_HOST`에는 `https://`나 경로 없이 실제 도메인을 넣습니다. HTTPS 주소 뒤에 서버가 출력한 `#key=...`를 붙여 접속합니다. 휴대폰의 localhost는 서버 PC가 아니며, 마이크 권한에는 HTTPS가 필요합니다. 터널·프록시는 별도로 구성해야 합니다.

## 4. 메뉴와 실행 확인

매장 목록은 `demo/stores.json`에 있습니다. 각 메뉴의 `aliases`에 매장별 별칭을 추가할 수 있습니다. 서버를 재시작하면 목록을 다시 읽습니다.

웹에서 목적지를 선택하고 짧게 녹음해 결과를 확인합니다. 기본은 Qwen 문맥 검증 + 별칭·오타 후보 보조이며, 녹음 원문을 덮어쓰지 않습니다.

## 저장되는 결과

웹 녹음과 결과는 `demo/sessions/`, CLI 결과는 지정한 출력 폴더에 저장됩니다. `orders.json`은 최종 주문, `order_events.jsonl`은 변경 이력, `menu_postprocessing.jsonl`은 원문·메뉴 후보·판단 기록입니다. 접속키와 이 폴더들은 Git에 올리지 마세요.

분석 결과는 주문 초안입니다. 없는 메뉴 대체, 모호한 취소, ASR 오류가 남을 수 있으므로 사용자가 최종 주문을 확인해야 합니다.
