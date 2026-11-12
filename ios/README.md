# 모아오더 iPhone 앱

현재 웹 기능을 사용하는 **서버 연결형** iOS 앱 소스와 홈 화면 설치형 웹 앱(PWA)을 준비했다. 사용자는 iPhone 15, iOS 26.3.1/26.6을 사용하고 Mac은 사용할 수 없으므로 **현재 설치 경로는 PWA**다. iPhone 15 자체에서 화자분리·ASR·LLM을 실행하는 버전은 아직 아니다. 이 Linux PC에는 Xcode가 없어 Swift 빌드, 서명, 실기기 마이크 검증은 수행하지 못했다. 프로젝트 파일 구조만 검사했다.

## Mac 없이 홈 화면에 설치

1. iPhone과 분석 PC를 같은 공유기 네트워크에 연결한다. PC가 유선이어도 같은 네트워크면 된다. 게스트 Wi-Fi의 기기 간 차단은 해제되어 있어야 한다.
2. 개발용 HTTPS를 위해 `../demo/tls/MoaOrder-Local-CA.cer` **한 파일만** iPhone에 전달하고 인증서 프로파일을 설치한다. 개인키(`*-key.pem`)는 PC에 보관한다.
3. iPhone **설정 → 일반 → 정보 → 인증서 신뢰 설정**에서 `Moa Order Local Test CA`를 신뢰하도록 설정한다. 이번 PC에 접속하기 위한 개발용 인증서이며 30일 후 만료된다. 테스트를 마치면 설치한 프로파일을 제거할 수 있다. [Apple 설명](https://support.apple.com/en-us/102390)
4. PC 서버가 출력한 `https://192.168.0.35:8767/#key=…` 전체 링크를 Safari로 연다. 이 주소의 PC가 다른 네트워크에 있으면 사용할 수 없다. 휴대폰의 `localhost`는 PC를 뜻하지 않는다.
5. Safari **공유 → 홈 화면에 추가**를 선택하고 ‘웹 앱으로 열기’가 보이면 켠다. 홈 화면의 **모아오더** 아이콘으로 실행한다. 다시 연결 화면이 나오면 같은 전체 링크를 입력한다. [Apple 설치 안내](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios)
6. 매장 선택 → 녹음 시작 → 마이크 허용 → 녹음 종료 → 사람 아이콘별 최종 주문 확인.

녹음 중에는 앱을 화면에 열어 둔다. 앱 전환·잠금 시 녹음 종료와 저장을 시도한다. iOS가 즉시 앱을 중지하면 마지막 업로드가 끝나지 않을 수 있으므로 가능하면 먼저 녹음 종료 버튼을 누르고 저장 확인을 기다린다. 백그라운드 연속 녹음이나 오프라인 분석을 지원한다고 표시하지 않는다. 서버가 꺼져 있으면 연결 안내만 표시하며, 음성·결과·접속 키를 서비스 워커에 캐시하지 않는다.

## 서버 실행

기존 서버와 중복 실행하지 않는다. 같은 프로세스에서 PC용 HTTP와 휴대폰용 HTTPS를 함께 제공하고 같은 녹음 이력을 사용한다.

```bash
cd /home/ssonniee/Public/Nemotron/drive-order
# 최초 한 번만. IP가 바뀌면 다른 출력 폴더에 새 인증서를 만들고 휴대폰에도 다시 설치한다.
python scripts/create_phone_certificate.py --ip 192.168.0.35
bash demo.sh --phone-port 8767 --public-host 192.168.0.35 \
  --tls-cert demo/tls/server.pem --tls-key demo/tls/server-key.pem
```

이미 `demo/tls/`가 준비되어 있다면 인증서 생성은 생략한다. 포트 8767이 방화벽에서 차단되어 있으면 같은 LAN의 휴대폰에서 해당 포트로 접근할 수 있도록 PC의 네트워크 설정을 조정해야 한다. 인터넷 공개 터널이나 라우터 포트포워딩은 이 구성에 포함하지 않는다.

CPU만 사용할 때는 위 실행 명령에 `--device cpu`를 추가한다. Nemotron ASR은 `--asr nemo`, 음원분리 없는 비교 실행은 `--separator none`으로 선택할 수 있다. 분리를 끈 상태의 겹침 발화는 확인 대상으로 보류하며 확정 주문으로 자동 반영하지 않는다. 모델과 Python 의존성이 설치된 PC가 필요하다. 2026-11-12 CPU 시험은 고성능 데스크탑에서 9.2초 음성에 약 103.5초가 걸렸으므로 휴대폰 처리 속도로 해석하면 안 된다.

## 네이티브 iOS 앱 빌드

1. `ios` 폴더를 Mac으로 복사하고 `MoaOrder.xcodeproj`를 Xcode로 연다.
2. `MoaOrder` 타깃 → Signing & Capabilities에서 본인의 Team을 선택하고 Bundle Identifier를 본인의 고유 값으로 바꾼다. 서명 계정 정보는 프로젝트에 포함하지 않았다.
3. iPhone 15를 Mac과 연결하고 Xcode의 실행 대상으로 선택한다. 기기에서 요청하는 Developer Mode·신뢰 설정을 완료한다.
4. Run으로 설치·실행한 뒤 위 HTTPS 접속 링크를 입력한다. 로컬 인증서 구성이라면 앞의 인증서 설치/신뢰 과정도 필요하다.
5. 마이크 허용 후 웹과 동일한 주문 흐름을 테스트한다. JSON 다운로드는 iOS 공유 창으로 전달한다.

최소 배포 대상은 iOS 16이다. 사용자의 iOS 26.3.1/26.6 실기기 동작은 미검증이다. 소스에는 접속 키나 모델 가중치가 들어 있지 않다. 설정에는 서버 주소만 저장하며 인증은 WebKit의 쿠키로 유지한다. 녹음 중 새로고침·서버 변경을 차단하고, 선택한 서버의 마이크 요청에만 사용자 허용 창을 띄운다. 인증서 검증을 우회하는 코드는 없다.

네이티브 빌드에는 지원되는 macOS/Xcode와 서명 설정이 필요하다. 여기서 제공한 것은 빌드 전 소스이며 IPA/TestFlight 배포본이 아니다. [Xcode 시스템 요구사항](https://developer.apple.com/xcode/system-requirements)

## iPhone 단독 분석으로 가는 구현 방향

현재 Python/PyTorch 모델을 웹뷰에 넣는 것으로는 단독 실행이 되지 않는다. 서버 요청 자리를 iOS 추론 모듈로 교체하되, 메뉴·발화·주문 변경 JSON 형식은 웹과 공통으로 유지하는 방식이 적절하다.

| 단계 | iPhone 15에서 우선 평가할 후보 | 검증할 점 |
|---|---|---|
| 녹음·저장 | AVAudioEngine/AVAudioRecorder, 로컬 파일 | 장시간 녹음, 인터럽트, 저장 복구 |
| 화자분리 | Core ML 기반 화자분리, 예: FluidAudio | 한국어·차량 소음·화자 재등장, 겹침에서 화자 대응 |
| ASR | whisper.cpp의 다국어 base/small 양자화 모델, 또는 Nemotron의 모바일 런타임 | 실제 메뉴명 CER, 메모리·발열·지연. 영어 전용 `.en` 모델 제외 |
| 주문 해석 | llama.cpp의 소형 한국어 지원 모델 + 제한된 JSON 출력 + 현재 주문 검증기 이식 | 메뉴 교체/취소와 화자 격리. 모델 크기만 줄이면 정확도가 떨어질 수 있음 |
| 겹침 | 겹친 구간만 선택적으로 분리하거나 사용자에게 재확인 | SepFormer 제거만으로 동일 정확도를 보장할 수 없음 |

이 표는 제안이며 앱에 해당 런타임을 통합했다는 뜻이 아니다. [FluidAudio](https://github.com/FluidInference/FluidAudio), [whisper.cpp iOS 지원](https://github.com/ggml-org/whisper.cpp), [llama.cpp](https://github.com/ggml-org/llama.cpp)에서 각 모바일 실행 경로를 제공한다. iPhone 15에서 이 조합의 처리 시간과 정확도는 아직 측정하지 않았다. 작은 모델은 순차 로딩하고, 서버에서 쓰던 4B 모델의 메모리 사용량을 그대로 휴대폰에 요구하지 않도록 설계한다. Apple 음성 인식을 대안으로 쓸 경우에도 한국어·기기별 `supportsOnDeviceRecognition`을 확인하고 로컬 인식을 요구해야 하며, 자동 다화자 분리가 함께 해결된다고 가정하면 안 된다.

웹과 iOS 앱은 목적지, 메뉴, 주문 장부 형식을 공유한다. 웹은 우선 CPU/GPU 서버 연결을 유지하고 iOS는 단독 추론을 별도 구현하는 단계적 접근을 권한다. Pleos Connect SDK는 차량용 Android 앱 단계에서 별도로 연결해야 하며, 이번 iPhone 앱에 FusedLocation/NaviHelper가 탑재된 것은 아니다.
