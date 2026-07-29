# Ticket2Patch VS Code extension

This is the initial, zero-build Ticket2Patch companion extension.

It currently provides:

- a Ticket2Patch Activity Bar container;
- a Runs sidebar view;
- a command for entering a Jira ticket key;
- refresh and settings commands;
- a configurable backend URL; and
- a Ticket2Patch status-bar entry.

Backend authentication, API calls, streaming run updates, approvals, and diff
views are intentionally not implemented yet.

## Run locally

1. Open the `extension` directory as a VS Code workspace.
2. Press `F5`.
3. In the Extension Development Host, select the Ticket2Patch icon in the
   Activity Bar.
4. Select **Start from Jira Ticket** and enter a key such as `PAY-142`.

No dependency installation or build step is required for this initial version.
