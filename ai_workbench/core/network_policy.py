"""URL policy and public address resolution for built-in network tools."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse


class NetworkPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class NetworkPolicy:
    max_redirects: int = 3
    max_response_bytes: int = 1024 * 1024

    def validate_url(self, url: str, *, resolve_dns: bool = True) -> str:
        value = str(url or "").strip()
        try:
            parsed = urlparse(value)
        except ValueError as exc:
            raise NetworkPolicyError("NETWORK_URL_HOST_FORBIDDEN", "URL contains an invalid host.") from exc
        if parsed.scheme not in {"http", "https"}:
            raise NetworkPolicyError("NETWORK_URL_SCHEME_FORBIDDEN", "Only http and https URLs are allowed.")
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise NetworkPolicyError("NETWORK_URL_HOST_FORBIDDEN", "URL must not include credentials and must include a host.")
        try:
            # Accessing ``port`` validates malformed values such as ``:abc``.
            _ = parsed.port
        except ValueError as exc:
            raise NetworkPolicyError("NETWORK_URL_HOST_FORBIDDEN", "URL contains an invalid port.") from exc
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"}:
            raise NetworkPolicyError("NETWORK_ADDRESS_FORBIDDEN", "Loopback hosts are not allowed.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            try:
                self._validate_address(address)
            except ValueError as exc:
                raise NetworkPolicyError("NETWORK_ADDRESS_FORBIDDEN", f"Address is not public: {host}.") from exc
        elif resolve_dns:
            try:
                infos = socket.getaddrinfo(
                    host,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            except OSError as exc:
                raise NetworkPolicyError("NETWORK_DNS_FAILED", f"DNS resolution failed for {host}.") from exc
            addresses = {info[4][0] for info in infos if info and info[4]}
            if not addresses:
                raise NetworkPolicyError("NETWORK_DNS_FAILED", f"DNS resolution returned no addresses for {host}.")
            for resolved in addresses:
                try:
                    self._validate_address(ipaddress.ip_address(resolved))
                except (ValueError, TypeError) as exc:
                    raise NetworkPolicyError("NETWORK_ADDRESS_FORBIDDEN", f"Resolved address for {host} is not public.") from exc
        return value

    def resolve_url(self, url: str) -> tuple[str, list[str]]:
        """Return validated addresses so HTTP connects to the same DNS answer."""
        value = self.validate_url(url, resolve_dns=False)
        parsed = urlparse(value)
        host = parsed.hostname.rstrip(".")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            return value, [str(address)]
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as exc:
            raise NetworkPolicyError("NETWORK_DNS_FAILED", "DNS resolution failed.") from exc
        addresses = list(dict.fromkeys(info[4][0] for info in infos if info and info[4]))
        if not addresses:
            raise NetworkPolicyError("NETWORK_DNS_FAILED", "DNS resolution returned no addresses.")
        for resolved in addresses:
            try:
                self._validate_address(ipaddress.ip_address(resolved))
            except (ValueError, TypeError) as exc:
                raise NetworkPolicyError("NETWORK_ADDRESS_FORBIDDEN", "A resolved address is not public.") from exc
        return value, addresses

    @staticmethod
    def _validate_address(address: ipaddress._BaseAddress) -> None:
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            address = mapped
        if (
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_unspecified
            or address.is_multicast
            or address.is_reserved
            or not address.is_global
        ):
            raise ValueError("non-public address")

    def validate_redirect_count(self, count: int) -> None:
        if int(count) < 0 or int(count) > self.max_redirects:
            raise NetworkPolicyError("NETWORK_REDIRECT_LIMIT", "Redirect limit exceeded.")

    def validate_response_size(self, size: int) -> None:
        if int(size) < 0 or int(size) > self.max_response_bytes:
            raise NetworkPolicyError("NETWORK_RESPONSE_TOO_LARGE", "Response exceeds the 1 MiB limit.")

    def validate_redirect_chain(self, urls: list[str]) -> list[str]:
        """Validate each URL in a redirect chain, including the first hop."""
        if len(urls) - 1 > self.max_redirects:
            raise NetworkPolicyError("NETWORK_REDIRECT_LIMIT", "Redirect limit exceeded.")
        return [self.validate_url(url) for url in urls]
