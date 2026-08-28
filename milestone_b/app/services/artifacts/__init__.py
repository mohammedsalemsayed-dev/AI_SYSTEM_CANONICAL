"""Artifact & version tracking (MILESTONE_P_PLAN.md).

Content-addressed blob store + a version chain per logical artifact. Canonical
(§11.3): never auto-deleted; `archive_before` marks, it does not remove.
"""
