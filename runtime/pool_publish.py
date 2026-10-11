"""Publish a signed Blake2b cap to the relays a user listed.

The DATUM Ed25519 signature is the cap. The Nostr signature only gets the
event onto a relay. Callers pass a socket factory in tests. This module
does not read RouteHash's relay setting and does not import the proxy.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from directory_events import generate_identity, nostr_hex_to_npub, sign_event
from pool_announce import (
    CAP_KIND,
    LISTING_KIND,
    listing_from_event,
    normalize_relays,
    verify_announcement,
    verify_listing,
)
from pool_chooser import collect_events, verified_from_events


def load_or_create_transport_key(path):
    """Local Nostr key used only as transport. The file keeps the private half."""
    file = Path(path)
    if file.exists():
        data = json.loads(file.read_text())
        private_key = str(data.get("private_key") or "")
        public_key = str(data.get("public_key") or "")
        if not private_key or not public_key:
            raise ValueError("transport key file is missing a key")
        return {"private_key": private_key, "public_key": public_key}
    identity = generate_identity()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(identity) + "\n")
    file.chmod(0o600)
    return identity


def transport_npub(identity):
    return nostr_hex_to_npub(identity["public_key"])


def cap_event(document, transport_private_key, now=None):
    """Kind 30080 event. The d tag keeps this cap beside any lower one."""
    current = int(time.time() if now is None else now)
    payload = verify_announcement(document, current)
    if payload is None:
        raise ValueError("announcement failed DATUM signature check")
    content = json.dumps(document, sort_keys=True, separators=(",", ":"))
    event = {
        "pubkey": "",
        "created_at": payload["created_at"],
        "kind": CAP_KIND,
        "tags": [
            ["d", f"{payload['pool_pubkey']}:{payload['created_at']}"],
            ["expiration", str(payload["expires_at"])],
        ],
        "content": content,
    }
    return sign_event(event, transport_private_key)


def nip01_intact(event):
    """True when the relay signature matches the id. This is not the cap check."""
    from hashlib import sha256
    from coincurve import PublicKeyXOnly
    try:
        serialized = json.dumps(
            [0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]],
            separators=(",", ":"),
        )
        if event.get("id") != sha256(serialized.encode("utf-8")).hexdigest():
            return False
        PublicKeyXOnly(bytes.fromhex(event["pubkey"])).verify(
            bytes.fromhex(event["sig"]),
            bytes.fromhex(event["id"]),
        )
        return True
    except Exception:
        return False


def listing_event(document, transport_private_key, now=None):
    """Kind 30081 event. The d tag is the DATUM pubkey, so a newer listing replaces it."""
    current = int(time.time() if now is None else now)
    payload = verify_listing(document, current)
    if payload is None:
        raise ValueError("listing failed DATUM signature check")
    content = json.dumps(document, sort_keys=True, separators=(",", ":"))
    event = {
        "pubkey": "",
        "created_at": payload["created_at"],
        "kind": LISTING_KIND,
        "tags": [
            ["d", payload["pool_pubkey"]],
            ["expiration", str(payload["expires_at"])],
        ],
        "content": content,
    }
    return sign_event(event, transport_private_key)


def _deliver(event, relays, websocket_factory, timeout):
    """Send one event to every listed relay. One failure does not stop the rest."""
    urls = normalize_relays(relays)
    if not urls:
        raise ValueError("at least one ws:// or wss:// relay is required")
    message = json.dumps(["EVENT", event], separators=(",", ":"))
    results = []
    for relay in urls:
        socket = None
        try:
            socket = websocket_factory(relay, timeout=timeout)
            socket.send(message)
            response = json.loads(socket.recv())
            accepted = (
                isinstance(response, list)
                and len(response) >= 3
                and response[0] == "OK"
                and response[1] == event["id"]
                and response[2] is True
            )
            results.append({"relay": relay, "accepted": accepted, "response": response})
        except Exception as error:
            results.append({"relay": relay, "accepted": False, "error": str(error)[:255]})
        finally:
            if socket is not None:
                try:
                    socket.close()
                except Exception:
                    pass
    return results


def publish_caps(document, relays, transport_private_key, websocket_factory, timeout=10, now=None):
    """Send one cap to every listed relay. One failure does not stop the rest."""
    event = cap_event(document, transport_private_key, now=now)
    return event, _deliver(event, relays, websocket_factory, timeout)


def publish_listing(document, relays, transport_private_key, websocket_factory, timeout=10, now=None):
    """Send one pool listing to every listed relay."""
    event = listing_event(document, transport_private_key, now=now)
    return event, _deliver(event, relays, websocket_factory, timeout)


def fetch_cap_events(relays, websocket_factory, timeout=10):
    """Read caps and pool listings in one request. Older caps stay in the list."""
    urls = normalize_relays(relays)
    found = []
    errors = []
    for relay in urls:
        socket = None
        try:
            socket = websocket_factory(relay, timeout=timeout)
            subscription = "rh-cap-" + uuid.uuid4().hex
            socket.send(json.dumps(
                ["REQ", subscription, {"kinds": [CAP_KIND, LISTING_KIND]}],
                separators=(",", ":"),
            ))
            while True:
                response = json.loads(socket.recv())
                if (
                    isinstance(response, list)
                    and len(response) >= 2
                    and response[0] == "EOSE"
                    and response[1] == subscription
                ):
                    break
                if (
                    isinstance(response, list)
                    and len(response) == 3
                    and response[0] == "EVENT"
                    and response[1] == subscription
                    and isinstance(response[2], dict)
                ):
                    found.append(response[2])
        except Exception as error:
            errors.append({"relay": relay, "error": str(error)[:255]})
        finally:
            if socket is not None:
                try:
                    socket.close()
                except Exception:
                    pass
    return found, errors


def announcements_from_relays(relays, websocket_factory, cache, now, timeout=10):
    """Fetch, keep the last good copy of a failed relay, and drop bad events.

    The returned list is caps only. Listings stay in the cache events.
    """
    def transport(url):
        events, errors = fetch_cap_events([url], websocket_factory, timeout=timeout)
        if errors and not events:
            raise ConnectionError(errors[0]["error"])
        return events

    events, updated = collect_events(relays, transport, cache, now)
    return verified_from_events(events, now), updated


def listings_from_events(events, now):
    """Signed pool listings from raw relay events. Caps are left out."""
    found = []
    for event in events or ():
        if not isinstance(event, dict):
            continue
        if event.get("kind") == LISTING_KIND:
            if listing_from_event(event, now) is None:
                continue
            content = event.get("content")
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (TypeError, ValueError):
                    continue
            if isinstance(content, dict):
                found.append(content)
            continue
        if verify_listing(event, now) is not None:
            found.append(event)
    return found


def listings_from_cache(cache, now):
    """Listings saved with the last good copy of each relay."""
    events = []
    for row in (cache or {}).values():
        if isinstance(row, dict):
            events.extend(row.get("events") or ())
    return listings_from_events(events, now)
