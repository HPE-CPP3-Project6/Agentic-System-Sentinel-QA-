"""Sidecar tools — static analysis, regression diff, etc.

These run ALONGSIDE the LangGraph pipeline (separate metadata buckets) and
never feed the Healer. They add a second evidence dimension (static) next to
the pipeline's dynamic API testing.
"""
