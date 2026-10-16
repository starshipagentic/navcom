import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def test_browser_leaving_mid_response_does_not_kill_the_bridge(tmp_path):
    # The real `navcom --menu` launch: navcom.py makes broken pipes fatal for the
    # CLI (`navcom ... | head`), and the web bridge runs in that same process.
    env = {**os.environ, 'HOME': str(tmp_path)}
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / 'navcom.py'), '--menu', '--no-browser', '--index', str(tmp_path / 'index.sqlite')],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        line = proc.stdout.readline()
        assert 'http://127.0.0.1:' in line, line
        port = int(line.split('http://127.0.0.1:')[1].split('/')[0])
        request = f'GET /navcom_space.js HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n'.encode()
        for _ in range(20):
            # Ask for a large asset, then vanish without reading it (a reload mid-flight).
            sock = socket.create_connection(('127.0.0.1', port))
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            sock.sendall(request)
            sock.close()
        time.sleep(.5)
        assert proc.poll() is None, f'bridge exited with {proc.returncode}'
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=5) as response:
            assert response.status == 200
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait(timeout=5)
