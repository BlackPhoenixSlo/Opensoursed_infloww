import json, os
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
READ_ONLY="Read-only in Inflowwww for now"
def fx(name):
    with open(os.path.join(ROOT, f"app/lib/__fixtures__/of/statistics-{name}.json")) as f: return json.load(f)
def rev(name):
    body=fx(name)
    for k in ("list","items","users"):
        if isinstance(body.get(k), list): body[k]=body[k][::-1]
    return body
def each(values, body): return {v: body for v in values}
def rekey(name, frm, to, total):
    body=fx(name); body[to]={**body.pop(frm), "total":total}; return body
def hits(name, text):
    body=fx(name); body["items"]=[i for i in body["items"] if text in i.get("text", "")]; return body
def top_by(field, n):
    body=fx("subs-top-tips"); u=body["users"][1]["subscribedOnData"]; u[field]+=n; u["totalSumm"]+=n
    body["users"].sort(key=lambda x: -x["subscribedOnData"][field]); return body
def spot(name, at, **top):
    body=fx(name)
    for path, (day, n) in at.items():
        *up, last=path.split("."); holder=body
        for k in up: holder=holder[k]
        holder[last]=[{**pt, "count": n if pt["date"].startswith(day) else 0} for pt in holder[last]]
    body.update(top); return body
def SNAP(rows, chart=None):
    return """() => {
  const t = (e) => e.textContent.replace(/\\s+/g, ' ').trim();
  const rows = [...document.querySelectorAll(%s)].filter((e) => e.checkVisibility()).map((e) => [...e.children].map(t).join(' | '));
  const sel = %s;
  const chart = sel ? [...document.querySelectorAll(sel)].filter((e) => e.checkVisibility() && !e.closest('.l-wrapper__sidebar')).map(t).join(' | ') : '';
  return { first: rows[0] ?? null, rows, chart };
}""" % (json.dumps(rows), json.dumps(chart))
def TIPS(rows, chart=None, canvas="canvas", checked=None):
    return """() => {
  const s = (%s)();
  const t = (e) => e.textContent.replace(/\\s+/g, ' ').trim();
  const c = [...document.querySelectorAll(%s)].find((e) => e.checkVisibility() && !e.closest('.l-wrapper__sidebar'));
  const tips = [];
  if (c) {
    const r = c.getBoundingClientRect();
    for (let x = r.left; x <= r.right; x += 3) {
      c.dispatchEvent(new MouseEvent('mousemove', { clientX: x, clientY: r.top + r.height / 2, bubbles: true }));
      const tip = (c.closest('.b-chart') ?? c.parentElement)?.querySelector('[data-oi-chart-tip]');
      if (tip && !tips.includes(t(tip))) tips.push(t(tip));
    }
    c.dispatchEvent(new MouseEvent('mouseleave'));
  }
  const cs = %s;
  const checked = cs ? [...document.querySelectorAll(cs)].map((e) => e.name) : [];
  return { ...s, tips, checked };
}""" % (SNAP(rows, chart), json.dumps(canvas), json.dumps(checked))
