# 0.6.2

- The live controller preview draws the controller you plugged in: Xbox 360, Xbox One,
  Xbox Series, DualShock 3, DualShock 4, DualSense, Switch Pro, Joy-Con (pair or single)
  and GameCube (including Mayflash adapters), each with its own shape, layout and
  button colours. Detected from the SDL controller type and USB vendor/product ids.
- Menu sounds for moving, buttons, screens, toggles, sliders, dialogs and results,
  generated in the app (no sound files). Audio > Menu sounds turns them off or sets
  their volume. The game's sound is not affected.

The rb3 gameplay runtime is unchanged. No game rebuild.

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
