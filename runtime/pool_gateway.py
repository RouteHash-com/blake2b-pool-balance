"""HTTP client for the DATUM gateway on this same machine.

Posts only Pool Host, port, and pubkey. Reads them back from the status
page on iohzrd pin 7491a509: labels Pool Host, Pool Tag, and Pool Pubkey.
The tag is the pool coinbase tag while connected, otherwise the gateway's
own primary tag. Tests pass a fake opener. This module does not open a
socket unless the caller uses the default opener.
"""
from __future__ import annotations

import time
from html import unescape
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPDigestAuthHandler,
    HTTPPasswordMgrWithDefaultRealm,
    Request,
    build_opener,
)

from pool_chooser import POOL_FORM_KEYS

_REALM = "DATUM Gateway"


class GatewayWriteError(Exception):
    """The gateway refused the pool form or the address was not accepted."""


def normalize_gateway_url(url):
    """http(s) base with no userinfo and no trailing slash."""
    text = str(url or "").strip().rstrip("/")
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("gateway url")
    if parsed.username or parsed.password:
        raise ValueError("gateway url")
    return text


def encode_pool_form(form):
    """Form body limited to the three DATUM pool fields, in POST order."""
    if set(form) != set(POOL_FORM_KEYS):
        raise ValueError("pool form")
    return urlencode([(key, form[key]) for key in POOL_FORM_KEYS]).encode("ascii")


def _cell(html, label):
    import re
    match = re.search(
        r'<td class="label">%s</td>\s*<td[^>]*>\s*(.*?)\s*</td>' % re.escape(label),
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return unescape(match.group(1)).strip()


def parse_gateway_status(html):
    """Host, port, pubkey, and tag from the gateway status table."""
    text = html.decode("utf-8", "replace") if isinstance(html, bytes) else str(html or "")
    found = {
        "host": "",
        "port": "",
        "pubkey": "",
        "tag": None,
    }
    host_cell = _cell(text, "Pool Host:")
    if host_cell and host_cell.upper() != "N/A" and ":" in host_cell:
        host, port = host_cell.rsplit(":", 1)
        found["host"] = host.strip()
        found["port"] = port.strip()
    pubkey = _cell(text, "Pool Pubkey:")
    if pubkey:
        found["pubkey"] = "".join(pubkey.split())
    tag = _cell(text, "Pool Tag:")
    if tag is not None:
        if len(tag) >= 2 and tag[0] == '"' and tag[-1] == '"':
            tag = tag[1:-1]
        tag = tag.strip()
        found["tag"] = tag or None
    return found


def _rejected(body):
    text = body if isinstance(body, bytes) else str(body or "").encode()
    return b"Errors Occurred" in text or b"Configuration - ERROR" in text


def digest_opener(base_url, password):
    """Digest auth as dashboard user admin, realm DATUM Gateway.

    An https address is the StartOS box certificate. This client only talks
    to the operator's own gateway, so that certificate is not checked.
    """
    manager = HTTPPasswordMgrWithDefaultRealm()
    manager.add_password(_REALM, base_url, "admin", password)
    manager.add_password(None, base_url, "admin", password)
    handlers = [HTTPDigestAuthHandler(manager)]
    if urlsplit(base_url).scheme == "https":
        import ssl
        from urllib.request import HTTPSHandler

        handlers.append(HTTPSHandler(context=ssl._create_unverified_context()))
    return build_opener(*handlers)


class DatumGatewayClient:
    """Read status and post the three pool fields. Restart waits out the gateway's own restart."""

    def __init__(self, base_url, password, opener=None, pause=2.0, timeout=10):
        self.base = normalize_gateway_url(base_url)
        self._password = password
        self._opener = opener if opener is not None else digest_opener(self.base, password)
        self.pause = pause
        self.timeout = timeout
        self.last_error = ""

    def __repr__(self):
        return "DatumGatewayClient(%r)" % (self.base,)

    def _exchange(self, method, url, data=None):
        request = Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        response = self._opener.open(request, timeout=self.timeout)
        try:
            payload = response.read()
        finally:
            response.close()
        status = getattr(response, "status", None)
        if status is None:
            status = getattr(response, "code", 0)
        return int(status or 0), payload

    def read(self):
        self.last_error = ""
        try:
            _status, payload = self._exchange("GET", self.base + "/")
        except Exception as error:
            self.last_error = type(error).__name__
            return {}
        return parse_gateway_status(payload)

    def write(self, form):
        payload = encode_pool_form(form)
        status, body = self._exchange("POST", self.base + "/config", payload)
        if status >= 400 or _rejected(body):
            raise GatewayWriteError("gateway rejected the pool form")
        return status

    def restart(self):
        if self.pause:
            time.sleep(self.pause)
