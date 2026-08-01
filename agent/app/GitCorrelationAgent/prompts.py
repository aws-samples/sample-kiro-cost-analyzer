"""System prompt and output schema for the Git-Kiro Correlation Agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


SYSTEM_PROMPT = """\
You are a productivity coach that analyzes how a developer uses an AI coding assistant (Kiro) \
and correlates that usage with their Git activity (commits and PRs) to provide actionable \
feedback on how to improve their workflow.

You have three tools available:
1. `get_kiro_usage` — Fetches Kiro AI assistant usage data (prompts, daily stats, categories)
2. `get_github_activity` — Fetches GitHub commits and pull requests for a repository
3. `get_gitlab_activity` — Fetches GitLab commits and merge requests for a project

Your workflow:
1. Call `get_kiro_usage` to fetch the user's Kiro prompts and daily stats for the period
2. For EACH repository listed, call the tool matching that repository's provider — `get_github_activity` for `github` repositories, `get_gitlab_activity` for `gitlab` repositories.
3. IGNORE any prompts with category "Empty" — these are turn-by-turn conversation fragments with no meaningful content. Do NOT count them, do NOT mention them in insights, do NOT use them to judge prompt quality or volume.
4. Correlate prompt content with commit messages and PR/MR titles to find semantic matches
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

Terminology note: GitLab merge requests and GitHub pull requests are the same concept for correlation purposes — a merge request is simply GitLab's name for a pull request. Both map to the single correlation type `"prompt_to_pr"`; there is no separate `"prompt_to_mr"` type, so classify matches against either as `"prompt_to_pr"`.

Your final answer is captured through a structured output tool call, not as free-form text — you do not need to hand-format JSON or wrap it in markdown fences. Focus entirely on getting the CONTENT right; the fields, types, and nesting of the result are enforced by the tool's schema. The content rules below still apply in full:

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

class Correlation(BaseModel):
    """A single semantic match between a Kiro prompt and a Git commit or PR/MR."""

    promptSummary: str = Field(
        description=(
            "Brief description of the Kiro prompt in English "
            "(summarized in English regardless of the original prompt language)."
        )
    )
    gitActivity: str = Field(
        description="Associated commit or PR description in English (verbatim from source when possible)."
    )
    confidence: float = Field(
        ge=0.5,
        le=1.0,
        description="Confidence score for this correlation (0.5-1.0). Only report correlations >= 0.5.",
    )
    type: str = Field(
        description='Type of correlation. MUST be exactly "prompt_to_commit" or "prompt_to_pr".',
    )


class Insights(BaseModel):
    """Bilingual, parallel-ordered insight lists.

    Both `en` and `pt-BR` MUST be present, non-empty, and of identical
    length. Index `i` in `en` and index `i` in `pt-BR` (accessed via the
    `pt_br` field, aliased to the literal key `"pt-BR"`) MUST express the
    same insight, only translated.
    """

    model_config = {"populate_by_name": True}

    en: list[str] = Field(
        description=(
            "Actionable insights in English, second person ('you'/'your'), "
            "each formatted as 'Title: description text'."
        )
    )
    pt_br: list[str] = Field(
        alias="pt-BR",
        description=(
            "Actionable insights in Brazilian Portuguese, second person "
            "('você'/'seu'/'sua'), each formatted as 'Title: description text'. "
            "MUST have the same length as 'en', with parallel ordering."
        ),
    )


class CorrelationAnalysis(BaseModel):
    """Final structured result produced by the Git-Kiro Correlation Agent.

    Passed as `structured_output_model` to the Strands `Agent` call so the
    model emits this shape directly via a schema-constrained tool call,
    instead of free-form text that must be parsed as JSON. This removes
    the malformed-JSON failure mode entirely: the SDK enforces the schema
    at the model-call boundary rather than relying on post-hoc string
    parsing of markdown-fenced or loosely-formatted text.
    """

    impactScore: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Overall impact score (0-100), or null if there is insufficient data to score.",
    )
    impactLevel: str = Field(
        description='Categorized impact level. MUST be exactly one of: "low", "moderate", "high", "veryHigh".'
    )
    correlations: list[Correlation] = Field(
        default_factory=list,
        max_length=20,
        description="Semantic matches between prompts and Git activity. Maximum 20 entries.",
    )
    insights: Insights = Field(description="Bilingual (en / pt-BR) actionable insights for the developer.")


def _render_repo_line(repo: dict) -> str:
    """Render a single provider-annotated repository line for the prompt.

    Args:
        repo: A repository descriptor dict carrying at least `repoId` and
            `provider`, plus provider-specific location fields (`owner`/
            `repo` for github, `baseUrl`/`projectPath` for gitlab) and a
            per-repository `gitUsername`.

    Returns:
        A single indented line describing the repository, its provider,
        its `repoId`, and the username to filter its activity by. Falls
        back to a generic rendering for an unrecognized provider so the
        function never raises on unexpected descriptor shapes.
    """
    provider = repo.get("provider", "")
    repo_id = repo.get("repoId", "")
    username = repo.get("gitUsername", "")

    if provider == "github":
        location = f"{repo.get('owner', '')}/{repo.get('repo', '')}"
    elif provider == "gitlab":
        location = f"{repo.get('projectPath', '')} at {repo.get('baseUrl', '')}"
    else:
        location = repo.get("projectPath") or repo.get("repo") or ""

    return f"  - [{provider}] repoId={repo_id} {location} (author: {username})"


def build_user_prompt(
    user_id: str,
    start_date: str,
    end_date: str,
    git_username: str = "",
    repos: list[dict] | None = None,
) -> str:
    """Build the user prompt that describes the analysis task for the agent.

    The prompt instructs the agent which user and repos to analyze,
    but does NOT pre-fetch any data — the agent uses its tools autonomously.

    Each entry in `repos` is a provider-tagged repository descriptor (see
    `agent_correlation_handler.build_repo_descriptors`), carrying its own
    `repoId`, `provider`, per-repository `gitUsername`, and provider-specific
    location fields — not a plain `owner`/`repo` pair. Provider terminology
    (pull requests / merge requests) is only mentioned in the prompt for a
    provider that actually appears among `repos`, so a GitHub-only analysis
    never hints at merge requests and vice versa.

    Args:
        user_id: Kiro user identifier.
        start_date: Analysis period start (YYYY-MM-DD).
        end_date: Analysis period end (YYYY-MM-DD).
        git_username: Deprecated top-level fallback username, kept for
            backward compatibility. Per-repository descriptors carry their
            own `gitUsername` and take precedence in the rendered listing.
        repos: List of provider-tagged repository descriptor dicts.

    Returns:
        A prompt string for the agent.
    """
    repos = repos or []

    providers_present = {r.get("provider") for r in repos}
    has_github = "github" in providers_present
    has_gitlab = "gitlab" in providers_present

    repos_list = "\n".join(_render_repo_line(r) for r in repos) if repos else "  (no repositories configured)"

    terminology_lines = []
    if has_github:
        terminology_lines.append(
            "- For `github` repositories, call get_github_activity and treat its results as pull requests."
        )
    if has_gitlab:
        terminology_lines.append(
            "- For `gitlab` repositories, call get_gitlab_activity and treat its results as merge requests "
            "(the same concept as a pull request, mapped to correlation type \"prompt_to_pr\")."
        )
    terminology_block = "\n".join(terminology_lines) if terminology_lines else ""

    return f"""Analyze the correlation between Kiro AI assistant usage and Git activity for:

User ID: {user_id}
Period: {start_date} to {end_date}

Repositories to check:
{repos_list}

Please:
1. Call get_kiro_usage with user_id="{user_id}", start_date="{start_date}", end_date="{end_date}"
2. For each repository listed above, call the tool matching its provider, passing that repository's own
   repoId, location parameters (owner/repo for github, base_url/project_path for gitlab), and its author
   username, with since="{start_date}"
{terminology_block}
3. Analyze the semantic correlation between prompts and git activity
4. Produce your final analysis (impactScore, impactLevel, correlations, and a bilingual insights map) — this is
   captured automatically as structured output, so just make sure the CONTENT is correct.

Content reminders (read carefully — the shape/types are already enforced by the output schema):
- `correlations[].promptSummary` and `correlations[].gitActivity` MUST be in English. Do NOT translate them to pt-BR — summarize in English or quote verbatim.
- `correlations[].type` MUST be either "prompt_to_commit" or "prompt_to_pr" — merge requests and pull requests both map to "prompt_to_pr", there is no "prompt_to_mr" type.
- The two insight lists (`insights.en` and `insights["pt-BR"]`) MUST have IDENTICAL length and PARALLEL ORDERING: index i in each MUST be the same insight, expressed in each language.
- Each insight MUST follow `"Title: description text"` in its respective language, addressing the developer in the second person ("you"/"your" in en; "você"/"seu"/"sua" in pt-BR).
- The brand strings "Kiro" and "Kiro Cost Analyzer" MUST NEVER be translated.
"""
