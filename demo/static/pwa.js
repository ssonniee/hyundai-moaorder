'use strict';
// Installation does not download speech models. API/audio responses are never cached.
function showConnectionForm(needsKey) {
  document.getElementById('connectionPanel').hidden = false;
  document.getElementById('pairForm').hidden = !needsKey;
  document.getElementById('connectionTitle').textContent = needsKey ? '모아오더 연결하기' : '서버 연결을 확인해 주세요';
  document.getElementById('connectionMessage').textContent = needsKey
    ? '처음 실행하거나 연결이 만료되면 접속 링크 또는 키를 입력해 주세요.'
    : '인터넷 연결과 분석 서버가 켜져 있는지 확인해 주세요. 연결이 돌아오면 다시 연결을 눌러 주세요.';
}
document.getElementById('pairForm').onsubmit = async event => {
  event.preventDefault();
  const input = document.getElementById('pairKey'), button = event.submitter;
  const error = document.getElementById('pairError');
  error.textContent = ''; button.disabled = true;
  try {
    let key = input.value.trim();
    if (/^https?:\/\//i.test(key)) {
      const url = new URL(key);
      if (url.origin !== location.origin) throw new Error('현재 앱과 같은 서버의 접속 링크를 입력해 주세요.');
      key = new URLSearchParams(url.hash.slice(1)).get('key') || '';
    }
    if (!key) throw new Error('접속 키가 포함된 전체 링크를 입력해 주세요.');
    const response = await fetch('/api/pair', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Drive-Order': '1'}, body: JSON.stringify({key})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '연결하지 못했어요.');
    input.value = ''; history.replaceState(null, '', '/'); location.reload();
  } catch (e) { error.textContent = e.message; }
  finally { button.disabled = false; }
};
document.getElementById('reconnectBtn').onclick = () => location.reload();
let installPrompt;
const installed = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
document.getElementById('installGuide').hidden = installed;
window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault(); installPrompt = event;
  document.getElementById('installBtn').hidden = false;
});
document.getElementById('installBtn').onclick = async () => {
  if (!installPrompt) return;
  await installPrompt.prompt(); installPrompt = null;
  document.getElementById('installBtn').hidden = true;
};
window.addEventListener('appinstalled', () => document.getElementById('installGuide').hidden = true);
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
// Mobile background execution can stop the microphone. End and save explicitly.
document.addEventListener('visibilitychange', () => {
  if (document.hidden && typeof phase !== 'undefined' && phase === 'recording') {
    toast('화면을 벗어나 녹음을 마쳤어요. 저장 상태를 확인해 주세요.');
    stopRecording();
  }
});
