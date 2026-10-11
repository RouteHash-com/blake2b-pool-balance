"""Chain samples for the local Blake2b chooser.

Network TH/s comes from the node RPC in the config when that call works.
Otherwise it comes from mempool.guide. Pool TH/s comes from mempool.guide,
matched to the signed coinbase tag. A pool stats URL in a cap is never fetched.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from pool_announce import effective_caps

MEMPOOL_NETWORK = "https://mempool.guide/api/v1/mining/hashrate/3d"
MEMPOOL_HASHRATES = "https://mempool.guide/api/v1/mining/hashrate/pools/1w"
MEMPOOL_POOLS = "https://mempool.guide/api/v1/mining/pools"
MEMPOOL_POOL = "https://mempool.guide/api/v1/mining/pool/"
FRESH_SECONDS = 15 * 60
STALE_SECONDS = 6 * 60 * 60
_TIMEOUT = 8
_WORKERS = 6


def hashes_to_th(value):
    try:
        hashes = float(value)
    except (TypeError, ValueError):
        return None
    if hashes <= 0:
        return None
    return round(hashes / 1e12, 4)


def _get_json(url, opener, data=None, headers=None):
    outgoing = {"User-Agent": "RouteHash/1.0"}
    if headers:
        outgoing.update(headers)
    if opener is not None:
        try:
            payload = opener(url, data=data, headers=outgoing)
        except Exception:
            return None
        if isinstance(payload, (dict, list)):
            return payload
        return None
    try:
        request = Request(url, data=data, headers=outgoing)
        with urlopen(request, timeout=_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    if isinstance(payload, (dict, list)):
        return payload
    return None


def _node_network_th(node, opener):
    node = node if isinstance(node, dict) else {}
    url = str(node.get("url") or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not parsed.hostname:
        return None
    body = json.dumps({
        "jsonrpc": "1.0",
        "id": "routehash",
        "method": "getnetworkhashps",
        "params": [],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    user = str(node.get("user") or "")
    password = str(node.get("password") or "")
    if user or password:
        import base64
        token = base64.b64encode(("%s:%s" % (user, password)).encode("utf-8")).decode("ascii")
        headers["Authorization"] = "Basic " + token
    payload = _get_json(url, opener, data=body, headers=headers)
    if not isinstance(payload, dict):
        return None
    return hashes_to_th(payload.get("result"))


def _mempool_network_th(opener):
    payload = _get_json(MEMPOOL_NETWORK, opener)
    if not isinstance(payload, dict):
        return None
    return hashes_to_th(payload.get("currentHashrate"))


def _chart(opener):
    payload = _get_json(MEMPOOL_HASHRATES, opener)
    if not isinstance(payload, list):
        return None
    latest = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        name = str(row.get("poolName") or "").strip()
        if not name or name.lower() == "unknown":
            continue
        th = hashes_to_th(row.get("avgHashrate"))
        if th is None:
            continue
        stamp = row.get("timestamp") or 0
        prev = latest.get(name)
        if prev is None or stamp >= prev[0]:
            latest[name] = (stamp, th)
    return latest


def _slugs(opener):
    payload = _get_json(MEMPOOL_POOLS, opener)
    found = {}
    if not isinstance(payload, list):
        return found
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        slug = str(item.get("slug") or "").strip()
        if name and slug:
            found[name] = slug
    return found


def _one_pool(name, th, slug, opener):
    detail = _get_json(MEMPOOL_POOL + quote(slug, safe=""), opener)
    regexes = []
    if isinstance(detail, dict):
        pool = detail.get("pool") if isinstance(detail.get("pool"), dict) else {}
        regexes = [str(item).strip() for item in (pool.get("regexes") or []) if str(item).strip()]
        estimated = hashes_to_th(detail.get("estimatedHashrate"))
        if estimated is not None and estimated > th:
            th = estimated
    if name not in regexes:
        regexes.append(name)
    return {"name": name, "th": th, "regexes": regexes}


def _pool_rows(opener):
    latest = _chart(opener)
    if latest is None:
        return None
    slugs = _slugs(opener)
    names = list(latest)
    if not names:
        return []

    def build(name):
        _stamp, th = latest[name]
        return _one_pool(name, th, slugs.get(name) or name, opener)

    if len(names) == 1:
        return [build(names[0])]
    with ThreadPoolExecutor(max_workers=min(_WORKERS, len(names))) as pool:
        return list(pool.map(build, names))


def _tag_matches(tag, pattern):
    if len(pattern) < 4 or len(pattern) > 80:
        return False
    if tag == pattern:
        return True
    import re
    try:
        return re.fullmatch(pattern, tag) is not None
    except re.error:
        return False


def match_tag(tag, rows):
    """Highest chain TH/s whose coinbase pattern matches the whole tag."""
    tag = str(tag or "")
    if not tag:
        return None
    found = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        if name.lower() == "unknown":
            continue
        try:
            th = float(row.get("th"))
        except (TypeError, ValueError):
            continue
        if th < 0:
            continue
        patterns = list(row.get("regexes") or [])
        if name and name not in patterns:
            patterns.append(name)
        if any(_tag_matches(tag, str(pattern)) for pattern in patterns):
            found.append(th)
    if not found:
        return None
    return max(found)


def project_samples(announcements, network_th, rows, now):
    pools = {}
    for cap in effective_caps(announcements, now).values():
        tag = cap.charge_tag
        th = match_tag(tag, rows)
        if th is not None:
            pools[tag] = th
    return {"network_th": network_th, "pools": pools}


def _load_cache(path):
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _save_cache(path, payload):
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.write("\n")


def _age_ok(cache, now, limit):
    if not isinstance(cache, dict):
        return False
    try:
        stamp = float(cache.get("fetched_at"))
    except (TypeError, ValueError):
        return False
    return 0 <= now - stamp <= limit


def fetch_samples(announcements, node=None, opener=None, now=None, cache_path=None):
    """Return {network_th, pools}. Pools are keyed by the signed coinbase tag."""
    import time
    moment = time.time() if now is None else float(now)
    cache = _load_cache(cache_path)
    if _age_ok(cache, moment, FRESH_SECONDS):
        return project_samples(announcements, cache.get("network_th"), cache.get("rows") or [], moment)
    network = _node_network_th(node, opener)
    if network is None:
        network = _mempool_network_th(opener)
    rows = _pool_rows(opener)
    if rows is None:
        if _age_ok(cache, moment, STALE_SECONDS):
            rows = cache.get("rows") or []
            if network is None:
                network = cache.get("network_th")
        else:
            rows = []
            if network is None and not _age_ok(cache, moment, STALE_SECONDS):
                network = None
    else:
        _save_cache(cache_path, {"fetched_at": moment, "network_th": network, "rows": rows})
    return project_samples(announcements, network, rows, moment)
