"""Invoice extraction service.

A lean backend that extracts header + line-item data from PDF invoices using a
Databricks-hosted LLM/VLM, behind an async (submit -> poll) API. See README.md and the
design docs under docs/ for the full architecture.
"""
