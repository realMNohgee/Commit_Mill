# Commit_Mill ⚙️

**Conventional commits → changelog generator.** Parse, group, version-bump, and
format release notes from conventional commits. Zero dependencies, pure Python
stdlib.

> Part of the **Hermtica DevTools suite** — agent-friendly CLI tools for the
> modern dev workflow.

## Why it exists

Teams that follow the [Conventional
Commits](https://www.conventionalcommits.org/) spec write machine-readable
commit history — but actually turning that into useful outputs (changelogs,
version bumps, release notes) still requires manual work or heavyweight tooling.
Commit_Mill bridges the gap: it reads your git log, parses conventional commit
messages, and produces everything from one-liner summaries to full
`CHANGELOG.md` entries. No config files, no dependencies, no lock-in.

## One tool, many domains

| Domain | What Commit_Mill does |
|---|---|
| **DevOps / CI** | Pipe `--format json` into CI gates: block on breaking changes, auto-bump versions, validate commit conventions. |
| **Open Source** | Generate `CHANGELOG.md` entries automatically from commit history. Consistent formatting, no manual editing. |
| **Agentic AI** | Give your coding agent a single command to inspect commit history, suggest version bumps, and draft release notes — structured JSON for machine consumption. |
| **Security / Auditing** | Parse `BREAKING CHANGE` footers and `!`-suffixed types. Count by type, author, and date range for compliance tracking. |

## Install

```bash
git clone git@github.com:realMNohgee/Commit_Mill.git
cd Commit_Mill
python3 commit_mill.py --help
```

## Quick start

```bash
# Parse commits since the last tag
python3 commit_mill.py parse

# Parse between two tags
python3 commit_mill.py parse --from v1.0.0 --to v2.0.0

# Suggest the next semver bump
python3 commit_mill.py bump

# Generate a changelog entry
python3 commit_mill.py changelog --output CHANGELOG.md

# List recent releases
python3 commit_mill.py releases --last 5

# Commit statistics
python3 commit_mill.py stats --author "Jane" --since 2024-01-01

# All commands support --format json for pipelines
python3 commit_mill.py parse --format json | jq .counts
```

### Conventional commit format

Commit_Mill recognizes the standard [Conventional
Commits](https://www.conventionalcommits.org/) format:

```
type(scope): description       # standard
type!: description             # breaking change (exclamation mark)
type(scope)!: description      # breaking change with scope
```

With optional `BREAKING CHANGE` footer:

```
feat(api): add rate limiting

BREAKING CHANGE: rate limit lowered from 1000/min to 100/min
```

**Recognized types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`,
`test`, `build`, `ci`, `chore`, `revert`.

## Commands

| Command | Description |
|---|---|
| `parse` | Parse conventional commits, group by type |
| `changelog` | Generate a `CHANGELOG.md` entry |
| `bump` | Suggest next semver version (major/minor/patch) |
| `releases` | List releases with tag, date, and commit count |
| `stats` | Commit stats: by type, author, and date range |

## License

MIT — see [LICENSE](LICENSE).

---

🧰 **[Tool on Hermtica Marketplace](https://hermtica.com/marketplace)** — the open, agent-agnostic marketplace for AI agent tools.
