"""I/O Bridge adapters: hardware (Home Assistant/MQTT) and software (webhooks)."""

from .base import Adapter, Entity, EntityKind
from .hardware import HardwareAdapter
from .software import SoftwareAdapter

__all__ = ["Adapter", "Entity", "EntityKind", "HardwareAdapter", "SoftwareAdapter"]
