# JUCE dependency

JUCE is fetched separately and is not re-licensed by Reidom's Apache-2.0 license.

- Upstream: https://github.com/juce-framework/JUCE
- Pinned commit: `f8f8864172464b9adf9eba6101e1f784838d1597`
- Setup: run `./scripts/setup-juce.ps1` from the repository root.
- License: AGPLv3 or the JUCE commercial license; see the upstream `LICENSE.md`.

The local `third_party/JUCE/` checkout is ignored by Reidom's Git repository.
The setup script verifies an existing checkout and never resets local changes.
