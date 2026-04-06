"""GovernAI Memory module: pluggable memory connector subsystem."""

from governai.memory.connector import MemoryConnector
from governai.memory.models import MemoryEntry, MemoryScope
from governai.memory.dict_connector import DictMemoryConnector
from governai.memory.auditing import AuditingMemoryConnector

__all__ = [
    "MemoryConnector",
    "MemoryEntry",
    "MemoryScope",
    "DictMemoryConnector",
    "AuditingMemoryConnector",
]
