# Qortium CLI architecture

## Product goal

Qortium CLI is a friendly daily-use client, not a thin menu over API tags. It is
organized around what a person is trying to accomplish:

1. Node & Minting
2. Chat & Groups
3. Wallets & Payments
4. QDN Files & Apps
5. Identity & Names
6. Advanced Tools
7. Help
8. Updates
9. Settings

The home screen is the dashboard. It answers the most common questions without
requiring another menu selection: Is my node reachable and synced? Can it mint?
Which account is active?

The Node & Minting workspace follows the same rule: node health and minting
readiness are visible immediately, while setup, settings, bootstrap, restart,
and stop actions live in one workflow-ordered menu below them.

Chat is conversation-first. Entering Chat & Groups opens a persistent Textual
workspace with a unified Direct/Groups inbox, selected timeline, and fixed
composer. Public, encrypted direct, and encrypted private-group conversations
share one user-facing model while retaining separate Core transports. The
sidebar collapses into an overlay on narrow terminals, and synchronous Core
work runs outside the UI event loop. Focus highlights and a pane-aware footer
teach the controls in context. A persisted first-use help dialog explains the
three-pane workflow and gives users an explicit Chat exit action.

## Layers

```text
entrypoint
  -> application shell and navigation
     -> feature hubs (user workflows)
        -> services (Qortium Core operations)
           -> HTTP transport

application shell
  -> UI components
     -> Rich for durable layouts
     -> Textual for the live, resizable chat workspace
     -> TerminalTextEffects for bounded motion
```

- `qortium_cli.app` owns startup and the main event loop only.
- `qortium_cli.navigation` defines the stable top-level information
  architecture.
- `qortium_cli.features` owns workflow-level screens.
- `qortium_cli.services` contains Core operations and will be split into typed
  service modules as each feature is rebuilt.
- `qortium_cli.ui` owns presentation, input, color, motion, and terminal
  capability fallbacks.
- `qortium_cli.tools` is a compatibility layer for proven workflows during the
  rebuild. New feature code should not accumulate there.

## Navigation rules

- Numbers have one meaning at a given level and `0` always goes back or exits.
- Daily workflows appear before maintenance and developer tools.
- Related read and write actions live together.
- Destructive node operations never appear on the dashboard.
- Public chat, direct private chat, and private group chat remain visibly
  distinct.
- QDN publishing, downloading, status, and local cache management stay in one
  feature area.
- Raw API calls and transaction builders are advanced tools.

## Visual rules

- Color communicates state: cyan is navigation, violet is identity, green is
  healthy/success, amber is waiting/warning, and red is failure/destructive.
- Rich renders persistent information. TerminalTextEffects renders short,
  bounded transitions and never owns application state.
- Motion supports `full`, `reduced`, and `off`. It is automatically disabled
  for non-interactive output, CI, `NO_COLOR`, and dumb terminals.
- Every animated state has a static equivalent.
- Screens must remain usable at 80 columns. Wider terminals may show additional
  columns but never different actions.

## Release constraints

- Python code and package assets are the source of truth on all platforms.
- Runtime data is stored outside the installation directory.
- The console entry point is `qortium-cli`; platform binaries wrap that same
  entry point.
- PyInstaller builds run natively on Windows, macOS, and Linux because binaries
  cannot be reliably cross-compiled.
- A tagged GitHub release is created only after tests and all platform builds
  succeed.

## Migration strategy

The existing Core transaction, chat formatting, wallet backup, and setup logic
is retained behind the new shell. Feature-by-feature work then moves API calls
out of the compatibility modules into typed services, with tests added before
the old path is removed. This keeps the CLI usable throughout the redesign.
