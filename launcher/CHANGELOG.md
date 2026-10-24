# 0.6.4

- Controllers is laid out like Ryujinx's input settings (player, profile, device and type on top; ZL/L/minus,
  left stick and D-pad left; the picture and trigger threshold in the middle; ZR/R/plus, buttons and right stick
  right), with drawings of each real controller: Xbox 360 / One / Series, DualSense, DualShock 4 / 3, Switch Pro,
  Joy-Con and GameCube, in their real layouts and button colours. Pressed parts light up; sticks move.
- Fullscreen: Play > "Start the game fullscreen" and Display & speed > Game window; F11 in the game is remembered.
- GameCube adapter: Controllers > Test adapter reads a Wii U-mode (WinUSB) adapter for 15 seconds and shows each
  port; "What the game saw last time" shows the game's controller lines. A busy adapter names Steam's GameCube
  Configuration Support and Dolphin / Slippi. Runtime rb5 (no game rebuild).

# 0.6.3

- Updates & build > Game save > Import save file...: load a Smash save backup you have (a JKSV
  backup .zip, its "100" folder, or save_data/system_data.bin) so everyone can play with the
  same save. The current save is backed up first and can be put back. BCAT (Spirit Board)
  data is skipped: this runtime does not read it. CoastLink never ships or downloads saves.
- Hidden rows stay hidden (the update download bar and the save backup list).

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
