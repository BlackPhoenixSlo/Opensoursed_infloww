"""Pinned curl_cffi stream setup; native metadata only after worker completion.

Initial metadata is parsed from received headers without touching a performing
handle. Duplicate ownership outlives an abandoned waiter and ends on cleanup.
"""

import queue
import weakref
import threading
from curl_cffi import CurlError
from curl_cffi.requests.session import NOT_SET, set_curl_options, STREAM_END
from curl_cffi.requests.exceptions import RequestException
from of_managed_session import StreamState, HeaderView


def stream_once(
    self,
    method,
    url,
    params=None,
    data=None,
    json=None,
    headers=None,
    cookies=None,
    files=None,
    auth=None,
    timeout=NOT_SET,
    allow_redirects=None,
    max_redirects=None,
    proxies=None,
    proxy=None,
    proxy_auth=None,
    verify=None,
    referer=None,
    accept_encoding="gzip, deflate, br",
    content_callback=None,
    impersonate=None,
    ja3=None,
    akamai=None,
    perk=None,
    extra_fp=None,
    default_headers=None,
    default_encoding="utf-8",
    quote="",
    http_version=None,
    interface=None,
    cert=None,
    stream=None,
    max_recv_speed=0,
    multipart=None,
    discard_cookies=False,
):
    slot = self._managed_local.lease_slot
    parent = self.curl
    with slot.lock:
        slot.pins += 1
        self.registry.event("pin", slot)
    try:
        c = parent.duphandle()
    except BaseException:
        with slot.lock:
            slot.pins -= 1
        raise
    state = StreamState(self, slot, c)
    try:
        parent.reset()
        req, buffer, header_buffer, q, header_recved, quit_now = set_curl_options(
            c,
            method=method,
            url=url,
            params_list=[self.params, params],
            base_url=self.base_url,
            data=data,
            json=json,
            headers_list=[self.headers, headers],
            cookies_list=[self._cookies, cookies],
            files=files,
            auth=auth or self.auth,
            timeout=self.timeout if timeout is NOT_SET else timeout,
            allow_redirects=(
                self.allow_redirects if allow_redirects is None else allow_redirects
            ),
            max_redirects=(
                self.max_redirects if max_redirects is None else max_redirects
            ),
            proxies_list=[self.proxies, proxies],
            proxy=proxy,
            proxy_auth=proxy_auth or self.proxy_auth,
            verify_list=[self.verify, verify],
            referer=referer,
            accept_encoding=accept_encoding,
            content_callback=content_callback,
            impersonate=impersonate or self.impersonate,
            ja3=ja3 or self.ja3,
            akamai=akamai or self.akamai,
            perk=perk or self.perk,
            extra_fp=extra_fp or self.extra_fp,
            default_headers=(
                self.default_headers if default_headers is None else default_headers
            ),
            quote=quote,
            http_version=http_version or self.http_version,
            interface=interface or self.interface,
            stream=stream,
            max_recv_speed=max_recv_speed,
            multipart=multipart,
            cert=cert or self.cert,
            curl_options=self.curl_options,
            queue_class=queue.Queue,
            event_class=threading.Event,
        )

        state.quit, state.q = quit_now, q

        def perform():
            error = None
            try:
                c.perform()
            except CurlError as e:
                error = e
            finally:
                try:
                    final = self._parse_response(
                        c,
                        buffer,
                        header_buffer,
                        default_encoding,
                        discard_cookies,
                        request_url=req.url,
                    )
                    final.request = req
                    state.publish(final)
                    if error is not None:
                        q.put_nowait(RequestException(str(error), error.code, final))
                except BaseException as e:
                    wrapped = RequestException(str(e))
                    wrapped.__cause__ = e
                    q.put_nowait(wrapped)
                finally:
                    state.done.set()
                    header_recved.set()
                    q.put(STREAM_END)

        state.future = self.executor.submit(perform)
        header_recved.wait()
        with state.meta_lock:
            if state.final is not None:
                rsp = self.response_class()
                state.update(rsp, state.final)
            else:
                rsp = self._parse_response(
                    HeaderView(
                        req.url,
                        header_buffer,
                        self.allow_redirects
                        if allow_redirects is None
                        else allow_redirects,
                    ),
                    buffer,
                    header_buffer,
                    default_encoding,
                    True,
                )
                rsp.metadata_pending = True
                for field in HeaderView.pending:
                    setattr(rsp, field, None)
            rsp.request, rsp.queue, rsp.quit_now, rsp.stream_task = (
                req,
                q,
                quit_now,
                state.future,
            )
            rsp._managed_stream = state
            state.response = weakref.ref(rsp)
            rsp._abandon_finalizer = weakref.finalize(rsp, state.abandon)
        with q.mutex:
            first = q.queue[0] if q.queue else None
        if isinstance(first, BaseException):
            state.finish()
            raise first
        if self.raise_for_status:
            try:
                rsp.raise_for_status()
            except BaseException:
                state.finish()
                raise
        return rsp
    except BaseException:
        state.finish()
        raise
