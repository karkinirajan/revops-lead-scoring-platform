"""Checks on URLs that a user supplies and the server then calls (webhook targets, a Salesforce instance).

Calling a user-supplied URL from the server lets the user reach what the server can reach: cloud metadata endpoints, the database, Redis, internal admin pages.
A target is therefore refused unless it is an http(s) URL without embedded credentials whose host resolves only to public addresses. The check is repeated
immediately before each delivery (a name can be re-pointed after it was accepted); redirects are never followed by the callers. A DNS answer that changes
between the check and the connection is not defended against here.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

from app.config import get_settings


class UnsafeUrlError(ValueError):
    """The URL may not be called; the message says why and is safe to show to the user."""


def _scheme_and_host(url: str, *, allow_http: bool) -> tuple[str, str]:
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for a port that is not a number or out of range
    except ValueError as exc:
        raise UnsafeUrlError("not a valid URL") from exc
    allowed = {"https", "http"} if allow_http else {"https"}
    if parts.scheme not in allowed:
        raise UnsafeUrlError("the URL must use " + (" or ".join(sorted(allowed))))
    if not host:
        raise UnsafeUrlError("the URL has no host")
    if parts.username or parts.password:
        raise UnsafeUrlError("the URL may not contain a user name or password")
    return parts.scheme, host


# IPv6 ranges that carry an IPv4 address inside them: NAT64 (the well-known and the local-use prefix), 6to4 and Teredo. Python calls most of them global, but on a
# network with a translator the connection ends at the embedded IPv4 address, which may be an internal one. No webhook receiver needs to be reachable only that way.
_TRANSLATION_NETWORKS = tuple(
    ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
)


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)  # scoped IPv6 addresses ("fe80::1%eth0", as getaddrinfo reports them) parse too
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped  # an IPv4 address written as IPv6 is judged as the IPv4 address
        elif any(ip in network for network in _TRANSLATION_NETWORKS):
            return False
    return ip.is_global and not ip.is_multicast


def ensure_public_url(url: str, *, allow_private: bool | None = None, allow_http: bool | None = None) -> str:
    """Return `url` if it may be called, else raise UnsafeUrlError. By default the settings decide whether private addresses and plain http are allowed."""
    settings = get_settings()
    url = url.strip()  # what is checked is what is returned, and so what is stored and called
    if allow_private is None:
        allow_private = settings.webhook_allow_private_targets
    if allow_http is None:
        allow_http = settings.webhook_allow_private_targets
    _, host = _scheme_and_host(url, allow_http=allow_http)
    if allow_private:
        return url
    try:
        resolved = {str(info[4][0]) for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise UnsafeUrlError("the host name does not resolve") from exc
    if not resolved or not all(_is_public(address) for address in resolved):
        raise UnsafeUrlError("the host resolves to a private, loopback, link-local or otherwise non-public address")
    return url


def ensure_salesforce_instance_url(url: str) -> str:
    """A Salesforce instance URL must be https on one of the configured Salesforce domains (it receives the stored access token)."""
    _, host = _scheme_and_host(url, allow_http=False)
    suffixes = tuple(s.strip().lower() for s in get_settings().salesforce_allowed_domains.split(",") if s.strip())
    host = host.rstrip(".")  # urlsplit has already lower-cased it
    if not any(host.endswith(suffix if suffix.startswith(".") else "." + suffix) for suffix in suffixes):
        raise UnsafeUrlError("the host is not a Salesforce domain (" + ", ".join(suffixes) + ")")
    return url.rstrip("/")
