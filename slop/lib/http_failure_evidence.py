"""Bounded browser 5xx evidence for local scenarios; no request cookies or auth."""
import asyncio
import time
from urllib.parse import urlsplit


class HttpFailureEvidence:
    def __init__(self, context, limit=32):
        self.context, self.limit = context, limit
        self.rows, self.tasks = [], []
        self.dropped = 0
        context.on('response', self.response)

    def response(self, response):
        if response.status < 500:
            return
        if len(self.rows) >= self.limit:
            self.dropped += 1
            return
        row = {'at': time.time(), 'path': urlsplit(response.url).path,
               'status': response.status, 'method': response.request.method}
        self.rows.append(row)
        self.tasks.append(asyncio.create_task(self.capture(response, row)))

    async def capture(self, response, row):
        try:
            headers = await response.all_headers()
            row['headers'] = {k: v for k, v in headers.items() if k.lower() in
                ('server', 'via', 'content-type', 'content-length', 'x-request-id')}
            length = headers.get('content-length')
            if length is None or not length.isdigit() or int(length) > 8192:
                row['body_unavailable'] = 'unknown or oversized content-length'
            else:
                row['body'] = (await response.body())[:8192].decode('utf-8', errors='replace')
        except Exception as exc:
            row['capture_error'] = type(exc).__name__

    async def finish(self):
        self.context.remove_listener('response', self.response)
        if self.tasks:
            done, pending = await asyncio.wait(self.tasks, timeout=5)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for row, task in zip(self.rows, self.tasks):
                if task in pending:
                    row['capture_error'] = 'timeout'
        return {'responses': self.rows, 'dropped': self.dropped}
