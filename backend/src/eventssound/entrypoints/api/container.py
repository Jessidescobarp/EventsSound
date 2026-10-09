"""Composition root: the only place where concrete adapters are bound to ports.

Extension point: later phases register the ``LlmProvider`` port here (choosing an
adapter from settings, or a replay provider in tests). No LLM code exists yet.
"""
