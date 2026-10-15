# Licensing boundary

Reidom-authored source is licensed under Apache-2.0; see the root LICENSE and
NOTICE. Third-party files and dependencies retain their own licenses. The root
license does not grant permission to re-license JUCE or other dependencies.

## JUCE

The pinned JUCE 9 Framework modules are dual-licensed under AGPLv3 and the JUCE
commercial license. See the [upstream license](https://github.com/juce-framework/JUCE/blob/f8f8864172464b9adf9eba6101e1f784838d1597/LICENSE.md)
and [JUCE 9 EULA](https://juce.com/legal/juce-9-licence/).

An Apache-2.0 license for Reidom's own source does not make a combined JUCE build
Apache-only. Building and distributing with JUCE must satisfy the chosen JUCE
licensing route. Distribution under the AGPL route carries its own source and
notice obligations; use under the commercial route may require an appropriate
JUCE commercial license. Obtain qualified advice for your particular distribution.

JUCE is fetched separately by scripts/setup-juce.ps1. Its source and notices
remain unchanged, and no JUCE binary is included in this source commit.

## Other components

The vendored Orbit Lit conversation component retains its Apache-2.0 LICENSE
and its upstream revision record. npm, Rust and Python dependencies retain their
respective licenses; consult their manifests, lockfiles and upstream notices.

Reidom no longer incorporates or distributes Ardour code. No GPL implementation
from the retired host may be copied into the JUCE engine; only independently
designed behavior and contracts may be implemented.

Before distributing binaries, review dependency notices, the applicable JUCE
route, plugin SDK/trademark terms, and licenses for any samples, presets, fonts,
impulse responses or other assets. This document is not a binary-release legal
clearance or a replacement for third-party license texts.
