# Documentation Map

This map defines one canonical document per topic to prevent overlap and
duplicate maintenance.

## Canonical topic ownership

- Runtime architecture and flow ownership:
  - `architecture.md`
- Database model and data ownership:
  - `database.md`
- Command surface and user-facing command behavior:
  - `commands_reference.md`
- Event taxonomy and event-bus contracts:
  - `events.md`
- Discord platform setup and response model:
  - `discord.md`
- Discord interaction protocol and response lifecycle:
  - `discord_interaction_flows.md`
- Discord UI primitives and component usage:
  - `discord_ui.md`
- Twitch IRC intake and protocol details:
  - `twitch_irc.md`
- Development tooling (ruff, build modes):
  - `development.md`
- Test strategy, test execution, and manual QA:
  - `testing_playbook.md`
- Command/feature extension workflow:
  - `adding_commands.md`
- Public legal templates:
  - `privacy_policy.md`
  - `terms_of_service.md`
- Public repository safety:
  - `repository_security.md`

## Editing rules

- Update the canonical document for the topic first.
- In secondary documents, link to canonical sections instead of repeating
  details.
- Keep examples aligned with the command surface in
  `commands_reference.md`.
