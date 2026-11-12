'use strict';
const $ = id => document.getElementById(id);
const presets = {
  cafe: '아메리카노 | 아아, 아메\n카페라떼 | 라떼, 카페 라떼\n바닐라라떼 | 바닐라 라떼\n카푸치노\n초콜릿 라떼 | 초코라떼\n카페모카 | 모카\n딸기 스무디\n레몬에이드',
  burger: '불고기버거 | 불고기 버거\n치즈버거 | 치즈 버거\n치킨버거 | 치킨 버거\n더블치즈버거 | 더블 치즈 버거\n감자튀김 | 감자 튀김, 프렌치프라이\n치킨너겟 | 너겟\n콜라\n제로콜라 | 제로 콜라\n사이다',
  meal: '김치찌개 | 김치 찌개\n된장찌개 | 된장 찌개\n비빔밥\n불고기\n제육볶음 | 제육\n돈까스 | 돈가스\n우동\n공기밥 | 공깃밥',
  custom: ''
};
let map, marker, position, current = null, phase = 'idle', recorder, stream, clock, meter, audioContext;
let chunks = 0, pending = new Map(), uploadQueue = Promise.resolve(), uploadError = null;
let started = 0, elapsed = 0, cancelled = false, config = {}, polling = 0, toastTimer;
let stores = [], selectedStore = null;
let meterSource = null, meterSink = null, savedBytes = 0;
let previewStream = null, previewStarting = false, previewGeneration = 0;
let appendTarget = null;
let accumulatedSeconds = 0, selectedUpload = null, uploadIndex = 0;

function pendingSummary(message = '매장을 고르고 주문 대화를 녹음해 주세요.', label = '분석 대기', state = 'idle') {
  const working = ['saving', 'queued', 'processing'].includes(state);
  $('orderSummary').dataset.state = state;
  $('orderCards').setAttribute('aria-busy', String(working));
  if (working) {
    let status = $('orderCards').querySelector('.analysis-status');
    if (!status) {
      status = node('div', undefined, 'analysis-status'); status.setAttribute('role', 'status');
      const spinner = node('span', undefined, 'analysis-spinner'); spinner.setAttribute('aria-hidden', 'true');
      status.append(spinner, node('strong'), node('p')); $('orderCards').replaceChildren(status);
    }
    status.querySelector('strong').textContent = state === 'saving' ? '녹음을 저장하고 있어요' : state === 'queued' ? '주문 분석을 기다리고 있어요' : '주문을 분석하고 있어요';
    status.querySelector('p').textContent = message;
  } else $('orderCards').replaceChildren(node('p', message, 'summary-empty'));
  $('summaryCount').textContent = label;
  $('summaryDescription').hidden = true;
  $('reviewBanner').hidden = true;
}
function personAvatar(index, small = false) {
  const palettes = [
    ['#e2eee0', '#ddb291', '#3d332f', '#527e65'], ['#eee4f5', '#a97555', '#292b39', '#8d6ab2'],
    ['#f8e6d7', '#f0c9a7', '#985b32', '#c17c49'], ['#deebf5', '#c68f6b', '#353b4b', '#527eab'],
    ['#f7e2e5', '#edc8ae', '#665052', '#b86f80'], ['#e3edee', '#95684c', '#24262d', '#4b8990'],
    ['#eee9d9', '#d7a584', '#d8d8d1', '#9b8952'], ['#e7e8f6', '#e6b291', '#75523c', '#747ab0']
  ];
  const [bg, skin, hair, shirt] = palettes[index % palettes.length];
  const hairStyles = [
    'M18 29V22C18 8 46 8 46 23V29L40 21L25 23L21 30Z',
    'M16 42V25C16 6 48 6 48 25V43L41 40V22L24 21V41Z',
    'M17 29C12 18 22 11 27 14C33 7 45 14 46 20L46 30L41 24L23 25Z',
    'M18 28C15 12 42 7 46 23L44 30L38 20L21 25Z',
    'M16 43V25C13 14 25 8 32 12C45 8 51 20 47 29V43L42 39V23L22 23V39Z',
    'M18 26C14 22 18 14 23 15C25 8 33 10 36 13C44 10 49 18 45 26L40 23L22 27Z',
    'M18 29V22C19 10 44 10 46 23V29L40 22L32 19L24 23Z',
    'M17 30V23C16 12 30 8 37 12C47 14 49 24 45 30L40 20L25 24L22 31Z'
  ];
  const glasses = [1, 3, 6].includes(index % 8) ? '<g fill="none" stroke="#514a46" stroke-width="1.4"><rect x="22" y="28" width="9" height="7" rx="3"/><rect x="33" y="28" width="9" height="7" rx="3"/><path d="M31 30h2"/></g>' : '';
  const avatar = node('span', undefined, 'person-avatar' + (small ? ' compact' : ''));
  avatar.setAttribute('role', 'img'); avatar.setAttribute('aria-label', `참여자 ${index + 1}`);
  avatar.title = `참여자 ${index + 1}`; avatar.dataset.person = String(index + 1);
  // All SVG markup and colors are local constants; no inferred identity or user HTML.
  avatar.innerHTML = `<svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="20" fill="${bg}"/><path d="M10 64V57Q12 44 32 44Q52 44 54 57V64Z" fill="${shirt}"/><path d="M27 40h10v9q-5 6-10 0Z" fill="${skin}"/><path d="${hairStyles[index % 8]}" fill="${hair}"/><ellipse cx="32" cy="30" rx="12" ry="15" fill="${skin}"/><path d="${hairStyles[index % 8]}" fill="${hair}"/><g fill="#42362f"><circle cx="27" cy="30" r="1.2"/><circle cx="37" cy="30" r="1.2"/></g><path d="M28 37q4 3 8 0" fill="none" stroke="#946252" stroke-width="1.4" stroke-linecap="round"/>${glasses}</svg>`;
  const number = node('span', String(index + 1), 'person-number'); number.setAttribute('aria-hidden', 'true'); avatar.append(number);
  return avatar;
}

function node(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
function actionIcon(kind) {
  const paths = {
    pin: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1114 0Z"/><circle cx="12" cy="10" r="2.5"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    play: '<path d="m8 5 11 7-11 7Z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>'
  };
  const icon = node('span', undefined, kind === 'pin' ? 'pin-symbol' : 'action-icon');
  icon.setAttribute('aria-hidden', 'true');
  icon.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[kind]}</svg>`;
  return icon;
}
function recordingControl(id, kind, label) {
  const text = node('span', undefined, 'control-label');
  text.append(node('span', '녹음 ', 'control-context'), document.createTextNode(label));
  $(id).replaceChildren(actionIcon(kind), text);
  $(id).setAttribute('aria-label', `녹음 ${label}`);
}
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 7000); }
function timeLabel(seconds) { seconds = Math.max(0, Math.floor(seconds)); return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; }
function busy() { return previewStarting || micChecking || ['starting', 'recording', 'paused', 'stopping', 'processing', 'upload_failed', 'uploading', 'deleting', 'delete_failed'].includes(phase); }
async function api(path, options = {}) {
  const headers = {...options.headers, 'X-Drive-Order': '1'};
  if (options.json !== undefined) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.json); delete options.json; }
  const response = await fetch(path, {...options, headers});
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.error || `요청 실패 (${response.status})`); error.status = response.status; throw error; }
  return data;
}
function lockSetup(locked) {
  locked = locked || Boolean(appendTarget);
  $('recorderCard').dataset.phase = phase;
  $('checkMicBtn').disabled = busy(); $('microphoneSelect').disabled = busy() || Boolean(previewStream);
  $('storeSearch').disabled = busy() || Boolean(appendTarget); $('searchStoresBtn').disabled = $('storeSearch').disabled;
  if (busy()) $('searchResults').hidden = true;
  syncMicButton(); syncRecordingActions();
  ['placeName', 'menuText', 'lat', 'lng', 'coordinateBtn'].forEach(id => $(id).disabled = locked || (Boolean(selectedStore) && ['placeName', 'menuText'].includes(id)));
  document.querySelectorAll('[data-menu]').forEach(b => b.disabled = locked);
  document.querySelectorAll('[data-store]').forEach(b => b.disabled = busy() || Boolean(appendTarget));
  $('newBtn').disabled = busy() || (!current && !appendTarget);
  $('appendOrderBtn').disabled = busy() || phase !== 'complete' || !config.append_orders;
  $('returnOrderBtn').disabled = busy();
  document.querySelectorAll('.history-add').forEach(b => b.disabled = busy());
}
function steps(which) { for (let i = 1; i <= 3; i++) $('step' + i).classList.toggle('active', i === which); }
function menuItems() {
  const items = $('menuText').value.split('\n').map(s => s.trim()).filter(Boolean).map(line => {
    const [name, ...rest] = line.split('|');
    return {name: name.trim(), aliases: rest.join('|').split(',').map(s => s.trim()).filter(Boolean)};
  });
  if (!items.length) throw new Error('이 매장에서 주문할 메뉴를 하나 이상 입력해 주세요.');
  if (items.length > 100) throw new Error('메뉴는 최대 100개까지 입력할 수 있어요.');
  return items;
}
function renderMenu() {
  $('menuChips').replaceChildren();
  try { menuItems().slice(0, 10).forEach(item => $('menuChips').append(node('span', item.name))); }
  catch { $('menuChips').append(node('span', '주문할 메뉴를 아래에 입력해 주세요')); }
}
function updateMenuTitle() {
  const name = selectedStore?.name || (position ? $('placeName').value.trim() : '');
  $('menuTitle').textContent = name ? `“${name}”의 메뉴` : '선택한 매장의 메뉴';
  $('menuDescription').hidden = true;
}
function syncStoreSelection() {
  document.querySelectorAll('[data-store]').forEach(b => {
    const selected = b.dataset.store === selectedStore?.id;
    b.classList.toggle('selected', selected); b.setAttribute('aria-pressed', String(selected));
  });
  $('customMenuTabs').hidden = Boolean(selectedStore) || !position;
  $('menuSource').textContent = selectedStore ? `${selectedStore.items.length}개 메뉴` : position ? '직접 설정' : '선택 전';
  updateMenuTitle();
  $('menuEditor').querySelector('summary').textContent = selectedStore ? '메뉴 이름과 별칭 보기 ＋' : '메뉴 수정하기 ＋';
  $('menuNote').textContent = selectedStore ? '직접 제공해 주신 메뉴입니다. 이 목록을 기준으로 음성과 주문 변경을 분석합니다.' : '지도에서 직접 지정한 위치에는 주문할 메뉴를 입력해 주세요.';
}
function chooseStore(store) {
  if (appendTarget) return toast('추가 주문은 기존 매장의 메뉴로 진행합니다. 다른 매장은 새로운 주문을 눌러 주세요.');
  if (busy()) return toast('진행 중인 녹음과 분석이 끝난 뒤 매장을 바꿔 주세요.');
  if (map) { map.stop(); map.setView([store.latitude, store.longitude], 16, {animate: false}); }
  choosePosition(store.latitude, store.longitude, store);
  localStorage.setItem('moa-store', store.id);
}
function searchStores() {
  if (busy()) return;
  const query = $('storeSearch').value.trim().toLocaleLowerCase().replace(/\s+/g, '');
  const matches = stores.filter(store => [store.name, store.address, store.category, ...store.items.map(item => item.name)]
    .some(value => String(value || '').toLocaleLowerCase().replace(/\s+/g, '').includes(query)));
  $('storeList').replaceChildren();
  $('searchResults').hidden = false;
  $('searchStatus').textContent = matches.length ? `${query ? '검색 결과' : '등록된 매장'} ${matches.length}곳${matches.length > 6 ? ' · 6곳 표시, 검색어를 더 입력해 주세요' : ''}` : '검색 결과가 없어요. 다른 이름으로 검색하거나 지도에서 직접 지정해 주세요.';
  matches.slice(0, 6).forEach(store => {
    const index = stores.indexOf(store);
    const button = node('button', undefined, 'store-choice'); button.type = 'button'; button.dataset.store = store.id;
    const info = node('span', undefined, 'store-info');
    info.append(node('strong', store.name), node('small', `${store.address} · 메뉴 ${store.items.length}개`));
    button.append(node('span', String(index + 1), 'store-number'), info, node('span', '↗', 'store-arrow'));
    button.onclick = () => chooseStore(store); $('storeList').append(button);
  });
  syncStoreSelection();
}
function setupStoreSearch() {
  $('storeSearch').oninput = searchStores;
  $('storeSearch').onfocus = searchStores;
  $('searchStoresBtn').onclick = searchStores;
  $('destinationSearch').onkeydown = event => {
    if (event.key === 'Escape') { event.preventDefault(); $('searchResults').hidden = true; $('storeSearch').focus(); $('searchResults').hidden = true; }
    if ((event.key === 'ArrowDown' || event.key === 'Enter') && event.target === $('storeSearch')) {
      event.preventDefault(); searchStores(); $('storeList').querySelector('button')?.focus();
    }
  };
  document.addEventListener('click', event => {
    if (!$('destinationSearch').contains(event.target)) $('searchResults').hidden = true;
  });
}
function renderStores() {
  // Map markers stay independent from the bounded search results.
  stores.forEach((store, index) => {
    if (map) {
      const icon = L.divIcon({html: `<span class="store-map-pin">${index + 1}</span>`, className: '', iconSize: [34, 34], iconAnchor: [17, 17]});
      const pin = L.marker([store.latitude, store.longitude], {icon, title: store.name, bubblingMouseEvents: false}).addTo(map);
      pin.bindTooltip(node('span', store.name)); pin.on('click', () => chooseStore(store));
    }
  });
  syncStoreSelection();
}
function choosePosition(lat, lng, store = null) {
  if (appendTarget) return;
  if (busy()) return toast('지금 대화를 마친 뒤 새로운 목적지를 선택해 주세요.');
  if (current) reset();
  selectedStore = store;
  $('searchResults').hidden = true; $('storeSearch').value = store ? store.name : '';
  position = {latitude: lat, longitude: lng};
  $('placeName').value = store ? store.name : '직접 선택한 매장';
  $('menuText').value = store ? store.items.map(m => m.name + (m.aliases.length ? ' | ' + m.aliases.join(', ') : '')).join('\n') : '';
  if (!store) localStorage.removeItem('moa-store');
  renderMenu(); syncStoreSelection(); lockSetup(false);
  pendingSummary('이 매장의 주문 대화를 녹음하면 최종 주문을 정리해 드려요.');
  $('lat').value = lat.toFixed(6); $('lng').value = lng.toFixed(6);
  $('coordinates').textContent = `${lat.toFixed(5)}° N  ·  ${lng.toFixed(5)}° E`;
  $('destinationBadge').textContent = '선택됨';
  if (!$('placeName').value.trim()) $('placeName').value = '선택한 매장';
  $('startBtn').disabled = !config.ready; $('startBtn').textContent = '녹음 시작';
  $('recordTitle').textContent = '목적지를 정했어요';
  $('recordDescription').textContent = '매장 이름과 메뉴를 확인한 뒤 출발해 주세요. 마이크 접근을 허용하면 녹음이 시작됩니다.';
  if (map) {
    if (marker) marker.remove();
    marker = L.marker([lat, lng], {icon: L.divIcon({html: '<div class="map-pin"></div>', className: '', iconSize: [30, 30], iconAnchor: [15, 30]})}).addTo(map);
    const popup = node('div'); popup.append(node('strong', '여기로 갈까요?'));
    const button = node('button', '이 지점으로 출발 · 녹음', 'button primary');
    button.type = 'button'; button.onclick = startRecording; popup.append(button);
    marker.bindPopup(popup, {maxWidth: 240, autoPan: false});
    if (!store) marker.openPopup();
  }
}
function showTrip(session) {
  const destination = session.destination;
  $('tripCard').hidden = false; $('tripName').textContent = destination.name;
  $('navigationLink').href = 'https://www.google.com/maps/dir/?' + new URLSearchParams({api: '1', destination: `${destination.latitude},${destination.longitude}`, travelmode: 'driving', dir_action: 'navigate'});
}
async function startRecording() {
  if (busy()) return;
  let menu;
  try { menu = menuItems(); } catch (e) { $('menuEditor').open = true; return toast(e.message); }
  if (!position) return toast('먼저 지도에서 위치를 선택해 주세요.');
  if (!config.ready) return toast('음성 분석 모델이 준비되지 않았습니다. 서버 설정을 확인해 주세요.');
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast(microphoneError({name: 'UnsupportedMicrophone'}));
  const name = $('placeName').value.trim();
  if (!name) return toast('목적지 이름을 입력해 주세요.');
  stopMicPreview();
  $('saveStatus').hidden = false;
  phase = 'starting'; lockSetup(true); $('startBtn').disabled = true; $('startBtn').textContent = '마이크 연결 중…';
  prepareMeter(); // Resume Web Audio inside the click gesture, before microphone/network awaits.
  try {
    stream = await openMicrophone();
    const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
    if (!mime) throw new Error('이 브라우저의 녹음 형식은 지원하지 않습니다. Chrome 또는 Edge로 열어 주세요.');
    recorder = new MediaRecorder(stream, {mimeType: mime, audioBitsPerSecond: 128000});
    current = await api('/api/sessions', {method: 'POST', json: {destination: {...position, name}, menu, mime, catalog_store_id: selectedStore?.id || null, parent_id: appendTarget?.id || null}});
    localStorage.setItem('moa-active', current.id);
    chunks = 0; pending = new Map(); uploadQueue = Promise.resolve(); uploadError = null; cancelled = false; elapsed = 0; savedBytes = 0;
    setSaveStatus('waiting', '첫 음성 저장을 기다리는 중');
    recorder.ondataavailable = event => {
      if (!event.data.size || cancelled) return;
      const index = chunks++; pending.set(index, event.data);
      setSaveStatus('saving', savedBytes ? `서버에 저장 중 · ${savedSize()} 저장 확인됨` : '첫 음성을 서버에 저장 중');
      uploadQueue = uploadQueue.then(() => sendChunk(index, event.data)).catch(error => {
        uploadError = error;
        setSaveStatus('error', '저장 연결 확인 필요 · 아직 보내지 못한 음성이 있어요');
        if (['recording', 'paused'].includes(recorder.state)) stopRecording();
      });
    };
    recorder.onerror = () => { uploadError = new Error('마이크 녹음 중 오류가 발생했습니다.'); if (['recording', 'paused'].includes(recorder.state)) stopRecording(); };
    recorder.onstop = recordingStopped;
    stream.getAudioTracks().forEach(track => track.onended = () => { if (['recording', 'paused'].includes(recorder.state)) { toast('마이크 연결이 종료되어 녹음을 저장합니다.'); stopRecording(); } });
    recorder.start(1000); accumulatedSeconds = 0; selectedUpload = null; started = Date.now(); phase = 'recording';
    pendingSummary('대화를 듣고 있어요. 녹음을 마치면 사람별 주문을 정리합니다.', '녹음 중');
    steps(2); lockSetup(true); if (map) map.closePopup();
    $('startBtn').hidden = true; $('stopBtn').hidden = false;
    $('retryBtn').hidden = true; $('results').hidden = true;
    $('recordBadge').textContent = '● 녹음 중'; $('recordTitle').textContent = '편하게 이야기해 주세요';
    $('recordDescription').textContent = '누가 어떤 메뉴를 고르는지 대화를 기록하고 있어요.';
    $('micOrbit').className = 'mic-orbit live';
    showTrip(current); startMeter(stream);
    clock = setInterval(() => { elapsed = recordingSeconds(); if (elapsed >= 3600) stopRecording(); }, 250);
    refreshHistory();
  } catch (e) {
    stream?.getTracks().forEach(t => t.stop()); stopMeter(); $('waveformPanel').hidden = true; phase = 'idle'; lockSetup(false);
    $('startBtn').disabled = false; $('startBtn').textContent = '녹음 시작';
    const micErrors = ['NotFoundError', 'DevicesNotFoundError', 'NotAllowedError', 'PermissionDeniedError', 'NotReadableError', 'TrackStartError', 'OverconstrainedError', 'SecurityError', 'UnsupportedMicrophone', 'AbortError'];
    toast(micErrors.includes(e.name) ? microphoneError(e) : e.message);
  }
}
async function sendChunk(index, blob) {
  let last;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (cancelled) return;
    try {
      await api(`/api/sessions/${current.id}/chunks/${index}`, {method: 'POST', body: blob, headers: {'Content-Type': current.mime}});
      if (pending.has(index)) savedBytes += blob.size;
      pending.delete(index);
      setSaveStatus(pending.size ? 'saving' : 'saved', pending.size ? `서버에 저장 중 · ${savedSize()} 저장 확인됨` : `서버 저장 확인 · ${savedSize()}`);
      return;
    } catch (error) { last = error; setSaveStatus('error', '서버 연결 재시도 중 · 이 탭을 닫지 마세요'); if (attempt < 2) await new Promise(r => setTimeout(r, 500 * (attempt + 1))); }
  }
  throw last;
}
function syncRecordingActions() {
  $('pauseBtn').hidden = !['recording', 'paused'].includes(phase);
  recordingControl('pauseBtn', phase === 'paused' ? 'play' : 'pause', phase === 'paused' ? '재개' : '일시정지');
  recordingControl('cancelBtn', 'trash', '삭제');
  if (phase !== 'stopping') recordingControl('stopBtn', 'stop', '중지·주문 정리');
  $('cancelBtn').hidden = !current || !['recording', 'paused', 'complete', 'failed', 'interrupted', 'upload_failed', 'delete_failed'].includes(phase);
  $('cancelBtn').disabled = phase === 'deleting';
  $('audioFile').disabled = phase !== 'idle' || busy() || !position || !config.ready;
  $('nextOrderBtn').hidden = phase !== 'complete';
  $('nextOrderBtn').disabled = !config.append_orders;
}
function recordingSeconds() {
  return accumulatedSeconds + (phase === 'recording' ? (Date.now() - started) / 1000 : 0);
}
function pauseRecording() {
  if (recorder?.state === 'recording' && phase === 'recording') {
    accumulatedSeconds = recordingSeconds(); elapsed = accumulatedSeconds;
    recorder.pause(); phase = 'paused';
    stream.getAudioTracks().forEach(track => track.enabled = false);
    stopMeter(); $('micOrbit').className = 'mic-orbit';
    pendingSummary('녹음을 재개하거나 중지해 주문을 정리할 수 있어요.', '일시정지');
    $('recordBadge').textContent = '일시정지';
  } else if (recorder?.state === 'paused' && phase === 'paused') {
    prepareMeter(); stream.getAudioTracks().forEach(track => track.enabled = true);
    recorder.resume(); started = Date.now(); phase = 'recording';
    startMeter(stream); $('recordBadge').textContent = '● 녹음 중';
    pendingSummary('대화를 듣고 있어요. 녹음을 마치면 사람별 주문을 정리합니다.', '녹음 중');
  } else return;
  lockSetup(true);
}
async function deleteSavedSession() {
  const previous = phase;
  phase = 'deleting'; lockSetup(true); ++polling;
  if (cancelled) $('stopBtn').hidden = true;
  try {
    $('playback').pause(); $('playback').removeAttribute('src'); $('playback').load();
    await api(`/api/sessions/${current.id}`, {method: 'DELETE'});
    const parent = current.status !== 'complete' ? current.parent_id : null;
    reset(); if (parent) await loadSession(parent);
    await refreshHistory(); toast(parent ? '추가 녹음을 삭제하고 이전 주문을 유지했어요.' : '녹음과 분석 결과를 삭제했어요.');
  } catch (error) {
    phase = cancelled ? 'delete_failed' : previous; lockSetup(true);
    pendingSummary('삭제하지 못했어요. 연결을 확인하고 녹음 삭제를 다시 눌러 주세요.', '삭제 실패');
    toast(error.message);
  }
}
async function deleteRecording() {
  if (!current || !['recording', 'paused', 'complete', 'failed', 'interrupted', 'upload_failed', 'delete_failed'].includes(phase)) return;
  const message = current.parent_id && current.status !== 'complete' ? '추가 녹음을 삭제할까요? 이전 주문은 그대로 보관됩니다.' : '이 주문에 포함된 모든 녹음과 분석 결과를 삭제할까요? 삭제 후에는 복구할 수 없습니다.';
  if (!window.confirm(message)) return;
  if (['recording', 'paused'].includes(recorder?.state)) { cancelled = true; stopRecording(); }
  else { await uploadQueue; await deleteSavedSession(); }
}
async function appendOrder(id) {
  if (!config.append_orders) return toast('서버 업데이트 후 새로고침해 주세요.');
  if (busy()) return toast('진행 중인 녹음이나 분석이 끝난 뒤 추가해 주세요.');
  try {
    const selected = await api(`/api/sessions/${id}`);
    const records = await api('/api/sessions');
    const latest = records.find(s => (s.order_id || s.id) === (selected.order_id || selected.id));
    if (latest?.pending_append) return await loadSession(latest.pending_append.id);
    await loadSession(latest?.id || id);
    if (current?.status !== 'complete') return;
    const parent = current;
    reset(); appendTarget = parent;
    $('appendNotice').hidden = false;
    $('appendLabel').textContent = `${parent.destination.name} · 기존 주문에 추가`;
    $('startBtn').textContent = '추가 녹음 시작';
    pendingSummary('추가 대화를 녹음하거나 파일을 올리면 이전 주문과 함께 정리합니다.', '추가 주문');
    lockSetup(true);
    $('recorderCard').scrollIntoView({behavior:'smooth', block:'start'});
  } catch (error) { toast(error.message); }
}
function selectResultView(view) {
  document.querySelectorAll('[data-view]').forEach(b => {
    b.classList.toggle('selected', b.dataset.view === view);
    b.setAttribute('aria-pressed', String(b.dataset.view === view));
  });
  ['savedResult', 'transcript', 'changes'].forEach(id => $(id).hidden = id !== view);
}
function newOrder() {
  if (busy()) return;
  reset(); position = null; selectedStore = null;
  marker?.remove(); marker = null; map?.closePopup();
  localStorage.removeItem('moa-store'); localStorage.removeItem('moa-menu');
  $('placeName').value = ''; $('menuText').value = ''; $('storeSearch').value = '';
  $('lat').value = ''; $('lng').value = ''; $('coordinates').textContent = '아직 선택된 위치가 없어요';
  $('destinationBadge').textContent = '선택 전';
  $('startBtn').disabled = true; $('startBtn').textContent = '목적지를 선택해 주세요';
  syncStoreSelection(); renderMenu(); lockSetup(false);
  $('storeSearch').focus(); $('workspace').scrollIntoView({behavior: 'smooth', block: 'start'});
}
async function uploadRemaining() {
  const size = Math.min(config.max_chunk_bytes || 8 * 1024 * 1024, 4 * 1024 * 1024);
  const total = Math.ceil(selectedUpload.size / size);
  for (; uploadIndex < total; uploadIndex++) {
    const blob = selectedUpload.slice(uploadIndex * size, (uploadIndex + 1) * size);
    chunks = uploadIndex + 1; pending.set(uploadIndex, blob);
    await sendChunk(uploadIndex, blob);
    $('fileStatus').textContent = `${selectedUpload.name} · 업로드 ${Math.round((uploadIndex + 1) / total * 100)}%`;
  }
}
async function uploadAudioFile(file) {
  if (!file || busy() || phase !== 'idle') return;
  const types = {wav:'audio/wav', mp3:'audio/mpeg', m4a:'audio/mp4', mp4:'audio/mp4', ogg:'audio/ogg', webm:'audio/webm', flac:'audio/flac'};
  const mime = types[file.name.split('.').pop().toLowerCase()];
  let menu;
  try {
    if (!position || !config.ready) throw new Error('먼저 목적지와 메뉴를 선택해 주세요.');
    menu = menuItems();
    if (!mime || !file.size || file.size > 250 * 1024 * 1024) throw new Error('250MB 이하의 WAV·MP3·M4A·MP4·OGG·WebM·FLAC 음성 파일을 선택해 주세요.');
    if (!$('placeName').value.trim()) throw new Error('목적지 이름을 입력해 주세요.');
  } catch (error) { $('audioFile').value = ''; toast(error.message); return; }
  stopMicPreview(); phase = 'uploading'; lockSetup(true); $('startBtn').hidden = true;
  $('fileStatus').textContent = `${file.name} · 업로드 준비 중`;
  pendingSummary('음성 파일을 업로드하고 있어요.', '업로드 중', 'saving');
  try {
    current = await api('/api/sessions', {method:'POST', json:{destination:{...position, name:$('placeName').value.trim()}, menu, mime, catalog_store_id:selectedStore?.id || null, source:'upload', expected_bytes:file.size, parent_id:appendTarget?.id || null}});
    localStorage.setItem('moa-active', current.id);
    selectedUpload = file; uploadIndex = 0; chunks = 0; elapsed = 0; savedBytes = 0;
    pending = new Map(); uploadQueue = Promise.resolve(); uploadError = null; cancelled = false;
    $('recordBadge').textContent = '업로드 중'; showTrip(current);
    await uploadRemaining(); await finalize();
  } catch (error) {
    uploadError = error;
    if (current) {
      phase = 'upload_failed'; lockSetup(true); $('retryBtn').hidden = false; $('retryBtn').textContent = '파일 업로드 다시 시도';
      pendingSummary('선택한 파일을 유지하고 있어요. 업로드를 다시 시도해 주세요.', '업로드 실패');
    } else {
      phase = 'idle'; lockSetup(false); $('startBtn').hidden = false; $('audioFile').value = '';
      pendingSummary('파일을 업로드하지 못했어요. 다시 선택해 주세요.', '업로드 실패');
      $('fileStatus').textContent = '업로드를 시작하지 못했어요. 다시 파일을 선택해 주세요.';
    }
    toast(error.message);
  }
}
function stopRecording() {
  if (!['recording', 'paused'].includes(recorder?.state)) return;
  elapsed = recordingSeconds(); clearInterval(clock); phase = 'stopping'; lockSetup(true);
  pendingSummary('저장이 끝나면 주문 분석을 시작합니다.', '저장 중', 'saving');
  $('orderSummary').scrollIntoView({behavior: 'smooth', block: 'center'});
  $('stopBtn').disabled = true; $('stopBtn').textContent = '녹음을 저장하고 있어요…';
  recorder.stop();
}
async function recordingStopped() {
  stream?.getTracks().forEach(t => t.stop()); stopMeter();
  setInputStatus('stopped', '녹음 종료');
  $('waveformPanel').hidden = true; $('micOrbit').className = 'mic-orbit';
  $('resumeMeterBtn').hidden = true; clearInterval(clock);
  await uploadQueue;
  if (cancelled) {
    await deleteSavedSession(); return;
  }
  if (pending.size || uploadError) {
    phase = 'upload_failed'; lockSetup(true); $('stopBtn').hidden = true;
    pendingSummary('녹음 업로드를 다시 시도하면 주문 정리를 이어갑니다.', '저장 확인 필요');
    $('micOrbit').className = 'mic-orbit'; $('recordBadge').textContent = '저장 확인 필요';
    $('recordTitle').textContent = '녹음 업로드를 다시 시도해 주세요';
    $('recordDescription').textContent = '아직 보내지 못한 음성은 이 탭에 남아 있어요. 탭을 닫지 말고 다시 시도해 주세요.';
    $('retryBtn').hidden = false; $('retryBtn').textContent = '업로드 다시 시도';
    setSaveStatus('error', '저장 확인 필요 · 업로드를 다시 시도해 주세요');
    toast(uploadError?.message || '녹음 일부가 아직 저장되지 않았어요.'); return;
  }
  await finalize();
}
async function finalize() {
  try {
    current = await api(`/api/sessions/${current.id}/finish`, {method: 'POST', json: {chunks, duration: elapsed}});
    renderProcessing(current); poll(current.id);
  } catch (e) {
    phase = 'upload_failed'; lockSetup(true); $('stopBtn').hidden = true; $('retryBtn').hidden = false;
    pendingSummary('분석을 시작하지 못했어요. 저장된 녹음으로 다시 시도해 주세요.', '다시 시도');
    $('retryBtn').textContent = '저장 완료 후 다시 분석'; $('recordTitle').textContent = '아직 분석을 시작하지 못했어요';
    $('recordDescription').textContent = e.message; toast(e.message);
  }
}
function renderProcessing(session) {
  selectedUpload = null;
  phase = 'processing'; lockSetup(true); steps(3);
  const queued = session.status === 'queued';
  pendingSummary(queued ? '앞선 분석이 끝나면 자동으로 시작합니다.' : '대화를 확인해 사람별 최종 주문을 정리하고 있어요.', queued ? '분석 대기' : '분석 중', queued ? 'queued' : 'processing');
  $('startBtn').hidden = true; $('stopBtn').hidden = true; $('retryBtn').hidden = true;
  $('recordBadge').textContent = session.status === 'queued' ? '분석 대기' : '분석 중';
  $('recordTitle').textContent = '주문을 정리하고 있어요'; $('recordDescription').textContent = session.phase;
  $('micOrbit').className = 'mic-orbit'; $('uploadStatus').textContent = '녹음 저장 완료';
}
async function poll(id) {
  const token = ++polling;
  while (token === polling && current?.id === id) {
    try {
      const session = await api(`/api/sessions/${id}`);
      if (token !== polling || current?.id !== id) return;
      current = session;
      if (session.status === 'complete') { await showResults(id); refreshHistory(); return; }
      if (session.status === 'failed') { showFailure(session); refreshHistory(); return; }
      renderProcessing(session);
    } catch (e) { pendingSummary('서버에 다시 연결하고 있어요. 저장된 녹음의 분석 상태를 확인합니다.', '연결 확인', 'queued'); }
    await new Promise(r => setTimeout(r, 1500));
  }
}
function showFailure(session) {
  phase = 'failed'; lockSetup(true); $('newBtn').disabled = false;
  pendingSummary('분석을 완료하면 이곳에 주문이 표시됩니다. 저장된 음성으로 다시 분석해 주세요.', '다시 분석');
  $('recordBadge').textContent = '다시 확인'; $('recordTitle').textContent = '분석을 완료하지 못했어요';
  $('recordDescription').textContent = session.phase; $('micOrbit').className = 'mic-orbit';
  $('startBtn').hidden = true; $('stopBtn').hidden = true;
  $('retryBtn').hidden = false; $('retryBtn').textContent = '저장된 음성 다시 분석';
}
async function retry() {
  $('retryBtn').disabled = true;
  try {
    if (selectedUpload && phase === 'upload_failed') {
      uploadError = null; phase = 'uploading'; lockSetup(true);
      await uploadRemaining();
    } else if (phase === 'upload_failed') {
      uploadError = null;
      for (const [i, blob] of [...pending].sort((a, b) => a[0] - b[0])) await sendChunk(i, blob);
    } else { chunks = current.next_chunk; elapsed = current.duration || Math.min(3600, Date.now()/1000 - current.created_at); }
    await finalize();
  } catch (e) { uploadError = e; phase = 'upload_failed'; lockSetup(true); toast(e.message); }
  finally { $('retryBtn').disabled = false; }
}
function savedSize() { return savedBytes < 1024 * 1024 ? `${(savedBytes / 1024).toFixed(1)} KB` : `${(savedBytes / 1024 / 1024).toFixed(2)} MB`; }
function setSaveStatus(state, text) {
  $('saveStatus').dataset.state = state;
  $('saveStatus').textContent = text;
  $('uploadStatus').textContent = text;
}
function setInputStatus(state, text) {
  $('waveformPanel').dataset.input = state;
  if ($('inputStatus').textContent !== text) $('inputStatus').textContent = text;
}
function stopMeter() {
  cancelAnimationFrame(meter); meter = null;
  meterSource?.disconnect(); meterSource = null;
  meterSink?.disconnect(); meterSink = null;
  const previous = audioContext; audioContext = null;
  if (previous && previous.state !== 'closed') previous.close().catch(() => {});
}
function prepareMeter() {
  stopMeter();
  try {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    audioContext.resume().catch(() => {});
  } catch { audioContext = null; }
}
function syncMicButton() {
  const preview = Boolean(previewStream) || previewStarting;
  $('micOrbit').hidden = phase === 'recording' || Boolean(previewStream);
  $('endPreviewBtn').hidden = !previewStream;
  if (phase !== 'recording' && !previewStream) $('waveformPanel').hidden = true;
  $('micOrbit').disabled = micChecking || (!preview && !['idle', 'recording'].includes(phase));
  $('micOrbit').setAttribute('aria-pressed', String(preview || phase === 'recording'));
  $('micOrbit').title = preview ? '입력 미리보기 종료 · 저장하지 않음' : phase === 'recording' ? '파형 다시 켜기' : '마이크 입력 미리보기 · 저장하지 않음';
  if (phase === 'idle') $('recordBadge').textContent = preview ? '입력 확인' : '시작 전';
  $('micOrbit').setAttribute('aria-label', preview ? '마이크 입력 미리보기 종료' : phase === 'recording' ? '녹음 파형 다시 켜기' : '마이크 입력 미리보기 시작');
}
function stopMicPreview() {
  ++previewGeneration;
  if (!previewStream && !previewStarting) return;
  previewStarting = false;
  previewStream?.getTracks().forEach(track => track.stop()); previewStream = null;
  stopMeter(); $('waveformPanel').hidden = true; $('saveStatus').hidden = false;
  $('micOrbit').className = 'mic-orbit'; syncMicButton();
  lockSetup(phase !== 'idle'); $('startBtn').disabled = !position || !config.ready || phase !== 'idle';
}
async function toggleMicPreview() {
  if (phase === 'recording') {
    if (!audioContext || audioContext.state === 'closed') { prepareMeter(); startMeter(stream); }
    else audioContext.resume().catch(() => toast('파형을 켜지 못했어요. 마이크 권한을 확인해 주세요.'));
    return;
  }
  if (previewStream || previewStarting) { stopMicPreview(); return; }
  if (busy() || phase !== 'idle') return;
  const token = ++previewGeneration;
  previewStarting = true; prepareMeter(); lockSetup(true); $('startBtn').disabled = true;
  try {
    const input = await openMicrophone();
    if (token !== previewGeneration) { input.getTracks().forEach(track => track.stop()); return; }
    previewStream = input; previewStarting = false;
    input.getAudioTracks().forEach(track => track.onended = stopMicPreview);
    $('saveStatus').hidden = true; $('micOrbit').className = 'mic-orbit preview';
    startMeter(input, () => previewStream === input);
    lockSetup(false); $('startBtn').disabled = !position || !config.ready;
  } catch (error) {
    if (token !== previewGeneration) return;
    stopMicPreview(); toast(microphoneError(error));
  }
}
function startMeter(mediaStream, isActive = () => recorder?.state === 'recording') {
  const panel = $('waveformPanel'), canvas = $('waveform');
  panel.hidden = false; $('resumeMeterBtn').hidden = true;
  setInputStatus('connecting', '마이크 입력 연결 중');
  try {
    if (!audioContext) throw new Error('Web Audio unavailable');
    const context = audioContext, analyser = context.createAnalyser(); analyser.fftSize = 2048;
    meterSource = context.createMediaStreamSource(mediaStream); meterSource.connect(analyser);
    // Keep the graph pulled on mobile browsers without playing microphone audio back.
    meterSink = context.createGain(); meterSink.gain.value = 0;
    analyser.connect(meterSink); meterSink.connect(context.destination);
    context.resume().catch(() => {});
    const data = new Float32Array(analyser.fftSize), ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Canvas unavailable');
    const history = [], track = mediaStream.getAudioTracks()[0];
    let lastSample = -Infinity, lastSound = -Infinity;
    const draw = now => {
      if (context !== audioContext || !isActive()) return;
      const running = context.state === 'running';
      $('resumeMeterBtn').hidden = running;
      const usable = running && track?.readyState === 'live' && !track.muted && track.enabled;
      if (now - lastSample >= 50) {
        lastSample = now; data.fill(0);
        if (usable) analyser.getFloatTimeDomainData(data);
        let sum = 0, peak = 0;
        for (const sample of data) { sum += sample * sample; peak = Math.max(peak, Math.abs(sample)); }
        const rms = Math.sqrt(sum / data.length);
        if (usable && rms > .003) lastSound = now;
        history.push({at: now, level: usable && rms > .001 ? Math.min(1, Math.sqrt(peak) * 1.7) : 0});
        while (history.length && history[0].at < now - 4000) history.shift();
        if (!running) setInputStatus('suspended', '파형 일시 정지 · 파형 켜기를 눌러 주세요');
        else if (!usable) setInputStatus('muted', '마이크 입력이 중단됐어요');
        else if (now - lastSound < 600) setInputStatus('signal', '소리 입력 중');
        else setInputStatus('quiet', '조용해요 · 소리 입력을 기다리는 중');
      }
      const width = Math.max(1, Math.round(canvas.clientWidth)), height = 112, ratio = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
      }
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, width, height);
      const count = Math.max(20, Math.floor(width / 6)), spacing = width / count;
      ctx.strokeStyle = '#79bfff'; ctx.lineWidth = 3; ctx.lineCap = 'round';
      for (let i = 0; i < count; i++) {
        const from = now - 4000 + (i / count) * 4000, to = from + 4000 / count;
        const level = history.reduce((max, sample) => sample.at >= from && sample.at < to ? Math.max(max, sample.level) : max, 0);
        const h = level * (height - 18), x = (i + .5) * spacing;
        ctx.beginPath(); ctx.moveTo(x, (height - h) / 2); ctx.lineTo(x, (height + h) / 2 + .1); ctx.stroke();
      }
      meter = requestAnimationFrame(draw);
    };
    meter = requestAnimationFrame(draw);
  } catch {
    setInputStatus('unavailable', '이 브라우저에서는 파형을 표시할 수 없어요');
    $('resumeMeterBtn').hidden = false;
    canvas.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
  }
}
async function showResults(id) {
  const result = await api(`/api/sessions/${id}/result`);
  if (current?.id !== id) return;
  current = result.session; appendTarget = null; $('appendNotice').hidden = true; phase = 'complete'; lockSetup(true); steps(3);
  syncRecordingActions();
  $('recordBadge').textContent = '정리 완료'; $('recordTitle').textContent = '우리의 주문이 모였어요';
  $('recordDescription').textContent = '아래에서 화자별 주문과 녹음 원문을 확인해 주세요.';
  $('micOrbit').className = 'mic-orbit';
  $('startBtn').hidden = true; $('stopBtn').hidden = true; $('retryBtn').hidden = true;
  $('uploadStatus').textContent = '녹음 및 분석 결과 저장됨'; $('results').hidden = false;
  $('resultSubtitle').textContent = `${current.destination.name} · ${timeLabel(result.metrics.audio_seconds || current.duration)} 녹음 · 주문 초안`;
  $('reviewBanner').hidden = result.orders.status !== 'needs_confirmation';
  $('downloadLink').href = `/api/sessions/${id}/result?download=1`;
  $('playback').src = `/api/sessions/${id}/audio`;
  const ids = [...new Set([...result.utterances.map(t => t.speaker), ...Object.keys(result.orders.speakers)])].filter(Boolean).sort();
  $('summaryCount').textContent = `${ids.length}명`;
  $('summaryDescription').hidden = false;
  $('summaryDescription').textContent = `${current.destination.name} · 마지막 변경까지 반영한 주문`;
  $('orderSummary').dataset.state = 'complete';
  $('orderCards').setAttribute('aria-busy', 'false');
  $('orderCards').replaceChildren();
  if (!ids.length) $('orderCards').append(node('p', '인식된 대화가 없어요. 마이크와 녹음 음량을 확인한 뒤 다시 녹음해 주세요.', 'empty-order'));
  for (const [index, speaker] of ids.entries()) {
    const card = node('div', undefined, 'order-card'), title = node('div', undefined, 'speaker-title');
    card.setAttribute('aria-label', `참여자 ${index + 1}의 최종 주문`);
    title.append(personAvatar(index)); card.append(title);
    const contents = node('div', undefined, 'person-orders'); card.append(contents);
    const items = result.orders.speakers[speaker] || [];
    if (!items.length) contents.append(node('p', '확인된 주문이 없어요. 대화 내용을 확인해 주세요.', 'empty-order'));
    for (const item of items) { const row = node('div', undefined, 'order-item'), text = node('div', item.name); if (item.options.length) text.append(node('p', item.options.join(' · '))); row.append(text, node('strong', `${item.quantity}개`)); contents.append(row); }
    $('orderCards').append(card);
  }
  $('savedOrders').replaceChildren(...[...$('orderCards').children].map(card => {
    const clone = card.cloneNode(true);
    if (clone.classList.contains('order-card')) clone.classList.replace('order-card', 'saved-order-card');
    return clone;
  }));
  const recordings = result.recordings || [{start:0, end:current.duration}];
  $('recordingList').replaceChildren(node('h3', `함께 정리한 녹음 ${recordings.length}개`));
  recordings.forEach((part, index) => {
    const button = node('button', `${index === 0 ? '첫 녹음' : `추가 녹음 ${index}`} · ${timeLabel(part.start)}–${timeLabel(part.end)}`, 'recording-part');
    button.onclick = () => { $('playback').currentTime = part.start; $('playback').play().catch(() => {}); };
    $('recordingList').append(button);
  });
  selectResultView('savedResult');
  renderTranscript(result, ids); showTrip(current);
  $('orderSummary').scrollIntoView({behavior: 'smooth', block: 'start'});
}
function renderTranscript(result, ids) {
  $('transcript').replaceChildren(); $('changes').replaceChildren(); $('turnCount').textContent = `${result.utterances.length}개 발화`;
  const makeRow = (start, speaker, text, note) => {
    const row = node('div', undefined, 'turn'), stamp = node('button', timeLabel(start), 'turn-time');
    stamp.onclick = () => { $('playback').currentTime = start; $('playback').play().catch(() => {}); };
    const content = node('div', text, 'turn-text'); if (note) content.append(node('small', note));
    const index = ids.indexOf(speaker);
    row.append(stamp, index >= 0 ? personAvatar(index, true) : node('span', '?', 'turn-name'), content); return row;
  };
  result.utterances.forEach(t => $('transcript').append(makeRow(t.start, t.speaker, t.text || '(인식된 말이 없습니다)', t.needs_review ? '음성 또는 화자 확인 필요' : t.overlap ? '겹친 대화 · 주문 내용을 확인해 주세요' : '')));
  const labels = {update: '주문 반영', noop: '주문 변경 없음', clarify: '확인 필요'};
  result.events.forEach(e => $('changes').append(makeRow(e.start, e.speaker, e.decision.reason, labels[e.decision.action])));
}
async function refreshHistory() {
  try {
    const records = await api('/api/sessions'); $('history').replaceChildren();
    if (!records.length) $('history').append(node('p', '아직 녹음이 없어요. 오늘의 첫 주문 대화를 시작해 보세요.', 'empty-history'));
    const labels = {recording: '녹음 중 / 미종료', queued: '분석 대기', processing: '분석 중', complete: '정리 완료', failed: '다시 분석'};
    records.forEach(session => {
      const row = node('div', undefined, 'history-entry');
      const button = node('button', undefined, 'history-row'), info = node('div');
      info.append(node('strong', session.destination.name), node('small', new Date(session.created_at * 1000).toLocaleString('ko-KR', {month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit'}) + ` · 녹음 ${session.recording_count || 1}개 · ${timeLabel(session.duration)}`));
      button.append(actionIcon('pin'), info);
      if (session.status !== 'complete') button.append(node('span', labels[session.status], 'tag'));
      button.onclick = () => loadSession(session.id).catch(e => toast(e.message)); row.append(button);
      if (session.status === 'complete' && config.append_orders) {
        const extra = node('button', session.pending_append ? '추가 녹음 이어보기' : '＋ 추가 주문', 'button secondary history-add');
        extra.disabled = busy();
        extra.onclick = () => session.pending_append ? loadSession(session.pending_append.id).catch(e => toast(e.message)) : appendOrder(session.id);
        row.append(extra);
      }
      $('history').append(row);
    });
  } catch (e) { toast(e.message); }
}
async function loadSession(id) {
  if (busy()) return toast('진행 중인 녹음이나 분석이 끝난 뒤 확인해 주세요.');
  appendTarget = null; $('appendNotice').hidden = true;
  stopMicPreview(); stopMeter(); $('waveformPanel').hidden = true;
  pendingSummary('저장된 녹음의 주문을 불러오고 있어요.', '불러오는 중');
  ++polling; current = await api(`/api/sessions/${id}`); showTrip(current);
  localStorage.setItem('moa-active', current.id);
  if (current.parent_id && current.status !== 'complete') {
    $('appendNotice').hidden = false; $('appendLabel').textContent = '이전 주문에 추가하는 녹음';
  }
  position = {latitude: current.destination.latitude, longitude: current.destination.longitude};
  selectedStore = stores.find(s => s.id === current.catalog_store_id) || null;
  syncStoreSelection();
  $('placeName').value = current.destination.name; updateMenuTitle();
  $('menuText').value = current.menu.items.map(m => m.name + (m.aliases?.length ? ' | ' + m.aliases.join(', ') : '')).join('\n'); renderMenu();
  $('coordinates').textContent = `${position.latitude.toFixed(5)}° N · ${position.longitude.toFixed(5)}° E`; $('results').hidden = true; lockSetup(true);
  if (current.status === 'complete') await showResults(id);
  else if (['queued', 'processing'].includes(current.status)) { renderProcessing(current); poll(id); }
  else if (current.status === 'failed') showFailure(current);
  else {
    phase = 'interrupted'; lockSetup(true); $('newBtn').disabled = false; $('startBtn').hidden = true;
    pendingSummary('저장된 음성을 분석하면 최종 주문이 표시됩니다.', '미종료 녹음');
    $('recordTitle').textContent = '종료되지 않은 녹음이 있어요'; $('recordDescription').textContent = '서버에 저장된 부분까지 분석하거나 새로운 녹음을 시작할 수 있어요.';
    if (current.source === 'upload' && current.bytes !== current.expected_bytes) $('recordDescription').textContent = '파일 업로드가 완료되지 않았어요. 녹음을 삭제한 뒤 파일을 다시 선택해 주세요.';
    $('recordBadge').textContent = '저장된 음성'; $('retryBtn').hidden = !current.bytes || (current.source === 'upload' && current.bytes !== current.expected_bytes); $('retryBtn').textContent = '저장된 부분 분석하기';
  }
}
function reset() {
  appendTarget = null; $('appendNotice').hidden = true;
  stopMicPreview(); stopMeter(); $('waveformPanel').hidden = true;
  pendingSummary();
  accumulatedSeconds = 0; selectedUpload = null; uploadIndex = 0; $('audioFile').value = ''; $('fileStatus').textContent = '최대 60분 · 250MB';
  ++polling; current = null; phase = 'idle'; recorder = null; uploadError = null; cancelled = false; pending.clear();
  localStorage.removeItem('moa-active'); $('playback').pause(); $('results').hidden = true; $('tripCard').hidden = true;
  $('startBtn').hidden = false; $('startBtn').disabled = !position || !config.ready;
  $('startBtn').textContent = position ? '녹음 시작' : '목적지를 선택해 주세요';
  $('stopBtn').hidden = true; $('stopBtn').disabled = false; $('stopBtn').replaceChildren(node('span', undefined, 'stop-square'), document.createTextNode(' 녹음 중지 · 주문 정리'));
  $('retryBtn').hidden = true; $('recordBadge').textContent = '시작 전'; $('micOrbit').className = 'mic-orbit';
  $('recordTitle').textContent = '다음 주문 대화를 시작해 볼까요?'; $('recordDescription').textContent = '목적지와 메뉴를 확인한 뒤 녹음을 시작해 주세요.';
  $('uploadStatus').textContent = ''; steps(1); lockSetup(false);
}
async function init() {
  setupMicrophones(); setupStoreSearch();
  $('micOrbit').onclick = toggleMicPreview;
  $('endPreviewBtn').onclick = stopMicPreview;
  $('placeName').oninput = updateMenuTitle;
  const key = new URLSearchParams(location.hash.slice(1)).get('key');
  if (key) {
    try { await api('/api/pair', {method: 'POST', json: {key}}); history.replaceState(null, '', location.pathname); }
    catch (e) { showConnectionForm(e.status === 401); toast(e.message); return; }
  }
  $('menuText').value = ''; renderMenu();
  document.querySelectorAll('[data-menu]').forEach(button => button.onclick = () => {
    document.querySelectorAll('[data-menu]').forEach(b => b.classList.toggle('selected', b === button));
    $('menuText').value = presets[button.dataset.menu]; renderMenu(); $('menuEditor').open = button.dataset.menu === 'custom';
    localStorage.setItem('moa-menu', $('menuText').value);
  });
  $('menuText').oninput = () => { renderMenu(); localStorage.setItem('moa-menu', $('menuText').value); };
  $('startBtn').onclick = startRecording; $('stopBtn').onclick = stopRecording; $('retryBtn').onclick = retry;
  $('resumeMeterBtn').onclick = () => { if (phase === 'recording') toggleMicPreview(); else audioContext?.resume().catch(() => toast('파형을 켜지 못했어요. 마이크 권한을 확인해 주세요.')); };
  $('cancelBtn').onclick = deleteRecording;
  $('pauseBtn').onclick = pauseRecording;
  $('audioFile').onchange = () => uploadAudioFile($('audioFile').files[0]);
  $('newBtn').onclick = newOrder; $('nextOrderBtn').onclick = () => current && appendOrder(current.id);
  $('appendOrderBtn').onclick = () => current && appendOrder(current.id);
  $('returnOrderBtn').onclick = () => {
    const id = appendTarget?.id || current?.parent_id;
    if (id && !busy()) loadSession(id).catch(e => toast(e.message));
  };
  $('refreshHistory').onclick = refreshHistory;
  $('coordinateBtn').onclick = () => {
    const lat = Number($('lat').value), lng = Number($('lng').value);
    if (!$('lat').value || !$('lng').value || !Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return toast('올바른 위도와 경도를 입력해 주세요.');
    choosePosition(lat, lng); map?.setView([lat, lng], 16);
  };
  $('locateBtn').onclick = () => {
    if (!navigator.geolocation) return toast('이 브라우저에서는 위치를 확인할 수 없어요. 지도에서 직접 선택해 주세요.');
    navigator.geolocation.getCurrentPosition(p => { map?.setView([p.coords.latitude, p.coords.longitude], 16); }, () => toast('현재 위치를 확인하지 못했어요. 지도에서 직접 선택하거나 좌표를 입력해 주세요.'), {timeout: 10000});
  };
  document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => {
    selectResultView(button.dataset.view);
  });
  try { config = await api('/api/config'); $('health').classList.toggle('ready', config.ready); $('health').lastChild.textContent = config.ready ? '분석 엔진 준비됨' : '분석 모델 확인 필요'; }
  catch (e) { $('health').lastChild.textContent = '접속 확인 필요'; showConnectionForm(e.status === 401); return; }
  stores = config.stores || [];
  if (window.L) {
    map = L.map('map', {zoomControl: false}).setView([37.559, 127.039], 15);
    L.control.zoom({position: 'bottomright'}).addTo(map);
    const tiles = L.tileLayer(config.tile_url || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>'}).addTo(map);
    tiles.on('tileerror', () => $('mapNotice').hidden = false);
    tiles.on('tileload', () => $('mapNotice').hidden = true);
    map.on('click', e => choosePosition(e.latlng.lat, e.latlng.lng));
  } else $('mapNotice').hidden = false;
  renderStores();
  const remembered = stores.find(s => s.id === localStorage.getItem('moa-store'));
  if (remembered) chooseStore(remembered);
  await refreshHistory();
  const saved = localStorage.getItem('moa-active');
  if (saved) { try { await loadSession(saved); } catch { localStorage.removeItem('moa-active'); } }
}
window.addEventListener('beforeunload', event => { if (['recording', 'paused', 'stopping', 'uploading', 'upload_failed', 'deleting', 'delete_failed'].includes(phase)) { event.preventDefault(); event.returnValue = ''; } });
document.addEventListener('visibilitychange', () => { if (document.hidden) stopMicPreview(); });
window.addEventListener('pagehide', stopMicPreview);
init().catch(e => toast(e.message));
