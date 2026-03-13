"""LLM-powered breakage detection and repair."""

from __future__ import annotations

import json

from site2cli.config import get_config
from site2cli.discovery.analyzer import TrafficAnalyzer
from site2cli.discovery.capture import TrafficCapture
from site2cli.models import EndpointInfo, HealthStatus
from site2cli.registry import SiteRegistry


class SelfHealer:
    """Detects API breakage and attempts auto-repair using LLM."""

    def __init__(self, registry: SiteRegistry) -> None:
        self._registry = registry
        self._config = get_config()

    async def diagnose_and_repair(
        self, domain: str, action_name: str
    ) -> dict:
        """Attempt to diagnose and repair a broken action.

        Steps:
        1. Re-capture traffic from the site
        2. Compare with stored endpoint patterns
        3. Use LLM to identify what changed
        4. Update the endpoint if a fix is found

        Returns:
            Dict with diagnosis and repair status.
        """
        site = self._registry.get_site(domain)
        if not site:
            return {"status": "error", "message": f"Site {domain} not found"}

        action = None
        for a in site.actions:
            if a.name == action_name:
                action = a
                break
        if not action:
            return {"status": "error", "message": f"Action {action_name} not found"}

        # Re-capture traffic
        capture = TrafficCapture(target_domain=domain)
        try:
            await capture.capture_page_traffic(f"https://{domain}", duration_seconds=15)
        except Exception as e:
            return {"status": "error", "message": f"Failed to capture traffic: {e}"}

        api_exchanges = capture.get_api_exchanges()
        if not api_exchanges:
            return {
                "status": "no_traffic",
                "message": "No API traffic captured. Site may have changed significantly.",
            }

        # Analyze new traffic
        analyzer = TrafficAnalyzer(api_exchanges)
        new_endpoints = analyzer.extract_endpoints()

        if not new_endpoints:
            return {"status": "no_endpoints", "message": "No endpoints found in new traffic."}

        # Compare old and new
        old_endpoint = action.endpoint
        if not old_endpoint:
            return {"status": "no_old_endpoint", "message": "No previous endpoint to compare."}

        # Use LLM to match old endpoint to new endpoints
        match = await self._llm_match_endpoint(old_endpoint, new_endpoints)
        if not match:
            return {
                "status": "no_match",
                "message": "Could not find a matching endpoint in new traffic.",
                "new_endpoints": [ep.path_pattern for ep in new_endpoints],
            }

        # Update the action with the new endpoint
        action.endpoint = match
        action.health = HealthStatus.HEALTHY
        self._registry.add_site(site)

        return {
            "status": "repaired",
            "message": f"Updated endpoint from {old_endpoint.path_pattern} to {match.path_pattern}",
            "old_path": old_endpoint.path_pattern,
            "new_path": match.path_pattern,
        }

    async def _llm_match_endpoint(
        self, old: EndpointInfo, candidates: list[EndpointInfo]
    ) -> EndpointInfo | None:
        """Use LLM to find the best match for an old endpoint among new candidates."""
        config = self._config
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=config.llm.get_api_key())
        except (ImportError, ValueError):
            # Fallback: simple path similarity matching
            return self._simple_match(old, candidates)

        old_summary = {
            "method": old.method,
            "path": old.path_pattern,
            "description": old.description,
            "params": [p.name for p in old.parameters],
        }
        candidate_summaries = [
            {
                "index": i,
                "method": ep.method,
                "path": ep.path_pattern,
                "params": [p.name for p in ep.parameters],
            }
            for i, ep in enumerate(candidates)
        ]

        prompt = (
            "An API endpoint has changed. Find the best match"
            " for the old endpoint among the new candidates.\n\n"
            f"Old endpoint:\n{json.dumps(old_summary, indent=2)}\n\n"
            "New candidate endpoints:\n"
            f"{json.dumps(candidate_summaries, indent=2)}\n\n"
            "Which candidate (by index) is most likely the"
            " same endpoint after a change?\n"
            "Respond with ONLY a JSON object: "
            '{{"index": <number>, "confidence":'
            ' "high"|"medium"|"low", "reason": "..."}}\n'
            "If none match, respond: "
            '{{"index": -1, "confidence": "none",'
            ' "reason": "..."}}'
        )

        try:
            response = client.messages.create(
                model=config.llm.model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            import re
            text = response.content[0].text
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                idx = result.get("index", -1)
                if 0 <= idx < len(candidates) and result.get("confidence") != "none":
                    return candidates[idx]
        except Exception:
            pass

        return self._simple_match(old, candidates)

    def _simple_match(
        self, old: EndpointInfo, candidates: list[EndpointInfo]
    ) -> EndpointInfo | None:
        """Simple matching based on method and path similarity."""
        best = None
        best_score = 0
        for candidate in candidates:
            score = 0
            if candidate.method == old.method:
                score += 2
            # Path component overlap
            old_parts = set(old.path_pattern.strip("/").split("/"))
            new_parts = set(candidate.path_pattern.strip("/").split("/"))
            overlap = len(old_parts & new_parts)
            score += overlap
            # Parameter name overlap
            old_params = {p.name for p in old.parameters}
            new_params = {p.name for p in candidate.parameters}
            score += len(old_params & new_params)

            if score > best_score:
                best_score = score
                best = candidate
        return best
