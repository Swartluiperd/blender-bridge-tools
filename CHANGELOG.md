# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-10-13

### Added
- **Step Through Selection**: **Previous / Next** buttons in the Bridges
  sidebar panel that cycle through the selected vertices, edges or faces one
  at a time. Each step centres the view (optionally zooming in), makes the
  element active, and shows its number, position and length, area or
  face count. The selection itself is not changed.
- **Zoom to Element** option for the stepper.
- README: explanation of the 3D Print Toolbox's "Zero Edges / Zero Faces"
  results on very small models, and the Degenerate threshold.

### Tested
- On Blender 5.2: stepping forwards and backwards with wrap-around in edge
  and face mode, with the selection left unchanged, and a clear warning when
  nothing is selected.

## [1.0.0] - 2026-10-13

### Added
- **Auto-Bridge Diagonal Corners**: finds every 4-face vertical edge
  (diagonal contact) and builds a square bridge post directly into the mesh,
  without Booleans. Handles both step corners and through-hole corners.
- Automatic cleanup of slanted seams between coplanar wall faces, with one
  retry per corner.
- Safe skipping of corners that don't match the expected layout, with their
  positions reported in the status message.
- **Add Bridge Cube on Selection**: adds a bridge cube around selected
  vertical edges (or a selected top and bottom vertex) and optionally merges
  it with Intersect (Boolean) Union.
- Adjustable bridge size in millimetres. Scene unit scale and object scale
  are taken into account.
- Sidebar panel (**N** → **Bridges**) plus entries in the Edit Mode *Mesh*
  menu and right-click menu.

### Tested
- On Blender 5.2, on three block-grid tiles: 60 × 60 mm (6 step corners),
  about 65 × 60 mm (3 corners next to through-holes) and 100 × 20 mm
  (12 corners, one beside a recessed pocket). All reached 0 non-manifold
  edges, and the volume added matched the expected bridge volume exactly.
