# Android APK 빌드

<details>
<summary>개발자용 빌드 방법 펼치기</summary>

JDK 17 이상과 Android SDK(Platform 35, Build Tools 35.0.0)가 필요합니다.
`ANDROID_HOME`을 SDK 설치 경로로 설정하세요.

```bash
cd android
# 최초 1회: 저장소 밖에 서명 키 생성
keytool -genkeypair -keystore "$HOME/moaorder-release.jks" -alias moaorder \
  -keyalg RSA -keysize 3072 -validity 10000

export MOA_KEYSTORE="$HOME/moaorder-release.jks"
export MOA_KEY_ALIAS=moaorder
read -rsp '서명 비밀번호: ' MOA_STORE_PASSWORD; echo
export MOA_STORE_PASSWORD
export MOA_KEY_PASSWORD="$MOA_STORE_PASSWORD"
./gradlew assembleRelease lintRelease
mkdir -p ../apk
cp app/build/outputs/apk/release/app-release.apk ../apk/MoaOrder_모아오더_release.apk
```

서명 키와 비밀번호는 Git에 올리지 말고 보관하세요. 동일한 앱을 업데이트할 때 같은 키가 필요합니다.

서버 주소를 바꾸려면 `android/app/src/main/java/ai/moaorder/app/MainActivity.java`의 `HOME`과 `HOST`를 함께 수정하고 다시 빌드하세요. 마이크 사용을 위해 유효한 HTTPS 주소가 필요합니다.

모델은 GPU 서버에서 실행됩니다. 서버 구성은 [로컬에서 실행하는 방법](SETUP.md)을 참고하세요. APK에는 API 키나 모델 가중치를 포함하지 않습니다.

</details>
