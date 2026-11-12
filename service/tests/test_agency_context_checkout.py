"""Real SQLite, authenticated settings handler; count only agency-resolution checkouts."""
import _harness
_harness.bootstrap()

import asyncio
import contextvars
from contextlib import asynccontextmanager
from unittest.mock import patch
from sqlalchemy import event, update, text
import _agency_fixtures as fx
import agency_context as ac
import employees
import settings_api
from db.engine import engine, get_session
from db.models import Employee

IDS = fx.seed_two_agencies()
MEASURE = contextvars.ContextVar('agency_measure', default=None)
REAL_CONTEXT = ac.agency_context
CHECKED_OUT = set()

async def measured_context(**kw):
    stats = {'checkouts': 0, 'held': 0, 'writes': 0}
    token = MEASURE.set(stats)
    try:
        result = await REAL_CONTEXT(**kw)
        assert stats['held'] == 0, stats
        measured_context.last = (result, stats)
        return result
    finally:
        MEASURE.reset(token)

@event.listens_for(engine.sync_engine, 'checkout')
def checkout(conn, rec, proxy):
    CHECKED_OUT.add(id(rec))
    stats = MEASURE.get()
    if stats is not None:
        stats['checkouts'] += 1
        stats['held'] += 1
        rec.info['agency_stats'] = stats

@event.listens_for(engine.sync_engine, 'checkin')
def checkin(conn, rec):
    CHECKED_OUT.discard(id(rec))
    stats = rec.info.pop('agency_stats', None)
    if stats is not None:
        stats['held'] -= 1

@event.listens_for(engine.sync_engine, 'before_cursor_execute')
def statement(conn, cursor, statement, params, context, many):
    stats = MEASURE.get()
    if stats is not None and statement.lstrip().split()[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):
        stats['writes'] += 1


def request(client):
    with patch.object(ac, 'agency_context', measured_context):
        return client.get('/admin/settings/applied', headers={'x-account-id': IDS['creator_a']})


def case_existing_mirror_one_checkout_no_write_same_response():
    client = fx.login_chatter('chatter_a')
    first = request(client)
    assert first.status_code == 200, first.text
    original_context, _ = measured_context.last
    second = request(client)
    ctx, stats = measured_context.last
    assert second.status_code == 200 and second.json() == first.json(), second.text
    assert ctx == original_context and ctx.agency_user_id == IDS['agency_a_owner']
    assert stats == {'checkouts': 1, 'held': 0, 'writes': 0}, stats
    print('measured existing mirror:', stats, ctx)


def case_inactive_mirror_included_and_lookup_failure_503():
    client = fx.login_chatter('chatter_a')
    request(client)
    ctx, _ = measured_context.last
    async def inactive():
        async with get_session() as s:
            await s.execute(update(Employee).where(Employee.id == ctx.employee_id).values(is_active=False))
    asyncio.run(inactive())
    assert request(client).status_code == 200
    assert measured_context.last[0] == ctx
    async def broken(*args):
        raise RuntimeError('injected mirror lookup failure')
    with patch.object(employees, 'mirror_id', broken):
        response = request(client)
    assert response.status_code == 503, response.text


def case_session_exit_failure_never_exposes_hit():
    client = fx.login_chatter('chatter_a')
    @asynccontextmanager
    async def failed_exit():
        async with get_session() as session:
            yield session
        raise RuntimeError('injected commit/session exit failure')
    with patch.object(ac, 'get_session', failed_exit):
        response = request(client)
    assert response.status_code == 503, response.text


def case_duplicate_pair_resolves_to_lowest_id():
    """A raced duplicate Mirror (no uq_employees_chatter_owner) takes the lowest id
    (employees.mirror_id, main's dup-safe read), as the role-hook path does."""
    client = fx.login_chatter('chatter_a')
    request(client)
    employee_id = measured_context.last[0].employee_id
    async def duplicate():
        async with get_session() as session:
            ddl = (await session.execute(text("SELECT sql FROM sqlite_master WHERE name='uq_employees_chatter_owner'"))).scalar_one()
            await session.execute(text('DROP INDEX uq_employees_chatter_owner'))
            original = await session.get(Employee, employee_id)
            row = Employee(display_name='duplicate', user_id=original.user_id,
                           chatter_id=original.chatter_id, is_active=True)
            session.add(row)
            await session.flush()
            return row.id, ddl
    duplicate_id, ddl = asyncio.run(duplicate())
    try:
        response = request(client)
        assert response.status_code == 200, response.text
        assert measured_context.last[0].employee_id == employee_id < duplicate_id, (measured_context.last, duplicate_id)
    finally:
        async def restore():
            async with get_session() as session:
                await session.delete(await session.get(Employee, duplicate_id))
                await session.flush()
                await session.execute(text(ddl))
        asyncio.run(restore())


def case_concurrent_lazy_create_rechecks_after_release_and_assigns_default_role():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import select
    clients = [fx.login_chatter('chatter_ab') for _ in range(2)]
    gate = Barrier(2)
    original = employees.get_or_create_mirror_employee
    calls = []
    async def fallback(*args, **kwargs):
        stats = MEASURE.get()
        assert stats is not None and stats['held'] == 0, stats
        calls.append(args)
        await asyncio.to_thread(gate.wait, 10)
        return await original(*args, **kwargs)
    with patch.object(ac, 'agency_context', measured_context), patch.object(employees, 'get_or_create_mirror_employee', fallback):
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda client: client.get('/admin/settings/applied', headers={'x-account-id': IDS['creator_a']}), clients))
    assert len(calls) == 2, calls
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    async def verify():
        async with get_session() as session:
            rows = (await session.execute(select(Employee.id).where(Employee.chatter_id == IDS['chatter_ab'], Employee.user_id == IDS['agency_a_owner']))).scalars().all()
            assert len(rows) == 1, rows
            roles = await settings_api.applied_blob(session, IDS['agency_a_owner'], 'roles')
            assert roles['assignments'][str(rows[0])] == settings_api.DEFAULT_LOGIN_ROLE, roles
    asyncio.run(verify())
    print('measured concurrent fallback: both read sessions released; one mirror with default role')


def case_actual_message_handler_releases_connections_before_of_boundary():
    import server
    import accounts
    accounts.upsert_account(IDS['creator_a'], nickname='local-fixture')
    client = fx.login_chatter('chatter_ab')
    calls = []
    class LocalPeer:
        def get_messages(self, *args, **kwargs):
            assert not CHECKED_OUT, CHECKED_OUT
            calls.append((args, kwargs))
            return {'list': [], 'hasMore': False}
    with patch.object(ac, 'agency_context', measured_context), patch.object(server, '_get_client', lambda: LocalPeer()):
        response = client.get('/api/of/v2/chats/123/messages', headers={'x-account-id': IDS['creator_a']})
    assert response.status_code == 200, response.text
    assert response.json() == {'list': [], 'hasMore': False}, response.text
    assert len(calls) == 1 and calls[0][0] == (123,), calls
    print('measured actual messages handler: zero checked-out connections at OF call boundary')


if __name__ == '__main__':
    _harness.run()
