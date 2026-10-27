"""Blake2b opt-in placement across listed DATUM nodes.

The placement function is pure: callers pass network TH and each door's
published pool TH. It does not fetch mempool.guide or open a socket.
Spill is an overlay. Saved idle fields are not written here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

DWELL_SECONDS = 30 * 60
SKIP_SECONDS = 10 * 60
_EPS = 1e-6
_MINER_PORTS_NOT_DEST = {28915, 28916}


@dataclass(frozen=True)
class Door:
    pool_id: int
    host: str = ""
    port: int = 0
    reachable: bool = True
    balance_receive: bool = False
    balance_max_percent: float | None = None
    capacity_th: float = 0.0
    published_th: float | None = None
    placed_th: float = 0.0
    spill_ok: bool = False
    network_th: float | None = None


@dataclass(frozen=True)
class Home:
    """Where the rig returns. door, house, unmatched, or none."""
    kind: str
    pool_id: int | None = None
    door: Door | None = None


@dataclass(frozen=True)
class Placement:
    """saved and home keep the assignment the caller already built.

    door and house replace it. reset_dwell starts the 30-minute hold.
    clear_spill drops the overlay so the saved dest is the live one.
    """
    kind: str
    pool_id: int | None = None
    reset_dwell: bool = False
    clear_spill: bool = False
    reason: str = ""


LOCAL_MAX_PERCENT = 30


def effective_max_th(balance_receive, percent, capacity_th, network_th):
    """TH ceiling for one opted-in node. None when the percent cannot be applied.

    A stored percent above 30 is used as 30, same as the local chooser ceiling.
    """
    if not balance_receive:
        return None
    try:
        pct = float(percent)
        network = float(network_th)
    except (TypeError, ValueError):
        return None
    if pct <= 0 or network <= 0:
        return None
    if pct > LOCAL_MAX_PERCENT:
        pct = LOCAL_MAX_PERCENT
    ceiling = (pct / 100.0) * network
    try:
        cap = float(capacity_th or 0)
    except (TypeError, ValueError):
        cap = 0.0
    if cap > 0:
        ceiling = min(ceiling, cap)
    return ceiling


def door_network_th(door, network_th):
    """A pool chain total wins. Callers without one keep the single network total."""
    value = getattr(door, "network_th", None)
    if value in (None, ""):
        return network_th
    try:
        number = float(value)
    except (TypeError, ValueError):
        return network_th
    if number <= 0:
        return network_th
    return number


def pool_load_th(published_th, placed_th):
    """Larger of the published pool sample and RouteHash-placed advertised TH."""
    try:
        published = float(published_th or 0)
    except (TypeError, ValueError):
        published = 0.0
    try:
        placed = float(placed_th or 0)
    except (TypeError, ValueError):
        placed = 0.0
    if published < 0:
        published = 0.0
    if placed < 0:
        placed = 0.0
    return max(published, placed)


def placement_username(placement, *, saved_user, house_user, guest_user):
    """Username the proxy dials. House Pool keeps its own identity."""
    if placement is None:
        return saved_user
    if placement.kind == "house":
        return house_user
    if placement.kind == "door":
        return guest_user
    return saved_user


def listen_key(host, port):
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        return None
    host_s = str(host or "").strip().lower().rstrip(".")
    if host_s.startswith("[") and host_s.endswith("]"):
        host_s = host_s[1:-1]
    if not host_s:
        return None
    return (host_s, port_i)


def resolve_home(*, saved_host, saved_port, house_host, house_port, doors):
    """Match the saved idle listen to a segment, House Pool, or a private dest."""
    saved = listen_key(saved_host, saved_port)
    if saved is None:
        return Home(kind="none")
    if saved == listen_key(house_host, house_port):
        return Home(kind="house")
    for door in doors or ():
        if listen_key(door.host, door.port) == saved:
            return Home(kind="door", pool_id=door.pool_id, door=door)
    return Home(kind="unmatched")


def _in_dwell(spill_since, now, dwell_seconds):
    if spill_since is None or now is None:
        return False
    try:
        elapsed = (now - spill_since).total_seconds()
    except (TypeError, ValueError):
        return False
    return elapsed < float(dwell_seconds)


def _new_fits(rig_th, max_th, published_th, placed_th):
    if published_th is None or max_th is None:
        return False, None
    room = max_th - pool_load_th(published_th, placed_th) - rig_th
    return room >= -_EPS, room


def _already_fits(rig_th, max_th, published_th, placed_th):
    if published_th is None or max_th is None:
        return False
    load = pool_load_th(published_th, float(placed_th or 0) + rig_th)
    return load <= max_th + _EPS


def _home_fits(home, rig_th, network_th, skipped, already_there):
    if home is None or home.kind in {"unmatched", "none"}:
        return False
    if home.kind == "house":
        return True
    door = home.door
    if door is None or not door.reachable or door.pool_id in skipped:
        return False
    if not door.balance_receive:
        return True
    max_th = effective_max_th(
        True, door.balance_max_percent, door.capacity_th, door_network_th(door, network_th),
    )
    if max_th is None or door.published_th is None:
        return True
    if already_there:
        return _already_fits(rig_th, max_th, door.published_th, door.placed_th)
    fits, _room = _new_fits(rig_th, max_th, door.published_th, door.placed_th)
    return fits


def _door_by_id(doors, pool_id):
    if pool_id is None:
        return None
    for door in doors or ():
        if door.pool_id == pool_id:
            return door
    return None


def _stay_home(home, *, reset_dwell=False, clear_spill=False, reason):
    return Placement(
        "home",
        pool_id=home.pool_id if home and home.kind == "door" else None,
        reset_dwell=reset_dwell,
        clear_spill=clear_spill,
        reason=reason,
    )


def select_balance_destination(
    *,
    rig_th,
    blake2b,
    opted_in,
    pinned,
    home,
    doors,
    spill_kind,
    spill_pool_id,
    spill_since,
    now,
    skipped_pool_ids,
    network_th,
    dwell_seconds=DWELL_SECONDS,
):
    """Pick home, the closest open node, or House Pool.

    During the dwell the rig stays unless that listen is already skipped.
    After the dwell, home wins when it fits. The current node wins when it
    still fits. Otherwise the open node with the least room left wins.
    Equal room uses the lower pool id.
    """
    if pinned:
        return Placement("saved", clear_spill=True, reason="pinned")
    if not opted_in or not blake2b:
        return Placement("saved", clear_spill=True, reason="not-opted-in")
    try:
        rig_th = float(rig_th)
    except (TypeError, ValueError):
        rig_th = 0.0
    if rig_th <= 0:
        return Placement("saved", clear_spill=True, reason="no-advertised-th")
    if home is None or home.kind == "none":
        return Placement("saved", clear_spill=True, reason="no-home")
    if home.kind == "unmatched":
        return Placement("saved", clear_spill=True, reason="unmatched-owner-pool")

    skipped = set(skipped_pool_ids or ())
    spill_kind = str(spill_kind or "") or None
    dwell = _in_dwell(spill_since, now, dwell_seconds)
    on_home = spill_kind in (None, "home")

    if dwell and spill_kind == "home":
        failed = (
            home.kind == "door"
            and (home.door is None or not home.door.reachable or home.pool_id in skipped)
        )
        if not failed:
            return _stay_home(home, reason="dwell-home")

    if dwell and spill_kind == "pool":
        door = _door_by_id(doors, spill_pool_id)
        failed = door is None or not door.reachable or spill_pool_id in skipped
        if not failed:
            return Placement("door", pool_id=spill_pool_id, reason="dwell")

    if dwell and spill_kind == "house":
        return Placement("house", reason="dwell-house")

    if _home_fits(
        home, rig_th, door_network_th(getattr(home, "door", None), network_th),
        skipped, already_there=on_home,
    ):
        if spill_kind in {"pool", "house"}:
            return _stay_home(home, reset_dwell=True, reason="return-home")
        if spill_kind == "home":
            return _stay_home(home, clear_spill=True, reason="home-dwell-expired")
        return _stay_home(home, reason="stay-home")

    if spill_kind == "pool":
        door = _door_by_id(doors, spill_pool_id)
        if (
            door
            and door.reachable
            and spill_pool_id not in skipped
            and door.balance_receive
        ):
            max_th = effective_max_th(
                True, door.balance_max_percent, door.capacity_th, door_network_th(door, network_th),
            )
            if (
                max_th is not None
                and door.published_th is not None
                and _already_fits(rig_th, max_th, door.published_th, door.placed_th)
            ):
                return Placement("door", pool_id=spill_pool_id, reason="still-fits")

    if spill_kind == "house":
        return Placement("house", reason="still-house")

    best = None
    for door in doors or ():
        if not door.spill_ok or not door.balance_receive or not door.reachable:
            continue
        if door.pool_id in skipped:
            continue
        if home.kind == "door" and door.pool_id == home.pool_id:
            continue
        if spill_kind == "pool" and door.pool_id == spill_pool_id:
            continue
        max_th = effective_max_th(
            True, door.balance_max_percent, door.capacity_th, door_network_th(door, network_th),
        )
        fits, room = _new_fits(rig_th, max_th, door.published_th, door.placed_th)
        if not fits:
            continue
        rank = (room, door.pool_id)
        if best is None or rank < best[0]:
            best = (rank, door)
    if best is not None:
        return Placement("door", pool_id=best[1].pool_id, reset_dwell=True, reason="spill")
    return Placement("house", reset_dwell=True, reason="house-sink")


def parse_balance_percent(value):
    """A stored share of global XBT hashrate, from just above 0 through 100."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number > 100:
        return None
    return number


def apply_pool_balance_fields(pool, data):
    """Store the node-runner opt-in. Absent keys leave the row alone."""
    if "balance_receive" not in data and "balance_max_percent" not in data:
        return None
    from house_pool import normalize_algorithm
    algo = normalize_algorithm(getattr(pool, "algorithm", None))
    if "balance_receive" in data:
        receive = bool(data.get("balance_receive"))
    else:
        receive = bool(getattr(pool, "balance_receive", False))
    if "balance_max_percent" in data:
        percent = parse_balance_percent(data.get("balance_max_percent"))
    else:
        percent = parse_balance_percent(getattr(pool, "balance_max_percent", None))
    if receive and algo != "blake2b":
        return "Pool balance is Blake2b only."
    if receive and percent is None:
        return "Set a percent of global XBT hashrate from 1 to 30 to receive overflow."
    if percent is not None and percent > LOCAL_MAX_PERCENT:
        return "Percent of global XBT hashrate cannot be above 30. The saved value was kept."
    pool.balance_receive = receive
    if "balance_max_percent" in data or receive:
        pool.balance_max_percent = percent
    return None


def _schema_missing(exc):
    text = str(exc).lower()
    return "no such column" in text or "no such table" in text or "undefinedcolumn" in text


def _sql_dt(value):
    """ISO text. sqlite3 on Python 3.12 warns when handed a datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")
    return str(value)


def _parse_dt(value):
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _door_from_row(row, placed_th, published_th, reachable):
    port = int(row["port"] or 0)
    if port in _MINER_PORTS_NOT_DEST:
        reachable = False
    return Door(
        pool_id=int(row["id"]),
        host=str(row["host"] or ""),
        port=port,
        reachable=bool(reachable),
        balance_receive=bool(row["balance_receive"]),
        balance_max_percent=_as_float(row["balance_max_percent"], None) if row["balance_max_percent"] not in (None, "") else None,
        capacity_th=_as_float(row["capacity_th"]),
        published_th=published_th,
        placed_th=placed_th,
        spill_ok=bool(row["spill_ok"]) and bool(reachable),
    )


def _row_map(cur, sql, params=()):
    cur.execute(sql, params)
    columns = [item[0] for item in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _persist(cur, rig_id, placement, home, now):
    if placement.clear_spill:
        cur.execute(
            """
            UPDATE rigs
            SET balance_spill_pool_id = NULL,
                balance_spill_kind = NULL,
                balance_spill_since = NULL
            WHERE id = ?
            """,
            (rig_id,),
        )
        return
    if not placement.reset_dwell:
        return
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
        return
    cur.execute(
        """
        UPDATE rigs
        SET balance_spill_pool_id = ?,
            balance_spill_kind = ?,
            balance_spill_since = ?
        WHERE id = ?
        """,
        (pool_id, kind, _sql_dt(now), rig_id),
    )


def apply_idle_balance(
    session,
    *,
    rig_id,
    saved_host,
    saved_port,
    house_host,
    house_port,
    now=None,
    network_th=None,
    published_for=None,
):
    """Recount placed TH and write this rig's overlay in one locked decision.

    Returns None when the balance columns are not there yet. The caller keeps
    the saved assignment. published_for(pool_row) must not fetch.
    """
    now = now or datetime.utcnow()
    engine = session.get_bind()
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            placement, home = _decide_locked(
                cur, rig_id, saved_host, saved_port, house_host, house_port,
                now, network_th, published_for,
            )
            if placement is not None:
                _persist(cur, rig_id, placement, home, now)
            raw.commit()
            return placement
        except Exception as exc:
            try:
                raw.rollback()
            except Exception:
                pass
            if _schema_missing(exc):
                return None
            raise
    finally:
        raw.close()


def _decide_locked(
    cur, rig_id, saved_host, saved_port, house_host, house_port,
    now, network_th, published_for,
):
    from house_pool import normalize_algorithm
    from pool_public import community_pool_hidden
    from pool_security import validate_pool_destination

    rig_rows = _row_map(
        cur,
        """
        SELECT id, algo, hashrate_th, is_archived, owner_id, balance_opt_in,
               balance_spill_pool_id, balance_spill_kind, balance_spill_since,
               idle_route_mode, idle_community_pool_id, idle_owner_host, idle_owner_port
        FROM rigs WHERE id = ?
        """,
        (rig_id,),
    )
    if not rig_rows:
        return Placement("saved", reason="missing-rig"), None
    rig = rig_rows[0]
    blake2b = normalize_algorithm(rig["algo"]) == "blake2b"
    opted_in = bool(rig["balance_opt_in"]) and blake2b
    spill_kind = str(rig["balance_spill_kind"] or "") or None
    spill_pool_id = rig["balance_spill_pool_id"]
    spill_since = _parse_dt(rig["balance_spill_since"])

    pinned = _pinned(cur, rig_id, now)
    if not opted_in or pinned or _as_float(rig["hashrate_th"]) <= 0:
        placement = select_balance_destination(
            rig_th=rig["hashrate_th"],
            blake2b=blake2b,
            opted_in=bool(rig["balance_opt_in"]),
            pinned=pinned,
            home=Home(kind="none"),
            doors=[],
            spill_kind=spill_kind,
            spill_pool_id=spill_pool_id,
            spill_since=spill_since,
            now=now,
            skipped_pool_ids=set(),
            network_th=network_th,
        )
        if not placement.clear_spill:
            placement = Placement("saved", reason=placement.reason)
        elif not spill_kind:
            placement = Placement("saved", reason=placement.reason)
        return placement, None

    pool_rows = _row_map(
        cur,
        """
        SELECT id, name, algorithm, host, port, upstream_host, provider_api_url,
               pool_pass_full_users, is_active, is_demo, balance_receive,
               balance_max_percent, capacity_th
        FROM datum_pools
        """,
    )
    placed = _placed_th(cur, rig_id, now, pool_rows)
    skips = _row_map(
        cur,
        """
        SELECT pool_id FROM balance_skips
        WHERE rig_id = ? AND retry_after > ?
        """,
        (rig_id, _sql_dt(now)),
    )
    skipped = {int(row["pool_id"]) for row in skips}
    doors = []
    for row in pool_rows:
        published = None
        if published_for is not None:
            published = published_for(row)
        reachable = False
        try:
            reachable, _error = validate_pool_destination(row["host"], row["port"])
        except Exception:
            reachable = False
        algo = normalize_algorithm(row["algorithm"])
        segment = bool(str(row["upstream_host"] or "").strip())
        hidden = community_pool_hidden(row["name"], row["host"])
        spill_ok = (
            bool(row["is_active"])
            and not bool(row["is_demo"])
            and algo == "blake2b"
            and segment
            and not hidden
            and bool(row["pool_pass_full_users"])
        )
        row = dict(row)
        row["spill_ok"] = spill_ok
        doors.append(_door_from_row(
            row,
            placed.get(int(row["id"]), 0.0),
            published,
            reachable,
        ))
    home = resolve_home(
        saved_host=saved_host,
        saved_port=saved_port,
        house_host=house_host,
        house_port=house_port,
        doors=doors,
    )
    placement = select_balance_destination(
        rig_th=rig["hashrate_th"],
        blake2b=True,
        opted_in=True,
        pinned=False,
        home=home,
        doors=doors,
        spill_kind=spill_kind,
        spill_pool_id=int(spill_pool_id) if spill_pool_id is not None else None,
        spill_since=spill_since,
        now=now,
        skipped_pool_ids=skipped,
        network_th=network_th,
    )
    return placement, home


def _pinned(cur, rig_id, now):
    cur.execute(
        """
        SELECT 1 FROM rentals
        WHERE rig_id = ? AND is_active = 1 AND end_time > ?
        LIMIT 1
        """,
        (rig_id, _sql_dt(now)),
    )
    if cur.fetchone():
        return True
    cur.execute(
        """
        SELECT 1 FROM idle_fills
        WHERE rig_id = ? AND is_active = 1 AND status = 'escrowed'
        LIMIT 1
        """,
        (rig_id,),
    )
    return bool(cur.fetchone())


def _placed_th(cur, rig_id, now, pool_rows):
    """Advertised TH already on each listen, excluding the rig being placed."""
    by_listen = {}
    for row in pool_rows:
        key = listen_key(row["host"], row["port"])
        if key:
            by_listen.setdefault(key, int(row["id"]))
    rigs = _row_map(
        cur,
        """
        SELECT id, hashrate_th, balance_spill_kind, balance_spill_pool_id,
               idle_route_mode, idle_community_pool_id, idle_owner_host, idle_owner_port
        FROM rigs
        WHERE id != ? AND COALESCE(is_archived, 0) = 0
          AND lower(replace(COALESCE(algo, ''), '-', '')) = 'blake2b'
        """,
        (rig_id,),
    )
    cur.execute(
        """
        SELECT rig_id, pool_host, pool_port FROM rentals
        WHERE is_active = 1 AND end_time > ?
        """,
        (_sql_dt(now),),
    )
    rentals = {int(row[0]): (row[1], row[2]) for row in cur.fetchall()}
    totals = {}
    for rig in rigs:
        th = _as_float(rig["hashrate_th"])
        if th <= 0:
            continue
        rid = int(rig["id"])
        if rid in rentals:
            pool_id = by_listen.get(listen_key(rentals[rid][0], rentals[rid][1]))
        elif str(rig["balance_spill_kind"] or "") == "pool" and rig["balance_spill_pool_id"]:
            pool_id = int(rig["balance_spill_pool_id"])
        elif str(rig["balance_spill_kind"] or "") == "house":
            pool_id = None
        elif str(rig["idle_route_mode"] or "") == "community_pool" and rig["idle_community_pool_id"]:
            pool_id = int(rig["idle_community_pool_id"])
        elif str(rig["idle_route_mode"] or "") == "owner_pool":
            pool_id = by_listen.get(listen_key(rig["idle_owner_host"], rig["idle_owner_port"]))
        else:
            pool_id = None
        if pool_id:
            totals[pool_id] = totals.get(pool_id, 0.0) + th
    return totals


def record_balance_skip(session, rig_id, pool_id, now=None, seconds=SKIP_SECONDS):
    """Remember a refused listen so the next choice skips it."""
    if not rig_id or not pool_id:
        return False
    now = now or datetime.utcnow()
    retry = now + timedelta(seconds=int(seconds))
    engine = session.get_bind()
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            """
            INSERT INTO balance_skips (rig_id, pool_id, retry_after)
            VALUES (?, ?, ?)
            ON CONFLICT(rig_id, pool_id) DO UPDATE SET retry_after = excluded.retry_after
            """,
            (int(rig_id), int(pool_id), _sql_dt(retry)),
        )
        raw.commit()
        return True
    except Exception:
        try:
            raw.rollback()
        except Exception:
            pass
        return False
    finally:
        raw.close()


def rig_balance_continue(session, rig_id):
    """True only for an opted-in Blake2b rig that is not on a rental or Fill hire."""
    import sqlalchemy as sa
    try:
        rows = session.execute(
            sa.text(
                """
                SELECT balance_opt_in, algo, hashrate_th
                FROM rigs WHERE id = :rig_id
                """
            ),
            {"rig_id": rig_id},
        ).fetchone()
    except Exception:
        return False
    if not rows or not rows[0]:
        return False
    from house_pool import normalize_algorithm
    if normalize_algorithm(rows[1]) != "blake2b":
        return False
    if _as_float(rows[2]) <= 0:
        return False
    now = datetime.utcnow()
    try:
        rental = session.execute(
            sa.text(
                """
                SELECT 1 FROM rentals
                WHERE rig_id = :rig_id AND is_active = 1 AND end_time > :now
                LIMIT 1
                """
            ),
            {"rig_id": rig_id, "now": now},
        ).fetchone()
        if rental:
            return False
        fill = session.execute(
            sa.text(
                """
                SELECT 1 FROM idle_fills
                WHERE rig_id = :rig_id AND is_active = 1 AND status = 'escrowed'
                LIMIT 1
                """
            ),
            {"rig_id": rig_id},
        ).fetchone()
    except Exception:
        return False
    return not bool(fill)


def spill_blocks_guest_notice(session, rig_id):
    """A live spill must not email the saved home operator."""
    import sqlalchemy as sa
    try:
        row = session.execute(
            sa.text("SELECT balance_spill_kind FROM rigs WHERE id = :rig_id"),
            {"rig_id": rig_id},
        ).fetchone()
    except Exception:
        return False
    return bool(row and str(row[0] or "") in {"pool", "house"})
