"""Knowledge-bench kernel (domain-neutral).

Kernel of the knowledge-bench platform: typed knowledge units, the four-tier
provenance taxonomy with the ground-truth guard, the domain pack registry, and
the deterministic (data) evaluation channel.

Domain-specific logic lives in domain packs under ``packs/<domain>/``. This
package MUST NOT import from any pack and MUST NOT contain domain-specific
constants (enforced by ``tests/test_kernel_domain_free.py``); adding a new
domain pack SHALL NOT require changes here.
"""
