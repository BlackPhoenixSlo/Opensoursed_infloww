import asyncio
import socket

from slop.lib import proxy_wire as pw


async def _relay(client_chunks: list[bytes], upstream_chunks: list[bytes], refusing: bool) -> tuple[bytes, bytes]:
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


def test_100_continue_split_across_reads_keeps_the_body_while_refusing():
    up, cl = asyncio.run(_relay([b"POST / HTTP/1.1\r\nExpect: 100-continue\r\n\r\n", b"", b"BODY", b""],
                                [b"HTTP/1.1 100 Cont", b"inue\r\n\r\n", b"HTTP/1.1 200 OK\r\n\r\n", b""], True))
    assert up.endswith(b"BODY") and cl.endswith(b"200 OK\r\n\r\n")


def test_answered_splits():
    assert pw._answered(b"HTTP/1.1 10") == (False, b"HTTP/1.1 10")
    assert pw._answered(b"HTTP/1.1 100 Continue\r\n") == (False, b"HTTP/1.1 100 Continue\r\n")
    assert pw._answered(b"HTTP/1.1 100 Continue\r\n\r\n") == (False, b"")
    assert pw._answered(b"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\n")[0]
    assert pw._answered(b"HTTP/1.1 101 Switching")[0] and pw._answered(b"HTTP/1.1 200")[0]
    assert pw._answered(b"\x16\x03\x01\x02\x00")[0]


def test_second_request_closes_the_tunnel_only_while_refusing():
    req = b"GET / HTTP/1.1\r\n\r\n"
    up, _ = asyncio.run(_relay([req, req], [b"HTTP/1.1 200 OK\r\n\r\n", b""], True))
    assert up.count(b"GET /") == 1
    up, _ = asyncio.run(_relay([req, req], [b"HTTP/1.1 200 OK\r\n\r\n", b""], False))
    assert up.count(b"GET /") == 2


def test_websocket_tunnels_through_the_wire():
    import websockets
    from websockets.asyncio.client import connect

    async def go() -> str:
        async def echo(ws):
            await ws.send(await ws.recv())

        async with websockets.serve(echo, "127.0.0.1", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            with pw.ProxyWire() as px:
                async with connect(f"ws://127.0.0.1:{port}/", proxy=f"socks5://127.0.0.1:{px.port}",
                                   open_timeout=5) as ws:
                    await ws.send("hi")
                    return await asyncio.wait_for(ws.recv(), 5)

    assert asyncio.run(go()) == "hi"
