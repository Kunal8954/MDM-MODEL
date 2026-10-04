"""
satguard/providers/groq_provider.py
Groq LPU Inference Provider for SATGUARD evidence synthesis.
Produces structured JSON situation reports (SITREPs) strictly from computed telemetry.
"""

from typing import Dict, Any, Optional
import json
from groq import Groq
from satguard.providers.base import LLMProvider


class GroqLLMProvider(LLMProvider):
    """
    Synthesizes multi-sensor geospatial metrics into government SITREPs.
    STRICT RULE: The LLM does NOT calculate physical risk; it interprets validated numbers.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "llama-3.3-70b-versatile",
    ):
        self.api_key = api_key
        self.model = model
        self.client = Groq(api_key=self.api_key) if self.is_configured() else None

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key != "gsk_your_groq_api_key_here")

    def synthesize_situation_report(
        self,
        location_name: str,
        location_type: str,
        computed_metrics: Dict[str, Any],
        environmental_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Executes zero-shot structured JSON extraction using Groq's high-speed LPU engine.
        """
        if not self.is_configured():
            raise ValueError(
                "GROQ_API_KEY is not configured in .env. "
                "Get a free API key at: https://console.groq.com/keys"
            )

        system_prompt = (
            "You are SATGUARD-Synthesizer, an expert government Earth observation intelligence analyst. "
            "You receive computed physical metrics and environmental indicators for critical sovereign infrastructure. "
            "You MUST NEVER fabricate numbers, make up sensor data, or generate hypothetical alerts. "
            "Cite the exact numerical metrics provided. Output strictly valid JSON matching the schema."
        )

        user_content = json.dumps(
            {
                "location_name": location_name,
                "location_type": location_type,
                "computed_satellite_metrics": computed_metrics,
                "environmental_telemetry": environmental_context,
            },
            indent=2,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Synthesize this situation report into structured JSON:\n{user_content}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=1500,
            )
            raw_json = response.choices[0].message.content
            return json.loads(raw_json)
        except Exception as e:
            raise RuntimeError(f"Groq API synthesis failed: {e}")
