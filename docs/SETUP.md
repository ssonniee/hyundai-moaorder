# 로컬 실행 안내

[프로젝트 소개](../README.md) · [웹 사용 안내](../demo/README.md)

기본 주문 해석은 Qwen3-4B 문맥 검증 + 매장별 별칭·오타 보조 방식입니다. 웹과 CLI 모두 이 구성을 사용합니다.

## 1. 환경 준비

저장소를 내려받고 루트 폴더에서 작업합니다.

```bash
git clone https://github.com/ssonniee/hyundai-moaorder.git
cd hyundai-moaorder
```

| 구성 | 준비 사항 |
|---|---|
| 기본 Python 환경 | CUDA를 사용할 수 있는 PyTorch와 [requirements.txt](../requirements.txt)의 패키지 |
| 음원분리 Python 환경 | 호환되는 PyTorch·Torchaudio·SpeechBrain |
| 시스템 도구 | ffmpeg |
| 모델 저장 공간 | 다운로드한 가중치를 둘 로컬 디스크 |

검증 환경의 패키지 버전은 [environment.txt](../environment.txt), [environment-separator.txt](../environment-separator.txt)에 기록되어 있습니다. 두 환경은 NeMo와 SpeechBrain 의존성을 분리하기 위한 구성입니다.

`demo.sh`와 `run.sh`는 개발 서버의 Python 경로를 기본값으로 사용합니다. 사용할 환경을 활성화한 뒤 지정합니다.

```bash
export DRIVE_ORDER_PYTHON="$(command -v python)"
python -m pip install -r requirements.txt
python scripts/download_models.py
```

다운로드 스크립트는 Qwen3-4B, Nemotron 화자분리, Whisper 가중치를 준비합니다. SepFormer는 분리용 환경에서 처음 실행할 때 다운로드합니다. 모델은 `models/` 또는 Hugging Face 캐시에 저장되며 Git에 포함되지 않습니다.

## 2. 음성 파일 분석

입력 음성과 매장 메뉴를 준비합니다. 아래 음성 경로와 분리용 Python 경로는 자신의 환경에 맞게 바꿉니다.

```bash
bash run.sh audio \
  --input /path/to/recording.wav \
  --menu examples/menu.json \
  --separator-python /path/to/separator-env/bin/python \
  --output results/my_first_order
```

웹 서버도 같은 파이프라인을 실행합니다. 이 기준 구현의 웹 서버에는 분리용 Python 경로를 받는 별도 옵션이 없으므로, 다른 PC에서는 [CLI 설정](../drive_order/__main__.py)의 `--separator-python` 기본값을 준비한 환경에 맞춰야 합니다.

```bash
bash demo.sh
```

기본 ASR은 Whisper입니다. 음원분리 구간은 `--separated-audio full`이 기본이며, `splice`로 겹친 부분만 교체할 수도 있습니다. 주문 해석은 `--order-backend qwen`이 기본이고, `llm`은 기존 LocalLLM 경로입니다. 선택 옵션 `--asr nemo`는 추가 NVIDIA ASR 모델과 호환 NeMo 환경이 필요합니다. `run.sh`는 인접한 `Nemotron-ASR/Speech` 경로가 있으면 함께 참조합니다.

## 3. 텍스트로 주문 해석만 확인

음성 인식을 반복하지 않고 주문 추가·변경·취소 로직을 확인합니다.

```bash
bash run.sh replay \
  --input examples/order_changes.jsonl \
  --menu examples/menu.json \
  --output results/my_order_replay
```

출력 경로는 매번 새 폴더를 사용합니다. 발화 입력은 시간순 JSONL이며, 서로 다른 녹음의 같은 화자 번호가 동일 인물을 뜻하지는 않습니다.

## 4. 결과 파일

| 파일 | 내용 |
|---|---|
| `utterances.jsonl` | 화자, 시작·종료 시간, 인식된 발화 |
| `orders.json` | 화자별 최신 주문 초안 |
| `order_events.jsonl` | 변경 근거와 적용 전·후 주문 |
| `menu_postprocessing.jsonl` | 원문, 매장별 별칭·오타 후보와 판단 기록 |
| `clips/`, `clips.json` | ASR 입력 음성과 구간 정보 |
| `metrics.json` | 실행 상태, 처리 시간, 메모리 측정값 |

목적지 입력은 `--trip examples/trip.json`으로 추가할 수 있습니다. 목적지와 메뉴의 매장 ID가 일치해야 합니다. 생성된 길 안내 요청 데이터는 SDK 호출 결과가 아닙니다.

## 5. 기능 검증

```bash
python -m unittest discover -s tests
```

정확도 검증은 [VALIDATION.md](../VALIDATION.md)를 참고합니다. 그 문서의 `results/` 경로는 과거 로컬 실행 결과이며 새로 복제한 저장소에는 포함되지 않습니다.
