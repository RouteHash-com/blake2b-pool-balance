"""Chain samples for the local Blake2b chooser.

XBT pool TH/s comes from mempool.guide. XBTC pool TH/s comes from
mempool.xbtcash.org. A signed coinbase tag is matched on both. The node
RPC total replaces the explorer total for the chain named on that node.
A pool stats URL in a cap is never fetched.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from pool_announce import effective_caps

XBT_ORIGIN = "https://mempool.guide"
XBTC_ORIGIN = "https://mempool.xbtcash.org"
MEMPOOL_NETWORK = XBT_ORIGIN + "/api/v1/mining/hashrate/3d"
MEMPOOL_HASHRATES = XBT_ORIGIN + "/api/v1/mining/hashrate/pools/1w"
MEMPOOL_POOLS = XBT_ORIGIN + "/api/v1/mining/pools"
MEMPOOL_POOL = XBT_ORIGIN + "/api/v1/mining/pool/"
FRESH_SECONDS = 50
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


def _origin_urls(origin):
    return {
        "network": origin + "/api/v1/mining/hashrate/3d",
        "chart": origin + "/api/v1/mining/hashrate/pools/1w",
        "pools": origin + "/api/v1/mining/pools",
        "pool": origin + "/api/v1/mining/pool/",
    }


def _explorer_network_th(urls, opener):
    payload = _get_json(urls["network"], opener)
    if not isinstance(payload, dict):
        return None
    return hashes_to_th(payload.get("currentHashrate"))


def _chart(opener, urls):
    payload = _get_json(urls["chart"], opener)
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


def _slugs(opener, urls):
    payload = _get_json(urls["pools"], opener)
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


def _one_pool(name, th, slug, opener, urls):
    detail = _get_json(urls["pool"] + quote(slug, safe=""), opener)
    regexes = []
    if isinstance(detail, dict):
        pool = detail.get("pool") if isinstance(detail.get("pool"), dict) else {}
        regexes = [str(item).strip() for item in (pool.get("regexes") or []) if str(item).strip()]
        estimated = hashes_to_th(detail.get("estimatedHashrate"))
        if estimated is not None:
            th = estimated
    if name not in regexes:
        regexes.append(name)
    return {"name": name, "th": th, "regexes": regexes}


def _pool_rows(opener, urls):
    latest = _chart(opener, urls)
    if latest is None:
        return None
    slugs = _slugs(opener, urls)
    names = list(latest)
    if not names:
        return []

    def build(name):
        _stamp, th = latest[name]
        return _one_pool(name, th, slugs.get(name) or name, opener, urls)

    if len(names) == 1:
        return [build(names[0])]
    with ThreadPoolExecutor(max_workers=min(_WORKERS, len(names))) as pool:
        return list(pool.map(build, names))


def _explorer(origin, opener, skip_network=False):
    urls = _origin_urls(origin)
    network = None if skip_network else _explorer_network_th(urls, opener)
    return network, _pool_rows(opener, urls)


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


def _pick_chain(xbt_th, xbtc_th, node_chain):
    """The higher pool reading wins. A tie follows the node chain."""
    if xbt_th is None and xbtc_th is None:
        return None, None
    if xbtc_th is None or (xbt_th is not None and xbt_th > xbtc_th):
        return xbt_th, "xbt"
    if xbt_th is None or xbtc_th > xbt_th:
        return xbtc_th, "xbtc"
    if node_chain == "xbtc":
        return xbtc_th, "xbtc"
    return xbt_th, "xbt"


def project_samples(announcements, network_th, rows, now, xbtc_rows=None, chains=None, sources=None, node_chain="xbt"):
    pools = {}
    pool_chain = {}
    for cap in effective_caps(announcements, now).values():
        tag = cap.charge_tag
        chosen, chain = _pick_chain(match_tag(tag, rows), match_tag(tag, xbtc_rows), node_chain)
        if chosen is None:
            continue
        pools[tag] = chosen
        pool_chain[tag] = chain
    return {
        "network_th": network_th,
        "pools": pools,
        "pool_chain": pool_chain,
        "chains": chains if isinstance(chains, dict) else {},
        "sources": sources if isinstance(sources, dict) else {},
    }


def _node_chain(node):
    if not isinstance(node, dict):
        return "xbt"
    chain = str(node.get("chain") or "").strip().lower()
    return "xbtc" if chain == "xbtc" else "xbt"


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


def _remember(cache, key, live, stale_ok):
    if live is not None:
        return live
    if stale_ok and isinstance(cache, dict) and cache.get(key) is not None:
        return cache.get(key)
    return None


def fetch_samples(announcements, node=None, opener=None, now=None, cache_path=None):
    """Return chain totals and pool TH/s keyed by the signed coinbase tag."""
    import time
    moment = time.time() if now is None else float(now)
    cache = _load_cache(cache_path)
    node_chain = _node_chain(node)
    if _age_ok(cache, moment, FRESH_SECONDS):
        cached_chain = cache.get("node_chain") or "xbt"
        return project_samples(
            announcements,
            cache.get("network_th"),
            cache.get("rows") or [],
            moment,
            xbtc_rows=cache.get("xbtc_rows") or [],
            chains={
                "xbt": cache.get("xbt_network_th", cache.get("network_th")),
                "xbtc": cache.get("xbtc_network_th"),
            },
            sources=cache.get("sources") or {},
            node_chain=cached_chain,
        )
    node_th = _node_network_th(node, opener)
    # The node already supplied this chain's total, so skip that explorer's network call.
    xbt_network, xbt_rows = _explorer(
        XBT_ORIGIN, opener, skip_network=node_th is not None and node_chain != "xbtc",
    )
    xbtc_network, xbtc_rows = _explorer(
        XBTC_ORIGIN, opener, skip_network=node_th is not None and node_chain == "xbtc",
    )
    live_xbt = xbt_rows is not None
    live_xbtc = xbtc_rows is not None
    sources = {}
    if xbt_network is not None:
        sources["xbt"] = "mempool.guide"
    if xbtc_network is not None:
        sources["xbtc"] = "mempool.xbtcash.org"
    if node_th is not None:
        sources[node_chain] = "node"
        if node_chain == "xbtc":
            xbtc_network = node_th
        else:
            xbt_network = node_th
    stale_ok = _age_ok(cache, moment, STALE_SECONDS)
    if not live_xbt:
        remembered = _remember(cache, "rows", None, stale_ok)
        xbt_rows = remembered if isinstance(remembered, list) else []
        if xbt_network is None:
            xbt_network = _remember(cache, "xbt_network_th", None, stale_ok)
            if xbt_network is None:
                xbt_network = _remember(cache, "network_th", None, stale_ok)
            if xbt_network is not None and "xbt" not in sources:
                sources["xbt"] = (cache.get("sources") or {}).get("xbt") or "mempool.guide"
    if not live_xbtc:
        remembered = _remember(cache, "xbtc_rows", None, stale_ok)
        xbtc_rows = remembered if isinstance(remembered, list) else []
        if xbtc_network is None:
            xbtc_network = _remember(cache, "xbtc_network_th", None, stale_ok)
            if xbtc_network is not None and "xbtc" not in sources:
                sources["xbtc"] = (cache.get("sources") or {}).get("xbtc") or "mempool.xbtcash.org"
    top = node_th if node_th is not None else xbt_network
    if live_xbt or live_xbtc or node_th is not None:
        _save_cache(cache_path, {
            "fetched_at": moment,
            "network_th": top,
            "rows": xbt_rows,
            "xbt_network_th": xbt_network,
            "xbtc_network_th": xbtc_network,
            "xbtc_rows": xbtc_rows,
            "node_chain": node_chain,
            "sources": sources,
        })
    return project_samples(
        announcements,
        top,
        xbt_rows,
        moment,
        xbtc_rows=xbtc_rows,
        chains={"xbt": xbt_network, "xbtc": xbtc_network},
        sources=sources,
        node_chain=node_chain,
    )
