/* Optional existing whisper.cpp recorder. Every transcript is reviewed in the
   same Navigator input; no recording or transcript automatically submits. */
window.NavcomVoice = (() => {
  'use strict';
  function wav(samples) {
    const buffer = new ArrayBuffer(44 + samples.length * 2), data = new DataView(buffer);
    const word = (at, value) => { for (let i = 0; i < value.length; i++) data.setUint8(at + i, value.charCodeAt(i)); };
    word(0, 'RIFF'); data.setUint32(4, buffer.byteLength - 8, true); word(8, 'WAVE'); word(12, 'fmt ');
    data.setUint32(16, 16, true); data.setUint16(20, 1, true); data.setUint16(22, 1, true);
    data.setUint32(24, 16000, true); data.setUint32(28, 32000, true); data.setUint16(32, 2, true); data.setUint16(34, 16, true);
    word(36, 'data'); data.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) { const v = Math.max(-1, Math.min(1, samples[i])); data.setInt16(44 + i * 2, v < 0 ? v * 32768 : v * 32767, true); }
    let binary = ''; const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(binary);
  }
  function attach({button, input, status, container, request}) {
    let job = null, serial = 0, inputVersion = 0;
    input.addEventListener('input', () => { inputVersion++; });
    const controls = document.createElement('div'); controls.className = 'space-voice-controls hidden';
    const stop = document.createElement('button'), cancel = document.createElement('button');
    stop.type = cancel.type = 'button'; stop.textContent = 'Stop & transcribe'; cancel.textContent = 'Cancel recording';
    controls.append(stop, cancel); container.append(controls);
    const draft = document.createElement('div'); draft.className = 'space-voice-draft hidden';
    const transcript = document.createElement('textarea'), lengthNote = document.createElement('p'), use = document.createElement('button'), dismiss = document.createElement('button');
    const limit = input.maxLength > 0 ? input.maxLength : 500;
    transcript.rows = 4; transcript.style.width = '100%'; transcript.setAttribute('aria-label', 'Review and edit local voice transcript');
    lengthNote.setAttribute('role', 'status'); lengthNote.setAttribute('aria-live', 'polite');
    function updateDraft() {
      const count = transcript.value.trim().length, excess = Math.max(0, count - limit);
      use.disabled = count === 0 || excess > 0;
      lengthNote.textContent = `${count}/${limit} characters` + (excess ? ` · Shorten by ${excess} before using this transcript. Your full recording text remains editable.` : ' · Review the text, then use it in the Navigator.');
    }
    function applyTranscript(value) { input.value = value; inputVersion++; draft.classList.add('hidden'); input.focus(); status.textContent = 'Heard locally: review the text, then Search. Your place and scope stayed unchanged.'; }
    transcript.addEventListener('input', updateDraft);
    use.type = dismiss.type = 'button'; use.textContent = 'Use transcript'; dismiss.textContent = 'Dismiss';
    use.addEventListener('click', () => { updateDraft(); if (!use.disabled) applyTranscript(transcript.value.trim()); });
    dismiss.addEventListener('click', () => draft.classList.add('hidden'));
    draft.append(transcript, lengthNote, use, dismiss); container.append(draft);
    function reset() { controls.classList.add('hidden'); button.disabled = false; button.setAttribute('aria-pressed', 'false'); }
    async function release(record) {
      clearInterval(record.timer); record.stream?.getTracks().forEach(track => track.stop());
      record.node?.disconnect(); record.source?.disconnect();
      if (record.context && record.context.state !== 'closed') await record.context.close();
    }
    function abort() {
      serial++; const record = job; job = null;
      if (record) { record.cancelled = true; release(record).catch(() => {}); status.textContent = 'Voice cancelled. Keep typing or record again.'; }
      reset(); return !!record;
    }
    async function finish() {
      const record = job; if (!record || record.finishing) return;
      record.finishing = true; stop.disabled = true; cancel.textContent = 'Discard transcript';
      status.textContent = 'Transcribing locally with two CPU threads…';
      try {
        await release(record); if (record.cancelled) return;
        if (record.frames < record.rate * .1) throw Error('Record at least a moment of speech.');
        const samples = new Float32Array(record.frames); let at = 0;
        for (const chunk of record.chunks) { samples.set(chunk, at); at += chunk.length; }
        record.chunks = [];
        const offline = new OfflineAudioContext(1, Math.min(320000, Math.floor(samples.length * 16000 / record.rate)), 16000);
        const sound = offline.createBuffer(1, samples.length, record.rate); sound.copyToChannel(samples, 0);
        const source = offline.createBufferSource(); source.buffer = sound; source.connect(offline.destination); source.start();
        const resampled = await offline.startRendering(); if (record.cancelled) return;
        const result = await request('/api/voice', {audio: wav(resampled.getChannelData(0))});
        if (record.cancelled || job !== record) return;
        if (result.text && (record.inputVersion !== inputVersion || result.text.trim().length > limit)) {
          transcript.value = result.text; updateDraft(); draft.classList.remove('hidden');
          status.textContent = result.text.trim().length > limit ? `Voice transcript exceeds the ${limit}-character Navigator limit. Shorten it below; your existing request was kept.` : 'Your newer typing was kept. Use the local transcript below if you prefer it.';
          if (record.inputVersion === inputVersion) transcript.focus();
        }
        else if (result.text) applyTranscript(result.text.trim());
        else status.textContent = 'No speech recognized. Try again or type your request.';
      } catch (error) { if (!record.cancelled) status.textContent = 'Voice unavailable: ' + error.message + ' You can keep typing.'; }
      finally { if (job === record) { job = null; reset(); } }
    }
    async function start() {
      if (job) { if (!job.finishing) await finish(); return; }
      const token = ++serial; button.disabled = true; status.textContent = 'Checking existing local speech tools…';
      const record = {chunks: [], frames: 0, cancelled: false, inputVersion}; job = record;
      draft.classList.add('hidden');
      try {
        const config = await request('/api/voice'); if (token !== serial) return;
        if (!config.available) throw Error(config.reason || 'No local speech model is installed.');
        if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) throw Error('This browser cannot capture local audio. Use system dictation.');
        status.textContent = 'Allow microphone access to record up to 20 seconds. Audio stays on this Mac.';
        controls.classList.remove('hidden'); stop.disabled = true; cancel.textContent = 'Cancel recording';
        record.stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true}, video: false});
        if (record.cancelled) { await release(record); return; }
        record.context = new AudioContext(); record.rate = record.context.sampleRate;
        await record.context.audioWorklet.addModule('/navcom_voice_worklet.js');
        if (record.cancelled) { await release(record); return; }
        record.source = record.context.createMediaStreamSource(record.stream);
        record.node = new AudioWorkletNode(record.context, 'navcom-capture');
        record.node.port.onmessage = event => {
          if (record.cancelled || record.finishing) return;
          if (event.data === 'done') { finish(); return; }
          if (!(event.data instanceof Float32Array)) return;
          const chunk = event.data.subarray(0, Math.max(0, 20 * record.rate - record.frames));
          record.chunks.push(chunk); record.frames += chunk.length;
        };
        record.source.connect(record.node); record.node.connect(record.context.destination); await record.context.resume();
        if (record.cancelled) { await release(record); return; }
        const began = performance.now(); record.timer = setInterval(() => {
          const elapsed = Math.min(20, Math.floor((performance.now() - began) / 1000));
          status.textContent = `Listening locally · ${elapsed}/20 seconds · Stop when ready`;
          if (elapsed >= 20) finish();
        }, 250);
        button.disabled = false; button.setAttribute('aria-pressed', 'true'); stop.disabled = false;
        status.textContent = 'Listening locally · Stop when ready';
      } catch (error) {
        if (record) await release(record);
        if (token === serial) { job = null; reset(); status.textContent = 'Voice unavailable: ' + error.message + ' You can keep typing.'; input.focus(); }
      }
    }
    stop.addEventListener('click', finish); cancel.addEventListener('click', abort);
    window.addEventListener('pagehide', abort);
    return {start, cancel: abort, active: () => !!job};
  }
  return {attach};
})();
