#!/usr/bin/env python3
"""Run the local Blake2b chooser about once a minute.

Reads /data/chooser.json. Writes Pool Host only when that file names a
gateway address and admin password. A file named pin in the data
directory holds Pool Host still. Pool size comes from mempool.guide.
The network total comes from the node RPC in the config when that call
works, and from mempool.guide otherwise. A samples.json file is not read.

Does not start with the RouteHash web app or proxy.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from pool_announce import (
    LISTING_LIFETIME,
    normalize_relays,
    public_identity,
    sign_announcement,
    sign_listing,
)
from pool_balance import parse_balance_percent
from pool_chooser import ceiling_refused, run_once
from pool_gateway import DatumGatewayClient

LOOP_SECONDS = 60
_UI_LIMIT = 65536
HOUSE_HOST = "pool.routehash.com"
HOUSE_PORT = 28915
HOUSE_PUBKEY = (
    "b1ccb80129763858d52249e4fef4f9d6aff97921543abf0559e03819a03aab10"
    "93872ef7b8f0481635d0221485379948a812c3d2ffcec3fe7cbc4f8ccec1d735"
)
DEFAULT_RELAYS = ["wss://relay.routehash.com"]

DEFAULT_CONFIG = {
    "algorithm": "blake2b",
    "opt_in": False,
    "ceiling_percent": "",
    "rig_th": 0,
    "pinned": False,
    "relays": list(DEFAULT_RELAYS),
    "home": {"host": "", "port": 28915, "pubkey": ""},
    "house": {"host": HOUSE_HOST, "port": HOUSE_PORT, "pubkey": HOUSE_PUBKEY},
    "gateway": {"url": "", "password": ""},
    "node": {"url": "", "user": "", "password": ""},
}


def _port(value, default=28915):
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    if port < 1 or port > 65535:
        return default
    return port


def _rig(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_config(raw):
    """Chooser config. An empty ceiling stays empty so the chooser stores 30."""
    raw = raw if isinstance(raw, dict) else {}
    home = raw.get("home") if isinstance(raw.get("home"), dict) else {}
    house = raw.get("house") if isinstance(raw.get("house"), dict) else {}
    gateway = raw.get("gateway") if isinstance(raw.get("gateway"), dict) else {}
    node = raw.get("node") if isinstance(raw.get("node"), dict) else {}
    if "relays" not in raw or raw.get("relays") is None:
        relays = list(DEFAULT_RELAYS)
    elif isinstance(raw.get("relays"), str):
        relays = [line.strip() for line in raw["relays"].splitlines() if line.strip()]
    elif isinstance(raw.get("relays"), list):
        relays = [str(item).strip() for item in raw["relays"] if str(item).strip()]
    else:
        relays = list(DEFAULT_RELAYS)
    ceiling = raw.get("ceiling_percent", "")
    if ceiling is None:
        ceiling = ""
    else:
        ceiling = str(ceiling).strip()
    house_host = HOUSE_HOST
    if "host" in house and house.get("host") is not None:
        house_host = str(house.get("host")).strip()
    if "pubkey" in house and house.get("pubkey") is not None:
        house_pubkey = str(house.get("pubkey") or "").strip()
    else:
        house_pubkey = HOUSE_PUBKEY
    home_host = ""
    if "host" in home and home.get("host") is not None:
        home_host = str(home.get("host")).strip()
    return {
        "algorithm": "blake2b",
        "opt_in": bool(raw.get("opt_in")),
        "ceiling_percent": ceiling,
        "rig_th": _rig(raw.get("rig_th")),
        "pinned": bool(raw.get("pinned")),
        "relays": normalize_relays(relays),
        "home": {
            "host": home_host,
            "port": _port(home.get("port"), 28915),
            "pubkey": str(home.get("pubkey") or "").strip(),
        },
        "home_from_gateway": bool(raw.get("home_from_gateway")),
        "house": {
            "host": house_host,
            "port": _port(house.get("port"), HOUSE_PORT),
            "pubkey": house_pubkey,
        },
        "gateway": {
            "url": str(gateway.get("url") or "").strip(),
            "password": str(gateway.get("password") or ""),
        },
        "node": {
            "url": str(node.get("url") or "").strip(),
            "user": str(node.get("user") or "").strip(),
            "password": str(node.get("password") or ""),
        },
    }


def _load(path, default):
    file = Path(path)
    if not file.exists():
        return default
    try:
        return json.loads(file.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _save(path, value, private=False):
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(value, indent=2) + "\n")
    if private:
        os.chmod(file, 0o600)


def _checked(flag):
    return " checked" if flag else ""


def _esc(value):
    text = str(value if value is not None else "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_IDENTITY_FILE = "pool-identity"
_PUBLISH_FILE = "pool-publish.json"
_SIGN_ERRORS = {
    "stats url": "The stats URL must be a public https address, or blank.",
    "percent": "Set a percent above 0 and at most 100.",
    "pool host": "The pool host must be a hostname with no scheme and no path.",
    "pool port": "The pool port must be from 1 to 65535.",
    "block tag": "Set the coinbase tag.",
    "name": "The pool name must be 80 characters or fewer.",
    "capacity": "Capacity TH/s cannot be below zero.",
    "key length": "The DATUM identity must be 320 hex characters.",
    "key hex": "The DATUM identity must be 320 hex characters.",
    "pubkey does not match the signing identity": "That identity does not match this pool.",
}


def _identity_file(data_dir):
    return Path(data_dir) / _IDENTITY_FILE


def _read_identity(data_dir):
    file = _identity_file(data_dir)
    if not file.exists():
        return ""
    try:
        text = file.read_text().strip().split()[0].strip().lower()
    except OSError:
        return ""
    if len(text) != 320 or any(char not in "0123456789abcdef" for char in text):
        return ""
    return text


def _store_identity(data_dir, text):
    file = _identity_file(data_dir)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text + "\n")
    os.chmod(file, 0o600)


def _blank_publish(config):
    return {
        "identity_saved": False,
        "pubkey": "",
        "name": "",
        "host": "",
        "port": 28915,
        "tag": "",
        "percent": "",
        "capacity": "",
        "stats_url": "",
        "relays": "\n".join(config["relays"]),
        "message": "",
        "ok": False,
    }


def publish_view(data_dir, config):
    """Last publish form, without the private DATUM identity."""
    config = normalize_config(config)
    saved = _load(Path(data_dir) / _PUBLISH_FILE, {})
    if not isinstance(saved, dict):
        saved = {}
    view = _blank_publish(config)
    identity = _read_identity(data_dir)
    view["identity_saved"] = bool(identity)
    if identity:
        try:
            view["pubkey"] = public_identity(identity)
        except ValueError:
            view["pubkey"] = ""
    relays = saved.get("relays")
    if isinstance(relays, list) and relays:
        view["relays"] = "\n".join(str(item) for item in relays)
    for key in ("name", "host", "tag", "stats_url", "message"):
        if saved.get(key) is not None:
            view[key] = str(saved.get(key))
    if saved.get("percent") not in (None, ""):
        view["percent"] = str(saved.get("percent"))
    if saved.get("capacity") not in (None, ""):
        view["capacity"] = str(saved.get("capacity"))
    view["port"] = _port(saved.get("port"), 28915)
    view["ok"] = bool(saved.get("ok"))
    return view


def _publish_record(fields, ok, message):
    record = dict(fields)
    record["ok"] = bool(ok)
    record["message"] = str(message)[:300]
    return record


def publish_pool(data_dir, form, config, now=None, websocket_factory=None):
    """Sign one cap and, only after a relay accepts it, the matching listing.

    The private identity is stored beside the config and is not returned.
    A remove still sends a cap first, with receiving turned off.
    """
    config = normalize_config(config)
    moment = int(time.time() if now is None else now)
    remove = _one(form, "form") == "remove"
    raw_port = _one(form, "pool_port").strip()
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = 0
    raw_capacity = _one(form, "pool_capacity").strip()
    host = _one(form, "pool_host").strip()
    name = _one(form, "pool_name").strip()
    tag = _one(form, "pool_tag").strip()
    percent_text = _one(form, "pool_percent").strip()
    stats_url = _one(form, "pool_stats_url").strip()
    if "pool_relays" in form:
        relay_lines = [line.strip() for line in _one(form, "pool_relays").splitlines() if line.strip()]
    else:
        relay_lines = list(config["relays"])
    relays = normalize_relays(relay_lines)
    fields = {
        "name": name,
        "host": host,
        "port": port if 1 <= port <= 65535 else 28915,
        "tag": tag,
        "percent": percent_text,
        "capacity": raw_capacity,
        "stats_url": stats_url,
        "relays": relays or relay_lines,
    }

    def finish(ok, message):
        record = _publish_record(fields, ok, message)
        _save(Path(data_dir) / _PUBLISH_FILE, record, private=True)
        return record

    typed = _one(form, "pool_identity").strip().lower()
    if typed:
        if len(typed) != 320 or any(char not in "0123456789abcdef" for char in typed):
            return finish(False, "The DATUM identity must be 320 hex characters.")
        _store_identity(data_dir, typed)
        identity = typed
    else:
        identity = _read_identity(data_dir)
    if not identity:
        return finish(False, "The signing key is the file ratum-prime.key in the RATUM Prime service data. The public pool key cannot sign a cap. Leave this blank if you only run a gateway.")
    if not host or not tag or not (1 <= port <= 65535):
        return finish(False, "Set the pool host, a port from 1 to 65535, and the coinbase tag.")
    percent = parse_balance_percent(percent_text)
    if not remove and percent is None:
        return finish(False, "Set a percent above 0 and at most 100.")
    if raw_capacity == "":
        capacity = 0.0
    else:
        try:
            capacity = float(raw_capacity)
        except (TypeError, ValueError):
            return finish(False, "Capacity TH/s must be a number.")
        if capacity < 0:
            return finish(False, "Capacity TH/s cannot be below zero.")
    if not relays:
        return finish(False, "Add at least one ws:// or wss:// relay.")
    try:
        pubkey = public_identity(identity)
    except ValueError as exc:
        return finish(False, _SIGN_ERRORS.get(str(exc), "The DATUM identity must be 320 hex characters."))
    created = moment
    cap_payload = {
        "version": 1,
        "algorithm": "blake2b",
        "pool_host": host,
        "pool_port": port,
        "pool_pubkey": pubkey,
        "block_tag": tag,
        "balance_receive": not remove,
        "max_percent": None if remove else percent,
        "capacity_th": capacity,
        "created_at": created,
        "expires_at": created + 24 * 60 * 60,
    }
    listing_payload = {
        "version": 1,
        "algorithm": "blake2b",
        "pool_pubkey": pubkey,
        "name": name or host,
        "pool_host": host,
        "pool_port": port,
        "block_tag": tag,
        "stats_url": stats_url,
        "removed": remove,
        "created_at": created,
        "expires_at": created + LISTING_LIFETIME,
    }
    try:
        cap = sign_announcement(cap_payload, identity)
        listing = sign_listing(listing_payload, identity)
    except ValueError as exc:
        return finish(False, _SIGN_ERRORS.get(str(exc), "The pool could not be signed."))
    from pool_publish import load_or_create_transport_key, publish_caps, publish_listing

    try:
        transport = load_or_create_transport_key(Path(data_dir) / "transport-key.json")
    except (OSError, ValueError, json.JSONDecodeError):
        return finish(False, "The local transport key could not be read.")
    factory = websocket_factory
    if factory is None:
        from websocket import create_connection
        factory = create_connection
    try:
        _event, cap_results = publish_caps(
            cap, relays, transport["private_key"], factory, now=created,
        )
    except ValueError as exc:
        return finish(False, _SIGN_ERRORS.get(str(exc), "The cap was not sent."))
    cap_ok = sum(1 for row in cap_results if row.get("accepted"))
    if cap_ok < 1:
        return finish(False, "No relay accepted the cap. The listing was not sent.")
    try:
        _listing_event, listing_results = publish_listing(
            listing, relays, transport["private_key"], factory, now=created,
        )
    except ValueError as exc:
        return finish(False, _SIGN_ERRORS.get(str(exc), "The cap was accepted. The listing was not sent."))
    list_ok = sum(1 for row in listing_results if row.get("accepted"))
    total = len(cap_results)
    if list_ok < 1:
        return finish(
            False,
            f"The cap was accepted by {cap_ok} of {total} relays. No relay accepted the listing.",
        )
    verb = "Removal" if remove else "Cap and listing"
    return finish(True, f"{verb} accepted by {list_ok} of {total} relays. The cap went first.")


def catalog_rows(cache, now=None):
    """Pools from the last relay read. A stats URL in a listing is not fetched."""
    moment = int(time.time() if now is None else now)
    events = []
    for row in (cache or {}).values():
        if isinstance(row, dict):
            events.extend(row.get("events") or ())
    from pool_announce import current_listings, effective_caps
    from pool_chooser import verified_from_events
    from pool_publish import listings_from_events

    listing_docs = listings_from_events(events, moment)
    listings = current_listings(listing_docs, moment)
    caps = effective_caps(
        verified_from_events(events, moment),
        moment,
        listings=listing_docs,
    )
    rows = []
    seen = set()
    for pubkey, listing in listings.items():
        seen.add(pubkey)
        rows.append(_catalog_row(
            listing.name,
            listing.host,
            listing.port,
            listing.block_tag,
            listing.removed,
            caps.get(pubkey),
        ))
    for _pubkey, cap in caps.items():
        if _pubkey in seen:
            continue
        rows.append(_catalog_row(cap.host, cap.host, cap.port, cap.block_tag, False, cap))
    rows.sort(key=lambda row: (str(row["name"]).lower(), str(row["host"]).lower(), int(row["port"])))
    return rows


def _percent_text(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return ("%.4f" % number).rstrip("0").rstrip(".")


def _catalog_row(name, host, port, tag, removed, cap):
    if removed:
        cap_text = "Removed"
    elif cap is None:
        cap_text = "No cap yet"
    elif not cap.consistent:
        cap_text = "Cap does not match the listing"
    elif not cap.receive:
        cap_text = "Not receiving"
    else:
        cap_text = "Receiving, %s percent" % (_percent_text(cap.percent) or "0")
    return {
        "name": str(name or host or ""),
        "host": str(host or ""),
        "port": int(port or 0),
        "tag": str(tag or ""),
        "cap": cap_text,
    }


def _catalog_html(rows):
    if not rows:
        return (
            "<p class=\"note\">No pools have been read from the relays yet. "
            "The service reads them about once a minute.</p>"
        )
    lines = []
    for row in rows:
        lines.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (
                _esc(row["name"]),
                _esc(row["host"]),
                _esc(row["port"]),
                _esc(row["tag"]),
                _esc(row["cap"]),
            )
        )
    return (
        "<table><thead><tr><th>Name</th><th>Host</th><th>Port</th><th>Tag</th><th>Cap</th></tr></thead><tbody>"
        + "".join(lines)
        + "</tbody></table>"
    )


def catalog_for_page(data_dir, config, now=None, websocket_factory=None):
    """Refresh the relay cache, then list pools. A failed read keeps the last list."""
    data = Path(data_dir)
    moment = time.time() if now is None else now
    cache = _load(data / "relay-cache.json", {})
    if not isinstance(cache, dict):
        cache = {}
    if config.get("relays"):
        try:
            from pool_publish import announcements_from_relays

            factory = websocket_factory
            if factory is None:
                from websocket import create_connection
                factory = create_connection
            _fetched, cache = announcements_from_relays(
                config["relays"], factory, cache, moment,
            )
            _save(data / "relay-cache.json", cache)
        except Exception:
            pass
    return catalog_rows(cache, moment)


def config_page(config, publish=None, catalog=None):
    """Local settings and pool publish page. Passwords and the private identity are not printed."""
    config = normalize_config(config)
    if not isinstance(publish, dict):
        publish = _blank_publish(config)
    relays = "\n".join(config["relays"])
    saved = "A password is already saved. Leave this blank to keep it." if config["gateway"]["password"] else "Dashboard user is admin."
    node_saved = "A password is already saved. Leave this blank to keep it." if config["node"]["password"] else "Leave blank when the address is blank. The total then comes from mempool.guide."
    if publish.get("identity_saved"):
        identity_note = "A DATUM identity is already saved. Leave this blank to keep it. This page does not show the private identity again."
        if publish.get("pubkey"):
            identity_note += " Public pool key: " + str(publish.get("pubkey"))
    else:
        identity_note = "The 320-character private key is the file ratum-prime.key in the RATUM Prime service data. RATUM Prime writes that file the first time it starts. Show Pool Pubkey is the public key only. This page stores the key and does not show it again. After it is saved, this page shows the public 128-character pool key."
    message = str(publish.get("message") or "")
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blake2b Pool Balance</title>
<style>
* { box-sizing: border-box; }
html { color-scheme: dark; }
body {
  margin: 0;
  background: #0b0f19;
  color: #e2e8f0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  line-height: 1.5;
}
.shell { max-width: 52rem; margin: 0 auto; padding: 28px 20px 64px; }
.eyebrow {
  margin: 0 0 6px;
  color: #38bdf8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .14em;
  text-transform: uppercase;
}
h1 { margin: 0 0 8px; color: #f8fafc; font-size: 1.7rem; line-height: 1.2; }
h2 { margin: 0 0 8px; color: #f8fafc; font-size: 1.15rem; }
h3 { margin: 14px 0 6px; color: #f8fafc; font-size: 0.98rem; }
p { margin: 0 0 10px; }
.lede, .note { color: #94a3b8; }
.card {
  background: #111827;
  border: 1px solid #1f2937;
  border-radius: 8px;
  padding: 16px 18px;
  margin: 14px 0;
}
.warn {
  background: rgba(251, 191, 36, 0.1);
  border: 1px solid rgba(202, 138, 4, 0.55);
  border-radius: 8px;
  padding: 14px 16px;
  margin: 16px 0;
  color: #fde68a;
}
.warn strong { color: #fbbf24; }
.danger {
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.5);
  color: #fecaca;
}
.danger strong { color: #f87171; }
.choices { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.choice {
  text-align: left;
  background: #162235;
  color: #e2e8f0;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  min-height: 96px;
}
.choice:hover { border-color: #38bdf8; }
.choice.on {
  background: #1e3a5f;
  border-color: #38bdf8;
  box-shadow: inset 0 0 0 1px #38bdf8;
}
.choice strong { display: block; color: #f8fafc; margin-bottom: 6px; }
.choice span { display: block; color: #94a3b8; font-size: 0.92rem; font-weight: 400; }
.choice.on span { color: #e2e8f0; }
details.guide > summary {
  cursor: pointer;
  color: #f8fafc;
  font-size: 1.15rem;
  font-weight: 700;
}
details.guide > summary span {
  display: block;
  margin-top: 4px;
  color: #94a3b8;
  font-size: 0.92rem;
  font-weight: 400;
}
details.guide[open] > summary { margin-bottom: 8px; }
.field { margin-top: 14px; }
label { font-weight: 600; color: #f8fafc; font-size: 0.92rem; }
.field > input, .field > textarea, .grid2 input {
  display: block;
  width: 100%%;
  margin-top: 6px;
  background: #030712;
  color: #e2e8f0;
  border: 1px solid #334155;
  border-radius: 8px;
  min-height: 40px;
  padding: 8px 10px;
  font: 400 15px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
textarea { min-height: 96px; resize: vertical; }
input[type=checkbox] { width: auto; min-height: 0; margin: 2px 8px 0 0; accent-color: #2563eb; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.ack {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: 16px;
  padding: 12px;
  border: 1px solid rgba(248, 113, 113, 0.5);
  border-radius: 8px;
  background: rgba(248, 113, 113, 0.08);
  color: #fecaca;
  font-weight: 600;
}
.block { margin-top: 10px; color: #f87171; font-weight: 700; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
button.primary, button.ghost {
  min-height: 40px;
  padding: 0 16px;
  border-radius: 8px;
  font-weight: 700;
  cursor: pointer;
}
button.primary { background: #2563eb; color: #fff; border: 0; }
button.primary:hover { background: #1d4ed8; }
button.ghost { background: transparent; color: #f87171; border: 1px solid #f87171; }
button.ghost:hover { background: rgba(248, 113, 113, 0.12); }
table { width: 100%%; border-collapse: collapse; margin-top: 8px; font-size: 0.92rem; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #1d2a3d; vertical-align: top; }
th { background: #101a2a; color: #7890ad; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; }
tbody tr:hover { background: #111f32; }
ol { margin: 8px 0 0; padding-left: 1.2rem; }
li { margin: 6px 0; }
.status {
  background: #162235;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 12px 14px;
  color: #e2e8f0;
}
.status:empty { display: none; }
details.help { position: relative; display: inline-block; margin-left: 6px; vertical-align: middle; }
details.help > summary {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border: 1px solid #334155;
  border-radius: 999px;
  background: #162235;
  color: #38bdf8;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  list-style: none;
}
details.help > summary::-webkit-details-marker { display: none; }
details.help[open] > p {
  position: absolute;
  z-index: 20;
  left: 0;
  top: 28px;
  width: min(380px, calc(100vw - 36px));
  max-height: 280px;
  overflow: auto;
  margin: 0;
  padding: 10px 12px;
  background: #162235;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #e2e8f0;
  font-weight: 400;
  box-shadow: 0 12px 30px rgba(0, 0, 0, .45);
  overflow-wrap: break-word;
}
button:focus-visible, input:focus-visible, textarea:focus-visible, .choice:focus-visible {
  outline: 2px solid #38bdf8;
  outline-offset: 2px;
}
.panel[hidden] { display: none !important; }
@media (max-width: 720px) {
  .shell { padding: 16px 14px 48px; }
  .choices, .grid2 { grid-template-columns: 1fr; }
}
</style>
<noscript><style>.panel, #pick { display: block !important; }</style></noscript>
</head>
<body>
<main class="shell">
<p class="eyebrow">RouteHash</p>
<h1>Blake2b Pool Balance</h1>
<p class="lede">This service sits beside your DATUM gateway. It writes only Pool Host, port, and pubkey, and only after a node runner opts in. Your ASICs stay on your gateway. House Pool is the last stop. Pick one role. Complete only that form.</p>
<p class="status" id="status">%s</p>
<aside class="warn">
<p><strong>Two roles. Do not fill in both for the same DATUM.</strong></p>
<p>Node Runner writes Pool Host on the one local DATUM whose API address you save. Use that form only for the DATUM your own ASICs mine through.</p>
<p>Pool Operator only lists a pool. That form does not move a gateway.</p>
<p>If you operate a pool and also mine, run a second DATUM for your own ASICs. Open Node Runner only for that second DATUM. Do not opt in the DATUM that is the pool. That would send every miner on that pool to some other pool.</p>
</aside>
<section id="pick">
<h2>Which role is this machine?</h2>
<p class="note">Open one form. A node runner stops after the local DATUM form. A pool operator stops after the list-your-pool form.</p>
<div class="choices">
<button type="button" class="choice" id="pick-node"><strong>Node Runner</strong><span>This DATUM is for my own ASICs. I want Pool Host on this gateway to move. I will not use this form on a public pool.</span></button>
<button type="button" class="choice" id="pick-pool"><strong>Pool Operator</strong><span>I am listing my pool so other machines can read it. I will not opt in the DATUM miners already use.</span></button>
</div>
</section>
<section id="panel-node" class="panel" hidden>
<div class="card danger">
<p><strong>This form changes Pool Host.</strong> Use it only for the DATUM your own ASICs mine through. Do not paste the API address of a public pool. Opting that pool in would send every miner on it to some other pool.</p>
</div>
<details class="card guide" id="move-guide">
<summary>Before this gateway can move<span>Nothing here is assumed. This page writes only Pool Host, port, and pubkey, and only after you opt in on your own mining DATUM.</span></summary>
<ol>
<li>Install a DATUM gateway on this machine for your own ASICs. Point each ASIC at that gateway miner port and leave it there. This service does not change the ASIC address. Never put port 28915 on an ASIC.</li>
<li>On the DATUM dashboard open Interface, then Web UI, then Local. Copy the address and the API Listen Port. The gateway API address below is http:// plus that address and port.</li>
<li>Copy the API Password from that same Local screen. The dashboard user is admin.</li>
<li>Turn on Allow API Config Writes on the DATUM dashboard. This service cannot turn that switch on. Pool Host does not change while it is off.</li>
<li>Paste the gateway API address and the API password below. Check the mining-DATUM box, then opt in. Local max percent is not a timer and it is not a cap on your rig. The 30-minute wait is separate. Leave it empty and this machine stores 30 percent of global XBT hashrate. The highest number is 30. A higher number is refused and the saved value stays. A pool publishes how much of the network it will hold. This number is how much of the network you will help one pool hold. This machine uses the lower of the two. Set Rig TH/s to the advertised figure. Zero stays on the saved Pool Host. Pin holds Pool Host still.</li>
<li>Leave Home Pool Host blank. About once a minute this service reads Pool Host, port, and pubkey from the gateway and keeps that as home. It does not wait for a DATUM restart. The read needs the gateway API address and admin password. A typed host replaces the copy.</li>
<li>House Pool is the last stop and is already filled in. Your ASICs stay on your gateway. When home does not fit and every receiving pool would go over its cap, this service points the gateway Pool Host here so the rig keeps hashing. After 30 minutes on House Pool, this service stays there until your home Pool Host fits again. Clear House Pool if you do not want that fallback.</li>
<li>The relay box on this form is what this machine reads. Add your own relay on the next line, using the Start9 or Umbrel steps in Your own Nostr relay. Pool size is read from mempool.guide.</li>
</ol>
</details>
<form id="node-form" method="post" action="/">
<div class="card">
<h2>Move settings</h2>
<div class="field">
<label><input type="checkbox" name="opt_in" value="1"%s> Opt in to move Pool Host</label>
<details class="help"><summary aria-label="Help">?</summary><p>When on, this service may change Pool Host on the gateway whose API address you saved. When off, it leaves Pool Host where it is. A move is written only when the gateway API address and admin password are saved and Allow API Config Writes is on. Leave this off for a DATUM that other miners use as a pool. The mining-DATUM box under Save must be checked or this page stores opt-in as off.</p></details>
</div>
<div class="field">
<label>Local max percent</label>
<details class="help"><summary aria-label="Help">?</summary><p>This is not a timer and it is not a cap on your rig TH/s. The 30-minute wait is separate. Leave empty and this machine stores 30 percent of global XBT hashrate. The highest number is 30. A higher number is refused and the saved value stays. A pool publishes how much of the network it will hold. This number is how much of the network you will help one pool hold. This machine uses the lower of the two. There is no blank setting that means no limit. The global XBT hashrate only turns the percent into TH. If adding your Rig TH/s would put a pool over that TH, this service tries the next pool. House Pool is not held to this number.</p></details>
<input type="number" name="ceiling_percent" min="0" max="30" step="0.01" value="%s">
</div>
<div class="field">
<label>Rig TH/s</label>
<details class="help"><summary aria-label="Help">?</summary><p>Advertised TH/s of the ASICs on this gateway. This is the amount added when checking whether a pool still has room. It does not change by itself. Zero stays on the saved Pool Host.</p></details>
<input type="number" name="rig_th" min="0" step="0.01" value="%s">
</div>
<div class="field">
<label><input type="checkbox" name="pinned" value="1"%s> Pin Pool Host</label>
<details class="help"><summary aria-label="Help">?</summary><p>While pinned, Pool Host is not moved. Clear the pin and the next choice can return to your home Pool Host. A file named pin in the service data directory pins as well.</p></details>
</div>
</div>
<div class="card">
<h2>Local gateway</h2>
<p class="danger"><strong>This is the DATUM that will be rewritten.</strong> Paste the API address of your own mining gateway. Do not paste the public pool.</p>
<div class="field">
<label>Gateway API address</label>
<details class="help"><summary aria-label="Help">?</summary><p>On the DATUM dashboard open Interface, then Web UI, then Local. The address is http:// plus the host and API Listen Port shown there. An example is http://10.0.3.1:7152. This is not the Node RPC address. Blank does not write. Use the DATUM your own ASICs mine through.</p></details>
<input type="text" name="gateway_url" value="%s">
</div>
<div class="field">
<label>Gateway admin password</label>
<details class="help"><summary aria-label="Help">?</summary><p>Paste the API Password from Interface, then Web UI, then Local. The dashboard user is admin. Turn on Allow API Config Writes on the DATUM dashboard. This service cannot turn that switch on. On this page a blank password keeps the saved one.</p></details>
<input type="password" name="gateway_password" value="" autocomplete="off">
<span class="note">%s</span>
</div>
</div>
<div class="card">
<h2>Home Pool Host</h2>
<div class="field">
<label>Pool Host</label>
<details class="help"><summary aria-label="Help">?</summary><p>Leave this blank. About once a minute this service reads the Pool Host already saved on your DATUM gateway, plus its port and pubkey, and keeps that as home. It does not wait for a DATUM restart. The read needs the gateway API address and admin password. Type a host only when you want a different home. Clearing a host that was already saved does not read the gateway again.</p></details>
<input type="text" name="home_host" value="%s">
</div>
<div class="grid2">
<div class="field">
<label>Port</label>
<details class="help"><summary aria-label="Help">?</summary><p>Filled from the gateway when Pool Host is left blank. This is the pool port, not an ASIC port. 28915 is only the placeholder until that copy happens.</p></details>
<input type="number" name="home_port" min="1" max="65535" value="%s">
</div>
<div class="field">
<label>Pubkey</label>
<details class="help"><summary aria-label="Help">?</summary><p>128 hex characters from that pool. Leave this blank when Pool Host is blank. The gateway copy fills it. Type it only when you set the host yourself.</p></details>
<input type="text" name="home_pubkey" value="%s">
</div>
</div>
</div>
<div class="card">
<h2>House Pool</h2>
<p class="note">House Pool is the last stop, already filled in. Your ASICs stay on your gateway. When home does not fit and every receiving pool would go over its cap, this service points the gateway Pool Host here so the rig keeps hashing. House Pool is not held to a percent. After 30 minutes here, it stays until home fits again. A pool that frees up does not pull the rig off House Pool.</p>
<div class="field">
<label>Pool Host</label>
<details class="help"><summary aria-label="Help">?</summary><p>Already pool.routehash.com. This is where the gateway Pool Host goes when no capped pool has room. You can replace it. Clear it to turn the fallback off.</p></details>
<input type="text" name="house_host" value="%s">
</div>
<div class="grid2">
<div class="field">
<label>Port</label>
<details class="help"><summary aria-label="Help">?</summary><p>Already 28915. This is the port the gateway uses for House Pool. Never put this port on an ASIC.</p></details>
<input type="number" name="house_port" min="1" max="65535" value="%s">
</div>
<div class="field">
<label>Pubkey</label>
<details class="help"><summary aria-label="Help">?</summary><p>Already the House Pool pubkey, 128 hex characters. The gateway needs this pubkey to connect to House Pool. Leave it unless you replace the host.</p></details>
<input type="text" name="house_pubkey" value="%s">
</div>
</div>
</div>
<div class="card">
<h2>Global Blake2b Network</h2>
<p class="note">Optional. This reads the global XBT hashrate from the Knots or Bitcoin Core node on this machine. When the RPC address is set, the total comes from that node. When it is blank, the total comes from mempool.guide. Pool size still comes from mempool.guide by coinbase tag.</p>
<div class="field">
<label>Node RPC address</label>
<details class="help"><summary aria-label="Help">?</summary><p>Optional. JSON-RPC of the Knots or Bitcoin Core node on this machine, such as http://10.0.3.1:8332. Use the RPC port that node shows. When this address is set, the global XBT hashrate comes from that node. When it is blank, the total comes from mempool.guide. This is not the DATUM gateway and not a Nostr relay.</p></details>
<input type="text" name="node_url" value="%s">
</div>
<div class="grid2">
<div class="field">
<label>Node RPC user</label>
<details class="help"><summary aria-label="Help">?</summary><p>RPC username for that node, the rpcuser in its settings. Leave blank when the address is blank. Not used when the total comes from mempool.guide.</p></details>
<input type="text" name="node_user" value="%s">
</div>
<div class="field">
<label>Node RPC password</label>
<details class="help"><summary aria-label="Help">?</summary><p>RPC password for that node, the rpcpassword in its settings. Leave blank to keep the saved password. Leave it blank when the address is blank.</p></details>
<input type="password" name="node_password" value="" autocomplete="off">
<span class="note">%s</span>
</div>
</div>
</div>
<label class="ack"><input type="checkbox" name="own_gateway" value="1"><span>This DATUM is my own mining gateway, not a public pool. Opt in stays off until this box is checked.</span></label>
<p class="block" id="node-block" hidden>Check the mining-gateway box before saving an opt-in. This form must not be used on the DATUM that is a public pool.</p>
<div class="actions"><button class="primary" type="submit" name="form" value="save">Save node runner settings</button></div>
</form>
</section>
<section id="panel-pool" class="panel" hidden>
<div class="card danger">
<p><strong>This form only lists your pool.</strong> It does not write Pool Host. Do not switch to Node Runner and paste this pool DATUM into Gateway API address. Do not opt in the DATUM that is the pool. That would send every miner on that pool to some other pool. Personal mining belongs on a second DATUM. Open Node Runner only for that second DATUM.</p>
</div>
<details class="card guide" id="list-guide">
<summary>List your pool<span>Skip this form if you only run a DATUM gateway. Your rig can move without it.</span></summary>
<p>The 320-character private key proves you own the pool. On StartOS it is the file ratum-prime.key in the RATUM Prime service data. DATUM Prime or RATUM writes that file the first time it starts and does not show it on screen. Show Pool Pubkey is the public key only. Pasting that public key cannot sign a cap, because anyone can read it. It is not the 128-character pool pubkey, and it is not a Nostr key. You do not paste a Nostr pubkey. A DATUM gateway does not have this file. Paste the key from that file once. This page stores it and does not show it again. After it is saved, this page shows the public 128-character pool key derived from it. This machine creates the Nostr key that only carries the events. The same DATUM identity signs the cap and the listing. This page sends the cap first. The listing is sent only after a relay accepts that cap. A listing with no cap does not move anyone. Name defaults to the host. Percent of global XBT hashrate on this form is the pool cap. A stats URL is optional, stored, and not fetched. Publish again within 24 hours. A cap lasts 24 hours and the listing lasts 7 days. Remove sends a cap that stops receiving, then a listing marked removed.</p>
</details>
<form id="pool-form" method="post" action="/">
<div class="card">
<div class="field">
<label>DATUM private identity</label>
<details class="help"><summary aria-label="Help">?</summary><p>This proves you own the pool. Paste the 320-character private key from the RATUM Prime that created the pool. On StartOS the file is ratum-prime.key in the RATUM Prime service data. That service writes the file the first time it starts and does not show it. Show Pool Pubkey shows only the public 128-character key, and that public key cannot sign. A DATUM gateway does not have this file. It is not a Nostr key. You do not paste a Nostr pubkey. Paste the key once. This page stores it and does not show it again. After it is saved, this page shows the public 128-character pool key derived from it. Skip this box if you only run a gateway.</p></details>
<input type="password" name="pool_identity" value="" autocomplete="off">
<span class="note">%s</span>
</div>
<div class="field">
<label>Pool name</label>
<details class="help"><summary aria-label="Help">?</summary><p>The name other choosers show in the pool list. Leave blank and the name defaults to the host.</p></details>
<input type="text" name="pool_name" value="%s">
</div>
<div class="field">
<label>Pool host</label>
<details class="help"><summary aria-label="Help">?</summary><p>The host other gateways use as Pool Host when they move toward your pool. This publishes an address. It does not change Pool Host on your gateway. This is not an ASIC address.</p></details>
<input type="text" name="pool_host" value="%s">
</div>
<div class="grid2">
<div class="field">
<label>Pool port</label>
<details class="help"><summary aria-label="Help">?</summary><p>The port other gateways use with that host. This is not an ASIC port. Never put port 28915 on an ASIC.</p></details>
<input type="number" name="pool_port" min="1" max="65535" value="%s">
</div>
<div class="field">
<label>Coinbase tag</label>
<details class="help"><summary aria-label="Help">?</summary><p>The tag this pool puts in the coinbase. Pool size is matched to this tag on mempool.guide. A missing or different tag is not a move target.</p></details>
<input type="text" name="pool_tag" value="%s">
</div>
</div>
<div class="grid2">
<div class="field">
<label>Percent of global XBT hashrate</label>
<details class="help"><summary aria-label="Help">?</summary><p>This is the pool cap, a percent of global XBT hashrate. A chooser skips this pool when adding its Rig TH/s would put the pool over this percent, or over that chooser local max percent when that number is lower. The number does not change by itself when the global XBT hashrate changes. The global XBT hashrate turns the percent into TH. Publish again within 24 hours.</p></details>
<input type="text" name="pool_percent" value="%s">
</div>
<div class="field">
<label>Capacity TH/s, optional</label>
<details class="help"><summary aria-label="Help">?</summary><p>Optional second cap in TH/s. When it is above zero, the pool max is the lower of this number and the percent times the global XBT hashrate. Leave blank for no extra TH cap.</p></details>
<input type="text" name="pool_capacity" value="%s">
</div>
</div>
<div class="field">
<label>Stats URL, optional</label>
<details class="help"><summary aria-label="Help">?</summary><p>Optional. Stored on the listing and not fetched. Choosers do not use it to measure the pool.</p></details>
<input type="text" name="pool_stats_url" value="%s">
</div>
<div class="field">
<label>Relays for this publish, one per line</label>
<details class="help"><summary aria-label="Help">?</summary><p>Where this page sends the cap and the listing. Add your own relay here too, with the Start9 or Umbrel address from Your own Nostr relay, under Pools on the relays. This list does not grow by itself. The cap is sent first. The listing is sent only after a relay accepts that cap.</p></details>
<textarea name="pool_relays" rows="4">%s</textarea>
</div>
<div class="actions">
<button class="primary" type="submit" name="form" value="publish">Publish cap and listing</button>
<button class="ghost" type="submit" name="form" value="remove">Remove this pool</button>
</div>
<p class="note">Publish and remove do not change Pool Host on a gateway.</p>
</div>
</form>
</section>
<section class="card" id="catalog">
<h2>Pools on the relays</h2>
<p class="note">This table is read only. It lists every signed listing read from the relays below. A pool appears here after its operator publishes it with the private key from the RATUM Prime that created that pool. The RouteHash relay does not ask for a separate login. The signature is the permission to update that pool. Adding your own relay lets others read your pool there after you publish to it. This list does not copy relays from one machine onto another. A listing with no cap does not move anyone. A pool that is not receiving stays off the move list. House Pool on this machine stays the last stop even when its cap says not receiving.</p>
%s
</section>
<div class="card">
<h2>Relays this machine reads</h2>
<p class="note">One address per line, ws:// or wss://. Install steps for Start9 and Umbrel are in Your own Nostr relay below. Add your own relay on the next line. This list does not grow by itself. Save node runner settings stores this list.</p>
<div class="field">
<label>Relay URLs, one per line</label>
<details class="help"><summary aria-label="Help">?</summary><p>The list starts with wss://relay.routehash.com. Add your own relay on the next line, as ws:// or wss://. This list does not grow by itself. This machine reads pools from every address in this list. Other machines see your pool when they already read one of those relays. A wss URL needs a certificate for that name. Start9 trusts its own certificate on the LAN. Turn Public on for StartTunnel, or forward the nostr port on your router, when other people should read your relay.</p></details>
<textarea name="relays" form="node-form" rows="4">%s</textarea>
</div>
<div class="actions"><button class="primary" type="submit" form="node-form" name="form" value="save">Save node runner settings</button></div>
</div>
<details class="card guide" id="relay-guide">
<summary>Your own Nostr relay<span>How to install a relay on Start9 or Umbrel, and why.</span></summary>
<p>The relay list starts with wss://relay.routehash.com. Add your own relay on the next line, as ws:// or wss://. This list does not grow by itself. This machine reads pool caps from every address on the list. Other machines see your pool only when they already read one of those relays. Your relay is a second copy. If the RouteHash relay is down, a machine that also reads your relay can still see a cap you published there.</p>
<h3>Why</h3>
<p>The shared RouteHash relay is enough for a first read. Your own relay keeps a copy you control. Install that relay on the Start9 or Umbrel that should store the copy, then paste its websocket address into the relay box on the form you save.</p>
<h3>Start9</h3>
<ol>
<li>On the Start9 that should host the relay, open the marketplace and install Nostr RS Relay. The package id is nostr-rs-relay. Start the service.</li>
<li>Open Interfaces and copy the Relay websocket address. It starts with ws:// or wss://.</li>
<li>Paste that address on the next line of the relay box in the form you use. Node Runner reads its relay box. Pool Operator publishes to the relay box on that form. A LAN address is enough for choosers on that same Start9.</li>
<li>A wss URL needs a certificate for that name. Start9 trusts its own certificate on the LAN. Turn Public on for StartTunnel, or forward the nostr port on your router, when other people should read your relay.</li>
<li>Leave Restrict Access alone. Saving Restrict Access while Authorized Pubkeys is empty locks every publish. Leave Permitted Events alone unless 30080 and 30081 are both allowed. 30080 is the pool cap and 30081 is the pool listing. A list that omits either one drops the publish. A fresh relay is open, which is what this page needs.</li>
</ol>
<h3>Umbrel</h3>
<ol>
<li>On the Umbrel that should host the relay, open the App Store, open Social, and install Nostr Relay. That app is the official Umbrel relay. It is powered by nostr-rs-relay.</li>
<li>Open Nostr Relay and copy the relay URL it shows. On a LAN that URL is often ws:// plus the Umbrel address and port 4848.</li>
<li>Paste that URL on the next line of the relay box in the form you use.</li>
<li>A wss URL needs a certificate for that name. Forward the nostr port on your router when other people should read your relay. Leave any kind filter alone unless 30080 and 30081 are both allowed.</li>
</ol>
<h3>Client and relay</h3>
<p>A Nostr client reads a relay. Damus, Amethyst, and noStrudel are clients. This list stores a relay address, not a client. You do not install a client to make pool balance work, and you do not add a client to this list. Install the relay above, then add the relay address here. You do not paste a Nostr pubkey.</p>
</details>
</main>
<script>
(function () {
  var nodePanel = document.getElementById("panel-node");
  var poolPanel = document.getElementById("panel-pool");
  var nodeChoice = document.getElementById("pick-node");
  var poolChoice = document.getElementById("pick-pool");
  function show(hash) {
    var picked = "";
    if (hash === "#pool" || hash === "pool") picked = "pool";
    if (hash === "#node" || hash === "node") picked = "node";
    nodePanel.hidden = picked !== "node";
    poolPanel.hidden = picked !== "pool";
    nodeChoice.className = picked === "node" ? "choice on" : "choice";
    poolChoice.className = picked === "pool" ? "choice on" : "choice";
    nodeChoice.setAttribute("aria-pressed", picked === "node" ? "true" : "false");
    poolChoice.setAttribute("aria-pressed", picked === "pool" ? "true" : "false");
  }
  function arm(button, hash) {
    button.addEventListener("click", function () {
      location.hash = hash;
      show(hash);
    });
  }
  arm(nodeChoice, "node");
  arm(poolChoice, "pool");
  window.addEventListener("hashchange", function () { show(location.hash); });
  show(location.hash);
  var form = document.getElementById("node-form");
  form.addEventListener("submit", function (event) {
    var opt = form.querySelector("input[name=opt_in]");
    var ack = form.querySelector("input[name=own_gateway]");
    var block = document.getElementById("node-block");
    var ceiling = form.querySelector("input[name=ceiling_percent]");
    if (ceiling && ceiling.value !== "" && Number(ceiling.value) > 30) {
      event.preventDefault();
      var status = document.getElementById("status");
      status.textContent = "Local max percent cannot be above 30. The saved value was kept.";
      return;
    }
    if (opt && opt.checked && (!ack || !ack.checked)) {
      event.preventDefault();
      block.hidden = false;
    }
  });
})();
</script>
</body>
</html>
""" % (
        _esc(message),
        _checked(config["opt_in"]),
        _esc(config["ceiling_percent"]),
        _esc(config["rig_th"]),
        _checked(config["pinned"]),
        _esc(config["gateway"]["url"]),
        _esc(saved),
        _esc(config["home"]["host"]),
        _esc(config["home"]["port"]),
        _esc(config["home"]["pubkey"]),
        _esc(config["house"]["host"]),
        _esc(config["house"]["port"]),
        _esc(config["house"]["pubkey"]),
        _esc(config["node"]["url"]),
        _esc(config["node"]["user"]),
        _esc(node_saved),
        _esc(identity_note),
        _esc(publish.get("name") or ""),
        _esc(publish.get("host") or ""),
        _esc(publish.get("port") or 28915),
        _esc(publish.get("tag") or ""),
        _esc(publish.get("percent") or ""),
        _esc(publish.get("capacity") or ""),
        _esc(publish.get("stats_url") or ""),
        _esc(publish.get("relays") or ""),
        _catalog_html(catalog),
        _esc(relays),
    )


def _one(form, key):
    value = form.get(key)
    if isinstance(value, list):
        value = value[-1] if value else ""
    return "" if value is None else str(value)


def form_for_save(form):
    """Drop opt-in unless the page confirmed this DATUM is personal mining.

    The checkbox is omitted from the post when it is unchecked. A pool
    operator who saves the node form without that check does not move the gateway.
    """
    opted = _one(form, "opt_in") in {"1", "on", "true", "yes"}
    owned = _one(form, "own_gateway") in {"1", "on", "true", "yes"}
    if opted and not owned:
        return {key: value for key, value in form.items() if key != "opt_in"}
    return form


def config_from_form(form, previous=None):
    """Settings posted by the local page. A blank password keeps the saved one."""
    previous = normalize_config(previous or {})

    def text(key, fallback):
        if key not in form:
            return fallback
        return _one(form, key).strip()

    password = text("gateway_password", "")
    if password == "":
        password = previous["gateway"]["password"]
    node_password = text("node_password", "")
    if node_password == "":
        node_password = previous["node"]["password"]
    relay_text = text("relays", "\n".join(previous["relays"]))
    relays = [line.strip() for line in relay_text.splitlines() if line.strip()]
    posted_home = text("home_host", previous["home"]["host"])
    home_from_gateway = bool(previous.get("home_from_gateway"))
    if "home_host" in form and (posted_home or previous["home"]["host"]):
        home_from_gateway = True
    return normalize_config({
        "opt_in": _one(form, "opt_in") in {"1", "on", "true", "yes"},
        "ceiling_percent": text("ceiling_percent", previous["ceiling_percent"]),
        "rig_th": text("rig_th", previous["rig_th"]) or 0,
        "pinned": _one(form, "pinned") in {"1", "on", "true", "yes"},
        "relays": relays,
        "home": {
            "host": text("home_host", previous["home"]["host"]),
            "port": text("home_port", previous["home"]["port"]) or 28915,
            "pubkey": text("home_pubkey", previous["home"]["pubkey"]),
        },
        "home_from_gateway": home_from_gateway,
        "house": {
            "host": text("house_host", previous["house"]["host"]),
            "port": text("house_port", previous["house"]["port"]) or 28915,
            "pubkey": text("house_pubkey", previous["house"]["pubkey"]),
        },
        "gateway": {
            "url": text("gateway_url", previous["gateway"]["url"]),
            "password": password,
        },
        "node": {
            "url": text("node_url", previous["node"]["url"]),
            "user": text("node_user", previous["node"]["user"]),
            "password": node_password,
        },
    })


def save_config(data_dir, config):
    data = Path(data_dir)
    config = normalize_config(config)
    _save(data / "chooser.json", config, private=True)
    pin = data / "pin"
    if config["pinned"]:
        pin.write_text("1\n")
    elif pin.exists():
        pin.unlink()
    return config


def _adopt_gateway_home(data_dir, config, gateway):
    """A blank home starts as the Pool Host already saved on this gateway.

    The snapshot is kept, so a later move does not become the new home.
    """
    if config["home"]["host"] or config.get("home_from_gateway") or gateway is None:
        return config
    current = gateway.read() or {}
    host = str(current.get("host") or "").strip()
    if not host:
        return config
    adopted = dict(config)
    adopted["home"] = {
        "host": host,
        "port": _port(current.get("port"), 28915),
        "pubkey": str(current.get("pubkey") or "").strip(),
    }
    adopted["home_from_gateway"] = True
    return save_config(data_dir, adopted)


def cycle(data_dir, now=None, opener=None, websocket_factory=None, pause=2.0, samples=None):
    """One choice. Returns the placement. Does not print the gateway password."""
    data = Path(data_dir)
    moment = time.time() if now is None else now
    config = normalize_config(_load(data / "chooser.json", {}))
    if (data / "pin").exists():
        config["pinned"] = True
    manual = _load(data / "announcements.json", [])
    if not isinstance(manual, list):
        manual = []
    announcements = list(manual)
    listings = []
    if config["relays"]:
        from pool_publish import announcements_from_relays, listings_from_cache

        factory = websocket_factory
        if factory is None:
            from websocket import create_connection
            factory = create_connection
        cache = _load(data / "relay-cache.json", {})
        fetched, cache = announcements_from_relays(config["relays"], factory, cache, moment)
        _save(data / "relay-cache.json", cache)
        announcements.extend(fetched)
        listings = listings_from_cache(cache, moment)
    if samples is None:
        from pool_samples import fetch_samples
        samples = fetch_samples(
            announcements,
            config.get("node"),
            now=moment,
            cache_path=str(data / "sample-cache.json"),
        )
    if not isinstance(samples, dict):
        samples = {}
    state = _load(data / "state.json", {})
    gateway = None
    block = config["gateway"]
    if block["url"] and block["password"]:
        gateway = DatumGatewayClient(block["url"], block["password"], opener=opener, pause=pause)
    config = _adopt_gateway_home(data_dir, config, gateway)
    config["listings"] = listings
    placement, new_state = run_once(config, state, announcements, samples, gateway, moment)
    _save(data / "state.json", new_state)
    _save(data / "last.json", {
        "kind": placement.kind,
        "reason": placement.reason,
        "pool_id": placement.pool_id,
    })
    return placement


def start_ui(data_dir, port):
    """Serve the settings page on this container only."""
    data = Path(data_dir)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt, *_args):
            return

        def _send(self, status, body, content_type):
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path.split("?", 1)[0] != "/":
                self._send(404, "Not found", "text/plain; charset=utf-8")
                return
            config = normalize_config(_load(data / "chooser.json", {}))
            catalog = catalog_for_page(data, config)
            self._send(
                200,
                config_page(config, publish_view(data, config), catalog),
                "text/html; charset=utf-8",
            )

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/":
                self._send(404, "Not found", "text/plain; charset=utf-8")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > _UI_LIMIT:
                self._send(413, "Too large", "text/plain; charset=utf-8")
                return
            raw = self.rfile.read(length).decode("utf-8", "replace")
            form = parse_qs(raw, keep_blank_values=True)
            previous = normalize_config(_load(data / "chooser.json", {}))
            posted = _one(form, "form")
            if posted in {"publish", "remove"}:
                publish_pool(data, form, previous)
                target = "/#pool"
            else:
                posted_config = config_from_form(form_for_save(form), previous)
                if ceiling_refused(posted_config["ceiling_percent"]):
                    view = dict(publish_view(data, previous))
                    view["message"] = (
                        "Local max percent cannot be above 30. The saved value was kept."
                    )
                    self._send(
                        200,
                        config_page(previous, view, catalog_for_page(data, previous)),
                        "text/html; charset=utf-8",
                    )
                    return
                save_config(data, posted_config)
                target = "/#node"
            self.send_response(303)
            self.send_header("Location", target)
            self.end_headers()

    server = ThreadingHTTPServer(("0.0.0.0", int(port)), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--ui", type=int, default=0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=LOOP_SECONDS)
    args = parser.parse_args(argv)
    if args.ui:
        start_ui(args.data, args.ui)
    interval = args.interval if args.interval >= LOOP_SECONDS else LOOP_SECONDS
    while True:
        try:
            placement = cycle(args.data)
            print(json.dumps({
                "kind": placement.kind,
                "reason": placement.reason,
                "pool_id": placement.pool_id,
            }), flush=True)
        except Exception as error:
            print(json.dumps({"error": type(error).__name__}), flush=True)
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
