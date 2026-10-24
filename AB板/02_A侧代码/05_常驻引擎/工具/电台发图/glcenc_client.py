#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glcenc_client.py —— 跟常驻编码器说一句话

    python3 glcenc_client.py PING
    python3 glcenc_client.py ENC p1 /root/glc/inputs_photo/p1.ftmp /root/enc/p1.glc

退出码：0 成功；1 服务没起；2 服务返回 ERR
"""
import os
import socket
import sys

SOCK = os.environ.get('GLC_ENC_SOCK', '/var/run/glcenc.sock')


def request(line, timeout=300.0):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(SOCK)
    s.sendall((line + '\n').encode())
    buf = b''
    while not buf.endswith(b'\n'):
        d = s.recv(4096)
        if not d:
            break
        buf += d
    s.close()
    return buf.decode('utf-8', 'replace').strip()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    if not os.path.exists(SOCK):
        print('NO_DAEMON')
        return 1
    try:
        rep = request(' '.join(sys.argv[1:]))
    except Exception as e:
        print('NO_DAEMON (%s)' % e)
        return 1
    print(rep)
    return 0 if rep.startswith(('OK', 'PONG', 'BYE')) else 2


if __name__ == '__main__':
    sys.exit(main())
