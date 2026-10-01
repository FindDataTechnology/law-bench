"""law-api client (integrate-law-semantic-search).

law-bench stays vector-free: embedding models, dimensions, and Qdrant live
behind the law-api gateway (APISIX key-auth + Lago metering). This module is
the ONLY place that talks to it.

Degradation contract: any failure (disabled, network, timeout, non-2xx
including 401/429, unexpected payload) is logged and returned as ``[]`` /
``None`` — never raised into callers. The drafting pipeline must be able to
complete a run with the gateway down.
"""
