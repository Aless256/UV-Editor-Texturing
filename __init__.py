import bpy
import bmesh

bl_info = {
    "name": "UV Material Sync",
    "author": "AlexandrCG",
    "version": (1.81),
    "blender": (5, 0, 1),
    "location": "Automated (UV Editor <-> 3D View)",
    "description": "Syncs UV Editor image with selected face material and vice versa",
    "category": "UV",
}

last_image_name = ""
last_selected_faces_key = None  # frozenset пар (индекс грани, индекс материала)


def get_image_from_material(mat):
    if mat and mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                return node.image
    return None


def sync_logic(context):
    global last_image_name, last_selected_faces_key

    obj = context.active_object
    if not obj or obj.type != 'MESH' or obj.mode != 'EDIT':
        return

    uv_area = next((a for a in context.screen.areas if a.type == 'IMAGE_EDITOR'), None)
    if not uv_area:
        return

    img_editor = uv_area.spaces.active
    bm = bmesh.from_edit_mesh(obj.data)

    selected_faces = [f for f in bm.faces if f.select]

    # Ключ текущего выделения: frozenset пар (индекс грани, индекс материала)
    current_key = frozenset((f.index, f.material_index) for f in selected_faces)

    # --- НАПРАВЛЕНИЕ А: От Полигона к Редактору ---
    if current_key != last_selected_faces_key:
        last_selected_faces_key = current_key

        if selected_faces:
            # Собираем уникальные материалы среди выделенных полигонов
            unique_mat_names = set()
            for face in selected_faces:
                if obj.data.materials and face.material_index < len(obj.data.materials):
                    mat = obj.data.materials[face.material_index]
                    if mat:
                        unique_mat_names.add(mat.name)

            # Синхронизируем ТОЛЬКО если у всех полигонов один и тот же материал
            if len(unique_mat_names) == 1:
                mat = bpy.data.materials.get(next(iter(unique_mat_names)))
                face_img = get_image_from_material(mat)
                if face_img and (not img_editor.image or img_editor.image != face_img):
                    img_editor.image = face_img
                    last_image_name = face_img.name
                    uv_area.tag_redraw()

            # Если материалы разные — не трогаем редактор

        return  # Выделение изменилось — не проверяем Направление Б в этот тик

    # --- НАПРАВЛЕНИЕ Б: От Редактора к Полигонам ---
    current_img = img_editor.image
    if current_img and current_img.name != last_image_name:
        last_image_name = current_img.name

        target_mat = None
        for mat in bpy.data.materials:
            if mat and mat.use_nodes and get_image_from_material(mat) == current_img:
                target_mat = mat
                break

        if not target_mat:
            target_mat = bpy.data.materials.new(name=f"Mat_{current_img.name}")
            target_mat.use_nodes = True
            nodes = target_mat.node_tree.nodes
            node_tex = nodes.new(type='ShaderNodeTexImage')
            node_tex.image = current_img
            node_bsdf = nodes.get("Principled BSDF") or nodes.new(type='ShaderNodeBsdfPrincipled')
            target_mat.node_tree.links.new(node_tex.outputs['Color'], node_bsdf.inputs['Base Color'])

        if target_mat.name not in obj.data.materials:
            obj.data.materials.append(target_mat)

        mat_idx = obj.data.materials.find(target_mat.name)

        if selected_faces:
            for face in selected_faces:
                face.material_index = mat_idx
            bmesh.update_edit_mesh(obj.data)
            context.view_layer.update()

            # Обновляем ключ, чтобы не сработало Направление А сразу после
            last_selected_faces_key = frozenset((f.index, mat_idx) for f in selected_faces)


@bpy.app.handlers.persistent
def auto_sync_handler(scene):
    sync_logic(bpy.context)


def register():
    handlers = bpy.app.handlers.depsgraph_update_post
    for h in handlers:
        if h.__name__ == "auto_sync_handler":
            handlers.remove(h)
    handlers.append(auto_sync_handler)


def unregister():
    handlers = bpy.app.handlers.depsgraph_update_post
    for h in handlers:
        if h.__name__ == "auto_sync_handler":
            handlers.remove(h)


if __name__ == "__main__":
    register()