# Changelog

All notable changes to this integration will be documented in this file.

## 0.1.1 - 2026-08-02

- Serialize setup, unload, and reconfiguration lifecycle operations so active
  coordinator polling cannot race configuration-flow access to the RS485 bus.
- Show a localized retry message when another reconfiguration or reload is still
  in progress instead of allowing overlapping scans.
- Wait for serial transports to close completely before reopening the same port.
- Require `huawei-esm48100==0.1.1` for matching protocol transport lifecycle
  serialization.

## 0.1.0 - 2026-07-30

- Initial public release.
- Add serial RTU and transparent TCP RTU configuration.
- Add multi-battery discovery, polling, diagnostics, and reconfiguration.
- Expose pack, cell, alarm, version, bar-code, and electronic-label entities.
- Add optional allowlisted controls, disabled by default.
