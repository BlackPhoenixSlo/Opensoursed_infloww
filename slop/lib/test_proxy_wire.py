"""proxy_wire._pipe: one exchange per tunnel while refusing, 1xx interim answers excluded."""
import asyncio
import socket

from slop.lib import proxy_wire as pw


async def _relay(client_chunks: list[bytes], upstream_chunks: list[bytes], refusing: bool) -> tuple[bytes, bytes]:
    """client <-> [_pipe pair] <-> upstream over socketpairs; returns (what upstream got, what client got)."""
    c_out, p_c = socket.socketpair()
    p_u, u_out = socket.socketpair()
    cr, cw = await asyncio.open_connection(sock=p_c)
    ur, uw = await asyncio.open_connection(sock=p_u)
    answered = asyncio.Event()
    tunnel = asyncio.gather(pw._pipe(ur, cw, (p_u, p_c), answered),
                            pw._pipe(cr, uw, (p_c, p_u), None, answered, lambda: refusing))
    loop = asyncio.get_running_loop()
    got_up, got_client = b"", b""
    for c, u in zip(client_chunks, upstream_chunks):
        if c:
            await loop.sock_sendall(c_out, c)
            await asyncio.sleep(0.05)
        if u:
            await loop.sock_sendall(u_out, u)
            await asyncio.sleep(0.05)
    c_out.shutdown(socket.SHUT_WR)
    await asyncio.wait_for(tunnel, 5)
    for s, acc in ((u_out, "up"), (c_out, "client")):
        s.setblocking(False)
        data = b""
        while True:
            try:
                chunk = s.recv(65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            data += chunk
        if acc == "up":
            got_up = data
        else:
            got_client = data
    return got_up, got_client


def test_100_continue_keeps_the_body_while_refusing():
    up, cl = asyncio.run(_relay([b"POST / HTTP/1.1\r\nExpect: 100-continue\r\n\r\n", b"BODY", b""],
                                [b"HTTP/1.1 100 Continue\r\n\r\n", b"HTTP/1.1 200 OK\r\n\r\n", b""], True))
    assert up.endswith(b"BODY") and cl.endswith(b"200 OK\r\n\r\n")


def test_second_request_closes_the_tunnel_only_while_refusing():
    req = b"GET / HTTP/1.1\r\n\r\n"
    up, _ = asyncio.run(_relay([req, req], [b"HTTP/1.1 200 OK\r\n\r\n", b""], True))
    assert up.count(b"GET /") == 1
    up, _ = asyncio.run(_relay([req, req], [b"HTTP/1.1 200 OK\r\n\r\n", b""], False))
    assert up.count(b"GET /") == 2
