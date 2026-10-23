# 0.6.1

- Live controller diagrams for Xbox, PlayStation, Switch, GameCube and keyboard;
  raw joysticks display their numbered inputs. Sticks, triggers and bindings
  respond in the preview. Controller input never navigates the launcher.
- Controller defaults now include device-family settings. Profile loading,
  keyboard reset, pending saves, automatic slots and reconnect handling were
  repaired. Keyboard movement keys and trigger threshold can be edited.
- Display saves preserve supported values and unrelated preferences. Audio,
  connection and verification controls report errors and preserve current choices.
  Concurrent settings saves no longer overwrite one another.
- Signed offline updates, safer extraction, restart/rollback repairs and a bundled
  GitHub release-feed setting. Game data and the completed build remain in place.

The rb3 gameplay runtime is unchanged. Real GameCube adapter troubleshooting and
online gameplay validation are still pending. UI/RPC checks use simulated input;
they do not establish compatibility with a physical adapter.
