'use strict';
let micChecking = false;

function microphoneError(error) {
  const messages = {
    NotFoundError: '이 브라우저에서 녹음 장치를 찾지 못했어요. 기기의 마이크 연결과 소리 설정의 입력 장치를 확인해 주세요.',
    DevicesNotFoundError: '이 브라우저에서 녹음 장치를 찾지 못했어요. 기기의 마이크 연결과 소리 설정의 입력 장치를 확인해 주세요.',
    NotAllowedError: '마이크 사용이 허용되지 않았어요. 브라우저의 사이트 권한과 기기의 앱 마이크 권한을 허용해 주세요.',
    PermissionDeniedError: '마이크 사용이 허용되지 않았어요. 브라우저와 기기의 마이크 권한을 확인해 주세요.',
    NotReadableError: '마이크를 열지 못했어요. 다른 녹음·회의 앱의 마이크 사용을 종료하고 다시 시도해 주세요.',
    TrackStartError: '마이크를 열지 못했어요. 다른 녹음·회의 앱의 마이크 사용을 종료하고 다시 시도해 주세요.',
    OverconstrainedError: '선택한 마이크를 사용할 수 없어요. 기본 마이크 또는 다른 입력 장치를 선택해 주세요.',
    SecurityError: '이 브라우저의 설정에서 마이크 사용이 제한되어 있어요. 일반 브라우저의 사이트 권한을 확인해 주세요.',
    UnsupportedMicrophone: '이 화면에서는 마이크에 접근할 수 없어요. HTTPS 주소 또는 이 PC의 localhost 주소를 일반 브라우저로 열어 주세요.',
    AbortError: '마이크 연결이 중단됐어요. 다시 시도해 주세요.'
  };
  const message = messages[error.name] || error.message || '마이크 연결을 확인해 주세요.';
  $('micStatus').textContent = message; $('micStatus').dataset.state = 'error';
  $('micHelp').hidden = false; $('micHelpText').textContent = message;
  return message;
}

async function refreshMicrophones() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  try {
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audioinput');
    const select = $('microphoneSelect'), selected = select.value;
    const options = [new Option('기본 마이크', '')];
    devices.filter(d => d.deviceId && d.deviceId !== 'default').forEach((d, i) => options.push(new Option(d.label || `마이크 ${i + 1}`, d.deviceId)));
    if (selected && !options.some(o => o.value === selected)) options.push(new Option('이전 마이크 · 연결을 확인해 주세요', selected));
    select.replaceChildren(...options); select.value = selected;
    // An empty list before permission is granted does not prove there is no hardware.
  } catch { /* Some browsers hide device information until microphone permission is granted. */ }
}

async function openMicrophone() {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    const error = new Error(); error.name = 'UnsupportedMicrophone'; throw error;
  }
  const device = $('microphoneSelect').value;
  // Open the default device without audio format constraints for browser compatibility.
  const media = await navigator.mediaDevices.getUserMedia({audio: device ? {deviceId: {exact: device}} : true, video: false});
  const track = media.getAudioTracks()[0];
  if (!track || track.readyState !== 'live') {
    media.getTracks().forEach(t => t.stop());
    const error = new Error(); error.name = 'NotFoundError'; throw error;
  }
  // Processing preferences are best-effort and must not block a valid recording device.
  if (track.applyConstraints) {
    try { await track.applyConstraints({channelCount: {ideal: 1}, echoCancellation: {ideal: true}, noiseSuppression: {ideal: false}, autoGainControl: {ideal: true}}); }
    catch { /* Keep the device's working settings. */ }
  }
  $('micStatus').textContent = `마이크 연결됨 · ${track.label || '선택한 입력 장치'}`;
  $('micStatus').dataset.state = 'ready'; $('micHelp').hidden = true;
  await refreshMicrophones();
  return media;
}

async function checkMicrophone() {
  if (busy()) return;
  micChecking = true; lockSetup(true); $('startBtn').disabled = true;
  $('micStatus').textContent = '마이크 권한을 허용한 뒤 짧게 말해 주세요. 음성은 저장하거나 보내지 않아요.';
  $('micStatus').dataset.state = 'checking'; $('micHelp').hidden = true;
  let input, context, frame, peak = 0;
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (Audio) { context = new Audio(); await context.resume(); }
    input = await openMicrophone();
    if (context) {
      const source = context.createMediaStreamSource(input), analyser = context.createAnalyser();
      analyser.fftSize = 1024; source.connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      $('micLevel').hidden = false;
      $('micStatus').textContent = '마이크 연결됨 · 3초 동안 말해 주세요. 음성은 저장하거나 보내지 않아요.';
      const draw = () => {
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((total, value) => total + value * value, 0) / samples.length);
        peak = Math.max(peak, rms); $('micLevel').value = Math.min(100, rms * 600);
        frame = requestAnimationFrame(draw);
      };
      draw(); await new Promise(resolve => setTimeout(resolve, 3000));
      $('micStatus').textContent = peak > .003 ? '마이크 확인 완료 · 실제 소리 입력이 감지됐어요.' : '마이크는 연결됐지만 소리가 작거나 없어요. 음소거와 입력 장치를 확인해 주세요.';
      source.disconnect();
    } else $('micStatus').textContent = '마이크 연결을 확인했어요. 녹음 후 재생해서 소리를 확인해 주세요.';
  } catch (error) { microphoneError(error); }
  finally {
    cancelAnimationFrame(frame); input?.getTracks().forEach(t => t.stop());
    if (context && context.state !== 'closed') await context.close().catch(() => {});
    $('micLevel').hidden = true; micChecking = false; lockSetup(phase !== 'idle');
    $('startBtn').disabled = !position || !config.ready || phase !== 'idle';
  }
}

async function copyBrowserLink() {
  try {
    const {key} = await api('/api/access-link', {method: 'POST', json: {}});
    const url = new URL('/', location.origin); url.hash = new URLSearchParams({key}).toString();
    // Use the browser's actual origin, including a forwarded port, never the server's localhost.
    const input = $('browserLink'); input.hidden = false; input.value = url.href;
    try { await navigator.clipboard.writeText(url.href); toast('접속 링크를 복사했어요. 별도로 연 Chrome·Edge·Safari의 주소창에 붙여넣어 주세요.'); }
    catch { input.focus(); input.select(); toast('표시된 주소를 복사해 일반 브라우저의 주소창에 붙여넣어 주세요.'); }
  } catch (error) { toast(error.message); }
}

function setupMicrophones() {
  $('checkMicBtn').onclick = checkMicrophone;
  $('copyBrowserLink').onclick = copyBrowserLink;
  $('microphoneSelect').onchange = () => {
    $('micStatus').textContent = '마이크를 바꿨어요. 마이크 확인을 눌러 입력을 확인해 주세요.';
    $('micStatus').dataset.state = ''; $('micHelp').hidden = true;
  };
  refreshMicrophones();
  navigator.mediaDevices?.addEventListener?.('devicechange', refreshMicrophones);
}
