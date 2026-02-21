# UI Kit

Lightweight component kit used by the EdgeWatch web app.

Design goals:

- **Small**: minimal dependencies; Tailwind + a few shadcn-style primitives.
- **Consistent**: shared spacing, typography, focus rings, and semantic color tokens.
- **Practical**: built for data-heavy dashboards (tables, filters, charts, audit trails).

This folder can be managed via **git subtree** if you want to reuse it across repos.

```bash
# Add once
git subtree add --prefix web/src/ui-kit <your-ui-kit-repo-url> main --squash

# Pull updates
git subtree pull --prefix web/src/ui-kit <your-ui-kit-repo-url> main --squash

# Push changes back
git subtree push --prefix web/src/ui-kit <your-ui-kit-repo-url> main
```
