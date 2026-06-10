---
name: git-conventional-commits
description: Formulate precise, standard-compliant Git commit messages based on the conventional commits specification. Use when you are ready to execute `git commit`.
---

This skill enables the code agent to formulate precise, standard-compliant Git commit messages and branch names based on the Conventional Commits 1.0.0 specification. Adhering to this standard allows automated tools to parse commit histories, bump semantic versions (Major/Minor/Patch) accurately, and generate clean changelogs.

## Requirements & Triggers
- **Trigger**: Whenever the agent completes a task, implements a feature, fixes an issue, or refactors code and is ready to execute `git commit`.
- **Pre-requisite**: Understand the scope of changes and know the associated GitHub Issue number (if any).

## Guidelines & Rules

### 1. Commit Message Structure
Every commit message must strictly follow this structural pattern:
```text
<type>(<scope>): <subject>

<body>

<footer>
```

-	<type> (Required): Must be one of the structural keywords defining the change intent.
-	<scope> (Optional): A noun describing the affected section of the codebase enclosed in parentheses (e.g., auth, api, parser).
-	<subject> (Required): A succinct description of the change. Use imperative mood ("add" not "added"). No period . at the end.
-	<body> (Optional): Detailed explanatory text, providing the motivation for the change and contrasting it with previous behavior.
-	<footer> (Optional): Used to reference tracking issues (e.g., Fixes: #123) or denote breaking changes.


### 2. Allowed Commit Types ( <type> )
| Type | Definition | SemVer Impact |
| :--- | :--- | :--- |
| `feat` | A new feature implemented in the codebase | **Minor** |
| `fix` | A bug fix implemented in the codebase | **Patch** |
| `docs` | Documentation only changes (e.g., markdown files) | None |
| `style` | Changes that do not affect the meaning of the code (white-space, formatting, etc.) | None |
| `refactor` | A code change that neither fixes a bug nor adds a feature | None |
| `perf` | A code change that improves performance | None |
| `test` | Adding missing tests or correcting existing tests | None |
| `build` | Changes that affect the build system or external dependencies | None |
| `ci` | Changes to CI configuration files and scripts | None |
| `chore` | Other changes that don't modify src or test files (e.g., .gitignore) | None |

### 3. Handling Breaking Changes
A breaking change must be indicated by an exclamation mark ! immediately after the type/scope, or by including BREAKING CHANGE: at the beginning of the footer. This triggers a Major version bump.

### 4. Issue Correlation Rule
When resolving a **tracked** issue, the agent MUST reference the issue number in the footer using specific keywords (Fixes: #<id>, Closes: #<id>) to trigger GitHub's automated issue-closure workflows.


## Examples
### Example 1: Standard Feature with Scope
```text
feat(auth): add JWT token expiration validation

Introduce an automated expiry verification check on the middleware layer 
to automatically reject tokens older than 15 minutes.
```
### Example 2: Bug Fix Correlated with Issue
```text
fix(api): prevent null pointer exception during report export

Ensure that user profile data is properly validated before serialization
to prevent catastrophic crashes on empty profiles.

Fixes: #142
```

### Example 3: Breaking Change (API Refactoring)
```text
refactor(core)!: drop support for legacy v1 endpoint routes

The old v1 gateway endpoints have been deprecated for 6 months and are 
now completely stripped out of the routing framework.

BREAKING CHANGE: Requests sent to `/api/v1/*` will now return a 404 error.
```

### Example 4: Branch Naming Pattern
When creating a branch to work on an issue, use the type and issue number format:
```bash
git checkout -b fix/142-null-pointer-export
```
