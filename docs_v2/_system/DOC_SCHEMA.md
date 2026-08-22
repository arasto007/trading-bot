# Documentation Schema

Every verified current-state document should follow this structure.

## Status

- Status: VERIFIED / PARTIAL / UNKNOWN
- Last Verified:
- Verification Method:

## Scope

What part of the system this document describes.

## Current Behavior

Only behavior proven by the current source code.

## Active Components

Components currently reachable on the documented execution path.

## Disabled Components

Components that exist but are currently disabled.

## Unreachable Components

Components that cannot be reached under the documented runtime configuration.

## Unknowns

Facts that cannot currently be proven from the repository.

## Evidence

For every important claim, provide:

- File
- Symbol
- Relevant configuration key if applicable
- Test or runtime artifact if applicable

## Change Impact

Source areas that can make this document stale.

## Verification

Commands/checks used to verify this document.
