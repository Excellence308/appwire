"""One bounded JSON packet per request; descriptors only for launching."""
import array
import json
import os
import socket

SOCKET = '/run/appwire/control.sock'
LIMIT = 131072


def send(sock, value, fds=()):
    data = json.dumps(value, separators=(',', ':')).encode()
    if len(data) > LIMIT:
        raise ValueError('Request too large')
    ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', fds))] if fds else []
    if sock.sendmsg([data], ancillary) != len(data):
        raise OSError('Incomplete request')


def receive(sock):
    data, ancillary, flags, _ = sock.recvmsg(LIMIT, socket.CMSG_SPACE(4 * 4), socket.MSG_CMSG_CLOEXEC)
    fds = []
    try:
        for level, kind, value in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                raise ValueError('Unexpected ancillary data')
            ints = array.array('i')
            ints.frombytes(value[:len(value) - len(value) % ints.itemsize])
            fds.extend(ints)
        if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or not data:
            raise ValueError('Truncated or empty packet')
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError('Request must be an object')
        return result, fds
    except Exception:
        for fd in fds:
            os.close(fd)
        raise
