---
name: context7-mcp
description: Fetch current dependency and tool documentation for setup, configuration, API usage, and version-specific questions, including Rust crates, Cargo, Tokio, Alloy, Serde, and Foundry. Do not use for ordinary business-logic debugging or general programming concepts.
---

When the user asks about libraries, frameworks, or needs code examples, use Context7 to fetch current documentation instead of relying on training data.

## When to Use This Skill

Activate this skill when the user:

- Asks setup or configuration questions ("How do I configure a Cargo workspace?")
- Requests library-specific code ("How do Alloy providers track receipts?")
- Needs API references ("How do Tokio task cancellation APIs work?")
- Needs version-specific crate, SDK, CLI, or cloud-service behavior.

## How to Fetch Documentation

### Step 1: Resolve the Library ID

Call `resolve-library-id` with:

- `libraryName`: The library name extracted from the user's question
- `query`: The user's full question (improves relevance ranking)

### Step 2: Select the Best Match

From the resolution results, choose based on:

- Exact or closest name match to what the user asked for
- Description relevance, snippet coverage, and source reputation (prefer High or Medium)
- Higher benchmark scores indicate better documentation quality
- If the user mentioned a version, prefer version-specific IDs

### Step 3: Fetch the Documentation

Call `query-docs` with:

- `libraryId`: The exact ID returned by resolution
- `query`: The user's specific question

### Step 4: Use the Documentation

Incorporate the fetched documentation into your response:

- Answer the user's question using current, accurate information
- Include relevant code examples from the docs
- Cite the library version when relevant

## Guidelines

- **Be specific**: Pass the user's full question as the query for better results
- **Version awareness**: Read `Cargo.lock`, the owning manifest's feature flags, and `rust-toolchain.toml` before choosing version-specific documentation.
- **Prefer official sources**: When multiple matches exist, prefer official/primary packages over community forks
