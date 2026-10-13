# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Swartluiperd
#
# Bridge Tools - a Blender add-on that fixes "diagonal contact" non-manifold
# edges by adding small square bridge posts.
#
# Developed with the help of Claude (Anthropic).
# See README.md for background, installation and usage.

"""
Bridge Tools
============

The problem
-----------
Models built from a grid of square blocks (height maps, tile reliefs, pixel
art, voxel-style designs) often contain places where two blocks - or two
holes - touch only along a single vertical edge, like the black squares of a
chessboard:

    +-----+-----+
    | LOW |HIGH |      Seen from above.  The two HIGH blocks touch only at
    |     |     |      the centre edge, and so do the two LOW areas.
    +-----X-----+
    |HIGH | LOW |      X = the shared vertical edge.
    |     |     |
    +-----+-----+

That shared edge is used by FOUR wall faces instead of two, which makes the
mesh "non-manifold". Slicers cannot tell whether the two HIGH blocks are
joined or separate, so they often produce errors, holes or missing layers.

The fix
-------
At each such corner we add a tiny square "post" (by default 0.2 x 0.2 mm)
that fills the corner, joining the two HIGH blocks with a thin bridge:

    +-----+-----+
    | LOW |HIGH |      The post (#) fills a small square centred on X,
    |    #|#    |      raising the two LOW quadrants' corners up to the
    +----##-----+      HIGH level. Every edge now has exactly two faces.
    |HIGH |#    |
    |     |     |
    +-----+-----+

Two tools are provided:

1. Auto-Bridge Diagonal Corners (recommended)
   Finds every 4-face vertical edge and builds the post directly into the
   existing mesh by splitting edges and rebuilding the faces around the
   corner. No Boolean is used, so the result is exact and robust even on
   meshes that were scaled, copied or joined together.

2. Add Bridge Cube on Selection
   The "manual" approach: adds a cube around each selected vertical edge
   (or around a selected top and bottom vertex) and merges it into the mesh
   with Blender's Intersect (Boolean) Union. Simple, but Booleans can fail
   on meshes with tiny floating-point noise - if the non-manifold count goes
   up, undo and use Auto-Bridge instead.

Assumptions (Auto-Bridge)
-------------------------
* The model is axis-aligned: block walls face +X, -X, +Y or -Y and block
  tops are flat (normal pointing +Z).
* The problem edge is vertical (both vertices share the same X and Y).
* Each wall next to the corner is at least 1.5x the post half-width long,
  so there is room to split it.
Corners that do not meet these assumptions are skipped and reported, and
the mesh is left unchanged at those corners.
"""

bl_info = {
    "name": "Bridge Tools (non-manifold corner fixer)",
    "author": "Swartluiperd (developed with Claude, Anthropic)",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Edit Mode > Sidebar (N) > Bridges tab, and Mesh / right-click menus",
    "description": "Fixes 'diagonal contact' non-manifold edges (4 faces on one vertical edge) "
                   "by adding small square bridge posts.",
    "doc_url": "https://github.com/Swartluiperd/blender-bridge-tools",
    "tracker_url": "https://github.com/Swartluiperd/blender-bridge-tools/issues",
    "category": "Mesh",
}

import bpy
import bmesh
from mathutils import Vector
from bpy.props import FloatProperty, BoolProperty


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _mm_to_local(obj, mm):
    """Convert a size in millimetres (world space) to the object's local units.

    Blender stores coordinates in metres by default (Scene > Units > Unit
    Scale = 1.0). The object may also be scaled, so we divide by the
    object's average X/Y scale to get the size in its own mesh coordinates.
    """
    scale = obj.matrix_world.to_scale()
    s = (abs(scale.x) + abs(scale.y)) / 2 or 1.0
    unit = bpy.context.scene.unit_settings.scale_length or 1.0
    return (mm / 1000.0) / unit / s


# The four horizontal directions a block wall can run in.
DIRS = {
    '+x': Vector((1, 0, 0)), '-x': Vector((-1, 0, 0)),
    '+y': Vector((0, 1, 0)), '-y': Vector((0, -1, 0)),
}


def _same_xy(a, b, tol=1e-7):
    """True if two vertices lie on the same vertical line."""
    return abs(a.co.x - b.co.x) < tol and abs(a.co.y - b.co.y) < tol


def _hedge(v, d, h):
    """Return the horizontal edge leaving vertex `v` in direction `d`.

    Only edges longer than 1.5x the post half-width `h` are accepted, so
    that splitting the edge at distance `h` leaves a sensible remainder.
    Returns None if no such edge exists.
    """
    for e in v.link_edges:
        o = e.other_vert(v)
        dv = o.co - v.co
        if (abs(dv.z) < 1e-7
                and dv.length > h * 1.5
                and abs(dv.normalized().dot(d) - 1) < 1e-5):
            return e
    return None


def _split_dir(bm, v, d, h):
    """Split the horizontal edge leaving `v` in direction `d` at distance `h`.

    Returns the new vertex (placed exactly at v + d*h), or None if there is
    no suitable edge in that direction.
    """
    e = _hedge(v, d, h)
    if e is None:
        return None
    length = (e.other_vert(v).co - v.co).length
    _new_edge, nv = bmesh.utils.edge_split(e, v, h / length)
    nv.co = v.co + d * h  # snap exactly, avoiding floating-point drift
    return nv


def _dissolve_slanted_coplanar(bm, verts):
    """Remove slanted seams between flat, coplanar wall faces near `verts`.

    Meshes produced by Booleans or triangulation sometimes split a flat
    vertical wall into several pieces with diagonal edges between them.
    Those diagonal edges stop Auto-Bridge from finding a clean vertical
    chain of vertices at the corner. Dissolving them merges the pieces back
    into one face without changing the shape or volume.
    Returns the number of edges dissolved.
    """
    faces = set(f for v in verts for f in v.link_faces)
    edges = set(e for f in faces for e in f.edges)
    to_dissolve = []
    for e in edges:
        if len(e.link_faces) != 2:
            continue
        d = e.verts[1].co - e.verts[0].co
        is_slanted = abs(d.z) > 1e-9 and (abs(d.x) > 1e-9 or abs(d.y) > 1e-9)
        if is_slanted:
            f1, f2 = e.link_faces
            coplanar_wall = f1.normal.dot(f2.normal) > 0.99999 and abs(f1.normal.z) < 1e-3
            if coplanar_wall:
                to_dissolve.append(e)
    if to_dissolve:
        bmesh.ops.dissolve_edges(bm, edges=to_dissolve, use_verts=False)
    return len(to_dissolve)


# ---------------------------------------------------------------------------
# The core: bridge one corner
# ---------------------------------------------------------------------------

def _bridge_one(bm, e, h):
    """Build a bridge post at one 4-face vertical edge `e`.

    `h` is half the post width in local units. Returns True on success, or
    False if the corner does not match the expected layout (in which case
    the mesh is NOT modified).

    Overview of the steps:
      1. Collect the vertical "chain" of vertices at the corner, from the
         top of the problem edge down to the lowest vertex on that line.
      2. Work out which two diagonal quadrants are LOW (the ones the post
         must fill) from the normals of the four wall faces.
      3. For each LOW quadrant, find its "floor": the top face of the lower
         block, or - if the quadrant is a through-hole - the bottom of the
         chain. The post in that quadrant runs from the floor to the top.
      4. Split the horizontal edges around the corner at distance h, so
         the walls can be shortened to make room for the post.
      5. Delete the old wall faces around the corner and rebuild them,
         adding the post's top, two side faces, and either a bottom face
         (hole) or a notch in the lower block's top face.
    """
    v0, v1 = sorted(e.verts, key=lambda v: v.co.z)   # v0 = bottom, v1 = top
    x, y, ztop = v0.co.x, v0.co.y, v1.co.z

    # --- 1. vertical chain of vertices below the edge ----------------------
    chain = [v1, v0]
    cur = v0
    while True:
        below = [ed.other_vert(cur) for ed in cur.link_edges
                 if _same_xy(ed.other_vert(cur), cur)
                 and ed.other_vert(cur).co.z < cur.co.z - 1e-9]
        if not below:
            break
        cur = below[0]
        chain.append(cur)
    chain.sort(key=lambda v: v.co.z)                 # bottom ... top

    # --- 2. which two diagonal quadrants are LOW ---------------------------
    # Each wall face touching the edge faces OUT of a high block INTO a low
    # quadrant. Its normal gives one axis of that quadrant; the face's
    # centre gives the other.  Quadrants are written as (sx, sy) with
    # sx, sy in {-1, +1}.
    quadrants = set()
    for f in e.link_faces:
        c = f.calc_center_median()
        n = f.normal
        if abs(n.x) > 0.9:
            quadrants.add((1 if n.x > 0 else -1, 1 if c.y > y else -1))
        elif abs(n.y) > 0.9:
            quadrants.add((1 if c.x > x else -1, 1 if n.y > 0 else -1))
    if len(quadrants) != 2:
        return False                                 # not a simple diagonal corner

    # --- 3. floor of each LOW quadrant ------------------------------------
    plan = []
    for sx, sy in quadrants:
        kx = '+x' if sx > 0 else '-x'
        ky = '+y' if sy > 0 else '-y'
        floor = top_face = None
        # Walk down the chain looking for an upward-facing face whose corner
        # at this vertex opens into quadrant (sx, sy).
        for v in reversed(chain):
            if v is v1:
                continue
            for f in v.link_faces:
                if f.normal.z > 0.9:
                    vs = list(f.verts)
                    i = vs.index(v)
                    neighbours = [vs[i - 1].co - v.co, vs[(i + 1) % len(vs)].co - v.co]
                    q = (1 if sum(n.x for n in neighbours) > 0 else -1,
                         1 if sum(n.y for n in neighbours) > 0 else -1)
                    if q == (sx, sy):
                        floor, top_face = v, f
                        break
            if floor:
                break
        is_hole = floor is None
        if is_hole:
            floor = chain[0]          # through-hole: post runs from the very bottom
        plan.append((sx, sy, kx, ky, floor, top_face, is_hole, floor.co.z))

    # --- sanity checks BEFORE modifying anything --------------------------
    # Every edge we need to split must exist...
    for sx, sy, kx, ky, floor, top_face, is_hole, fz in plan:
        for v, k in ((floor, kx), (floor, ky), (v1, kx), (v1, ky)):
            if _hedge(v, DIRS[k], h) is None:
                return False
    # ...and the chain must only connect to vertical or horizontal edges.
    for v in chain:
        for ed in v.link_edges:
            o = ed.other_vert(v)
            if not _same_xy(o, v) and abs((o.co - v.co).z) > 1e-7:
                return False

    # --- 4. split edges around the corner ---------------------------------
    built = []
    for sx, sy, kx, ky, floor, top_face, is_hole, fz in plan:
        levels = [v for v in chain if v.co.z >= fz - 1e-12]
        split_x = [p for p in (_split_dir(bm, v, DIRS[kx], h) for v in levels) if p]
        split_y = [p for p in (_split_dir(bm, v, DIRS[ky], h) for v in levels) if p]
        split_x.sort(key=lambda v: v.co.z)
        split_y.sort(key=lambda v: v.co.z)
        built.append((sx, sy, floor, top_face, is_hole, fz, split_x, split_y))

    # --- 5. rebuild faces ---------------------------------------------------
    # Wall faces touching the corner lose their corner vertices; the split
    # vertices created above now form their new edge.
    walls = set(f for v in chain for f in v.link_faces if abs(f.normal.z) < 0.1)
    chain_set = set(chain)
    new_faces = [[v for v in f.verts if v not in chain_set] for f in walls]
    old_faces = list(walls)

    for sx, sy, floor, top_face, is_hole, fz, split_x, split_y in built:
        # Outer corner of the post, at floor height (c0) and top height (c1).
        c0 = bm.verts.new((x + sx * h, y + sy * h, fz))
        c1 = bm.verts.new((x + sx * h, y + sy * h, ztop))
        new_faces.append([v1, split_x[-1], c1, split_y[-1]])          # post top
        new_faces.append([c0, c1] + list(reversed(split_x)))          # post side
        new_faces.append([c0, c1] + list(reversed(split_y)))          # post side
        if is_hole:
            new_faces.append([floor, split_x[0], c0, split_y[0]])     # post bottom
        else:
            # The lower block's top face gets a small square notch where
            # the post stands on it.
            vs = list(top_face.verts)
            vs[vs.index(floor)] = c0
            new_faces.append(vs)
            old_faces.append(top_face)

    for f in old_faces:
        bm.faces.remove(f)
    for vs in new_faces:
        bm.faces.new(vs)

    # Clean up chain vertices / edges that are no longer used.
    for v in chain:
        if not v.is_valid:
            continue
        for ed in list(v.link_edges):
            if not ed.link_faces:
                bm.edges.remove(ed)
        if not v.link_edges:
            bm.verts.remove(v)
    return True


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class MESH_OT_auto_bridge_corners(bpy.types.Operator):
    """Fix every diagonal-contact non-manifold edge (4 faces on one vertical edge) """ \
        """by building small square bridge posts directly into the mesh"""
    bl_idname = "mesh.auto_bridge_corners"
    bl_label = "Auto-Bridge Diagonal Corners"
    bl_options = {'REGISTER', 'UNDO'}

    size_mm: FloatProperty(
        name="Bridge Size (mm)", default=0.2, min=0.01, max=10.0,
        description="Width of the square bridge at each corner")

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def invoke(self, context, event):
        # Use the size set in the sidebar panel when run from the UI.
        self.size_mm = context.scene.bridge_tools_size_mm
        return self.execute(context)

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        h = _mm_to_local(obj, self.size_mm) / 2.0    # half the post width

        fixed = 0
        skipped = []          # (x, y) of corners we could not handle
        tried_cleanup = set() # corners where we already tried dissolving seams
        done = set()          # corners to ignore from now on

        # Each successful bridge changes the mesh, so re-scan after every fix.
        for _ in range(500):
            bm.normal_update()
            candidates = [
                e for e in bm.edges
                if len(e.link_faces) == 4 and e.is_valid
                and abs(e.verts[0].co.x - e.verts[1].co.x) < 1e-7
                and abs(e.verts[0].co.y - e.verts[1].co.y) < 1e-7
                and (round(e.verts[0].co.x, 7), round(e.verts[0].co.y, 7)) not in done
            ]
            if not candidates:
                break
            e = candidates[0]
            key = (round(e.verts[0].co.x, 7), round(e.verts[0].co.y, 7))

            if _bridge_one(bm, e, h):
                fixed += 1
                continue

            # First failure at this corner: try removing slanted wall seams,
            # then retry once.
            if key not in tried_cleanup:
                tried_cleanup.add(key)
                if _dissolve_slanted_coplanar(bm, list(e.verts)):
                    continue

            done.add(key)
            skipped.append(key)

        # Final tidy-up: remove loose geometry and make normals consistent.
        for e in [e for e in bm.edges if not e.link_faces]:
            bm.edges.remove(e)
        for v in [v for v in bm.verts if not v.link_edges]:
            bm.verts.remove(v)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bmesh.update_edit_mesh(obj.data)

        non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
        msg = f"Bridged {fixed} corner(s). Non-manifold edges now: {non_manifold}."
        if skipped:
            pts = ", ".join(f"({x * 1000:.2f}, {y * 1000:.2f})" for x, y in skipped[:5])
            msg += f" Skipped {len(skipped)} unusual corner(s) at {pts} mm."
            self.report({'WARNING'}, msg)
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


class MESH_OT_add_bridge_post(bpy.types.Operator):
    """Add a square bridge cube around each selected vertical edge """ \
        """(or around the two selected vertices), spanning their full height"""
    bl_idname = "mesh.add_bridge_post"
    bl_label = "Add Bridge Cube on Selection"
    bl_options = {'REGISTER', 'UNDO'}

    size_mm: FloatProperty(name="Bridge Size (mm)", default=0.2, min=0.01, max=10.0)
    union: BoolProperty(
        name="Union into Mesh", default=True,
        description="Merge the cube(s) with Intersect (Boolean) Union. "
                    "Turn off to just add the cube geometry")

    @classmethod
    def poll(cls, context):
        return context.edit_object is not None and context.edit_object.type == 'MESH'

    def invoke(self, context, event):
        self.size_mm = context.scene.bridge_tools_size_mm
        return self.execute(context)

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        h = _mm_to_local(obj, self.size_mm) / 2.0

        # Each "span" is (x, y, z_bottom, z_top) for one cube.
        spans = []
        for e in (e for e in bm.edges if e.select):
            a, b = e.verts
            if _same_xy(a, b):
                spans.append((a.co.x, a.co.y, min(a.co.z, b.co.z), max(a.co.z, b.co.z)))
        if not spans:
            sel_verts = [v for v in bm.verts if v.select]
            if len(sel_verts) == 2:
                a, b = sel_verts
                spans.append(((a.co.x + b.co.x) / 2, (a.co.y + b.co.y) / 2,
                              min(a.co.z, b.co.z), max(a.co.z, b.co.z)))
        if not spans:
            self.report({'ERROR'},
                        "Select vertical edge(s), or exactly two vertices (top and bottom).")
            return {'CANCELLED'}

        # Deselect everything so that only the new cubes are selected; the
        # Boolean below uses "selected vs. unselected".
        for elem in (*bm.verts, *bm.edges, *bm.faces):
            elem.select = False

        for x, y, z0, z1 in spans:
            vs = [bm.verts.new((x + dx, y + dy, z)) for z in (z0, z1)
                  for dx, dy in ((-h, -h), (h, -h), (h, h), (-h, h))]
            for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
                bm.faces.new([vs[i] for i in idx]).select = True
        bm.select_flush(True)
        bmesh.update_edit_mesh(obj.data)

        if not self.union:
            self.report({'INFO'}, f"Added {len(spans)} bridge cube(s) (not merged).")
            return {'FINISHED'}

        bpy.ops.mesh.intersect_boolean(operation='UNION', use_swap=False,
                                       use_self=False, solver='EXACT')
        bm = bmesh.from_edit_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-9)
        bmesh.update_edit_mesh(obj.data)
        non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
        self.report(
            {'INFO'} if non_manifold == 0 else {'WARNING'},
            f"Added {len(spans)} bridge cube(s). Non-manifold edges now: {non_manifold}."
            + ("" if non_manifold == 0 else " If this went up, undo and use Auto-Bridge instead."))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# User interface
# ---------------------------------------------------------------------------

class VIEW3D_PT_bridge_tools(bpy.types.Panel):
    """Sidebar panel: View3D > N > Bridges (Edit Mode only)."""
    bl_label = "Bridge Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Bridges"
    bl_context = "mesh_edit"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.prop(context.scene, "bridge_tools_size_mm")
        col.separator()
        col.operator(MESH_OT_auto_bridge_corners.bl_idname, icon='MOD_BUILD')
        col.operator(MESH_OT_add_bridge_post.bl_idname, icon='MESH_CUBE')


def _menu(self, context):
    """Adds both tools to the Mesh menu and the right-click menu."""
    self.layout.separator()
    self.layout.operator(MESH_OT_auto_bridge_corners.bl_idname, icon='MOD_BUILD')
    self.layout.operator(MESH_OT_add_bridge_post.bl_idname, icon='MESH_CUBE')


classes = (MESH_OT_auto_bridge_corners, MESH_OT_add_bridge_post, VIEW3D_PT_bridge_tools)


def register():
    bpy.types.Scene.bridge_tools_size_mm = FloatProperty(
        name="Bridge Size (mm)", default=0.2, min=0.01, max=10.0,
        description="Width of the square bridge posts")
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_edit_mesh.append(_menu)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(_menu)


def unregister():
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(_menu)
    bpy.types.VIEW3D_MT_edit_mesh.remove(_menu)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.bridge_tools_size_mm


if __name__ == "__main__":
    register()
