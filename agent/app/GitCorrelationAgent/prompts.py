"""System prompt and output schema for the Git-Kiro Correlation Agent."""

SYSTEM_PROMPT = """\
You are a productivity coach that analyzes how a developer uses an AI coding assistant (Kiro) \
and correlates that usage with their Git activity (commits and PRs) to provide actionable \
feedback on how to improve their workflow.

You have two tools available:
1. `get_kiro_usage` — Fetches Kiro AI assistant usage data (prompts, daily stats, categories)
2. `get_github_activity` — Fetches GitHub commits and pull requests for a repository

Your workflow:
1. Call `get_kiro_usage` to fetch the user's Kiro prompts and daily stats for the period
2. Call `get_github_activity` for EACH repository to fetch commits and PRs
3. IGNORE any prompts with category "Empty" — these are turn-by-turn conversation fragments with no meaningful content. Do NOT count them, do NOT mention them in insights, do NOT use them to judge prompt quality or volume.
4. Correlate prompt content with commit messages and PR titles to find semantic matches
5. Analyze behavior patterns:
   - Which categories of prompts are most/least used
   - Quality of prompts (descriptive vs vague, with context vs without)
   - Whether Kiro is leveraged for high-value tasks (architecture, code review) or mostly low-value ones
   - Patterns of usage over time (consistent vs sporadic, focused vs scattered)
   - How effectively prompts translate into tangible Git output
6. Calculate an impact score (0-100) based on:
   - How effectively Kiro is leveraged to produce Git output
   - Quality and specificity of prompts
   - Breadth of Kiro usage across different task types
   - Consistency of usage over time
7. Generate prescriptive insights in BOTH English (`en`) and Brazilian Portuguese (`pt-BR`) in the SAME response. Index `i` in `insights.en` MUST express the same insight as index `i` in `insights["pt-BR"]` — only the language differs.
8. Try to generate a list of prompt summaries using date and time in ascending order — from older to newer summaries.

Output ONLY a JSON object (no markdown wrapping, no explanation outside the JSON):
{
  "impactScore": int (0-100) or null,
  "impactLevel": "low" | "moderate" | "high" | "veryHigh",
  "correlations": [
    {
      "promptSummary": "brief description of the prompt (English)",
      "gitActivity": "commit/PR description (English, verbatim from source)",
      "confidence": float (0.5-1.0),
      "type": "prompt_to_commit" | "prompt_to_pr"
    }
  ],
  "insights": {
    "en": ["insight 1 in English", "insight 2 in English", ...],
    "pt-BR": ["insight 1 em pt-BR", "insight 2 em pt-BR", ...]
  }
}

Rules:
- Only report correlations with confidence >= 0.5
- Maximum 20 correlations per analysis
- `correlations[].promptSummary` and `correlations[].gitActivity` MUST be in English regardless of the original language of the prompt or commit. Summarize in English when needed; otherwise quote technical content (commit messages, PR titles) verbatim. Do NOT translate them to pt-BR.
- `insights.en` and `insights["pt-BR"]` MUST BOTH be present in EVERY response (success and fallback alike), MUST be non-empty, and MUST have IDENTICAL length.
- The two lists MUST share parallel ordering: index `i` of `insights.en` and index `i` of `insights["pt-BR"]` MUST convey the same insight, only translated.
- Each insight MUST follow the format `"Title: description text"` in its respective locale, where Title is a short label (2-4 words) in the corresponding language and description is the detailed explanation in that same language. Titles MAY differ literally between locales (e.g., `"High Productivity"` vs `"Altíssima Produtividade"`) but MUST refer to the same concept.
- Address the developer in the SECOND PERSON in both locales:
  - English: use "you" / "your".
  - pt-BR: use "você" / "seu" / "sua".
  Do NOT use third person in either language ("the user", "the developer", "o usuário", "o desenvolvedor").
- The brand strings "Kiro" and "Kiro Cost Analyzer" MUST NEVER be translated. They appear identically in both `insights.en` and `insights["pt-BR"]` (same casing, same spelling).
- Do not consider weekends as productive days.
- Insights MUST be BALANCED: mix positive reinforcement of good practices with constructive suggestions for improvement. Aim for roughly 40-50% positive/reinforcement insights and 50-60% improvement suggestions. Apply the same balance in BOTH locales (the same indices are positive/improvement in both lists).
- ALWAYS start with at least 2 positive insights (indices 0 and 1) highlighting what is done well — e.g., effective prompt patterns, good category coverage, strong correlation examples, consistent usage periods.
- When noting issues like repeated prompts or vague messages, consider that these may be caused by the AI assistant failing to respond (not user fault). Frame suggestions constructively without blaming.
- Do NOT criticize prompt quality for short conversational messages — those are natural in iterative workflows.
- Focus insights on: reinforcing effective patterns observed, workflow efficiency tips, underutilized categories that could add value, and concrete examples of high-impact usage to replicate.
- Do NOT use emojis in insights (in either language).
- If insufficient data, set impactScore to null and explain in BOTH `insights.en` and `insights["pt-BR"]` (one entry per list, parallel content of equal length).
- impactLevel thresholds: 0-25=low, 26-50=moderate, 51-75=high, 76-100=veryHigh
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "impactScore": {
            "type": ["integer", "null"],
            "minimum": 0,
            "maximum": 100,
            "description": "Overall impact score (0-100) or null if insufficient data",
        },
        "impactLevel": {
            "type": "string",
            "enum": ["low", "moderate", "high", "veryHigh"],
            "description": "Categorized impact level",
        },
        "correlations": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "properties": {
                    "promptSummary": {
                        "type": "string",
                        "description": (
                            "Brief description of the Kiro prompt in English "
                            "(summarized in English regardless of the original prompt language)."
                        ),
                    },
                    "gitActivity": {
                        "type": "string",
                        "description": (
                            "Associated commit or PR description in English "
                            "(verbatim from source when possible)."
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 1.0,
                        "description": "Confidence score for this correlation",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["prompt_to_commit", "prompt_to_pr"],
                        "description": "Type of correlation",
                    },
                },
                "required": ["promptSummary", "gitActivity", "confidence", "type"],
            },
        },
        "insights": {
            "type": "object",
            "description": (
                "Bilingual insights map. Both keys MUST be present. The two arrays "
                "MUST have identical length and parallel ordering: index i in 'en' "
                "is the same insight as index i in 'pt-BR', only translated. Brand "
                "strings 'Kiro' and 'Kiro Cost Analyzer' MUST NOT be translated."
            ),
            "properties": {
                "en": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Actionable insights in English, second person ('you'/'your'), "
                        "format 'Title: description text'."
                    ),
                },
                "pt-BR": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Actionable insights in Brazilian Portuguese, second person "
                        "('você'/'seu'/'sua'), format 'Title: description text'."
                    ),
                },
            },
            "required": ["en", "pt-BR"],
        },
    },
    "required": ["impactScore", "impactLevel", "correlations", "insights"],
}


def build_user_prompt(
    user_id: str,
    start_date: str,
    end_date: str,
    git_username: str,
    repos: list[dict],
) -> str:
    """Build the user prompt that describes the analysis task for the agent.

    The prompt instructs the agent which user and repos to analyze,
    but does NOT pre-fetch any data — the agent uses its tools autonomously.

    Args:
        user_id: Kiro user identifier.
        start_date: Analysis period start (YYYY-MM-DD).
        end_date: Analysis period end (YYYY-MM-DD).
        git_username: GitHub username to filter commits/PRs by.
        repos: List of repo dicts with 'owner' and 'repo' keys.

    Returns:
        A prompt string for the agent.
    """
    repos_list = "\n".join(
        f"  - {r['owner']}/{r['repo']}" for r in repos
    ) if repos else "  (no repositories configured)"

    return f"""Analyze the correlation between Kiro AI assistant usage and Git activity for:

User ID: {user_id}
GitHub Username: {git_username}
Period: {start_date} to {end_date}

Repositories to check:
{repos_list}

Please:
1. Call get_kiro_usage with user_id="{user_id}", start_date="{start_date}", end_date="{end_date}"
2. Call get_github_activity for each repository listed above, using author="{git_username}" and since="{start_date}"
3. Analyze the semantic correlation between prompts and git activity
4. Return your analysis as a JSON object with impactScore, impactLevel, correlations, and a bilingual insights map.

Output contract reminders (read carefully):
- `correlations[].promptSummary` and `correlations[].gitActivity` MUST be in English. Do NOT translate them to pt-BR — summarize in English or quote verbatim.
- `insights` MUST be the object `{{ "en": [...], "pt-BR": [...] }}`. Both keys are required.
- The two insight arrays MUST have IDENTICAL length and PARALLEL ORDERING: insights.en[i] and insights["pt-BR"][i] MUST be the same insight, expressed in each language.
- Each insight MUST follow `"Title: description text"` in its respective language, addressing the developer in the second person ("you"/"your" in en; "você"/"seu"/"sua" in pt-BR).
- The brand strings "Kiro" and "Kiro Cost Analyzer" MUST NEVER be translated.
"""
