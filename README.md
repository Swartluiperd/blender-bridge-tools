# Blender Bridge Tools

A small Blender add-on that makes block-grid models **manifold** (watertight)
for 3D printing by adding tiny square "bridges" wherever two blocks — or two
holes — touch only along a single edge. It also includes a **Step Through
Selection** helper for inspecting flagged problem spots one at a time.

Developed by [Swartluiperd](https://github.com/Swartluiperd) with the help of
Claude (Anthropic).

---

## The problem

Models built from a grid of square blocks — height-map tiles, terrain,
pixel or voxel-style art — often contain spots where two diagonal blocks
meet only along one vertical edge, like the black squares on a chessboard:

```
+------+------+
| LOW  | HIGH |        Seen from above.
|      |      |
+------X------+        X = the shared vertical edge.
| HIGH | LOW  |
|      |      |
+------+------+
```

That shared edge belongs to **four** wall faces instead of two, so the mesh
is **non-manifold**. Blender's 3D Print Toolbox reports these as
"Non-manifold Edges", and slicers can't tell whether the two blocks should
be joined or separate. The result is slicing errors, holes or missing layers.

Fixing a handful by hand is fine. Fixing dozens on every tile is not.

## The fix

At each such corner the add-on builds a small square **bridge post**
(0.2 × 0.2 mm by default) centred on the shared edge. The post joins the two
diagonal high blocks and gives every edge exactly two faces.

```
+------+------+
| LOW  | HIGH |        The post (#) fills a tiny square around X,
|     #|#     |        joining the two HIGH blocks.
+-----##------+
| HIGH |#     |
|      |      |
+------+------+
```

It handles two kinds of corner:

- **Step corners**: the low quadrants are lower blocks. The post stands on
  each lower block and rises to the top of the edge.
- **Hole corners**: a low quadrant is a through-hole. The post fills that
  corner of the hole from the very bottom of the model to the top.

## Requirements

- Blender **4.2 or newer**. Developed and tested on Blender 5.2.
- An **axis-aligned** model: block walls face ±X / ±Y and block tops are
  flat. This is how block grids are normally built.

## Installation

1. Download [`bridge_tools.py`](bridge_tools.py).
2. In Blender, open *Edit → Preferences → Add-ons*.
3. Click the **▾** menu (top right) → **Install from Disk…**, then choose
   `bridge_tools.py`.
4. Tick the checkbox to enable **Bridge Tools (non-manifold corner fixer)**.

## Usage

Select your object and enter **Edit Mode** (Tab). The tools appear in three
places:

- Sidebar: press **N** and open the **Bridges** tab
- *Mesh* menu (bottom of the list)
- Right-click context menu

### Auto-Bridge Diagonal Corners (recommended)

No selection needed. It finds **every** 4-face vertical edge in the mesh and
builds a bridge post into the existing geometry. When it finishes, the
status bar reports:

```
Bridged 12 corner(s). Non-manifold edges now: 0.
```

If a corner doesn't match the expected layout, it is **skipped and left
untouched**, and its position is listed in the message, e.g.
`Skipped 1 unusual corner(s) at (-71.25, -6.25) mm.`

### Add Bridge Cube on Selection

The manual approach. Select one or more **vertical edges**, or exactly
**two vertices** (the top and bottom of the problem edge), then run it. A
square cube spanning that height is added and merged into the mesh with
Blender's *Intersect (Boolean)* Union.

- Turn off **Union into Mesh** in the operator panel (bottom left after
  running) to add only the cube without merging.
- Booleans can fail on meshes that were scaled, copied or joined, because
  of tiny floating-point differences. If the reported non-manifold count
  goes **up**, press **Ctrl+Z** and use Auto-Bridge instead.

### Step Through Selection

A helper for inspecting problem spots one at a time. It lives in the
**Step Through Selection** box in the sidebar panel.

1. Select the elements you want to inspect. For example, click
   *Non-manifold Edges* or *Zero Edges* in the 3D Print Toolbox results,
   which selects them. Or use *Select → Select All by Trait*.
2. Click **Next** (or **Previous**) to move through them one by one.

Each step:

- centres the view on the element and, if **Zoom to Element** is ticked,
  zooms in to about 8× its size (never closer than 2 mm);
- makes it the **active** element, drawn highlighted, so you can see
  exactly which one you're on;
- shows its number and a measurement in the panel and status bar, e.g.
  `Edge 3 of 17: length 0.1000 mm, at (12.500, -6.250, 0.197) mm`.

Notes:

- The **selection is never changed**. All the elements stay selected, so
  you can still fix them all at once afterwards.
- The element type follows the select mode: vertices, edges or faces
  (keys **1 / 2 / 3** in Edit Mode). Vertices report how many faces use
  them, edges report their length, and faces report their area.
- Stepping wraps around at either end. Changing the selection or the
  select mode starts again from 1.
- Tip: untick **Zoom to Element** to keep your current zoom level and only
  pan to each element.

### Bridge size

Set **Bridge Size (mm)** in the sidebar panel before running either tool.
The size is in real-world millimetres; the add-on accounts for the scene's
unit scale and the object's scale.

- **0.2 mm** (default) suits resin printers.
- For FDM printers, use at least one nozzle width, e.g. **0.4 mm**.

## Tips

- **Keep a backup.** Duplicate the object (Shift+D, then right-click to
  cancel the move) and hide the copy before bridging. Both tools can be
  undone with **Ctrl+Z**.
- **Check afterwards.** Run *3D Print Toolbox → Check All*, or *Select →
  Select All by Trait → Non-Manifold*, to confirm the count is 0.
- **"Zero Edges" / "Zero Faces" on very small models.** The 3D Print
  Toolbox reports edges and faces smaller than its **Degenerate** threshold,
  which defaults to 0.0001 m (0.1 mm). On fine models, and with 0.2 mm
  bridges, real features can be that small. Lower the threshold to e.g.
  0.000001 m (0.001 mm) and re-check. Anything still reported is genuinely
  degenerate, and **Step Through Selection** makes it easy to inspect.
- **Avoid noise when building tiles.** Position copies by typing exact
  values rather than dragging or scaling them. This keeps coordinates clean,
  which matters most for the Boolean-based tool.
- **Exporting for print.** Blender works in metres while STL files have no
  units, so set the STL export **Scale** to 1000 if your slicer reads the
  model as 1000× too small.

## How it works

Auto-Bridge works directly on the mesh using `bmesh` and does not use a
Boolean. For each problem edge it:

1. Collects the vertical chain of vertices at that X/Y position, from the
   top of the edge down to the lowest vertex on that line.
2. Works out which two diagonal quadrants are **low**, from the normals of
   the four wall faces that share the edge.
3. Finds each low quadrant's **floor**: the top face of the lower block, or
   the bottom of the model if the quadrant is a through-hole.
4. Splits the horizontal edges around the corner at half the bridge width,
   making room for the post.
5. Rebuilds the faces around the corner: shortened walls, the post's top
   and two sides, and either a notch in the lower block's top face or a
   bottom face for a hole.

If a corner fails, the tool first dissolves any slanted seams between flat,
coplanar wall faces (often left behind by Booleans or triangulation), then
retries once. Before changing anything, it checks that every edge it needs
exists. Corners that still don't fit are skipped, so the mesh is never left
half-edited.

## Limitations

- Only **vertical** problem edges in **axis-aligned** geometry are handled.
- The walls next to the corner must be longer than 1.5× half the bridge
  width. At the default 0.2 mm, that's about 0.15 mm.
- Non-manifold edges of other kinds, such as open holes or cracks
  (1-face edges) and loose geometry, are **not** fixed by this add-on. Use
  *Merge by Distance*, *Fill* or *3D Print Toolbox → Make Manifold* for those.

## Licence

[MIT](LICENSE). Free to use, modify and share, including commercially, as long
as the copyright and licence notice are kept.

> Note: Blender itself is GPL. If you ever want to publish this add-on on
> Blender's official Extensions platform, that platform expects add-ons to be
> GPL-compatible. MIT is GPL-compatible, but check the platform's current
> requirements before submitting.

## Credits

Written by **Swartluiperd**, with code and documentation developed using
**Claude** (Anthropic).
