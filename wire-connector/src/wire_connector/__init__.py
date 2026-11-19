"""wire-connector: fd-wire <-> knowledge-bench internal connector (P2 组5).

Implemented surface (柏讯贯通, add-knowledge-bench-platform P2 task 5.x):

- ``wire_connector.client.WireClient`` — minimal bearer-auth HTTP client over
  the REAL fd-wire entity endpoints (graph/list/update; recon-verified).
- ``wire_connector.sync`` — fetch_entities: graph sync into the PUBLIC bench
  kernel's promotion machine (bronze landing, wire-key idempotency).
- ``wire_connector.writeback`` — write_back_gold through the real (limited)
  wire surface: ``column_notes["_bench"]`` stamp carrying tier/sensitivity;
  relations fail honestly (no upstream update surface). Promote itself
  (bronze→silver→gold) is human review done on the bench platform, driven by
  the kernel state machine — not by this connector.

Dependency direction: internal → public (``LAW_BENCH_REPO`` sys.path wiring,
VAAS precedent); law-bench NEVER imports this package. See README for the
contract gaps found on the real API.
"""

from .client import WireAuthError, WireClient, WireClientError
from .sync import WIRE_NAMESPACE, import_kernel, sync_graph, sync_now
from .writeback import BENCH_NOTE_KEY, WireWriteback, format_bench_stamp

__all__ = [
    "WIRE_NAMESPACE",
    "WireAuthError",
    "WireClient",
    "WireClientError",
    "BENCH_NOTE_KEY",
    "WireWriteback",
    "format_bench_stamp",
    "import_kernel",
    "sync_graph",
    "sync_now",
]
