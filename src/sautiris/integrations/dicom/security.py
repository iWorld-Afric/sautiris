"""DICOM Association Security — AE title whitelist, connection limiting, rate limiting.

Issue #17: Provides EVT_REQUESTED / EVT_RELEASED / EVT_ABORTED handlers
that enforce AE title whitelists, per-IP connection limits, and
per-IP request rate limits.
"""

from __future__ import annotations

import fnmatch
import time
from collections import defaultdict
from threading import Lock
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pynetdicom.events import Event

logger = structlog.get_logger(__name__)


class DicomAssociationSecurity:
    """Security policy enforcer for DICOM associations.

    Features:
    - AE title whitelist with fnmatch wildcard support (``None`` = allow all).
    - Maximum concurrent connections per IP address.
    - Per-IP rate limiting (requests per minute).

    Usage::

        security = DicomAssociationSecurity(
            ae_whitelist=["CT_SCANNER_*", "MR_1"],
            max_connections_per_ip=5,
            rate_limit_per_minute=60,
        )

        handlers = [
            (evt.EVT_REQUESTED, security.handle_association_request),
            (evt.EVT_RELEASED, security.handle_association_released),
            (evt.EVT_ABORTED, security.handle_association_aborted),
            ...
        ]
    """

    def __init__(
        self,
        ae_whitelist: list[str] | None = None,
        max_connections_per_ip: int = 10,
        rate_limit_per_minute: int = 60,
    ) -> None:
        # None = disabled (allow all); empty list = deny all
        self._ae_whitelist = ae_whitelist
        self._max_connections = max_connections_per_ip
        self._rate_limit = rate_limit_per_minute
        self._lock = Lock()
        self._active_connections: dict[str, int] = defaultdict(int)
        # Maps IP → list of monotonic timestamps for rate window
        self._request_times: dict[str, list[float]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Public predicate methods (easy to unit-test without pynetdicom)
    # ------------------------------------------------------------------

    def is_ae_allowed(self, calling_ae_title: str) -> bool:
        """Return True if *calling_ae_title* is permitted by the whitelist."""
        if self._ae_whitelist is None:
            return True
        ae = calling_ae_title.strip()
        return any(fnmatch.fnmatch(ae, pattern) for pattern in self._ae_whitelist)

    def check_connection_limit(self, ip_address: str) -> bool:
        """Return True if *ip_address* has not reached the concurrent connection limit."""
        with self._lock:
            return self._active_connections[ip_address] < self._max_connections

    def acquire_connection(self, ip_address: str) -> bool:
        """Acquire a connection slot for *ip_address*. Returns True if granted."""
        with self._lock:
            if self._active_connections[ip_address] >= self._max_connections:
                return False
            self._active_connections[ip_address] += 1
            return True

    def release_connection(self, ip_address: str) -> None:
        """Release a previously acquired connection slot."""
        with self._lock:
            if self._active_connections[ip_address] > 0:
                self._active_connections[ip_address] -= 1
                if self._active_connections[ip_address] == 0:
                    # Evict zero-count entries to bound memory under IP sweeps
                    del self._active_connections[ip_address]

    # Evict stale IP entries from the rate-limit window dict when it exceeds this
    # size.  Prevents OOM under sustained IP-sweep attacks.
    _MAX_RATE_KEYS: int = 50_000

    def check_rate_limit(self, ip_address: str) -> bool:
        """Return True if *ip_address* is within the per-minute rate limit.

        Also records this request in the sliding window.
        """
        now = time.monotonic()
        window_start = now - 60.0
        with self._lock:
            existing = self._request_times.get(ip_address, [])
            active = [t for t in existing if t > window_start]
            if len(active) >= self._rate_limit:
                # Update in place; evict key entirely if window is empty
                if active:
                    self._request_times[ip_address] = active
                else:
                    self._request_times.pop(ip_address, None)
                return False
            active.append(now)
            self._request_times[ip_address] = active
            # Periodic eviction of stale keys to bound memory under IP sweeps
            if len(self._request_times) > self._MAX_RATE_KEYS:
                stale = [
                    ip
                    for ip, times in self._request_times.items()
                    if not any(t > window_start for t in times)
                ]
                for ip in stale:
                    del self._request_times[ip]
            return True

    # ------------------------------------------------------------------
    # pynetdicom EVT_* handlers
    # ------------------------------------------------------------------

    def handle_association_request(self, event: Event) -> None:
        """EVT_REQUESTED handler — reject disallowed associations.

        Rejects by calling ``event.assoc.acse.send_reject()`` when policy
        is violated. Pynetdicom treats any exception from this handler as a
        reason to abort the association, so we raise RuntimeError on rejection.
        """
        calling_ae = ""
        ip = ""
        try:
            calling_ae = str(event.assoc.requestor.ae_title).strip()
            ip = str(event.assoc.requestor.address)
        except Exception:
            logger.error(
                "dicom.security.association_request_extraction_failed",
                exc_info=True,
                msg="Could not extract AE title/IP from association — rejecting for safety",
            )
            raise RuntimeError(
                "Failed to extract AE title/IP from DICOM association — rejecting"
            ) from None

        if not self.is_ae_allowed(calling_ae):
            logger.warning(
                "dicom.security.ae_rejected",
                calling_ae=calling_ae,
                ip=ip,
            )
            raise RuntimeError("Association rejected")

        if not self.check_rate_limit(ip):
            logger.warning("dicom.security.rate_limit_exceeded", ip=ip)
            raise RuntimeError("Association rejected")

        if not self.acquire_connection(ip):
            logger.warning("dicom.security.connection_limit_exceeded", ip=ip)
            raise RuntimeError("Association rejected")

        logger.info("dicom.security.association_accepted", calling_ae=calling_ae, ip=ip)

    def handle_association_released(self, event: Event) -> None:
        """EVT_RELEASED handler — release a connection slot."""
        ip = ""
        calling_ae = "unknown"
        try:
            ip = str(event.assoc.requestor.address)
            calling_ae = str(event.assoc.requestor.ae_title).strip()
        except Exception:
            logger.error("dicom.security.release_ip_extraction_failed", exc_info=True)
        if ip:
            self.release_connection(ip)
        else:
            logger.error(
                "dicom.security.connection_slot_leaked",
                msg="Could not release connection slot — IP address unknown",
            )
        logger.info("dicom.security.association_released", calling_ae=calling_ae, ip=ip)

    def handle_association_aborted(self, event: Event) -> None:
        """EVT_ABORTED handler — release a connection slot on abort."""
        ip = ""
        calling_ae = "unknown"
        try:
            ip = str(event.assoc.requestor.address)
            calling_ae = str(event.assoc.requestor.ae_title).strip()
        except Exception:
            logger.error("dicom.security.abort_ip_extraction_failed", exc_info=True)
        if ip:
            self.release_connection(ip)
        else:
            logger.error(
                "dicom.security.connection_slot_leaked",
                msg="Could not release connection slot on abort — IP address unknown",
            )
        logger.info("dicom.security.association_aborted", calling_ae=calling_ae, ip=ip)

    @property
    def active_connections(self) -> dict[str, int]:
        """Snapshot of current active connection counts per IP (for monitoring)."""
        with self._lock:
            return dict(self._active_connections)
