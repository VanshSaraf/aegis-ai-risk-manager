# Aegis Public Release Checklist

## Automated and local checks

- [ ] Run `make verify`.
- [ ] Run the complete Python suite with a disposable PostgreSQL database.
- [ ] Run migrations from an empty database and confirm `alembic check` is clean.
- [ ] Start the showcase with `make up`, then run `make smoke`.
- [ ] Confirm dashboard, simulation, graph, investigation, and Evaluation Lab in a browser.
- [ ] Stop services with `make down`.

## Repository release

- [ ] Review `git status --short`, `git diff`, and `git diff --check`.
- [ ] Confirm no `.env`, credentials, generated datasets, caches, or local absolute paths are tracked.
- [ ] Commit the final changes manually.
- [ ] Push manually and make the GitHub repository public.
- [ ] Verify the repository URL works without authentication.
- [ ] Verify README tables, links, and the Mermaid architecture diagram render on GitHub.
- [ ] Perform one final clean-clone test on a local machine using the documented commands.

## Submission

- [ ] Remove or disable any local secrets before sharing logs or screenshots.
- [ ] Submit before the deadline and verify the submission confirmation.
