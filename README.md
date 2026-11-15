# 모아오더(MoaOrder)

**함께 가는 길, 주문은 하나로.**

목적지로 이동하며 나눈 대화에서 누가 무엇을 주문할지 정리하는 음성 기반 주문 도우미입니다.
선택한 매장의 메뉴를 참고해 화자별 발화를 기록하고, 메뉴 추가·변경·취소를 반영하여 주문서를 작성합니다.
목적지를 선택하고 직접 녹음하거나 음성 파일을 올려, 화자별 주문 결과를 확인할 수 있습니다.

## Try MoaOrder

### 🌐 Live Web Demo

Experience MoaOrder directly in your browser.

[**Launch MoaOrder →**](https://udder-purify-retract.ngrok-free.dev/)

---

## 🎬 Watch MoaOrder in Action

See how MoaOrder turns multi-speaker conversations into a clear, organized order.

[**Watch the Demo →**](https://youtu.be/Sa-5V4HNdrk)

---

## 실행 Pipeline
FusedLocation과 NaviHelper의 Android 연동은 추후 진행 예정.

```mermaid
flowchart LR
  A[사용자가 목적지 선택] --> B[지점 ID에 맞는 메뉴 목록]
  A --> N[NaviHelper Android 연동 예정]
  L[FusedLocation Android 연동 예정] --> A
  W[녹음 파일] --> D[Nemotron 스트리밍 화자분리]
  D --> S{겹침 여부}
  S -->|없음| R[화자별 ASR]
  S -->|두 화자| P[SepFormer 음원분리와 화자 대응]
  P --> R
  R --> T[화자·시간·발화 원문 저장]
  B --> H[매장별 별칭·오타 후보 생성]
  T --> H
  B --> Q[Qwen 문맥 기반 주문 변경 해석]
  T --> Q
  H --> Q
  C[모든 화자의 주문 상태와 최근 대화] --> Q
  Q --> V[메뉴·증거·수량 검증]
  V --> O[화자별 주문 초안과 변경 이력]
```

---

[**Self-hosting Guide →**](docs/SETUP.md)
