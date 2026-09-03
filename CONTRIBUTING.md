# Contributing

Thank you for considering an improvement.

## Before starting

- Search existing issues and pull requests.
- Open an issue before a large behavioral or architectural change.
- Keep each contribution focused on one clear problem.
- Never include credentials, customer information, generated databases, or unrelated files.

## Development workflow

1. Fork the repository.
2. Create a branch such as `feature/short-description` or `fix/short-description`.
3. Install the project using the README.
4. Make the smallest complete change.
5. Run the available lint, build, and test commands.
6. Update documentation when behavior changes.
7. Open a pull request explaining the problem, solution, verification, and any limitations.

## Pull request checklist

- [ ] The project builds or starts successfully.
- [ ] Existing behavior remains compatible or the breaking change is explained.
- [ ] New behavior is tested where practical.
- [ ] User-facing documentation is updated.
- [ ] No secrets, tokens, personal data, or generated runtime files are included.
- [ ] Screenshots are included for meaningful interface changes.
- [ ] Commit messages explain the change clearly.

## Code quality

Prefer readable names, small functions, explicit error handling, and helpful logs. Validate external input. Keep provider-specific logic isolated. Do not add a dependency when the platform or language already provides a clear solution.

## Communication

Be direct and respectful. Explain technical decisions in plain language so maintainers and users can evaluate the tradeoffs.
