"""
offline_first.py — Offline First Engine (FASE 10, v4.0 FREE-FIRST).

Si no hay internet, el sistema debe seguir funcionando.

Modos de operación:
  - ONLINE:  Funcionamiento normal con todos los proveedores
  - DEGRADED: Sin internet, usar heurísticas + memoria + caché
  - OFFLINE:  Sin internet ni caché, solo heurísticas básicas

Nunca romper el flujo del usuario.
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


class ConnectionStatus(Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


@dataclass
class ConnectionCheck:
    """Resultado de una verificación de conexión."""
    status: ConnectionStatus
    latency_ms: float = 0.0
    details: str = ""


# Hosts a verificar para determinar conectividad
_CHECK_HOSTS = [
    ("google.com", 80),
    ("cloudflare.com", 80),
]

# Cache de estado de conexión
_last_check: Optional[ConnectionCheck] = None
_last_check_time: float = 0.0
_CACHE_TTL = 30  # segundos


class ConnectionMonitor:
    """
    Monitorea la conectividad a internet.

    Usa múltiples hosts para determinar el estado real.
    Cachea el resultado por 30 segundos para no verificar en cada llamada.

    Usage:
        monitor = ConnectionMonitor()
        status = monitor.get_status()
        if status == ConnectionStatus.OFFLINE:
            # usar solo heurísticas
        elif status == ConnectionStatus.DEGRADED:
            # usar caché + memoria
        else:
            # usar IA normal
    """

    def get_status(self, force_check: bool = False) -> ConnectionStatus:
        """
        Obtiene el estado actual de conectividad.

        Args:
            force_check: Si True, fuerza una verificación aunque esté en caché.

        Returns:
            ConnectionStatus actual.
        """
        global _last_check, _last_check_time

        now = time.time()
        if not force_check and _last_check and (now - _last_check_time) < _CACHE_TTL:
            return _last_check.status

        result = self._check_connectivity()
        _last_check = result
        _last_check_time = now
        return result.status

    def _check_connectivity(self) -> ConnectionCheck:
        """Verifica conectividad real contra múltiples hosts."""
        t0 = time.perf_counter()

        # Usar hosts configurados o defaults
        hosts = getattr(settings, "AI_CONNECTIVITY_HOSTS", _CHECK_HOSTS)

        for host, port in hosts:
            try:
                sock_t0 = time.perf_counter()
                sock = socket.create_connection((host, port), timeout=3)
                sock.close()
                latency = (time.perf_counter() - sock_t0) * 1000
                return ConnectionCheck(
                    status=ConnectionStatus.ONLINE,
                    latency_ms=latency,
                    details=f"Conexión exitosa a {host}:{port} ({latency:.0f}ms)",
                )
            except (socket.timeout, OSError):
                continue

        # Intentar DNS resolution como fallback
        for host, _ in hosts:
            try:
                sock_t0 = time.perf_counter()
                socket.getaddrinfo(host, 80, socket.AF_INET, socket.SOCK_STREAM, timeout=2)
                latency = (time.perf_counter() - sock_t0) * 1000
                return ConnectionCheck(
                    status=ConnectionStatus.DEGRADED,
                    latency_ms=latency,
                    details=f"DNS resuelve pero conexión falla ({host})",
                )
            except (socket.gaierror, OSError):
                continue

        elapsed = (time.perf_counter() - t0) * 1000
        return ConnectionCheck(
            status=ConnectionStatus.OFFLINE,
            latency_ms=elapsed,
            details=f"Sin conexión después de verificar {len(hosts)} host(s)",
        )

    def force_check(self) -> ConnectionStatus:
        """Fuerza una verificación de conectividad (ignora caché)."""
        return self.get_status(force_check=True)


# ======================================================================
# OfflineFirstEngine
# ======================================================================

class OfflineFirstEngine:
    """
    Engine principal de operación offline-first.

    Decide automáticamente el modo de operación basado en
    la conectividad actual y aplica las restricciones correspondientes.

    Usage:
        engine = OfflineFirstEngine()
        mode = engine.get_mode()
        if mode.can_use_ai:
            # llamar IA
        else:
            # usar heurísticas
    """

    def __init__(self):
        self.monitor = ConnectionMonitor()

    def get_mode(self) -> "OperationMode":
        """
        Obtiene el modo de operación actual.

        Returns:
            OperationMode con restricciones y sugerencias.
        """
        status = self.monitor.get_status()
        return OperationMode(status)

    def can_use_providers(self) -> bool:
        """¿Puede usar proveedores AI externos?"""
        return self.monitor.get_status() == ConnectionStatus.ONLINE

    def can_use_cache(self) -> bool:
        """¿Puede usar caché (siempre disponible, es local)?"""
        return True

    def can_use_memory(self) -> bool:
        """¿Puede usar memoria (siempre disponible, es local)?"""
        return True

    def can_use_heuristics(self) -> bool:
        """¿Puede usar heurísticas (siempre disponible)?"""
        return True

    def get_status_string(self) -> str:
        """Obtiene descripción del estado para logging/dashboard."""
        status = self.monitor.get_status()
        mode = OperationMode(status)
        return (
            f"[{status.value.upper()}] "
            f"{mode.description} | "
            f"AI={'✓' if mode.can_use_ai else '✗'} | "
            f"Cache={'✓' if mode.can_use_cache else '✗'} | "
            f"Heurísticas={'✓' if mode.can_use_heuristics else '✗'}"
        )


@dataclass
class OperationMode:
    """Modo de operación basado en conectividad."""
    status: ConnectionStatus

    def __post_init__(self):
        if self.status == ConnectionStatus.ONLINE:
            self.can_use_ai = True
            self.can_use_cache = True
            self.can_use_heuristics = True
            self.can_use_memory = True
            self.description = "Funcionamiento normal — todos los recursos disponibles"
            self.recommendation = "Usar ProviderRouter para seleccionar el mejor proveedor"
        elif self.status == ConnectionStatus.DEGRADED:
            self.can_use_ai = False
            self.can_use_cache = True
            self.can_use_heuristics = True
            self.can_use_memory = True
            self.description = "Modo degradado — sin conexión a proveedores AI, usando caché + heurísticas"
            self.recommendation = "Usar resultados en caché. Si no hay caché, usar heurísticas."
        else:
            self.can_use_ai = False
            self.can_use_cache = True
            self.can_use_heuristics = True
            self.can_use_memory = True
            self.description = "Modo offline — sin internet, usando solo recursos locales"
            self.recommendation = "Usar heurísticas + memoria local. Datos en caché disponibles."


_default_offline: Optional[OfflineFirstEngine] = None


def get_offline_first_engine() -> OfflineFirstEngine:
    global _default_offline
    if _default_offline is None:
        _default_offline = OfflineFirstEngine()
    return _default_offline
