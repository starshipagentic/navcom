"""Bounded PCM intake and process-wide local model admission."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import wave

import pytest

import navcom_voice as voice


def wav(*, frames=1600, channels=1, rate=16000, width=2, sample=0):
    data = io.BytesIO()
    with wave.open(data, 'wb') as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(width)
        stream.setframerate(rate)
        stream.writeframes(sample.to_bytes(width, 'little', signed=True) * frames * channels)
    return data.getvalue()


@contextmanager
def other_process_slot(tmp_path):
    code = """import sys
from pathlib import Path
import navcom_voice as v
v.RUNTIME_BASE = Path(sys.argv[1])
with v._voice_slot():
 print('locked',flush=True)
 sys.stdin.readline()
"""
    child = subprocess.Popen([sys.executable, '-c', code, str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([child.stdout], [], [], 5)
        assert ready, 'fixture could not acquire local model slot'
        assert child.stdout.readline().strip() == 'locked'
        yield child
    finally:
        if child.poll() is None:
            child.communicate('\n', timeout=5)
        else:
            child.communicate(timeout=5)


def test_cross_process_slot_rejects_before_loading_and_releases(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, 'RUNTIME_BASE', tmp_path)
    monkeypatch.setattr(voice, 'status', lambda: dict(available=True))
    with other_process_slot(tmp_path):
        monkeypatch.setattr(voice.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('Second model was loaded'))
        with pytest.raises(ValueError, match='Another voice recording'):
            voice.transcribe(wav(sample=1))
    with voice._voice_slot():
        runtime = tmp_path / f'navcom-voice-{os.getuid()}'
        assert sorted(p.name for p in runtime.iterdir()) == ['transcription.lock']
        assert (runtime / 'transcription.lock').stat().st_size == 0
        assert runtime.stat().st_mode & 0o777 == 0o700
        assert (runtime / 'transcription.lock').stat().st_mode & 0o777 == 0o600


def test_process_exit_and_failed_transcription_release_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, 'RUNTIME_BASE', tmp_path)
    with other_process_slot(tmp_path) as child:
        child.terminate()
        child.wait(timeout=5)
        with voice._voice_slot():
            pass
    with pytest.raises(RuntimeError):
        with voice._voice_slot():
            raise RuntimeError('fixture failure')
    with voice._voice_slot():
        pass


@pytest.mark.parametrize('kind', ['directory-link', 'directory-permissions', 'file-link', 'file-hardlink', 'file-permissions', 'file-contents'])
def test_lock_rejects_shared_or_linked_material_without_reading_it(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(voice, 'RUNTIME_BASE', tmp_path)
    runtime = tmp_path / f'navcom-voice-{os.getuid()}'
    private = tmp_path / 'unrelated.txt'
    private.write_text('PRIVATE_FIXTURE_NOT_AUDIO')
    if kind == 'directory-link':
        target = tmp_path / 'other-directory'
        target.mkdir(mode=0o700)
        runtime.symlink_to(target)
    else:
        runtime.mkdir(mode=0o700)
        lock = runtime / 'transcription.lock'
        if kind == 'directory-permissions':
            runtime.chmod(0o755)
        elif kind == 'file-link':
            lock.symlink_to(private)
        elif kind == 'file-hardlink':
            private.chmod(0o600)
            os.link(private, lock)
        elif kind == 'file-permissions':
            lock.write_text('')
            lock.chmod(0o666)
        elif kind == 'file-contents':
            lock.write_text('UNRELATED CONTENT')
            lock.chmod(0o600)
    with pytest.raises((ValueError, OSError)):
        with voice._voice_slot():
            pytest.fail('Unsafe lock admitted model')
    assert private.read_text() == 'PRIVATE_FIXTURE_NOT_AUDIO'
    assert not voice._active.locked()


def test_voice_slot_reuses_inode_and_is_independent_of_tmpdir(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, 'RUNTIME_BASE', tmp_path)
    with voice._voice_slot():
        lock = tmp_path / f'navcom-voice-{os.getuid()}' / 'transcription.lock'
        inode = lock.stat().st_ino
    monkeypatch.setenv('TMPDIR', str(tmp_path / 'another-shell'))
    with voice._voice_slot():
        assert lock.stat().st_ino == inode


@pytest.mark.parametrize('options', [dict(frames=320001), dict(frames=1599), dict(channels=2), dict(rate=44100), dict(width=1)])
def test_audio_limits_fail_before_provider_discovery(options, monkeypatch):
    monkeypatch.setattr(voice, 'status', lambda: pytest.fail('Bad audio reached provider'))
    with pytest.raises(ValueError):
        voice.transcribe(wav(**options))


def test_valid_pcm_is_reencoded_without_riff_metadata():
    original = wav() + b'JUNK' + (16).to_bytes(4, 'little') + b'PRIVATE_METADATA'
    sanitized, seconds = voice._audio(original)
    assert seconds == .1
    assert b'PRIVATE_METADATA' not in sanitized
    assert sanitized == wav()


def test_status_does_not_accept_large_model_or_start_process(tmp_path, monkeypatch):
    model = tmp_path / 'selected-model.bin'
    monkeypatch.setenv('NAVCOM_WHISPER_MODEL', str(model))
    monkeypatch.setattr(voice.shutil, 'which', lambda _: '/installed/whisper-cli')
    monkeypatch.setattr(voice.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('Status loaded model'))
    with model.open('wb') as stream:
        stream.truncate(voice.MAX_MODEL_BYTES + 1)
    assert voice.status()['available'] is False
    model.write_bytes(b'model fixture')
    status = voice.status()
    assert status['available'] and status['model_bytes'] == 13
    assert not status['model_loaded'] and not status['downloads']


def test_native_fixture_uses_cpu_bounds_and_removes_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, 'RUNTIME_BASE', tmp_path)
    monkeypatch.setattr(voice.tempfile, 'tempdir', str(tmp_path))
    executable = tmp_path / 'fixture-whisper'
    executable.write_text('#!' + sys.executable + '\n' + """import json,sys
from pathlib import Path
args=sys.argv[1:]
assert args[args.index('--threads')+1]=='2'
assert args[args.index('--processors')+1]=='1'
assert '--no-gpu' in args
assert Path(args[args.index('--file')+1]).is_file()
Path(args[args.index('--output-file')+1]+'.json').write_text(json.dumps({'transcription':[{'text':'Find the login work'}]}))
""")
    executable.chmod(0o700)
    monkeypatch.setattr(voice, 'status', lambda: dict(available=True, executable=str(executable), model=str(tmp_path / 'tiny.bin')))
    result = voice.transcribe(wav(sample=1))
    assert result['text'] == 'Find the login work'
    assert result['threads'] == 2 and result['device'] == 'CPU' and not result['audio_retained']
    assert not list(tmp_path.rglob('*.wav'))
    assert not list(tmp_path.rglob('transcript.json'))


def test_exact_digital_silence_returns_no_speech_before_any_model_or_lock(monkeypatch):
    monkeypatch.setattr(voice, 'status', lambda: pytest.fail('Silence discovered a provider'))
    monkeypatch.setattr(voice, '_voice_slot', lambda: pytest.fail('Silence occupied the model slot'))
    result = voice.transcribe(wav(frames=32000))
    assert result['text'] == '' and result['duration'] == 2
    assert result['reason'] == 'digital_silence' and result['provider_invoked'] is False
    assert result['model'] is None and result['threads'] == 0
    assert not result['audio_retained'] and not result['downloads'] and not result['cloud']


def test_single_nonzero_sample_is_never_discarded_as_quiet_speech(monkeypatch):
    data = bytearray(wav(frames=1600))
    data[-2:] = b'\x01\x00'
    monkeypatch.setattr(voice, 'status', lambda: dict(available=False, reason='Provider was reached'))
    with pytest.raises(ValueError, match='Provider was reached'):
        voice.transcribe(bytes(data))
