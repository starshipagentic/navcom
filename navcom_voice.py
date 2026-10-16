"""Optional bounded local speech recognition using an already installed whisper.cpp.

Discovery does not load models. Explicit transcription starts one short-lived,
two-thread CPU process; no model download, daemon or cloud endpoint is involved.
"""
import argparse
import base64
import binascii
from contextlib import contextmanager
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import wave

MAX_SECONDS = 20
MAX_BYTES = 700000
MAX_MODEL_BYTES = 200 * 1024 * 1024
RUNTIME_BASE = Path('/tmp')
_active = threading.Lock()


@contextmanager
def _voice_slot():
    """One transcription per user across CLI and web processes.

    Keep a private, empty runtime lock file. Unlinking it after release would
    allow a waiter on the old inode to overlap a new lock. No audio or transcript
    is stored here. Reject links and other-user/group-writable runtime material.
    """
    if not _active.acquire(blocking=False):
        raise ValueError('Another voice recording is being transcribed; try again shortly.')
    directory_fd = lock_fd = None
    try:
        # TMPDIR varies between shells/app launches. A stable system runtime
        # location makes separate NavCom processes contend on the same inode.
        runtime = RUNTIME_BASE.resolve() / ('navcom-voice-' + str(os.getuid()))
        runtime.mkdir(mode=0o700, exist_ok=True)
        info = runtime.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Local voice runtime directory is not private and owned by this user.')
        directory_fd = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        checked = os.fstat(directory_fd)
        if ((checked.st_dev, checked.st_ino) != (info.st_dev, info.st_ino)
                or checked.st_uid != os.getuid() or checked.st_mode & 0o077):
            raise ValueError('Local voice runtime directory changed; try again.')
        lock_fd = os.open('transcription.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                          0o600, dir_fd=directory_fd)
        checked = os.fstat(lock_fd)
        if (not stat.S_ISREG(checked.st_mode) or checked.st_uid != os.getuid()
                or checked.st_mode & 0o077 or checked.st_nlink != 1 or checked.st_size != 0):
            raise ValueError('Local voice lock is not a private owned regular file.')
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another voice recording is being transcribed; try again shortly.') from None
        yield
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if directory_fd is not None:
            os.close(directory_fd)
        _active.release()


def status():
    executable = shutil.which('whisper-cli')
    selected = os.environ.get('NAVCOM_WHISPER_MODEL')
    candidates = ([Path(selected).expanduser()] if selected else
                  [Path.home()/'.cache/whisper-cpp'/name for name in
                   ('ggml-base.en.bin','ggml-tiny.en.bin','ggml-base.bin','ggml-tiny.bin')])
    model = None
    model_bytes = None
    for path in candidates:
        try:
            size = path.stat().st_size
            if path.is_file() and 0 < size <= MAX_MODEL_BYTES:
                model = path.resolve(); model_bytes = size; break
        except OSError:
            continue
    return dict(schema_version=1, available=bool(executable and model), provider='whisper.cpp',
                executable=executable, model=str(model) if model else None,
                model_bytes=model_bytes,
                max_seconds=MAX_SECONDS, max_audio_bytes=MAX_BYTES, threads=2, device='CPU',
                downloads=False, cloud=False, model_loaded=False,
                reason=None if executable and model else
                'Install whisper.cpp and select an existing tiny/base model with NAVCOM_WHISPER_MODEL, or use browser/system dictation. NavCom downloads nothing.')


def _audio(data):
    if not isinstance(data, bytes) or not 44 <= len(data) <= MAX_BYTES:
        raise ValueError('Supply a short PCM WAV recording (at most 20 seconds).')
    try:
        with wave.open(io.BytesIO(data),'rb') as stream:
            frames=stream.getnframes()
            if (stream.getnchannels(),stream.getsampwidth(),stream.getframerate(),stream.getcomptype()) != (1,2,16000,'NONE'):
                raise ValueError('Voice input must be mono 16-bit PCM WAV at 16000 Hz.')
            if not 1600 <= frames <= MAX_SECONDS*16000:
                raise ValueError('Voice recordings must be between 0.1 and 20 seconds.')
            pcm=stream.readframes(frames)
            if len(pcm)!=frames*2:
                raise ValueError('The WAV recording is incomplete.')
    except (wave.Error,EOFError) as exc:
        raise ValueError('Voice input must be an uncompressed PCM WAV recording.') from exc
    # Re-encode only the validated PCM. Original RIFF metadata never reaches the
    # native decoder, and there is no URL, playlist, or arbitrary-file input.
    safe=io.BytesIO()
    with wave.open(safe,'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(pcm)
    return safe.getvalue(), frames/16000


def transcribe(data):
    audio,duration=_audio(data)
    # Whisper can hallucinate words even for literal digital silence. Skip only
    # exact zero PCM; no amplitude threshold may discard quiet speech.
    with wave.open(io.BytesIO(audio), 'rb') as stream:
        silent = not any(stream.readframes(stream.getnframes()))
    if silent:
        return dict(schema_version=1,text='',duration=round(duration,3),seconds=0,
                    provider=None,model=None,device=None,threads=0,
                    provider_invoked=False,reason='digital_silence',
                    audio_retained=False,cloud=False,downloads=False)
    config=status()
    if not config['available']:
        raise ValueError(config['reason'])
    with _voice_slot():
        started=time.monotonic()
        with tempfile.TemporaryDirectory(prefix='navcom-voice-') as folder:
            path=Path(folder);input_path=path/'recording.wav';input_path.write_bytes(audio)
            output_path=path/'transcript'
            argv=[config['executable'],'--model',config['model'],'--file',str(input_path),
                  '--no-gpu','--threads','2','--processors','1','--language','en',
                  '--no-timestamps','--no-prints','--output-json','--output-file',str(output_path)]
            with tempfile.TemporaryFile() as console,tempfile.TemporaryFile() as errors:
                process=subprocess.Popen(argv,stdout=console,stderr=errors,cwd=folder)
                deadline=time.monotonic()+45
                try:
                    while process.poll() is None:
                        if time.monotonic()>deadline:
                            raise ValueError('Local transcription exceeded 45 seconds; try a shorter recording.')
                        if max(console.tell(),errors.tell())>2*1024*1024:
                            raise ValueError('Local speech provider exceeded its output budget.')
                        try:process.wait(timeout=.05)
                        except subprocess.TimeoutExpired:pass
                    if max(console.tell(),errors.tell())>2*1024*1024:
                        raise ValueError('Local speech provider exceeded its output budget.')
                    if process.returncode:
                        raise ValueError('Local speech recognition failed. Check the existing whisper.cpp model with navcom voice status.')
                    result_path=output_path.with_suffix('.json')
                    if not result_path.is_file() or result_path.stat().st_size>256*1024:
                        raise ValueError('Local speech provider returned no bounded transcript.')
                    result=json.loads(result_path.read_text())
                    if not isinstance(result,dict) or not isinstance(result.get('transcription'),list):
                        raise ValueError('Local speech provider returned an invalid transcript.')
                    segments=result.get('transcription',[])
                    text=' '.join(str(s.get('text','')).strip() for s in segments if isinstance(s,dict)).strip()
                    if len(text)>4000:
                        raise ValueError('Local speech transcript exceeds the command length limit.')
                    return dict(schema_version=1,text=text,duration=round(duration,3),
                                seconds=round(time.monotonic()-started,3),provider='whisper.cpp',
                                model=Path(config['model']).name,device='CPU',threads=2,
                                provider_invoked=True,audio_retained=False,cloud=False,downloads=False)
                finally:
                    if process.poll() is None:process.kill();process.wait()


def transcribe_request(data):
    encoded=data.get('audio')
    if not isinstance(encoded,str) or len(encoded)>((MAX_BYTES+2)//3)*4:
        raise ValueError('Voice payload must contain one bounded WAV recording.')
    try:audio=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error) as exc:raise ValueError('Invalid voice recording encoding.') from exc
    return transcribe(audio)


def parser():
    p=argparse.ArgumentParser(prog='navcom voice',description='Use optional existing local speech tools; no model downloads or cloud audio.')
    commands=p.add_subparsers(dest='action')
    check=commands.add_parser('status',help='Check existing whisper.cpp and tiny/base model availability without loading a model.')
    check.add_argument('--json',action='store_true')
    run=commands.add_parser('transcribe',help='Transcribe a short mono 16 kHz PCM WAV locally with two CPU threads.')
    run.add_argument('file',type=Path);run.add_argument('--json',action='store_true')
    return p


def run(argv):
    p=parser();args=p.parse_args(argv)
    if not args.action:p.print_help();return 0
    try:
        if args.action=='status':result=status()
        else:
            if not args.file.is_file() or args.file.stat().st_size>MAX_BYTES:raise ValueError('Supply a short WAV file, at most 700000 bytes.')
            result=transcribe(args.file.read_bytes())
        if args.json:print(json.dumps(result))
        elif args.action=='transcribe':print(result['text'])
        else:
            print('Local voice '+('available' if result['available'] else 'unavailable'))
            print(result['model'] or result['reason'])
            print('20 seconds per recording; two CPU threads; no downloads or cloud audio.')
        return 0
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        import sys
        print('navcom voice: '+str(exc),file=sys.stderr);return 2
