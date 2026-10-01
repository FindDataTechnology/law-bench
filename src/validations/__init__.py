"""Standalone compliance-validation layer for law-bench.

Reads generator rules (via ``src.clauses.generator_import``) into the
``type_validations`` table and evaluates assembled drafts/slots against
those legal hard limits. NOT wired into generation/assembly — a separate
post-hoc compliance check.
"""
