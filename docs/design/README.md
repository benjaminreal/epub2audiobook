# Plugin UI explorations (2026-10-10)

These are explorations, not decisions. They are HTML mockups of the Calibre plugin's screens, made to compare directions before v0.5. Open them in a browser. `standalone.css` supplies the page theme.

| File | Content |
|---|---|
| `calibre_entry_points.html` | Where a plugin can appear in Calibre (schematic, not a screenshot) |
| `direction_a_calibre_native.html` | A: Calibre-native widgets, a separate small dialog for each moment |
| `direction_b_one_sheet.html` | B: native widgets with brand accents; one batch sheet for decisions and options |
| `direction_c_custom_skin.html` | C: full custom skin with covers first; needs a light and a dark theme |

**Status:** the owner has not chosen a direction yet (open item in `../v1_release_definition.md` §6).

**Identity:** the plugin gets **its own identity** (owner decision, 2026-10-10). B and C borrow colors and type from another project only as placeholders. Replace them with the plugin's own identity before any of this is built.

**Limits of the mockups:**
- They are HTML approximations of Qt dialogs. Qt stylesheet fidelity, especially for C's rounded cards and serif type, has not been tested.
- Book data, durations and the Spanish voice (`ef_dora`, a candidate) are illustrative.

Research behind the screens: `../calibre_plugin_ui_research.md`.
