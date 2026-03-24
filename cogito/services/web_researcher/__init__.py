"""WebResearcher service — builds ConceptGraphV1 directly from web searches.

Internal pipeline:
  1. planner.py    : determine topic headings (from config or LLM inference)
  2. searcher.py   : web-search per heading
  3. aggregator.py : summarise search results per heading → synthetic chunks
  4. synthesizer.py: merge synthetic chunks → ConceptGraphV1
"""
