"""Canonical signed events for local-first RouteHash peer directories."""
import base64
import binascii
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from coincurve import PrivateKey, PublicKeyXOnly
from bip_utils.bech32.bech32 import Bech32Decoder, Bech32Encoder


EVENT_KIND = "routehash.listing.v1"
REVOCATION_KIND = "routehash.signer-revocation.v1"
NOSTR_LISTING_KIND = 30078
NOSTR_REVOCATION_KIND = 30079


def _encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _public_key_hex(key):
    return key.public_key_xonly.format().hex()


def generate_identity():
    private_key = PrivateKey()
    return {
        "private_key": _encode(private_key.secret),
        "public_key": _public_key_hex(private_key),
    }


def public_key_from_private(private_key):
    return _public_key_hex(PrivateKey(_decode(private_key)))


def nostr_hex_to_npub(hex_key):
    text = str(hex_key or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError("Nostr hex public key must be 64 characters")
    return Bech32Encoder.Encode("npub", bytes.fromhex(text))


def normalize_nostr_pubkey(value):
    """Accept npub1… or 64-char hex. Return (hex, npub) or raise ValueError."""
    text = str(value or "").strip()
    if text.lower().startswith("nostr:"):
        text = text[6:]
    if re.fullmatch(r"[0-9a-fA-F]{64}", text):
        hex_key = text.lower()
        return hex_key, nostr_hex_to_npub(hex_key)
    if text.lower().startswith("npub1"):
        try:
            decoded = Bech32Decoder.Decode("npub", text)
        except Exception as exc:
            raise ValueError("that npub could not be decoded") from exc
        if not decoded or len(decoded) != 32:
            raise ValueError("npub must decode to a 32-byte Nostr public key")
        hex_key = decoded.hex()
        return hex_key, nostr_hex_to_npub(hex_key)
    raise ValueError("paste a Nostr public key as npub1… or 64-character hex")


def canonical_event(kind, payload, created_at=None, expires_at=None, tags=None):
    created_value = created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    created = int(datetime.fromisoformat(created_value.replace("Z", "+00:00")).timestamp())
    expires_value = expires_at or (datetime.fromtimestamp(created, timezone.utc) + timedelta(hours=24)).isoformat()
    expires = int(datetime.fromisoformat(expires_value.replace("Z", "+00:00")).timestamp())
    nostr_kind = NOSTR_LISTING_KIND if kind == EVENT_KIND else NOSTR_REVOCATION_KIND
    content = json.dumps({"routehash_kind": kind, "expires_at": expires, "payload": payload}, sort_keys=True, separators=(",", ":"))
    event_tags = [["expiration", str(expires)]] + list(tags or [])
    return {"pubkey": "", "created_at": created, "kind": nostr_kind,
            "tags": event_tags, "content": content}


def sign_event(event, private_key):
    key = PrivateKey(_decode(private_key))
    signed = dict(event)
    signed["pubkey"] = _public_key_hex(key)
    serialized = json.dumps([0, signed["pubkey"], signed["created_at"], signed["kind"], signed["tags"], signed["content"]], separators=(",", ":"))
    signed["id"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    signed["sig"] = key.sign_schnorr(bytes.fromhex(signed["id"])).hex()
    return signed


def verify_event(event, now=None, max_future_seconds=300, revoked_signers=None):
    try:
        signer = event["pubkey"]
        if signer in set(revoked_signers or ()):
            return False
        serialized = json.dumps([0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]], separators=(",", ":"))
        if event.get("id") != hashlib.sha256(serialized.encode("utf-8")).hexdigest():
            return False
        PublicKeyXOnly(bytes.fromhex(signer)).verify(bytes.fromhex(event["sig"]), bytes.fromhex(event["id"]))
        content = json.loads(event["content"])
        if content.get("routehash_kind") not in {EVENT_KIND, REVOCATION_KIND}:
            return False
        expiration_tags = [tag[1] for tag in event.get("tags", [])
                           if isinstance(tag, list) and len(tag) >= 2 and tag[0] == "expiration"]
        if len(expiration_tags) != 1 or int(expiration_tags[0]) != int(content["expires_at"]):
            return False
        d_tags = [tag[1] for tag in event.get("tags", [])
                  if isinstance(tag, list) and len(tag) >= 2 and tag[0] == "d"]
        payload = content.get("payload")
        expected_d = payload.get("listing_id") if content["routehash_kind"] == EVENT_KIND else payload.get("revoked_signer")
        if len(d_tags) != 1 or str(d_tags[0]) != str(expected_d):
            return False
        current = now or datetime.now(timezone.utc)
        created_at = datetime.fromtimestamp(int(event["created_at"]), timezone.utc)
        expires_at = datetime.fromtimestamp(int(content["expires_at"]), timezone.utc)
        if created_at > current + timedelta(seconds=max_future_seconds) or expires_at <= current or expires_at <= created_at:
            return False
        return True
    except (binascii.Error, KeyError, TypeError, ValueError, OverflowError, json.JSONDecodeError):
        return False


def verify_trusted_event(event, trusted_signers, now=None, max_future_seconds=300):
    """Verify an event only when its public key is in the supplied active trust set."""
    trusted = {str(signer).strip().lower() for signer in (trusted_signers or ())}
    public_key = str(event.get("pubkey", "")).strip().lower()
    if public_key not in trusted:
        return False
    return verify_event(event, now=now, max_future_seconds=max_future_seconds)


def listing_directory_fingerprint(listing):
    payload = {
        "listing_id": int(listing["listing_id"]),
        "rig_id": int(listing["rig_id"]),
        "algo": str(listing["algo"]),
        "hashrate_th": float(listing["hashrate_th"]),
        "price_btc_th_day": float(listing["price_btc_th_day"]),
        "min_hours": float(listing["min_hours"]),
        "endpoint": str(listing.get("endpoint", "")),
        "is_active": bool(listing.get("is_active", True)),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def listing_event(listing, created_at=None, expires_at=None):
    payload = {
        "listing_id": int(listing["listing_id"]),
        "rig_id": int(listing["rig_id"]),
        "algo": str(listing["algo"]),
        "hashrate_th": float(listing["hashrate_th"]),
        "price_btc_th_day": float(listing["price_btc_th_day"]),
        "min_hours": float(listing["min_hours"]),
        "endpoint": str(listing.get("endpoint", "")),
    }
    return canonical_event(
        EVENT_KIND,
        payload,
        created_at=created_at,
        expires_at=expires_at,
        tags=[["d", str(payload["listing_id"])]],
    )


def revocation_event(revoked_signer, reason, created_at=None, expires_at=None):
    """Create a signed event stating that a public signer must no longer be trusted."""
    return canonical_event(
        REVOCATION_KIND,
        {"revoked_signer": str(revoked_signer), "reason": str(reason)},
        created_at=created_at,
        expires_at=expires_at,
        tags=[["d", str(revoked_signer)]],
    )
