# portfolio-ui (shared UI kit)

This directory is intentionally identical across the portfolio repos and is designed to be managed via **git subtree**.

## Why subtree?

- Keeps the repos independent (no runtime coupling), while still sharing UI building blocks.
- Updates are explicit and reviewable.

## Subtree workflow (example)

> Replace `<your-portfolio-ui-repo-url>` with the repo that contains the canonical `portfolio-ui` source.

```bash
# Add once
git subtree add --prefix web/src/portfolio-ui <your-portfolio-ui-repo-url> main --squash

# Pull updates
git subtree pull --prefix web/src/portfolio-ui <your-portfolio-ui-repo-url> main --squash

# Push changes back (if you edit here first)
git subtree push --prefix web/src/portfolio-ui <your-portfolio-ui-repo-url> main
```

## Contents

- **shadcn-style UI primitives** (Tailwind-based): Button, Card, Badge, Input, etc.
- **AppShell** layout shared across apps (consistent look/feel)
- **DataTable** (TanStack Table + TanStack Virtual) for performant lists
- **RangeSlider** (TanStack Ranger) for sliders
- **Devtools** (TanStack Devtools + Query/Router/Pacer plugins)
