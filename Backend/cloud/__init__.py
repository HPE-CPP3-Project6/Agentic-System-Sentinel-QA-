"""Cloud-runtime helpers — wired only inside the container/Cloud Run Job.

Nothing here is imported by the LangGraph agents; these modules exist to
bootstrap the target app, capture credentials, and publish artifacts when
Sentinel-QA runs in a managed environment.
"""
