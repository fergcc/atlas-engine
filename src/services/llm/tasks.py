"""
LLM service module — DeepSeek-powered analysis tasks.
"""

from __future__ import annotations

from src.services.llm import client

SECTOR_CLASSIFIER_PROMPT = """You are an economic analyst specializing in global industrial value chains.

Evaluate the following sector using the Rabellotti & Giuliani (2017) framework with three criteria:

1. **Collective efficiency** — Does the sector benefit from clustering, knowledge spillovers, and shared supply chains?
2. **Innovation capacity** — R&D intensity, patent activity, technological dynamism.
3. **Market openness** — Trade intensity, global competition, barriers to entry.

For each criterion, provide:
- score (1-10, where 10 is highest)
- justification (2-3 sentences in the SAME language as the sector description)

Also provide:
- overall_score (1-10 average)
- recommended (boolean: true if all criteria score >= 5)
- strategic_potential (string: "high", "medium", or "low")
- key_opportunities (list of 2-4 strings, in the same language)
- key_risks (list of 2-4 strings, in the same language)

Respond with JSON only. No markdown fences."""


INDICATOR_EXTRACTION_PROMPT = """You are a data extraction specialist. Extract quantitative information from economic reports.

Given the text below, extract values for the requested indicators. For each indicator:
- value: the numeric value found (null if not found)
- unit: the unit of measurement
- year: the year of the data
- confidence: "high" (explicitly stated), "medium" (can be inferred), or "low" (guesswork)
- source_context: the sentence or paragraph where the value was found

Indicators requested: {indicators}

If multiple values exist for the same indicator, return the most recent one.
If an indicator is not found, set value to null and confidence to "not_found".

Respond with JSON only: {{"indicators": {{"indicator_id": {{...}}}}}}"""


NARRATIVE_PROMPT = """You are an economic analyst writing a professional report on industrial value chains.

Generate a comprehensive sector analysis for the {sector_name} sector in {country_names}.
The report should be in {language} and follow this structure:

## 1. Panorama global del sector
- Global market size and growth trends (last 5 years)
- Key global players (countries and companies)
- Trade patterns and global value chain structure

## 2. Cadena nacional de valor
- Position of {country_names} within the global value chain
- Domestic production, exports, and imports
- Key national firms and clusters

## 3. Factores de competitividad
- Innovation and R&D landscape
- Labor force and specialized talent
- Infrastructure and logistics
- Government policies and incentives

## 4. Perspectivas y recomendaciones
- Growth opportunities (2-3)
- Key risks and challenges (2-3)
- Strategic recommendations for investment attraction

Write in a professional, analytical tone suitable for a government/investor audience.
Use the provided context where available; otherwise base analysis on general knowledge of the sector.
Keep each section concise (2-3 paragraphs). Total: 800-1200 words.

Context: {context}"""


def classify_sector(
    sector_name: str,
    description: str = "",
    context: str = "",
    *,
    model: str = "deepseek-chat",
) -> dict:
    user_content = f"Sector: {sector_name}"
    if description:
        user_content += f"\nDescription: {description}"
    if context:
        user_content += f"\nAdditional context: {context}"

    messages = [
        {"role": "system", "content": SECTOR_CLASSIFIER_PROMPT},
        {"role": "user", "content": user_content},
    ]

    result = client.chat_json(messages, model=model, temperature=0.2)
    return result.get("parsed", result)


def extract_indicators(
    text: str,
    indicator_ids: list[str] | None = None,
    *,
    model: str = "deepseek-chat",
) -> dict:
    ids = indicator_ids or [
        "manufacturing_value_added",
        "employment_total",
        "exports_usd",
        "rd_expenditure_pct_gdp",
        "fdi_inflows",
    ]
    system_msg = INDICATOR_EXTRACTION_PROMPT.format(indicators=", ".join(ids))

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": text[:8000]},
    ]

    result = client.chat_json(messages, model=model, temperature=0.1)
    return result.get("parsed", result)


def generate_narrative(
    sector_name: str,
    country_names: str,
    language: str = "es",
    context: str = "",
    *,
    model: str = "deepseek-chat",
) -> dict:
    system_msg = NARRATIVE_PROMPT.format(
        sector_name=sector_name,
        country_names=country_names,
        language=language,
        context=context or "No additional context provided.",
    )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": f"Generate the sector analysis report for {sector_name} in {country_names}."},
    ]

    result = client.chat(messages, model=model, temperature=0.5, max_tokens=4096)
    return {
        "sector": sector_name,
        "countries": country_names,
        "language": language,
        "content": result.get("content", ""),
        "model": result.get("model"),
        "usage": result.get("usage"),
        "source": result.get("source"),
    }
