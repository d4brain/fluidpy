"""Run in Blender: blender --background --python build_assets.py.
Creates original extruded cutaway vessels and exports their evaluated meshes.
"""
import bpy, bmesh, json, math
from pathlib import Path
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'web' / 'assets'
OUT.mkdir(parents=True, exist_ok=True)
scene = bpy.data.scenes.new('FluidPy vessels')
bpy.context.window.scene = scene

def rect(x,y,w,h):
    return [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]

def vessel(outer, inner):
    return outer + inner[::-1]

specs = {
 'mug': ('Kaffeetasse', '#e8a56b', [vessel([(-.25,.53),(-.24,.10),(-.19,.05),(.19,.05),(.24,.10),(.25,.53)], [(-.208,.53),(-.198,.13),(-.17,.10),(.17,.10),(.198,.13),(.208,.53)]),
    [( .235,.44),(.36,.44),(.41,.39),(.41,.22),(.36,.17),(.235,.17),(.235,.215),(.33,.215),(.365,.245),(.365,.365),(.33,.395),(.235,.395)]]),
 'glass': ('Trinkglas', '#8dd9e5', [vessel([(-.22,.68),(-.17,.07),(.17,.07),(.22,.68)], [(-.19,.68),(-.14,.12),(.14,.12),(.19,.68)])]),
 'toilet': ('Toilette', '#e1e9ed', [vessel([(-.32,.48),(-.28,.26),(-.17,.18),(.13,.18),(.26,.28),(.30,.48)], [(-.27,.48),(-.23,.30),(-.13,.24),(.10,.24),(.21,.32),(.25,.48)]),rect(-.16,.04,.30,.15),rect(-.24,.015,.47,.055),rect(.30,.28,.15,.49),rect(.28,.76,.19,.04),rect(-.34,.47,.07,.035),rect(.25,.47,.08,.035)]),
 'bowl': ('Schüssel', '#b6c68b', [vessel([(-.36,.38),(-.29,.18),(-.19,.055),(.19,.055),(.29,.18),(.36,.38)], [(-.318,.38),(-.25,.20),(-.17,.10),(.17,.10),(.25,.20),(.318,.38)])]),
 'bucket': ('Eimer', '#6ba9bd', [vessel([(-.30,.61),(-.22,.045),(.22,.045),(.30,.61)], [(-.26,.61),(-.184,.09),(.184,.09),(.26,.61)]),rect(-.32,.59,.06,.04),rect(.26,.59,.06,.04)])
}
catalog = {}
for key,(label,hexcolor,polys) in specs.items():
    collection = bpy.data.collections.new(label)
    scene.collection.children.link(collection)
    rgb = [int(hexcolor[i:i+2],16)/255 for i in (1,3,5)]
    mat = bpy.data.materials.new(label); mat.diffuse_color=(*rgb,1)
    mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=(*rgb,1);bsdf.inputs['Roughness'].default_value=.24
    triangles=[]; objects=[]
    for idx,poly in enumerate(polys):
        n=len(poly)
        verts=[(x,depth,z) for depth in (-.065,.065) for x,z in poly]
        faces=[tuple(range(n-1,-1,-1)),tuple(range(n,2*n))]
        faces += [(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
        mesh=bpy.data.meshes.new(key+str(idx));mesh.from_pydata(verts,[],faces);mesh.update()
        bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
        obj=bpy.data.objects.new(key+str(idx),mesh);collection.objects.link(obj);objects.append(obj);obj.data.materials.append(mat)
        bevel=obj.modifiers.new('Soft ceramic edges','BEVEL');bevel.width=.006;bevel.segments=3
        evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());geo=evaluated.to_mesh();geo.calc_loop_triangles()
        for tri in geo.loop_triangles:
            # Front-facing evaluated mesh, projected into the 2D game plane.
            vs=[geo.vertices[i].co for i in tri.vertices]
            area=(vs[1].x-vs[0].x)*(vs[2].z-vs[0].z)-(vs[1].z-vs[0].z)*(vs[2].x-vs[0].x)
            if abs(area)<1e-10 or sum(v.y for v in vs)>0: continue
            shade=.72+.28*abs(tri.normal.y)
            for v in vs: triangles.extend([round(v.x,6),round(v.z,6),*[round(c*shade,4) for c in rgb]])
        evaluated.to_mesh_clear()
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.export_scene.gltf(filepath=str(OUT/(key+'.glb')),export_format='GLB',use_selection=True,use_active_scene=True)
    catalog[key]={'name':label,'polygons':polys,'vertices':triangles}
    for obj in objects: obj.location.x=list(specs).index(key)*1.05
(OUT/'vessels.json').write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'vessels.blend'))
print('Exported',len(catalog),'Blender vessels to',OUT)
