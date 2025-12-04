import c4d
import math
import random
from collections import defaultdict

# ---------------------------------------------------------
# UV ISLAND DETECTION
# ---------------------------------------------------------

def get_uv_islands(obj):
    uvw_tag = obj.GetTag(c4d.Tuvw)
    if uvw_tag is None:
        return None

    face_to_uvs = defaultdict(set)
    uv_to_faces = defaultdict(set)
    poly_count = obj.GetPolygonCount()

    def uv_key(v):
        return (round(v.x, 5), round(v.y, 5))

    # Build connectivity
    for i in range(poly_count):
        poly = obj.GetPolygon(i)
        uv_data = uvw_tag.GetSlow(i)

        if poly.IsTriangle() and 'd' in uv_data:
            del uv_data['d']

        for key in uv_data:
            uv = uv_data[key]
            k = uv_key(uv)
            face_to_uvs[i].add(k)
            uv_to_faces[k].add(i)

    islands = []
    faces_left = set(range(poly_count))

    while faces_left:
        isl = []
        stack = [next(iter(faces_left))]
        while stack:
            f = stack.pop()
            if f not in faces_left:
                continue

            faces_left.remove(f)
            isl.append(f)

            for uv_val in face_to_uvs[f]:
                for nbr in uv_to_faces[uv_val]:
                    if nbr in faces_left:
                        stack.append(nbr)

        islands.append(isl)

    return islands

# ---------------------------------------------------------
# COMPUTE UV BOUNDS + CENTER PER ISLAND
# ---------------------------------------------------------

def get_island_uv_center(obj, uvw_tag, island):
    min_u, max_u = float('inf'), -float('inf')
    min_v, max_v = float('inf'), -float('inf')

    pts = {}

    for face in island:
        poly = obj.GetPolygon(face)
        uv_data = uvw_tag.GetSlow(face)

        if poly.IsTriangle() and 'd' in uv_data:
            del uv_data['d']

        for k in uv_data:
            uv = uv_data[k]

            u = uv.x
            v = 1.0 - uv.y

            if u < 0 or v < 0:
                continue

            pts[(round(u, 6), round(v, 6))] = (u, v)

    if not pts:
        return None

    for u, v in pts.values():
        min_u = min(min_u, u)
        max_u = max(max_u, u)
        min_v = min(min_v, v)
        max_v = max(max_v, v)

    center_u = (min_u + max_u) * 0.5
    center_v = (min_v + max_v) * 0.5

    return center_u, center_v, min_u, max_u, min_v, max_v

# ---------------------------------------------------------
# UDIM TILE ASSIGNMENT
# ---------------------------------------------------------

def assign_tile(min_u, max_u, min_v, max_v, center_u, center_v):
    tile_u = math.floor(center_u)
    tile_v = math.floor(center_v)

    def inter(minv, maxv, tilec):
        tmin = tilec
        tmax = tilec + 1
        c = max(0, min(maxv, tmax) - max(minv, tmin))
        total = maxv - minv
        return c / total if total > 0 else 0

    def frac(tu, tv):
        return inter(min_u, max_u, tu) * inter(min_v, max_v, tv)

    start_frac = frac(tile_u, tile_v)
    best_tile = (tile_u, tile_v)
    best_frac = start_frac

    # 3×3 neighborhood
    for du in (-1, 0, 1):
        for dv in (-1, 0, 1):
            f = frac(tile_u + du, tile_v + dv)
            if f > best_frac:
                best_frac = f
                best_tile = (tile_u + du, tile_v + dv)

    # Reassign if less than 49% coverage
    if start_frac < 0.49 and best_tile != (tile_u, tile_v):
        return best_tile

    return (tile_u, tile_v)

# ---------------------------------------------------------
# UNIQUE PASTEL PALETTE (NO SIMILAR COLORS)
# ---------------------------------------------------------

def pastel_color_unique(existing_colors, min_dist=0.28):
    """
    Generate a new pastel color far enough from existing ones.
    min_dist = Euclidean RGB distance threshold.
    """

    def random_pastel():
        h = random.random()
        s = 0.30
        v = 1.00

        i = int(h * 6)
        f = h * 6 - i
        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)
        i %= 6

        if i == 0: r,g,b = v,t,p
        elif i == 1: r,g,b = q,v,p
        elif i == 2: r,g,b = p,v,t
        elif i == 3: r,g,b = p,q,v
        elif i == 4: r,g,b = t,p,v
        else:        r,g,b = v,p,q

        return c4d.Vector(r,g,b)

    for _ in range(400):  # retry limit
        c = random_pastel()
        ok = True

        for old in existing_colors:
            dist = math.sqrt(
                (c.x - old.x)**2 +
                (c.y - old.y)**2 +
                (c.z - old.z)**2
            )
            if dist < min_dist:
                ok = False
                break

        if ok:
            return c

    return c  # fallback

# ---------------------------------------------------------
# PROCESS SINGLE OBJECT (USING SHARED MATERIALS)
# ---------------------------------------------------------

def process_object(obj, mat_map):
    uvw = obj.GetTag(c4d.Tuvw)
    if uvw is None:
        print(f"[SKIP] {obj.GetName()} – No UVW tag.")
        return

    islands = get_uv_islands(obj)
    if not islands:
        print(f"[SKIP] {obj.GetName()} – No UV islands.")
        return

    tile_to_islands = defaultdict(list)

    # Assign islands to UDIMs
    for idx, isl in enumerate(islands):
        c = get_island_uv_center(obj, uvw, isl)
        if c is None:
            continue

        cu, cv, min_u, max_u, min_v, max_v = c
        tile = assign_tile(min_u, max_u, min_v, max_v, cu, cv)
        tile_to_islands[tile].append(idx)

    doc = obj.GetDocument()

    # Create selection tags + apply shared materials
    for tile, isl_indices in tile_to_islands.items():

        polys = []
        for i in isl_indices:
            polys.extend(islands[i])

        sel_name = f"{obj.GetName()}_UDIM_{tile[0]}_{tile[1]}"
        sel_tag = c4d.SelectionTag(c4d.Tpolygonselection)
        sel_tag.SetName(sel_name)
        bs = sel_tag.GetBaseSelect()

        for p in polys:
            bs.Select(p)

        obj.InsertTag(sel_tag)

        # Same material for all objects sharing this tile
        mat = mat_map[tile]

        tex = c4d.TextureTag()
        tex.SetMaterial(mat)
        obj.InsertTag(tex)

    c4d.EventAdd()
    print(f"[OK] {obj.GetName()} processed.")

# ---------------------------------------------------------
# MAIN — GLOBAL MATERIAL GENERATION + PER-OBJECT PROCESSING
# ---------------------------------------------------------

def main():
    doc = c4d.documents.GetActiveDocument()
    objs = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_CHILDREN)

    if not objs:
        c4d.gui.MessageDialog("Select at least one object.")
        return

    # ------------------------------------------
    # 1) COLLECT ALL UDIM TILES ACROSS OBJECTS
    # ------------------------------------------
    all_tiles = set()

    for obj in objs:
        uvw = obj.GetTag(c4d.Tuvw)
        if uvw is None:
            continue

        islands = get_uv_islands(obj)
        if not islands:
            continue

        for isl in islands:
            c = get_island_uv_center(obj, uvw, isl)
            if c is None:
                continue
            cu, cv, min_u, max_u, min_v, max_v = c
            tile = assign_tile(min_u, max_u, min_v, max_v, cu, cv)
            all_tiles.add(tile)

    # ------------------------------------------
    # 2) CREATE ONE SHARED MATERIAL PER UDIM TILE
    # ------------------------------------------
    mat_map = {}
    used_colors = []  # for unique pastel spacing

    for tile in sorted(all_tiles):
        color = pastel_color_unique(used_colors, min_dist=0.28)
        used_colors.append(color)

        mat = c4d.BaseMaterial(c4d.Mmaterial)
        mat.SetName(f"Mat_UDIM_{tile[0]}_{tile[1]}")
        mat[c4d.MATERIAL_COLOR_COLOR] = color
        mat[c4d.MATERIAL_USE_REFLECTION] = False
        doc.InsertMaterial(mat)

        mat_map[tile] = mat

    # ------------------------------------------
    # 3) PROCESS EACH OBJECT
    # ------------------------------------------
    for obj in objs:
        process_object(obj, mat_map)

    print("\n=== DONE ===\n")

if __name__ == "__main__":

    main()
