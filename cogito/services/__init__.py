"""Analyst service — processes ChunksV1 → ConceptGraphV1.

Internal pipeline:
  1. extractor.py  : per-chunk concept extraction (→ list[dict])
  2. synthesizer.py: merge chunk analyses → ConceptGraphV1
"""
