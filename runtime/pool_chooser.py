"""Local Blake2b chooser. It writes one gateway's Pool Host and nothing else.

The proxy and the web app do not start this. Tests pass a fake gateway.
"""
from __future__ import annotations

import json
import zlib
from datetime import datetime, timezone

from pool_announce import (
    announcement_from_event,
    effective_caps,
    fullness_th,
    normalize_relays,
    tighter_percent,
    verify_announcement,
)
from pool_balance import Door, Home, Placement, listen_key, resolve_home, select_balance_destination

POOL_FORM_KEYS = ("datum_pool_host", "datum_pool_port", "datum_pool_pubkey")
LOCAL_MAX_PERCENT = 30
_MAX_ATTEMPTS = 8


def local_ceiling(value):
    """Empty means 30. A stored number above 30 is used as 30."""
    if value in (None, ""):
        return LOCAL_MAX_PERCENT
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return value
    if number > LOCAL_MAX_PERCENT:
        return LOCAL_MAX_PERCENT
    return value


def ceiling_refused(value):
    """True when a posted Local max percent is above 30. Blank is allowed."""
    if value in (None, ""):
        return False
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return False
    return number > LOCAL_MAX_PERCENT


def pool_change_form(host, port, pubkey):
    """The only fields a chooser may post to the local gateway."""
    host_s = str(host or "").strip()
    pubkey_s = str(pubkey or "").strip().lower()
    if not host_s or len(pubkey_s) != 128:
        raise ValueError("pool host and 128-character pubkey are required")
    port_i = int(port)
    if port_i < 1 or port_i > 65535:
        raise ValueError("pool port")
    return {
        "datum_pool_host": host_s,
        "datum_pool_port": str(port_i),
        "datum_pool_pubkey": pubkey_s,
    }


def pool_id_for(pubkey):
    text = str(pubkey or "").strip().lower()
    if len(text) >= 8 and all(ch in "0123456789abcdef" for ch in text[:8]):
        value = int(text[:8], 16)
        if value:
            return value
    return zlib.crc32(text.encode("utf-8")) or 1


def _unix(now):
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return int(now.timestamp())
    return int(now)


def _as_datetime(now):
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(int(now), timezone.utc)


def _skips(state, now):
    current = _unix(now)
    active = {}
    for row in (state or {}).get("skips") or ():
        try:
            retry = int(row["retry_after"])
            pool_id = int(row["pool_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if retry > current:
            active[pool_id] = retry
    return active


def remember_skip(state, pool_id, now, seconds):
    skips = _skips(state, now)
    skips[int(pool_id)] = _unix(now) + int(seconds)
    state["skips"] = [{"pool_id": key, "retry_after": value} for key, value in skips.items()]
    return state


def _sample(samples, tag):
    pools = (samples or {}).get("pools") or {}
    if tag not in pools:
        return None
    return pools[tag]


def _self_report(samples, tag):
    reported = (samples or {}).get("self_reported") or {}
    if tag not in reported:
        return None
    return reported[tag]


def doors_from_announcements(announcements, samples, ceiling, now, confirmed, listings=None):
    """One Door per consistent pubkey. Missing chain hashrate is not a target.

    A pool listing alone does not become a move target. A cap that disagrees
    with the current listing is left out.
    """
    doors = []
    for cap in effective_caps(announcements, _unix(now), listings=listings).values():
        if not cap.consistent:
            continue
        tag = cap.charge_tag
        published = fullness_th(_sample(samples, tag), _self_report(samples, tag))
        percent = tighter_percent(cap.percent, ceiling) if cap.receive else None
        observed = (confirmed or {}).get(cap.pubkey)
        tag_ok = observed is None or observed == tag
        doors.append(Door(
            pool_id=pool_id_for(cap.pubkey),
            host=cap.host,
            port=cap.port,
            reachable=tag_ok,
            balance_receive=bool(cap.receive and percent is not None and tag_ok),
            balance_max_percent=percent,
            capacity_th=cap.capacity_th,
            published_th=published,
            placed_th=0.0,
            spill_ok=bool(cap.receive and percent is not None and published is not None and tag_ok),
        ))
    return doors


def _endpoint(block):
    if not isinstance(block, dict):
        return None
    return listen_key(block.get("host"), block.get("port"))


def home_from_config(config, doors):
    home = config.get("home") or {}
    house = config.get("house") or {}
    saved = _endpoint(home)
    house_ep = _endpoint(house)
    if saved is None:
        return Home(kind="none")
    resolved = resolve_home(
        saved_host=home.get("host"),
        saved_port=home.get("port"),
        house_host=house.get("host"),
        house_port=house.get("port"),
        doors=doors,
    )
    if resolved.kind != "unmatched":
        return resolved
    if house_ep is not None and saved == house_ep:
        return Home(kind="house")
    return Home(
        kind="door",
        pool_id=pool_id_for(home.get("pubkey") or home.get("host")),
        door=Door(
            pool_id=pool_id_for(home.get("pubkey") or home.get("host")),
            host=str(home.get("host") or ""),
            port=int(home.get("port") or 0),
            reachable=True,
            balance_receive=False,
            published_th=None,
            spill_ok=False,
        ),
    )


def choose(config, state, announcements, samples, now, confirmed=None):
    """Return placement, doors, and home. Does not touch a gateway."""
    if config.get("pinned"):
        return Placement("saved", reason="pinned"), [], Home(kind="none")
    ceiling = local_ceiling(config.get("ceiling_percent"))
    doors = doors_from_announcements(
        announcements, samples, ceiling, now, confirmed, listings=config.get("listings"),
    )
    home = home_from_config(config, doors)
    when = _as_datetime(now)
    spill_since = (state or {}).get("spill_since")
    if spill_since is not None:
        spill_since = _as_datetime(spill_since)
    placement = select_balance_destination(
        rig_th=config.get("rig_th"),
        blake2b=str(config.get("algorithm") or "blake2b") == "blake2b",
        opted_in=bool(config.get("opt_in")),
        pinned=False,
        home=home,
        doors=doors,
        spill_kind=(state or {}).get("spill_kind"),
        spill_pool_id=(state or {}).get("spill_pool_id"),
        spill_since=spill_since,
        now=when,
        skipped_pool_ids=set(_skips(state, now)),
        network_th=(samples or {}).get("network_th"),
    )
    return placement, doors, home


def note_choice(state, placement, home, now):
    """Record dwell the same way the central overlay does."""
    state = dict(state or {})
    if placement.clear_spill or placement.kind == "saved":
        state["spill_kind"] = None
        state["spill_pool_id"] = None
        state["spill_since"] = None
        return state
    if not placement.reset_dwell:
        return state
    if placement.kind == "home":
        kind = "home"
        pool_id = home.pool_id if home and home.kind == "door" else None
    elif placement.kind == "door":
        kind = "pool"
        pool_id = placement.pool_id
    elif placement.kind == "house":
        kind = "house"
        pool_id = None
    else:
        return state
    state["spill_kind"] = kind
    state["spill_pool_id"] = pool_id
    state["spill_since"] = _unix(now)
    return state


def _door_by_id(doors, pool_id):
    for door in doors or ():
        if door.pool_id == pool_id:
            return door
    return None


def _listen(block):
    if not block:
        return None
    try:
        return pool_change_form(block.get("host"), block.get("port"), block.get("pubkey"))
    except ValueError:
        return None


def target_form(config, placement, doors):
    """Pool form for this placement, or None when the chooser must not write."""
    if placement.kind == "pinned" or (placement.kind == "saved" and placement.reason == "pinned"):
        return None
    if placement.kind == "door":
        door = _door_by_id(doors, placement.pool_id)
        cap = None
        if door is not None:
            for block in (config.get("announcement_targets") or ()):
                if listen_key(block.get("host"), block.get("port")) == listen_key(door.host, door.port):
                    cap = block
                    break
        if cap is None:
            cap = _target_index(config).get(placement.pool_id)
        return _listen(cap)
    if placement.kind == "house":
        return _listen(config.get("house"))
    if placement.kind in {"home", "saved"}:
        return _listen(config.get("home"))
    return None


def _target_index(config):
    index = {}
    for block in config.get("targets") or ():
        pubkey = block.get("pubkey")
        if pubkey:
            index[pool_id_for(pubkey)] = block
    home = config.get("home") or {}
    if home.get("pubkey"):
        index.setdefault(pool_id_for(home["pubkey"]), home)
    return index


def expected_tag(config, placement, doors):
    if placement.kind != "door":
        return None
    block = _target_index(config).get(placement.pool_id)
    if not block:
        return None
    return block.get("prime_tag") or block.get("tag")


def apply_choice(config, state, placement, doors, gateway, now):
    """Write Pool Host when the choice changed. A bad overflow tag is reverted."""
    form = target_form(config, placement, doors)
    if form is None or gateway is None:
        return note_choice(state, placement, home_from_config(config, doors), now), "held"
    current = gateway.read()
    same = (
        str(current.get("host") or "") == form["datum_pool_host"]
        and str(current.get("port") or "") == form["datum_pool_port"]
        and str(current.get("pubkey") or "").lower() == form["datum_pool_pubkey"]
    )
    previous = _listen({
        "host": current.get("host"),
        "port": current.get("port"),
        "pubkey": current.get("pubkey"),
    })
    if not same:
        gateway.write(form)
        read_back = gateway.read()
        if str(read_back.get("host") or "") != form["datum_pool_host"]:
            gateway.restart()
            read_back = gateway.read()
        if str(read_back.get("host") or "") != form["datum_pool_host"]:
            return state, "unchanged"
    if placement.kind == "door":
        tag = gateway.read().get("tag")
        expected = expected_tag(config, placement, doors)
        if not expected or tag != expected:
            if previous and previous != form:
                gateway.write(previous)
            if placement.pool_id is not None:
                from pool_balance import SKIP_SECONDS
                remember_skip(state, placement.pool_id, now, SKIP_SECONDS)
            return state, "rejected"
    return note_choice(state, placement, home_from_config(config, doors), now), ("unchanged" if same else "wrote")


def targets_from_caps(announcements, now, listings=None):
    """Config targets the chooser can write, taken from verified caps."""
    targets = []
    for cap in effective_caps(announcements, _unix(now), listings=listings).values():
        if not cap.consistent:
            continue
        targets.append({
            "host": cap.host,
            "port": cap.port,
            "pubkey": cap.pubkey,
            "tag": cap.charge_tag,
            "prime_tag": cap.prime_tag,
        })
    return targets


def run_once(config, state, announcements, samples, gateway, now):
    """Choose and apply, skipping a pool whose tag does not match."""
    state = dict(state or {})
    config = dict(config or {})
    config["targets"] = list(config.get("targets") or []) + targets_from_caps(
        announcements, now, listings=config.get("listings"),
    )
    placement = Placement("saved", reason="no-choice")
    for _attempt in range(_MAX_ATTEMPTS):
        current = gateway.read() if gateway is not None else {}
        confirmed = {}
        pubkey = str(current.get("pubkey") or "").lower()
        if pubkey and current.get("tag"):
            confirmed[pubkey] = current.get("tag")
        placement, doors, _home = choose(config, state, announcements, samples, now, confirmed)
        state, status = apply_choice(config, state, placement, doors, gateway, now)
        if status != "rejected":
            return placement, state
    return placement, state


def collect_events(relays, transport, cache, now):
    """Read every user relay. A failed relay keeps its last events."""
    cache = dict(cache or {})
    events = []
    for url in normalize_relays(relays):
        try:
            fetched = list(transport(url) or ())
        except Exception:
            fetched = None
        if fetched is not None:
            cache[url] = {"events": fetched, "fetched_at": _unix(now)}
        for event in cache.get(url, {}).get("events") or ():
            events.append(event)
    return events, cache


def verified_from_events(events, now):
    """Keep signed caps and kind-30080 events. Everything else is dropped."""
    found = []
    current = _unix(now)
    for event in events or ():
        if isinstance(event, dict) and "signature" in event and "payload" in event:
            if verify_announcement(event, current) is not None:
                found.append(event)
            continue
        if announcement_from_event(event, current) is None:
            continue
        content = event.get("content")
        if isinstance(content, str):
            content = json.loads(content)
        found.append(content)
    return found
