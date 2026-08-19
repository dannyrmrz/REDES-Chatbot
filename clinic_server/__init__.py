"""Our own MCP server: appointment booking for a medical clinic.

* :mod:`clinic_server.store`  -- doctors, availability and appointments
* :mod:`clinic_server.server` -- the MCP/JSON-RPC layer over stdio
"""

from .server import TOOLS, ClinicServer
from .store import ClinicError, ClinicStore

__all__ = ["ClinicServer", "TOOLS", "ClinicStore", "ClinicError"]
