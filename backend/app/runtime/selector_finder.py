"""
Enhanced selector finding strategy that prioritizes automated approaches
before requesting user input.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

LOGGER = logging.getLogger("tekno.phantom.selector_finder")


class SelectorFindingStrategy:
    """
    Implements a multi-stage selector finding strategy:
    1. Try with selector memory from previous successful runs
    2. Try with LLM-generated candidates based on page content
    3. Try with live page inspection (visual matching)
    4. Only ask user if all automated approaches fail
    """

    def __init__(
        self,
        selector_memory: Any,
        browser_client: Any,
        llm_client: Any | None = None,
    ):
        self.selector_memory = selector_memory
        self.browser_client = browser_client
        self.llm_client = llm_client

    async def find_selector(
        self,
        raw_selector: str,
        step_type: str,
        run_domain: str | None,
        selector_profile: dict[str, list[str]],
        test_data: dict[str, Any],
        text_hint: str | None = None,
        executor: Any | None = None,
    ) -> tuple[str, bool]:
        """
        Try to find a working selector automatically.
        
        Returns:
            (selector, was_user_input) - The selector string and whether it came from user
        """
        attempts = []

        # Stage 1: Memory candidates (previous successful runs)
        if executor and hasattr(executor, '_memory_candidates'):
            memory_candidates = executor._memory_candidates(run_domain, step_type, raw_selector)
            if memory_candidates:
                LOGGER.info(
                    f"Stage 1 (Memory): Found {len(memory_candidates)} candidates from selector memory"
                )
                attempts.append(("memory", memory_candidates))
            else:
                LOGGER.debug(f"Stage 1 (Memory): No candidates found in selector memory for '{raw_selector}'")

        # Stage 2: Profile candidates (predefined patterns)
        if executor and hasattr(executor, '_selector_candidates'):
            profile_candidates = executor._selector_candidates(
                raw_selector,
                step_type,
                selector_profile,
                test_data,
                run_domain,
                text_hint=text_hint,
            )
            if profile_candidates:
                # Remove memory candidates already in profile to avoid duplication
                memory_set = set()
                if attempts and attempts[0][0] == "memory":
                    memory_set = set(attempts[0][1][:5])

                unique_profile = [c for c in profile_candidates if c not in memory_set]
                if unique_profile:
                    LOGGER.info(
                        f"Stage 2 (Profile): Found {len(unique_profile)} unique profile candidates"
                    )
                    attempts.append(("profile", unique_profile[:10]))

        # Stage 3: Live page inspection (visual matching)
        if executor and hasattr(executor, '_live_page_selector_candidates'):
            try:
                live_candidates = await executor._live_page_selector_candidates(
                    raw_selector=raw_selector,
                    step_type=step_type,
                    text_hint=text_hint,
                )
                if live_candidates:
                    # Filter out candidates already tried
                    all_tried = set()
                    for _, cands in attempts:
                        all_tried.update(cands)

                    unique_live = [c for c in live_candidates if c not in all_tried]
                    if unique_live:
                        LOGGER.info(
                            f"Stage 3 (Live Page): Found {len(unique_live)} candidates from page inspection"
                        )
                        attempts.append(("live_page", unique_live[:6]))
            except Exception as e:
                LOGGER.debug(f"Stage 3 (Live Page) failed: {e}")

        # Flatten all candidates in priority order
        all_candidates = []
        for source, candidates in attempts:
            all_candidates.extend(candidates)

        return all_candidates, False

    def get_last_resort_candidates(
        self,
        raw_selector: str,
        step_type: str,
        executor: Any | None = None,
    ) -> list[str]:
        """Get last resort selector variants as fallback."""
        if not executor or not hasattr(executor, '_derive_selector_variants'):
            return []

        try:
            variants = executor._derive_selector_variants(raw_selector, step_type)
            LOGGER.info(f"Last resort: Generated {len(variants)} selector variants")
            return variants
        except Exception as e:
            LOGGER.warning(f"Last resort variant generation failed: {e}")
            return []
