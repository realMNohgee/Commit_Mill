#!/usr/bin/env python3
"""
Commit_Mill — Conventional Commits → Changelog Generator.

Parse, group, version-bump, and format release notes from conventional
commits. Zero dependencies. Pure Python stdlib.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

# Conventional Commit type labels (sorted for stable output)
TYPE_LABELS: dict[str, str] = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "docs": "Documentation",
    "style": "Style",
    "refactor": "Refactoring",
    "perf": "Performance",
    "test": "Tests",
    "build": "Build System",
    "ci": "CI/CD",
    "chore": "Chores",
    "revert": "Reverts",
}

# All recognized types
RECOGNIZED_TYPES = set(TYPE_LABELS)

# Pattern for conventional commits: type(scope)!: description or type!: description
# Also captures BREAKING CHANGE footer
CC_PATTERN = re.compile(
    r"^(?P<type>[a-zA-Z]+)"          # type
    r"(?:\((?P<scope>[^)]*)\))?"     # optional (scope)
    r"(?P<breaking>!)?"              # optional ! for breaking change
    r":\s*(?P<desc>.*)$",            # : description
    re.MULTILINE,
)

BREAKING_FOOTER = re.compile(r"^BREAKING[-\s]CHANGE:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_git(repo: str, *args: str) -> str:
    """Run a git command in the repo and return stdout. Raises on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or "git command failed"
            raise SystemExit(f"git error: {msg}")
        return result.stdout
    except FileNotFoundError:
        raise SystemExit("git not found — is it installed?")
    except subprocess.TimeoutExpired:
        raise SystemExit("git command timed out")


def git_tags(repo: str) -> list[str]:
    """Return all tags sorted by commit date (newest first)."""
    output = run_git(repo, "tag", "--sort=-creatordate")
    return [t for t in output.strip().split("\n") if t]


def semver_key(tag: str) -> tuple[int, ...]:
    """Convert a semver-ish tag (with or without 'v' prefix) to a sortable tuple."""
    stripped = tag.lstrip("v")
    parts: list[int] = []
    for p in stripped.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def resolve_range(repo: str, from_tag: Optional[str], to_tag: Optional[str]) -> str:
    """Build a git log range string from --from/--to tags."""
    if from_tag and to_tag:
        return f"{from_tag}..{to_tag}"
    if from_tag:
        return f"{from_tag}..HEAD"
    if to_tag:
        return f"{to_tag}"
    # Default: from last tag to HEAD, or all commits if no tags
    tags = git_tags(repo)
    if tags:
        return f"{tags[0]}..HEAD"
    return "HEAD"


# ---------------------------------------------------------------------------
# Commit parsing
# ---------------------------------------------------------------------------

class ParsedCommit:
    __slots__ = ("hash", "author", "date", "type", "scope", "breaking", "desc", "body")

    def __init__(
        self,
        hash: str,
        author: str,
        date: str,
        type: str,
        scope: str,
        breaking: bool,
        desc: str,
        body: str = "",
    ):
        self.hash = hash
        self.author = author
        self.date = date
        self.type = type
        self.scope = scope
        self.breaking = breaking
        self.desc = desc
        self.body = body

    def to_dict(self) -> dict:
        return {
            "hash": self.hash,
            "author": self.author,
            "date": self.date,
            "type": self.type,
            "scope": self.scope,
            "breaking": self.breaking,
            "description": self.desc,
            "body": self.body,
        }


def fetch_commits(repo: str, range_spec: str) -> list[ParsedCommit]:
    """Fetch commits from git log in the given range."""
    # Use %x00 as a field separator (null byte unlikely in commit data)
    fmt = "%x00%H%x00%an%x00%aI%x00%s%x00%b%x00%x01"
    output = run_git(repo, "log", range_spec, f"--format={fmt}", "--no-merges")
    # Split by the record separator %x01
    raw_commits = [c for c in output.split("\x01") if c.strip("\x00\n ")]

    commits: list[ParsedCommit] = []
    for raw in raw_commits:
        parts = raw.split("\x00")
        if len(parts) < 5:
            continue
        # parts: ['', hash, author, date, subject, body, ...]
        # The leading empty string is from the first %x00 delimiter
        hash_val = parts[1]
        author = parts[2]
        date = parts[3]
        subject = parts[4]
        body = parts[5] if len(parts) > 5 else ""

        # Parse conventional commit subject
        m = CC_PATTERN.match(subject)
        if not m:
            continue  # not a conventional commit

        ctype = m.group("type").lower()
        if ctype not in RECOGNIZED_TYPES:
            continue

        scope = (m.group("scope") or "").strip()
        desc = m.group("desc").strip()

        # Breaking: ! in subject OR BREAKING CHANGE footer
        breaking = m.group("breaking") == "!" or bool(BREAKING_FOOTER.search(body))

        commits.append(
            ParsedCommit(
                hash=hash_val,
                author=author,
                date=date,
                type=ctype,
                scope=scope,
                breaking=breaking,
                desc=desc,
                body=body,
            )
        )

    return commits


def group_by_type(commits: list[ParsedCommit]) -> dict[str, list[ParsedCommit]]:
    """Group commits by their type, preserving order."""
    groups: dict[str, list[ParsedCommit]] = defaultdict(list)
    for c in commits:
        groups[c.type].append(c)
    return dict(groups)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_parse(args: argparse.Namespace) -> None:
    """Parse conventional commits between tags."""
    repo = args.repo or "."
    range_spec = resolve_range(repo, args.from_tag, args.to_tag)
    commits = fetch_commits(repo, range_spec)
    groups = group_by_type(commits)

    if args.format == "json":
        result: dict = {}
        for ctype in sorted(groups, key=lambda t: list(TYPE_LABELS).index(t) if t in TYPE_LABELS else 99):
            result[ctype] = [c.to_dict() for c in groups[ctype]]
        result["counts"] = {ctype: len(groups[ctype]) for ctype in sorted(groups)}
        result["total"] = len(commits)
        print(json.dumps(result, indent=2))
    else:
        if not commits:
            print(f"No conventional commits found in range: {range_spec}")
            return
        print(f"Commits in range: {range_spec}\n")
        for ctype in sorted(groups, key=lambda t: list(TYPE_LABELS).index(t) if t in TYPE_LABELS else 99):
            label = TYPE_LABELS.get(ctype, ctype.capitalize())
            print(f"## {label} ({len(groups[ctype])})")
            for c in groups[ctype]:
                scope_str = f"({c.scope})" if c.scope else ""
                breaking_str = " ⚡BREAKING" if c.breaking else ""
                print(f"  - {c.hash[:7]} {scope_str}: {c.desc}{breaking_str}")
            print()


def cmd_changelog(args: argparse.Namespace) -> None:
    """Generate a CHANGELOG.md entry."""
    repo = args.repo or "."
    range_spec = resolve_range(repo, args.from_tag, args.to_tag)
    commits = fetch_commits(repo, range_spec)

    # Determine version
    tags = git_tags(repo)
    if args.to_tag:
        version = args.to_tag.lstrip("v")
    elif tags:
        # Use the latest tag for the version header
        version = tags[0].lstrip("v")
    else:
        version = "Unreleased"

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    groups = group_by_type(commits)

    if args.format == "json":
        entry = {
            "version": version,
            "date": date_str,
            "range": range_spec,
            "total": len(commits),
            "sections": {},
        }
        for ctype in sorted(groups, key=lambda t: list(TYPE_LABELS).index(t) if t in TYPE_LABELS else 99):
            label = TYPE_LABELS.get(ctype, ctype.capitalize())
            items: list[str] = []
            for c in groups[ctype]:
                scope_str = f"**{c.scope}**: " if c.scope else ""
                breaking_str = " ⚡BREAKING" if c.breaking else ""
                items.append(f"{scope_str}{c.desc}{breaking_str}")
            entry["sections"][ctype] = {"label": label, "count": len(groups[ctype]), "items": items}
        print(json.dumps(entry, indent=2))
        return

    # Text format
    lines: list[str] = []
    lines.append(f"# {version} ({date_str})\n")

    # Section order: feat, fix, breaking, then the rest
    ordered = ["feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert"]
    remaining = [t for t in ordered if t in groups]

    for ctype in remaining:
        label = TYPE_LABELS.get(ctype, ctype.capitalize())
        lines.append(f"## {label}\n")
        for c in groups[ctype]:
            scope_str = f"**{c.scope}**: " if c.scope else ""
            lines.append(f"- {scope_str}{c.desc} ({c.hash[:7]})")
            if c.breaking:
                # Find breaking change footer
                bm = BREAKING_FOOTER.search(c.body)
                if bm:
                    lines.append(f"  ⚠ **BREAKING**: {bm.group(1)}")
                else:
                    lines.append(f"  ⚠ **BREAKING**")
        lines.append("")

    changelog_text = "\n".join(lines)

    if args.output:
        with open(args.output, "w") as f:
            f.write(changelog_text)
        print(f"Changelog written to: {args.output}")
    else:
        print(changelog_text)


def cmd_bump(args: argparse.Namespace) -> None:
    """Suggest the next version bump."""
    repo = args.repo or "."
    range_spec = resolve_range(repo, args.from_tag, None)
    commits = fetch_commits(repo, range_spec)

    has_breaking = any(c.breaking for c in commits)
    has_feat = any(c.type == "feat" for c in commits)

    if has_breaking:
        bump_level = "major"
    elif has_feat:
        bump_level = "minor"
    else:
        bump_level = "patch"

    # Get current latest tag
    tags = git_tags(repo)
    current = "0.0.0"
    if tags:
        current = tags[0].lstrip("v")

    # Compute next version
    parts = current.split(".")
    while len(parts) < 3:
        parts.append("0")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if bump_level == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_level == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1

    next_ver = f"{major}.{minor}.{patch}"

    if args.format == "json":
        result = {
            "current": current,
            "bump": bump_level,
            "next": next_ver,
            "breaking_changes": sum(1 for c in commits if c.breaking),
            "features": sum(1 for c in commits if c.type == "feat"),
            "total_commits": len(commits),
            "range": range_spec,
        }
        print(json.dumps(result, indent=2))
    else:
        print(f"Current: {current}")
        print(f"Bump:    {bump_level}")
        print(f"Next:    {next_ver}")
        print(f"\nBased on {len(commits)} commits in range: {range_spec}")
        if has_breaking:
            print(f"  ⚡ {sum(1 for c in commits if c.breaking)} breaking change(s)")
        if has_feat:
            print(f"  ✨ {sum(1 for c in commits if c.type == 'feat')} feature(s)")


def cmd_releases(args: argparse.Namespace) -> None:
    """List recent releases with tag, date, and commit count."""
    repo = args.repo or "."

    # Get tags sorted by version (newest first)
    # Sort tags by semver (newest first) for reliable ordering
    tag_list = run_git(repo, "tag").strip().split("\n")
    tag_list = [t for t in tag_list if t]
    try:
        tag_list.sort(key=semver_key, reverse=True)
    except Exception:
        pass  # fall back to git sort if semver fails

    if args.last and args.last > 0:
        tag_list = tag_list[: args.last]

    # For each tag, get date and commit count since previous tag
    releases: list[dict] = []
    for i, tag in enumerate(tag_list):
        date = run_git(repo, "log", "-1", "--format=%aI", tag).strip()

        # Count commits in this tag's range
        if i + 1 < len(tag_list):
            prev_tag = tag_list[i + 1]
            range_spec = f"{prev_tag}..{tag}"
        else:
            range_spec = tag

        count_output = run_git(repo, "rev-list", "--count", range_spec, "--no-merges")
        count = int(count_output.strip() or "0")

        releases.append({"tag": tag, "version": tag.lstrip("v"), "date": date, "commits": count})

    if args.format == "json":
        print(json.dumps(releases, indent=2))
    else:
        if not releases:
            print("No releases found.")
            return
        print(f"{'Tag':<16} {'Date':<12} {'Commits':<8}")
        print("-" * 36)
        for r in releases:
            d = r["date"][:10] if r["date"] else "-"
            print(f"{r['tag']:<16} {d:<12} {r['commits']:<8}")


def cmd_stats(args: argparse.Namespace) -> None:
    """Commit stats: count by type, author, time range."""
    repo = args.repo or "."

    # Build git log args
    log_args = ["log", "--no-merges", "--format=%x00%an%x00%s%x00%aI%x00%x01"]

    if args.since:
        log_args.insert(1, f"--since={args.since}")
    if args.author:
        log_args.insert(1, f"--author={args.author}")

    output = run_git(repo, *log_args)

    raw_commits = [c for c in output.split("\x01") if c.strip("\x00\n ")]

    type_counts: defaultdict[str, int] = defaultdict(int)
    author_counts: defaultdict[str, int] = defaultdict(int)
    total = 0

    for raw in raw_commits:
        parts = raw.split("\x00")
        if len(parts) < 4:
            continue
        author_name = parts[1]
        subject = parts[2]

        m = CC_PATTERN.match(subject)
        ctype = m.group("type").lower() if m else "other"
        if ctype not in RECOGNIZED_TYPES:
            ctype = "other"

        type_counts[ctype] += 1
        author_counts[author_name] += 1
        total += 1

    if args.format == "json":
        result = {
            "total": total,
            "by_type": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
            "by_author": dict(sorted(author_counts.items(), key=lambda x: -x[1])),
        }
        if args.since:
            result["since"] = args.since
        if args.author:
            result["author_filter"] = args.author
        print(json.dumps(result, indent=2))
    else:
        print(f"Total commits: {total}")
        if args.since:
            print(f"Since: {args.since}")
        if args.author:
            print(f"Author: {args.author}")
        print()
        print("By type:")
        for ctype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            label = TYPE_LABELS.get(ctype, ctype.capitalize())
            print(f"  {label:<16} {count}")
        print()
        print("By author:")
        for author, count in sorted(author_counts.items(), key=lambda x: -x[1]):
            print(f"  {author:<24} {count}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def add_format_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )


def add_repo_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="Path to git repository (default: .)")


def add_range_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from", dest="from_tag", default=None, help="Start tag (e.g., v1.0.0)")
    parser.add_argument("--to", dest="to_tag", default=None, help="End tag (e.g., v2.0.0)")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description="Commit_Mill — Conventional Commits → Changelog Generator.\n"
        "Parse, group, version-bump, and format release notes from conventional commits.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # parse
    p_parse = sub.add_parser("parse", help="Parse conventional commits")
    add_format_arg(p_parse)
    add_repo_arg(p_parse)
    add_range_args(p_parse)

    # changelog
    p_cl = sub.add_parser("changelog", help="Generate CHANGELOG.md entry")
    add_format_arg(p_cl)
    add_repo_arg(p_cl)
    add_range_args(p_cl)
    p_cl.add_argument("--output", "-o", help="Write changelog to file instead of stdout")

    # bump
    p_bump = sub.add_parser("bump", help="Suggest next version bump")
    add_format_arg(p_bump)
    add_repo_arg(p_bump)
    p_bump.add_argument("--from", dest="from_tag", default=None, help="Start tag (default: latest tag)")

    # releases
    p_rel = sub.add_parser("releases", help="List recent releases")
    add_format_arg(p_rel)
    add_repo_arg(p_rel)
    p_rel.add_argument("--last", type=int, default=None, help="Show last N releases")

    # stats
    p_stats = sub.add_parser("stats", help="Commit statistics")
    add_format_arg(p_stats)
    add_repo_arg(p_stats)
    p_stats.add_argument("--author", help="Filter by author name")
    p_stats.add_argument("--since", help="Filter commits since date (e.g., 2024-01-01)")

    args = p.parse_args(argv)

    commands = {
        "parse": cmd_parse,
        "changelog": cmd_changelog,
        "bump": cmd_bump,
        "releases": cmd_releases,
        "stats": cmd_stats,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
