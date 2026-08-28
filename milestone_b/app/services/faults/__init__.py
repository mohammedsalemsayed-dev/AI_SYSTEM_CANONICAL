"""Fault-injection toolkit (MILESTONE_Q_PLAN.md).

Thin wrappers over the injectable dependencies that raise / delay / corrupt on a
schedule, plus a log-append interrupt hook. A production build attaches none of
this — it exists to prove every induced failure lands safely.
"""
