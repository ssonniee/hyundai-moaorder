# Pleos Android 연결 계약

이 폴더는 다음 앱 단계의 연동 명세다. SDK 바이너리나 Android 프로젝트는 아직 포함하지 않았으며, 실제 차량·에뮬레이터 호출을 검증한 상태가 아니다. Python `trip.py`는 목적지와 메뉴의 일치 여부 및 좌표를 검사하고 요청 데이터를 만든다. `status=pending_android_adapter`는 실제 길 안내가 시작되지 않았다는 뜻이다.

## 사용자 흐름

1. 식당/드라이브스루의 **지점** 선택 → `store_id`, POI ID, 좌표 확정.
2. 지점 메뉴를 조회/로드하고 해당 버전을 주문 세션에 고정.
3. NaviHelper로 목적지 요청 → SDK 콜백에서 경로 탐색 성공/실패 확인.
4. 사용자가 녹음 시작 → 녹음 중 상태 표시, 길 안내와 병행.
5. 화자별 발화와 주문 변경 결과를 수신해 주문 초안을 갱신.
6. 도착 또는 녹음 종료 → 미확인 발화와 최종 수량·옵션 확인.

현재 CLI는 4–6의 녹음 완료 파일 처리 부분을 검증한다. 서버 연결 시 녹음 세션마다 화자 cache를 유지해야 한다. 앱에서 잘라 보낸 파일마다 새로운 `audio` 명령을 실행하면 화자 ID가 다시 시작되므로 이 CLI를 그대로 실시간 API처럼 사용해서는 안 된다.

## FusedLocation

공식 안내의 진입점은 `FusedLocation`이며, `isSupported()` → `initialize()` → `registerFusedLocationCallback()` → `unregisterFusedLocationCallback()` → `release()` 수명주기를 따른다. 한 번의 조회에는 `getLastKnownLocation()`을 사용한다. 마지막 위치는 새로 측정된 위치라는 보장이 없으므로 timestamp를 함께 검사한다. SDK 미지원, null 위치, 오류는 정상적인 상태 분기로 다룬다. [공식 소개](https://document.pleos.ai/en/docs/pleos-only/connect-sdk-pleos/FusedLocation/intro)

권한은 `pleos.car.permission.FUSED_LOCATION`이다. 차량 개인정보 설정으로 위치 접근이 차단된 경우 `showLocationAccessBlockedPopup()`을 사용하며, 이 함수가 권한을 부여하는 것은 아니다. Android/Google Fused Location의 동작을 Pleos SDK에 그대로 적용하지 않는다. [공식 권한 안내](https://document.pleos.ai/en/docs/pleos-only/connect-sdk-pleos/FusedLocation/declaring-permissions)

앱이 엔진에 전달할 위치 데이터 예:

```json
{"latitude":37.5,"longitude":127.04,"timestamp":"2026-11-11T18:00:00+09:00","source":"FusedLocation"}
```

위치는 목적지 선택과 세션에 연결한다. 좌표만으로 실제 지점 메뉴가 확정되지는 않는다. 메뉴는 사용자가 선택한 `store_id`로 조회한다.

## NaviHelper

목적지 설정은 `requestRoute(RouteInfo(...))`, 조회는 `getDestinationInfo()`, 취소는 `cancelRoute()`를 사용한다. `requestRoute()` 반환만으로 경로 탐색 성공으로 표시하면 안 된다. `NaviHelperEventListener`의 `onRouteStarted`, `onRoutingCompleted`, `onDestinationChanged`, `onError`에서 상태를 갱신한다. [공식 목적지 안내](https://document.pleos.ai/en/docs/pleos-only/connect-sdk-pleos/NaviHelper/destinations)

사용 API에 맞춰 `pleos.car.permission.NAVI_ROUTE_SEARCH`, `pleos.car.permission.NAVI_ROUTE`를 선언한다. 내비게이션 화면 요청까지 사용하는 경우 `pleos.car.permission.NAVI_CUSTOM_MAP`도 확인한다. [공식 권한 안내](https://document.pleos.ai/en/api-reference/connect-sdk-pleos/NaviHelper/declaring-permissions)

`navigation_request.json`의 `route.name`을 SDK `RouteInfo.poiName`에, `poi_id`를 `poiId`에, 위도·경도·주소를 각각 대응한다. Kotlin의 실제 생성자와 패키지 import는 프로젝트에 설치한 SDK 버전의 API 문서에서 확정한다. 현재 계약은 POI ID가 없는 경우도 표현하지만 실제 SDK 요청 가능 여부는 앱 단계에서 검사해야 한다.

## 목적지/세션 변경

`session_id`와 `store_id`를 요청·응답마다 포함한다. 지점 변경 콜백을 받으면 진행 중인 이전 세션 결과를 새 지점 장부에 적용하지 않는다. 기존 주문은 이전 지점에 보존하고 새 메뉴로 재확인한다. 경로 변경과 지점 변경은 구별한다. 동일 지점의 경로만 다시 탐색한 경우 주문 세션을 재시작할 필요는 없다.

모델의 `speaker_0` 등은 한 녹음 안의 익명 화자이며 좌석/실명과 무관하다. 앱은 사용자가 화자 라벨을 확인하거나 이름을 붙이는 기능을 제공해야 한다.
