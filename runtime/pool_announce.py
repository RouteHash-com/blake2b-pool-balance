"""Signed Blake2b pool-cap announcements and pool listings.

The signature is the Ed25519 half of a DATUM pool identity. Nostr and a
web mirror only carry the bytes. A listing stats URL is stored and is
not fetched. This module does not import the proxy.
"""
from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from urllib.parse import urlunsplit, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from pool_balance import parse_balance_percent

CAP_KIND = 30080
LISTING_KIND = 30081
SIGNATURE_LIFETIME = 24 * 60 * 60
LISTING_LIFETIME = 7 * 24 * 60 * 60
_FUTURE_SKEW = 300
_STATS_URL_LIMIT = 200


def canonical_bytes(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hex_bytes(value, size):
    text = str(value or "").strip().lower()
    if len(text) != size * 2:
        raise ValueError("key length")
    try:
        raw = bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError("key hex") from exc
    if len(raw) != size:
        raise ValueError("key length")
    return raw


def public_identity(private_hex):
    """128-hex DATUM pubkey from the 320-hex private identity file."""
    raw = _hex_bytes(private_hex, 160)
    return (raw[0:32] + raw[96:128]).hex()


def _seed(private_hex):
    raw = _hex_bytes(private_hex, 160)
    return raw[32:64]


def _normalize_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload")
    allowed = {
        "version", "algorithm", "pool_host", "pool_port", "pool_pubkey",
        "block_tag", "balance_receive", "max_percent", "capacity_th",
        "prime_pubkey", "prime_tag", "created_at", "expires_at",
    }
    extra = set(payload) - allowed
    if extra:
        raise ValueError("unknown field")
    if int(payload.get("version", 0)) != 1:
        raise ValueError("version")
    if str(payload.get("algorithm") or "") != "blake2b":
        raise ValueError("algorithm")
    host = str(payload.get("pool_host") or "").strip().lower().rstrip(".")
    if not host or "://" in host or "/" in host:
        raise ValueError("pool host")
    port = int(payload["pool_port"])
    if port < 1 or port > 65535:
        raise ValueError("pool port")
    pubkey = _hex_bytes(payload.get("pool_pubkey"), 64).hex()
    tag = str(payload.get("block_tag") or "").strip()
    if not tag or len(tag) > 64:
        raise ValueError("block tag")
    receive = bool(payload.get("balance_receive"))
    percent = parse_balance_percent(payload.get("max_percent"))
    if receive and percent is None:
        raise ValueError("percent")
    if not receive and payload.get("max_percent") not in (None, "") and percent is None:
        raise ValueError("percent")
    try:
        capacity = float(payload.get("capacity_th") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("capacity") from exc
    if capacity < 0:
        raise ValueError("capacity")
    prime_pubkey = str(payload.get("prime_pubkey") or "").strip().lower()
    if prime_pubkey:
        prime_pubkey = _hex_bytes(prime_pubkey, 64).hex()
    prime_tag = str(payload.get("prime_tag") or "").strip()
    if prime_pubkey and not prime_tag:
        raise ValueError("prime tag")
    if prime_tag and not prime_pubkey:
        raise ValueError("prime pubkey")
    created = int(payload["created_at"])
    expires = int(payload["expires_at"])
    if expires <= created or expires - created > SIGNATURE_LIFETIME:
        raise ValueError("lifetime")
    body = {
        "version": 1,
        "algorithm": "blake2b",
        "pool_host": host,
        "pool_port": port,
        "pool_pubkey": pubkey,
        "block_tag": tag,
        "balance_receive": receive,
        "max_percent": percent,
        "capacity_th": capacity,
        "prime_pubkey": prime_pubkey,
        "prime_tag": prime_tag,
        "created_at": created,
        "expires_at": expires,
    }
    return body


def sign_announcement(payload, private_hex):
    body = _normalize_payload(payload)
    if body["pool_pubkey"] != public_identity(private_hex):
        raise ValueError("pubkey does not match the signing identity")
    signature = Ed25519PrivateKey.from_private_bytes(_seed(private_hex)).sign(canonical_bytes(body))
    return {"payload": body, "signature": signature.hex()}


def verify_announcement(document, now):
    """Return the payload when the signature, pubkey, and lifetime hold."""
    if not isinstance(document, dict):
        return None
    payload = document.get("payload")
    try:
        body = _normalize_payload(payload)
        signature = _hex_bytes(document.get("signature"), 64)
        public = _hex_bytes(body["pool_pubkey"], 64)[:32]
        Ed25519PublicKey.from_public_bytes(public).verify(signature, canonical_bytes(body))
    except (InvalidSignature, ValueError, TypeError, KeyError):
        return None
    current = int(now)
    if body["created_at"] > current + _FUTURE_SKEW:
        return None
    if body["expires_at"] <= current:
        return None
    return body


def announcement_from_event(event, now):
    """Inner Ed25519 check. The Nostr transport signature is ignored."""
    if not isinstance(event, dict) or event.get("kind") != CAP_KIND:
        return None
    content = event.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            return None
    verified = verify_announcement(content, now)
    if verified is None:
        return None
    tags = event.get("tags") or []
    expected = f"{verified['pool_pubkey']}:{verified['created_at']}"
    d_tags = [tag[1] for tag in tags if isinstance(tag, list) and len(tag) >= 2 and tag[0] == "d"]
    if expected not in d_tags:
        return None
    return verified


def clean_stats_url(value):
    """https URL only. Empty is allowed. Private and local names are rejected.

    The result is stored on the listing. Nothing in this module requests it.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > _STATS_URL_LIMIT:
        raise ValueError("stats url")
    parts = urlsplit(text)
    if parts.scheme.lower() != "https" or parts.username is not None or parts.password is not None:
        raise ValueError("stats url")
    if parts.fragment:
        raise ValueError("stats url")
    host = (parts.hostname or "").strip().rstrip(".").lower()
    if not host or host in {"localhost", "localhost.localdomain"} or host.endswith(".local") or host.endswith(".localhost"):
        raise ValueError("stats url")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    ):
        raise ValueError("stats url")
    if ip is not None and ip.version == 6:
        host = f"[{ip.compressed}]"
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    cleaned = urlunsplit(("https", netloc, parts.path or "", parts.query or "", ""))
    if len(cleaned) > _STATS_URL_LIMIT:
        raise ValueError("stats url")
    return cleaned


def _normalize_listing(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload")
    allowed = {
        "version", "algorithm", "pool_pubkey", "name", "pool_host", "pool_port",
        "block_tag", "prime_pubkey", "prime_tag", "stats_url", "removed",
        "created_at", "expires_at",
    }
    if set(payload) - allowed:
        raise ValueError("unknown field")
    if int(payload.get("version", 0)) != 1:
        raise ValueError("version")
    if str(payload.get("algorithm") or "") != "blake2b":
        raise ValueError("algorithm")
    pubkey = _hex_bytes(payload.get("pool_pubkey"), 64).hex()
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 80 or any(ord(ch) < 32 for ch in name):
        raise ValueError("name")
    host = str(payload.get("pool_host") or "").strip().lower().rstrip(".")
    if not host or "://" in host or "/" in host:
        raise ValueError("pool host")
    port = int(payload["pool_port"])
    if port < 1 or port > 65535:
        raise ValueError("pool port")
    tag = str(payload.get("block_tag") or "").strip()
    if not tag or len(tag) > 64:
        raise ValueError("block tag")
    prime_pubkey = str(payload.get("prime_pubkey") or "").strip().lower()
    if prime_pubkey:
        prime_pubkey = _hex_bytes(prime_pubkey, 64).hex()
    prime_tag = str(payload.get("prime_tag") or "").strip()
    if prime_pubkey and not prime_tag:
        raise ValueError("prime tag")
    if prime_tag and not prime_pubkey:
        raise ValueError("prime pubkey")
    if "removed" in payload and not isinstance(payload.get("removed"), bool):
        raise ValueError("removed")
    stats_url = clean_stats_url(payload.get("stats_url"))
    created = int(payload["created_at"])
    expires = int(payload["expires_at"])
    if expires <= created or expires - created > LISTING_LIFETIME:
        raise ValueError("lifetime")
    return {
        "version": 1,
        "algorithm": "blake2b",
        "pool_pubkey": pubkey,
        "name": name,
        "pool_host": host,
        "pool_port": port,
        "block_tag": tag,
        "prime_pubkey": prime_pubkey,
        "prime_tag": prime_tag,
        "stats_url": stats_url,
        "removed": bool(payload.get("removed", False)),
        "created_at": created,
        "expires_at": expires,
    }


def sign_listing(payload, private_hex):
    body = _normalize_listing(payload)
    if body["pool_pubkey"] != public_identity(private_hex):
        raise ValueError("pubkey does not match the signing identity")
    signature = Ed25519PrivateKey.from_private_bytes(_seed(private_hex)).sign(canonical_bytes(body))
    return {"payload": body, "signature": signature.hex()}


def verify_listing(document, now):
    """Return the listing payload when the DATUM signature and lifetime hold."""
    if not isinstance(document, dict):
        return None
    payload = document.get("payload")
    try:
        body = _normalize_listing(payload)
        signature = _hex_bytes(document.get("signature"), 64)
        public = _hex_bytes(body["pool_pubkey"], 64)[:32]
        Ed25519PublicKey.from_public_bytes(public).verify(signature, canonical_bytes(body))
    except (InvalidSignature, ValueError, TypeError, KeyError):
        return None
    current = int(now)
    if body["created_at"] > current + _FUTURE_SKEW:
        return None
    if body["expires_at"] <= current:
        return None
    return body


def listing_from_event(event, now):
    """Inner Ed25519 check. The d tag is the DATUM pubkey, not the Nostr key."""
    if not isinstance(event, dict) or event.get("kind") != LISTING_KIND:
        return None
    content = event.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            return None
    verified = verify_listing(content, now)
    if verified is None:
        return None
    tags = event.get("tags") or []
    d_tags = [tag[1] for tag in tags if isinstance(tag, list) and len(tag) >= 2 and tag[0] == "d"]
    if verified["pool_pubkey"] not in d_tags:
        return None
    return verified


@dataclass(frozen=True)
class ResolvedListing:
    pubkey: str
    name: str
    host: str
    port: int
    block_tag: str
    prime_pubkey: str
    prime_tag: str
    stats_url: str
    removed: bool
    created_at: int


def current_listings(documents, now):
    """Newest unexpired listing for each DATUM pubkey.

    A newer signature replaces the name, host, port, tag, and stats URL.
    A newer removal stays in the result so that pubkey is not a target.
    """
    best = {}
    for item in documents or ():
        payload = verify_listing(item, now)
        if not payload:
            continue
        previous = best.get(payload["pool_pubkey"])
        rank = (payload["created_at"], payload["expires_at"])
        if previous is not None and rank < (previous["created_at"], previous["expires_at"]):
            continue
        best[payload["pool_pubkey"]] = payload
    return {
        pubkey: ResolvedListing(
            pubkey=pubkey,
            name=row["name"],
            host=row["pool_host"],
            port=int(row["pool_port"]),
            block_tag=row["block_tag"],
            prime_pubkey=row["prime_pubkey"],
            prime_tag=row["prime_tag"],
            stats_url=row["stats_url"],
            removed=bool(row["removed"]),
            created_at=int(row["created_at"]),
        )
        for pubkey, row in best.items()
    }


def _listing_matches(row, listing):
    return (
        not listing.removed
        and row["pool_host"] == listing.host
        and int(row["pool_port"]) == int(listing.port)
        and row["block_tag"] == listing.block_tag
        and row["prime_pubkey"] == listing.prime_pubkey
        and row["prime_tag"] == listing.prime_tag
    )


def normalize_relays(values):
    """User-typed ws:// and wss:// URLs, in order, without duplicates."""
    from urllib.parse import urlparse
    relays = []
    seen = set()
    for raw in values or ():
        url = str(raw or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        relays.append(url)
    return relays


@dataclass(frozen=True)
class ResolvedCap:
    pubkey: str
    host: str
    port: int
    block_tag: str
    prime_pubkey: str
    prime_tag: str
    receive: bool
    percent: float | None
    capacity_th: float
    consistent: bool

    @property
    def charge_tag(self):
        return self.prime_tag or self.block_tag


def _inconsistent_cap(pubkey, listing):
    return ResolvedCap(
        pubkey=pubkey,
        host=listing.host,
        port=int(listing.port),
        block_tag=listing.block_tag,
        prime_pubkey=listing.prime_pubkey,
        prime_tag=listing.prime_tag,
        receive=False,
        percent=None,
        capacity_th=0.0,
        consistent=False,
    )


def effective_caps(announcements, now, listings=None):
    """Lowest unexpired percent and capacity for each pool pubkey.

    Host, port, and tags must agree across the caps that still count. A
    disagreement marks the cap inconsistent so it cannot be an overflow
    target. When a current listing is passed, a cap that names a different
    host, port, or tag is ignored. The newest listing then wins the same
    day. A listing with no matching cap, or a removed listing, is not a
    target. Pass listings as None when there is no pool list. An empty
    list does not add that rule. Among caps that still count, the lowest
    percent and the lowest positive capacity apply.
    """
    catalog = current_listings(listings, now) if listings is not None else None
    grouped = {}
    for item in announcements or ():
        payload = verify_announcement(item, now)
        if not payload:
            continue
        grouped.setdefault(payload["pool_pubkey"], []).append(payload)
    resolved = {}
    for pubkey, rows in grouped.items():
        listing = catalog.get(pubkey) if catalog is not None else None
        if listing is not None:
            if listing.removed:
                resolved[pubkey] = _inconsistent_cap(pubkey, listing)
                continue
            matched = [row for row in rows if _listing_matches(row, listing)]
            if rows and not matched:
                resolved[pubkey] = _inconsistent_cap(pubkey, listing)
                continue
            rows = matched
        if not rows:
            continue
        identity = {
            (row["pool_host"], row["pool_port"], row["block_tag"], row["prime_pubkey"], row["prime_tag"])
            for row in rows
        }
        receive = all(row["balance_receive"] for row in rows)
        percents = [row["max_percent"] for row in rows if row["max_percent"] is not None]
        percent = min(percents) if percents else None
        capacities = [float(row["capacity_th"]) for row in rows if float(row["capacity_th"]) > 0]
        capacity = min(capacities) if capacities else 0.0
        sample = max(rows, key=lambda row: (row["created_at"], row["expires_at"]))
        resolved[pubkey] = ResolvedCap(
            pubkey=pubkey,
            host=sample["pool_host"],
            port=int(sample["pool_port"]),
            block_tag=sample["block_tag"],
            prime_pubkey=sample["prime_pubkey"],
            prime_tag=sample["prime_tag"],
            receive=receive and percent is not None,
            percent=percent,
            capacity_th=capacity,
            consistent=len(identity) == 1,
        )
    return resolved


def fullness_th(chain_th, self_reported_th):
    """Chain hashrate is the floor. A self-report can only raise it."""
    if chain_th is None or chain_th == "":
        return None
    try:
        chain = float(chain_th)
    except (TypeError, ValueError):
        return None
    if chain < 0:
        return None
    if self_reported_th is None or self_reported_th == "":
        return chain
    try:
        reported = float(self_reported_th)
    except (TypeError, ValueError):
        return chain
    if reported < chain:
        return chain
    return reported


def tighter_percent(pool_percent, hasher_ceiling):
    pool = parse_balance_percent(pool_percent)
    ceiling = parse_balance_percent(hasher_ceiling)
    if pool is None or ceiling is None:
        return None
    return min(pool, ceiling)
