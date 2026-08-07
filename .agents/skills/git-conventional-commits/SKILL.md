---
name: git-conventional-commits
description: Formulate precise Git commit messages that conform to Conventional Commits 1.0.0 and the target repository's documented conventions. Use when changes are staged and you are ready to execute `git commit`.
---

# Git Conventional Commits

## Goal

Formulate a commit message that describes the staged change accurately. Follow
[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) and any applicable
conventions in the target repository. Keep repository-specific rules separate from requirements
of the standard.

## Workflow

### 1. Inspect the Staged Change

- Run `git status --short` and inspect `git diff --cached`.
- Stop if no change is staged.
- Confirm that the staged change represents one atomic intent.
- If the staged change contains unrelated intents, stop and split it before formulating the
  message.

### 2. Find Repository Conventions

Check the target repository for commit-message rules, validator configuration, and release or
merge policy. These sources can define:

- An allowed or preferred type set.
- Scope conventions.
- Description style, capitalization, punctuation, or line length.
- Required issue references or footer syntax.
- How commit messages affect releases and version numbers.

Apply these rules when they exist. Do not present them as requirements of Conventional Commits.

### 3. Formulate the Message

Use this Conventional Commits grammar:

```text
<type>[optional scope][optional !]: <description>

[optional body]

[optional footer(s)]
```

- **type** is a noun that identifies the kind of change. `feat` introduces a feature, and `fix`
  corrects a bug. The standard permits other types. Use the repository's type vocabulary when it
  defines one.
- **scope** is an optional noun in parentheses that identifies a section of the codebase. Use the
  repository's scope vocabulary when it defines one.
- **description** is a short summary of the staged change.
- **body** provides optional context about the change.
- **footer** records optional metadata. Format footer tokens as specified by Conventional Commits
  and any applicable repository or hosting policy.

Indicate a breaking change in either of these ways:

- Add `!` immediately before the colon.
- Add a `BREAKING CHANGE: <description>` footer.

In Conventional Commits, `fix` corresponds to a patch change, `feat` corresponds to a minor
change, and a breaking change corresponds to a major change under Semantic Versioning. Before
predicting an actual release or version number, check the target repository's release policy.
Other types have no implicit effect on Semantic Versioning unless they indicate a breaking
change.

Add issue-closing or issue-reference footers only when the repository and hosting platform define
their meaning. Check the merge policy before assuming that a footer in an individual commit will
reach the default branch or close an issue.

### 4. Validate the Message

Before committing, confirm that:

- The message matches the staged change and does not describe unstaged work.
- The message follows the Conventional Commits grammar.
- The type, scope, description, and footers follow applicable repository conventions.
- A breaking marker is present when the staged change breaks a public contract.
- Any claimed issue or release effect is supported by the target repository's policy.

If authorized to commit, use the validated message without changing its meaning.

## Examples

### Feature with a Scope

```text
feat(auth): reject expired access tokens

Check the expiration time before accepting an access token.
```

### Fix with an Issue Reference Defined by the Repository

```text
fix(export): handle profiles without a display name

Use an empty label when the profile has no display name.

Fixes: #142
```

Use the footer in this example only when the repository and hosting platform assign the intended
meaning to `Fixes: #142`.

### Breaking Change

```text
refactor(router)!: remove v1 route support

BREAKING CHANGE: Requests to `/api/v1/*` now return a 404 response.
```
