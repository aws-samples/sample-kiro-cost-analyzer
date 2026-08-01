"""Provider-aware Git repository URL parsing.

Derives provider-specific location parameters (GitHub owner/repo, GitLab
instance base URL and namespace path) from a configured repository URL,
without relying on regular expressions. Every function here is total: it
never raises and signals an unparseable input by returning ``None``.

This module is the analysis-time structural derivation used once a
repository is already configured. The cheap create-time validity gate
(``_URL_PATTERN`` in ``git_repo_handler``) is intentionally left untouched
and continues to do its own, simpler job.
"""

from __future__ import annotations

from typing import TypedDict
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


class RepoLocation(TypedDict, total=False):
    """Provider-specific location parameters derived from a repository URL."""

    owner: str  # github
    repo: str  # github
    baseUrl: str  # gitlab — scheme://host[:port], no trailing slash
    projectPath: str  # gitlab — full namespace path, subgroups preserved


def normalize_repo_url(url: str) -> str | None:
    """Normalize a repository URL.

    Strips surrounding whitespace, a trailing slash, and a trailing
    ``.git`` suffix. Lowercases the scheme and host; the path case is left
    intact since GitLab namespace paths are case-sensitive in practice. A
    default port matching the scheme (80 for http, 443 for https) is
    dropped. Any query string or fragment on the input is discarded, since
    they carry no meaning for repository identity.

    Args:
        url: The raw repository URL to normalize.

    Returns:
        The normalized URL, or None if the input is not an http(s) URL
        with a host and at least one non-empty path segment.
    """
    try:
        if not isinstance(url, str):
            return None

        candidate = url.strip()
        if not candidate:
            return None

        parts = urlsplit(candidate)

        scheme = parts.scheme.lower()
        if scheme not in _DEFAULT_PORTS:
            return None

        host = parts.hostname
        if not host:
            return None
        host = host.lower()

        try:
            port = parts.port
        except ValueError:
            return None

        netloc = host
        if port is not None and port != _DEFAULT_PORTS[scheme]:
            netloc = f"{host}:{port}"

        path = parts.path.rstrip("/")
        if path.endswith(".git"):
            path = path[: -len(".git")]
        path = path.rstrip("/")

        segments = [segment for segment in path.split("/") if segment]
        if not segments:
            return None

        return f"{scheme}://{netloc}/" + "/".join(segments)
    except Exception:
        return None


def parse_repo_url(provider: str, url: str) -> RepoLocation | None:
    """Derive provider-specific location parameters from a repository URL.

    ``github`` takes the last two path segments as ``owner`` and ``repo``,
    tolerating (and ignoring) any extra leading segments. ``gitlab`` takes
    every path segment, joined by ``/``, so arbitrary subgroup depth is
    preserved.

    Args:
        provider: The Git provider name (``"github"`` or ``"gitlab"``).
        url: The repository URL to parse.

    Returns:
        A RepoLocation dict, or None for an unsupported provider or an
        unparseable URL.
    """
    try:
        normalized = normalize_repo_url(url)
        if normalized is None:
            return None

        parts = urlsplit(normalized)
        segments = [segment for segment in parts.path.split("/") if segment]
        if not segments:
            return None

        if provider == "github":
            if len(segments) < 2:
                return None
            owner, repo = segments[-2], segments[-1]
            return {"owner": owner, "repo": repo}

        if provider == "gitlab":
            base_url = f"{parts.scheme}://{parts.netloc}"
            project_path = "/".join(segments)
            return {"baseUrl": base_url, "projectPath": project_path}

        return None
    except Exception:
        return None


def build_repo_url(provider: str, location: RepoLocation) -> str | None:
    """Reconstruct a normalized repository URL from location parameters.

    Inverse of parse_repo_url on the normalized URL space. Used by the
    round-trip property and by log/diagnostic rendering. GitHub URLs are
    always rebuilt against ``github.com`` over https, since a RepoLocation
    for GitHub carries no host of its own.

    Args:
        provider: The Git provider name (``"github"`` or ``"gitlab"``).
        location: The location parameters to reconstruct a URL from.

    Returns:
        The reconstructed URL, or None for an unsupported provider or
        incomplete location parameters.
    """
    try:
        if provider == "github":
            owner = location.get("owner")
            repo = location.get("repo")
            if not owner or not repo:
                return None
            return f"https://github.com/{owner}/{repo}"

        if provider == "gitlab":
            base_url = location.get("baseUrl")
            project_path = location.get("projectPath")
            if not base_url or not project_path:
                return None
            return f"{base_url}/{project_path}"

        return None
    except Exception:
        return None
