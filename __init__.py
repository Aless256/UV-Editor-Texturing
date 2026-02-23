bl_info = {
    "name": "UV Editor Texturing",
    "author": "AlexandrCG",
    "version": (2, 0),
    "blender": (4, 0, 0),
    "location": "UV Editor <-> 3D Viewport",
    "description": "Automatic synchronization between selected face materials and UV Editor images",
    "category": "UV",
}

import bpy
import bmesh

class SyncState:
    """Stores the last known state to prevent redundant updates and infinite loops."""
    last_image_name = ""
    last_selection_hash = None

def get_image_from_material(mat: bpy.types.Material) -> bpy.types.Image:
    """
    Finds the first Image Texture node in the material's node tree.
    Returns the associated image or None.
    """
    if mat and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                return node.image
    return None

def get_active_uv_space(context: bpy.types.Context):
    """Returns the active space of the first found Image Editor area."""
    for area in context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            return area.spaces.active
    return None

def ensure_material_for_image(image: bpy.types.Image, obj: bpy.types.Object) -> int:
    """
    Ensures a material with the specified image exists and is assigned to the object.
    Returns the index of the material slot.
    """
    # Try to find an existing material in the blend file with this image
    mat = next((m for m in bpy.data.materials if get_image_from_material(m) == image), None)
    
    # If not found, create a new one with a standard Principled BSDF setup
    if not mat:
        mat = bpy.data.materials.new(name=f"Mat_{image.name}")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.image = image
        bsdf = nodes.get("Principled BSDF") or nodes.new('ShaderNodeBsdfPrincipled')
        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])

    # Add material to object slots if not already present
    if mat.name not in obj.data.materials:
        obj.data.materials.append(mat)
        
    return obj.data.materials.find(mat.name)

# --- Logic 1: UV Editor Image Changes -> Update Face Materials (Timer-based) ---
def uv_to_mesh_poll():
    """Monitors the UV Editor image and applies it to selected faces in 3D View."""
    context = bpy.context
    obj = context.active_object
    
    # Only run in Mesh Edit Mode
    if not (obj and obj.mode == 'EDIT' and obj.type == 'MESH'):
        return 0.1
        
    uv_space = get_active_uv_space(context)
    if not uv_space or not uv_space.image:
        return 0.1

    # Check if the image in the UV editor has changed since the last check
    current_img = uv_space.image
    if current_img.name == SyncState.last_image_name:
        return 0.1
    
    SyncState.last_image_name = current_img.name
    mat_index = ensure_material_for_image(current_img, obj)
    
    # Apply material index to all selected faces
    bm = bmesh.from_edit_mesh(obj.data)
    selected_faces = [f for f in bm.faces if f.select]
    
    if selected_faces:
        for face in selected_faces:
            face.material_index = mat_index
        bmesh.update_edit_mesh(obj.data)
        
        # Update hash to prevent Direction 2 from firing immediately
        SyncState.last_selection_hash = hash(tuple((f.index, mat_index) for f in selected_faces))
        for area in context.screen.areas:
            area.tag_redraw()

    return 0.1

# --- Logic 2: Selection/Material Changes -> Update UV Editor Image (Depsgraph-based) ---
@bpy.app.handlers.persistent
def mesh_to_uv_handler(scene, depsgraph):
    """Monitors face selection in 3D View and updates the UV Editor image."""
    context = bpy.context
    obj = context.active_object
    
    if not (obj and obj.mode == 'EDIT' and obj.type == 'MESH'):
        return
        
    uv_space = get_active_uv_space(context)
    if not uv_space:
        return

    bm = bmesh.from_edit_mesh(obj.data)
    selected_faces = [f for f in bm.faces if f.select]
    if not selected_faces:
        return

    # Check if selection or material assignment has changed via hash
    current_hash = hash(tuple((f.index, f.material_index) for f in selected_faces))
    if current_hash == SyncState.last_selection_hash:
        return
    
    SyncState.last_selection_hash = current_hash
    
    # Identify unique images across selected faces
    mats = obj.data.materials
    images = {get_image_from_material(mats[f.material_index]) 
              for f in selected_faces if f.material_index < len(mats)}
    images.discard(None)

    # If all selected faces share exactly one image, display it in the UV Editor
    # If all selected faces share exactly one image, display it in the UV Editor
    if len(images) == 1:
        img = images.pop()
        if uv_space.image != img:
            uv_space.image = img
            # Ensure the image updates visually (especially for sequences)
            if uv_space.image_user:
                uv_space.image_user.use_auto_refresh = True
            
            SyncState.last_image_name = img.name
            for area in context.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    area.tag_redraw()

# --- Registration ---
def register():
    # Clean up handlers before registering to avoid duplicates
    unregister_handlers()
    bpy.app.handlers.depsgraph_update_post.append(mesh_to_uv_handler)
    
    if not bpy.app.timers.is_registered(uv_to_mesh_poll):
        bpy.app.timers.register(uv_to_mesh_poll, persistent=True)

def unregister_handlers():
    """Removes the depsgraph handler safely."""
    handlers = bpy.app.handlers.depsgraph_update_post
    for h in list(handlers):
        if h.__name__ == "mesh_to_uv_handler":
            handlers.remove(h)

def unregister():
    unregister_handlers()
    if bpy.app.timers.is_registered(uv_to_mesh_poll):
        bpy.app.timers.unregister(uv_to_mesh_poll)

if __name__ == "__main__":
    register()