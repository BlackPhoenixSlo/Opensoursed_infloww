"""Scoped cookie intent, no network or account access."""
import _harness
_harness.bootstrap()
from curl_cffi.requests import Headers
from of_cookie_events import response_cookie_events, apply_cookie_events, cookie_from_row


def events(*values, url='https://api.onlyfans.com/a/request'):
    return response_cookie_events(url, Headers([('Set-Cookie', x) for x in values]), now=1000)


def case_scoped_deletion_and_empty():
    rows=[dict(name='__cf_bm',value='old',domain='.onlyfans.com',path=p) for p in ('/a','/b')]
    assert apply_cookie_events(rows,events('__cf_bm=; Domain=onlyfans.com; Path=/a; Max-Age=0'))
    assert len(rows)==1 and rows[0]['path']=='/b'
    assert apply_cookie_events(rows,events('__cf_bm=; Domain=onlyfans.com; Path=/a'))
    assert next(x for x in rows if x['path']=='/a')['value']==''


def case_domain_and_path():
    assert not events('__cf_bm=x; Domain=evil.test','__cf_bm=x; Domain=com','__cf_bm=x; Domain=onlyfans.com.evil.test')
    assert events('__cf_bm=x')[0].domain=='api.onlyfans.com'
    assert events('__cf_bm=x')[0].path=='/a'
    assert events('__cf_bm=x; Domain=onlyfans.com')[0].domain=='.onlyfans.com'
    assert not events('__cf_bm=x; Domain=0.0.1',url='https://127.0.0.1/a')


def case_expiry_secure_and_duplicate_order():
    e=events('__cf_bm=same; Max-Age=60; Expires=Thu, 01 Jan 1970 00:00:01 GMT; Secure')[0]
    assert e.expires==1060 and not e.delete and e.secure
    assert events('__cf_bm=x; Expires=Thu, 01 Jan 1970 00:00:01 GMT')[0].delete
    assert not events('__cf_bm=x; Secure',url='http://onlyfans.com/a')
    rows=[]
    apply_cookie_events(rows,events('__cf_bm=a; Path=/','__cf_bm=; Path=/; Max-Age=0','__cf_bm=b; Path=/'))
    assert len(rows)==1 and rows[0]['value']=='b'
    assert apply_cookie_events(rows,events('__cf_bm=b; Path=/; Secure; Max-Age=60'))
    assert rows[0]['secure'] and rows[0]['expires']==1060
    assert not apply_cookie_events(rows,events('__cf_bm=b; Path=/; Secure; Max-Age=60'))


def case_reload_attributes():
    row=dict(name='__cf_bm',value='',domain='onlyfans.com',path='/a',secure=True,expires=1060,hostOnly=True)
    c=cookie_from_row(row,now=1000)
    assert c.secure and c.expires==1060 and c.path=='/a' and not c.domain_specified
    assert cookie_from_row(row,now=1061) is None
    assert cookie_from_row(dict(row,expires=0),now=1000) is None
    assert cookie_from_row(dict(row,expires=-1),now=1000).expires is None

_harness.run()
