"""Opt-in local request phase probe; SLOP_VAULT_ITEMS_TRACE=1 only. No service hooks.

All spans are inclusive elapsed wall time, not CPU time. SQL includes driver/loop
scheduling; execute includes pool, SQL and ORM work. Do not sum nested spans.
Only synthetic vault-ai items requests are retained, in memory, until teardown.
"""
import contextvars
import functools
import os
import time

_active = contextvars.ContextVar('slop_vault_items_trace', default=None)
_rows = []


def wire(app, loopback, _relay):
    if os.environ.get('SLOP_VAULT_ITEMS_TRACE') != '1':
        return
    from fastapi import Request
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncSession
    from starlette.responses import JSONResponse
    import importlib
    import fastapi.routing
    import vault_ai_api
    db_module = importlib.import_module('db.engine')

    def add(key, start):
        row = _active.get()
        if row is not None:
            row[key] = row.get(key, 0.0) + (time.perf_counter() - start) * 1000

    def wrap_sync(obj, name, key):
        real = getattr(obj, name)
        @functools.wraps(real)
        def wrapped(*a, **kw):
            start = time.perf_counter()
            try:
                return real(*a, **kw)
            finally:
                add(key, start)
        setattr(obj, name, wrapped)

    def wrap_async(obj, name, key):
        real = getattr(obj, name)
        @functools.wraps(real)
        async def wrapped(*a, **kw):
            start = time.perf_counter()
            try:
                return await real(*a, **kw)
            finally:
                add(key, start)
        setattr(obj, name, wrapped)

    wrap_sync(db_module.engine.sync_engine.pool, '_do_get', 'pool_ms')
    wrap_async(AsyncSession, 'execute', 'execute_ms')
    wrap_sync(vault_ai_api, '_overlay', 'overlay_ms')
    wrap_async(fastapi.routing, 'serialize_response', 'serialize_ms')
    wrap_sync(JSONResponse, 'render', 'render_ms')
    for route in app.routes:
        if getattr(route, 'path', None) == '/admin/vault-ai/items':
            wrap_async(route.dependant, 'call', 'endpoint_ms')

    def before(conn, cursor, statement, parameters, context, many):
        context._slop_trace_started = time.perf_counter()

    def after(conn, cursor, statement, parameters, context, many):
        row = _active.get()
        if row is not None:
            elapsed = (time.perf_counter() - context._slop_trace_started) * 1000
            row['sql_ms'] = row.get('sql_ms', 0.0) + elapsed
            row.setdefault('sql', []).append({'ms': elapsed, 'statement': statement})

    event.listen(db_module.engine.sync_engine, 'before_cursor_execute', before)
    event.listen(db_module.engine.sync_engine, 'after_cursor_execute', after)

    class TraceMiddleware:
        def __init__(self, app):
            self.app = app
        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http' or scope['path'] != '/admin/vault-ai/items':
                return await self.app(scope, receive, send)
            row = {'id': str(len(_rows)), 'query': scope.get('query_string', b'').decode(),
                   'start_epoch': time.time()}
            _rows.append(row)
            token = _active.set(row)
            start = time.perf_counter()
            async def traced_send(message):
                if message['type'] == 'http.response.start':
                    row['status'] = message['status']
                    message['headers'] = [*message.get('headers', []),
                                          (b'x-slop-trace', row['id'].encode())]
                await send(message)
            try:
                await self.app(scope, receive, traced_send)
            finally:
                row['server_ms'] = (time.perf_counter() - start) * 1000
                _active.reset(token)
    app.add_middleware(TraceMiddleware)

    async def dump(request: Request):
        loopback(request)
        return {'rows': _rows, 'spans': 'inclusive wall ms; SQL includes driver/loop scheduling'}
    app.add_api_route('/__slop/vault-items-trace', dump, methods=['GET'])
