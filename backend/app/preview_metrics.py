"""Opt-in fictitious Neon request counters. Never SQL text, values or wire egress.

Counts raw libpq result-field lengths before decoding. Missing/cursor-delayed
results are explicitly incomplete. Does not add queries or change ranking data.
"""
from contextvars import ContextVar
from dataclasses import dataclass

_current = ContextVar('sigra_preview_request_metrics', default=None)
_installed = False


@dataclass
class Counters:
    statements: int = 0
    result_field_bytes: int = 0
    incomplete: bool = False


def observe(connection, cursor, statement, parameters, context, executemany):
    value = _current.get()
    if value is None:
        return
    value.statements += 1
    try:
        result = getattr(cursor, 'pgresult', None)
        if getattr(cursor, 'name', None) or result is None:
            value.incomplete = True
            return
        # Never decode, retain, log or include any field content in headers.
        value.result_field_bytes += sum(len(item) for row in range(result.ntuples)
                                       for col in range(result.nfields)
                                       if (item := result.get_value(row, col)) is not None)
    except Exception:
        value.incomplete = True


def install():
    global _installed
    if not _installed:
        from sqlalchemy import event
        from sqlalchemy.engine import Engine
        event.listen(Engine, 'after_cursor_execute', observe)
        _installed = True


class PreviewMetrics:
    def __init__(self, app):
        install()
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or not scope.get('path', '').endswith('/api/v1/test-runs/recommendation'):
            return await self.app(scope, receive, send)
        value = Counters()
        token = _current.set(value)
        async def measured(message):
            if message['type'] == 'http.response.start':
                message = {**message, 'headers': [*message.get('headers', []),
                    (b'x-sigra-preview-db-statements', str(value.statements).encode('ascii')),
                    (b'x-sigra-preview-db-result-field-bytes', str(value.result_field_bytes).encode('ascii')),
                    (b'x-sigra-preview-db-metrics-complete', str(not value.incomplete).lower().encode('ascii'))]}
            await send(message)
        try:
            await self.app(scope, receive, measured)
        finally:
            _current.reset(token)
