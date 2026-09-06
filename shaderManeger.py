bl_info = {
    "name": "Blender Shader Manager",
    "author": "Buddha",
    "version": (2, 3),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Shaders",
    "description": "Save and load shaders via JSON/ZIP with Categories",
    "category": "Material",
}

import bpy
import json
import os
import zipfile

# --- SERIALIZATION HELPERS ---
EXCLUDE_PROPS = {
    'rna_type', 'name', 'type', 'location', 'width', 'height', 'dimensions',
    'inputs', 'outputs', 'internal_links', 'parent', 'select', 'bl_idname',
    'bl_label', 'bl_description', 'bl_icon', 'bl_static_type', 'bl_width_default',
    'bl_width_min', 'bl_width_max', 'bl_height_default', 'bl_height_min', 'bl_height_max',
    'color', 'use_custom_color'
}

def serialize_value(val):
    if val is None or isinstance(val, (int, float, str, bool)):
        return val
    if isinstance(val, bpy.types.ID):
        return {"__id_type__": getattr(val.rna_type, "name", "ID"), "name": val.name}
    try:
        if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
            return [serialize_value(v) for v in val]
    except Exception:
        pass
    return None

def deserialize_value(val):
    if isinstance(val, dict) and "__id_type__" in val:
        id_type = val["__id_type__"]
        name = val["name"]
        if id_type == 'Object': return bpy.data.objects.get(name)
        if id_type == 'Collection': return bpy.data.collections.get(name)
        if id_type == 'Material': return bpy.data.materials.get(name)
        if id_type == 'Image': return bpy.data.images.get(name)
        if id_type == 'Texture': return bpy.data.textures.get(name)
        if 'NodeTree' in id_type: return bpy.data.node_groups.get(name)
        if id_type == 'Text': return bpy.data.texts.get(name)
        if id_type == 'Action': return bpy.data.actions.get(name)
        return None
    if isinstance(val, list):
        return [deserialize_value(v) for v in val]
    return val

def serialize_node_properties(node):
    props = {}
    for p in node.bl_rna.properties:
        pid = p.identifier
        if pid in EXCLUDE_PROPS or p.is_readonly:
            continue
        try:
            val = getattr(node, pid)
            s_val = serialize_value(val)
            if s_val is not None:
                props[pid] = s_val
        except Exception:
            pass
    return props

def serialize_color_ramp(ramp):
    return {
        "color_mode": ramp.color_mode,
        "interpolation": ramp.interpolation,
        "elements": [{"position": el.position, "color": list(el.color)} for el in ramp.elements]
    }

def restore_color_ramp(ramp, data):
    ramp.color_mode = data.get("color_mode", ramp.color_mode)
    ramp.interpolation = data.get("interpolation", ramp.interpolation)
    elements_data = data.get("elements", [])
    
    while len(ramp.elements) < len(elements_data):
        ramp.elements.new(0.5)
    while len(ramp.elements) > len(elements_data):
        ramp.elements.remove(ramp.elements[-1])
        
    for i, el_data in enumerate(elements_data):
        ramp.elements[i].position = el_data["position"]
        ramp.elements[i].color = el_data["color"]

def serialize_curve_mapping(mapping):
    curves_data = []
    for curve in mapping.curves:
        points = [{"x": p.handle_type, "location": list(p.location)} for p in curve.points]
        curves_data.append(points)
    return curves_data

def restore_curve_mapping(mapping, data):
    for i, curve_data in enumerate(data):
        if i < len(mapping.curves):
            curve = mapping.curves[i]
            while len(curve.points) < len(curve_data):
                curve.points.new(0.5, 0.5)
            while len(curve.points) > len(curve_data):
                curve.points.remove(curve.points[-1])
            for j, p_data in enumerate(curve_data):
                curve.points[j].location = p_data["location"]

# --- CORE EXTRACTION & RESTORATION ---
def extract_node_data(tree):
    shader_data = {"nodes": {}, "links": []}
    image_paths = []
    
    for node in tree.nodes:
        node_info = {
            "type": node.bl_idname,
            "location": [node.location.x, node.location.y],
            "width": getattr(node, "width", 140.0),
            "height": getattr(node, "height", 100.0),
            "label": node.label,
            "hide": getattr(node, "hide", False),
            "mute": getattr(node, "mute", False),
            "use_custom_color": getattr(node, "use_custom_color", False),
            "color": list(getattr(node, "color", [1,1,1])),
            "inputs": {},
            "properties": serialize_node_properties(node)
        }
        
        # Images
        if getattr(node, "image", None) and node.image.filepath:
            img_path = bpy.path.abspath(node.image.filepath)
            if os.path.exists(img_path):
                img_name = os.path.basename(img_path)
                node_info["packed_image"] = img_name
                image_paths.append((img_path, img_name))
                
        # Ramps & Curves
        if hasattr(node, "color_ramp") and node.color_ramp:
            node_info["color_ramp"] = serialize_color_ramp(node.color_ramp)
        if hasattr(node, "mapping") and hasattr(node.mapping, "curves"):
            node_info["curve_mapping"] = serialize_curve_mapping(node.mapping)
            
        # Inputs
        for i, sock in enumerate(node.inputs):
            if not sock.is_linked and hasattr(sock, "default_value"):
                val = serialize_value(sock.default_value)
                if val is not None:
                    node_info["inputs"][str(i)] = {
                        "identifier": getattr(sock, "identifier", ""),
                        "name": sock.name,
                        "value": val
                    }
                    
        shader_data["nodes"][node.name] = node_info
        
    for link in tree.links:
        if not link.is_valid:
            continue
        try:
            from_idx = list(link.from_node.outputs).index(link.from_socket)
            to_idx = list(link.to_node.inputs).index(link.to_socket)
            
            shader_data["links"].append({
                "from_node": link.from_node.name,
                "from_socket_idx": from_idx,
                "from_socket_id": getattr(link.from_socket, "identifier", ""),
                "from_socket_name": link.from_socket.name,
                "to_node": link.to_node.name,
                "to_socket_idx": to_idx,
                "to_socket_id": getattr(link.to_socket, "identifier", ""),
                "to_socket_name": link.to_socket.name,
            })
        except ValueError:
            continue
            
    return shader_data, image_paths

def resolve_socket(node, is_output, idx, identifier, name):
    sockets = node.outputs if is_output else node.inputs
    if not sockets: return None
    for s in sockets:
        if hasattr(s, "identifier") and s.identifier == identifier and identifier != "":
            return s
    for s in sockets:
        if s.name == name:
            return s
    if 0 <= idx < len(sockets):
        return sockets[idx]
    return sockets[-1]

# --- DIRECTORY / CATEGORY HELPERS ---
def get_target_directory(props):
    base_folder = bpy.path.abspath(props.folder)
    if props.category_list != "NONE":
        return os.path.join(base_folder, props.category_list)
    return base_folder

def get_category_items(self, context):
    props = getattr(context.scene, "shader_lib_props", None)
    if not props or not props.folder:
        return [("NONE", "No Folder Selected", "")]
        
    folder_path = bpy.path.abspath(props.folder)
    if not os.path.isdir(folder_path):
        return [("NONE", "Invalid Folder", "")]
        
    items = [("NONE", "Root Folder", "")]
    for file in os.listdir(folder_path):
        full_path = os.path.join(folder_path, file)
        if os.path.isdir(full_path) and not file.startswith("_extracted"):
            items.append((file, file, "", 'FILE_FOLDER', len(items)))
            
    return items

def get_shader_items(self, context):
    props = getattr(context.scene, "shader_lib_props", None)
    if not props or not props.folder:
        return [("NONE", "No Folder Selected", "")]
        
    target_folder = get_target_directory(props)
    
    if not os.path.isdir(target_folder):
        return [("NONE", "Invalid Folder", "")]
    
    items = []
    for file in os.listdir(target_folder):
        if file.endswith(".json") or file.endswith(".zip"):
            name = os.path.splitext(file)[0]
            icon = 'FILE_ARCHIVE' if file.endswith(".zip") else 'FILE_SCRIPT'
            items.append((file, name, "", icon, len(items)))
            
    return items if items else [("NONE", "No Shaders Found", "")]

# --- ADD-ON UI & OPERATORS ---
class ShaderLibraryProperties(bpy.types.PropertyGroup):
    folder: bpy.props.StringProperty(name="Library Folder", subtype='DIR_PATH')
    
    new_category_name: bpy.props.StringProperty(name="New Category")
    category_list: bpy.props.EnumProperty(name="Categories", items=get_category_items)
    
    save_name: bpy.props.StringProperty(name="Shader Name")
    shader_list: bpy.props.EnumProperty(name="Saved Shaders", items=get_shader_items)
    
    temp_color: bpy.props.FloatVectorProperty(name="Color", subtype='COLOR', size=4, default=(0.8, 0.8, 0.8, 1.0))
    temp_texture: bpy.props.StringProperty(name="Texture", subtype='FILE_PATH')
    temp_value: bpy.props.FloatProperty(name="Value", default=0.5)

class MATERIAL_OT_create_category(bpy.types.Operator):
    bl_idname = "material.create_category"
    bl_label = "Create Category"
    
    def execute(self, context):
        props = context.scene.shader_lib_props
        if not props.folder or not props.new_category_name:
            return {'CANCELLED'}
            
        base_folder = bpy.path.abspath(props.folder)
        new_dir = os.path.join(base_folder, props.new_category_name)
        os.makedirs(new_dir, exist_ok=True)
        
        # Switch to new category and clear text field
        props.category_list = props.new_category_name
        props.new_category_name = ""
        
        self.report({'INFO'}, f"Created Category: {props.category_list}")
        return {'FINISHED'}

class MATERIAL_OT_save_shader_json(bpy.types.Operator):
    bl_idname = "material.save_shader_json"
    bl_label = "Save as JSON"
    
    def execute(self, context):
        props = context.scene.shader_lib_props
        if not props.folder or not props.save_name:
            return {'CANCELLED'}
            
        obj = context.active_object
        if not obj or not obj.active_material or not obj.active_material.use_nodes:
            self.report({'WARNING'}, "No active material with nodes found")
            return {'CANCELLED'}
            
        shader_data, _ = extract_node_data(obj.active_material.node_tree)
        
        folder = get_target_directory(props)
        os.makedirs(folder, exist_ok=True)
        
        filepath = os.path.join(folder, f"{props.save_name}.json")
        with open(filepath, 'w') as f:
            json.dump(shader_data, f, indent=4)
            
        self.report({'INFO'}, f"Saved Shader: {props.save_name}.json in {os.path.basename(folder)}")
        return {'FINISHED'}

class MATERIAL_OT_save_shader_zip(bpy.types.Operator):
    bl_idname = "material.save_shader_zip"
    bl_label = "Pack as ZIP"
    
    def execute(self, context):
        props = context.scene.shader_lib_props
        if not props.folder or not props.save_name:
            return {'CANCELLED'}
            
        obj = context.active_object
        if not obj or not obj.active_material or not obj.active_material.use_nodes:
            self.report({'WARNING'}, "No active material with nodes found")
            return {'CANCELLED'}
            
        shader_data, image_paths = extract_node_data(obj.active_material.node_tree)
        
        folder = get_target_directory(props)
        os.makedirs(folder, exist_ok=True)
        
        zip_filepath = os.path.join(folder, f"{props.save_name}.zip")
        
        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{props.save_name}.json", json.dumps(shader_data, indent=4))
            for img_path, img_name in image_paths:
                zf.write(img_path, arcname=img_name)
                
        self.report({'INFO'}, f"Packed Shader ZIP: {props.save_name}.zip in {os.path.basename(folder)}")
        return {'FINISHED'}

class MATERIAL_OT_refresh_shader_list(bpy.types.Operator):
    bl_idname = "material.refresh_shader_list"
    bl_label = "Refresh List"
    
    def execute(self, context):
        for area in context.screen.areas:
            if area.type == 'VIEW_3D': area.tag_redraw()
        return {'FINISHED'}

class MATERIAL_OT_load_shader(bpy.types.Operator):
    bl_idname = "material.load_shader"
    bl_label = "Apply Shader"
    bl_options = {'REGISTER', 'UNDO'}
    
    def invoke(self, context, event):
        props = context.scene.shader_lib_props
        if props.shader_list in ("NONE", ""): return {'CANCELLED'}
            
        folder = get_target_directory(props)
        filepath = os.path.join(folder, props.shader_list)
        
        self.is_zip = filepath.endswith(".zip")
        self.extracted_folder = ""
        
        if self.is_zip:
            self.extracted_folder = os.path.join(folder, "_extracted_shader", props.shader_list[:-4])
            os.makedirs(self.extracted_folder, exist_ok=True)
            with zipfile.ZipFile(filepath, 'r') as zf:
                zf.extractall(self.extracted_folder)
            json_file = os.path.join(self.extracted_folder, f"{props.shader_list[:-4]}.json")
        else:
            json_file = filepath
            
        with open(json_file, 'r') as f:
            self.shader_data = json.load(f)
            
        self.has_tex, self.has_val, self.has_rgb = False, False, False
        self.tex_label, self.val_label, self.rgb_label = "Texture Input", "Value Input", "Color Input"
        
        for name, n in self.shader_data.get("nodes", {}).items():
            if n["type"] in ("ShaderNodeTexImage", "ShaderNodeTexEnvironment") and "packed_image" not in n: 
                self.has_tex = True
                self.tex_label = n.get("label") or name
            if n["type"] == "ShaderNodeValue":
                self.has_val = True
                self.val_label = n.get("label") or name
            if n["type"] == "ShaderNodeRGB":
                self.has_rgb = True
                self.rgb_label = n.get("label") or name
        
        if self.has_tex or self.has_val or self.has_rgb:
            return context.window_manager.invoke_props_dialog(self)
            
        return self.execute(context)
        
    def draw(self, context):
        layout = self.layout
        props = context.scene.shader_lib_props
        if self.has_tex: layout.prop(props, "temp_texture", text=self.tex_label)
        if self.has_val: layout.prop(props, "temp_value", text=self.val_label)
        if self.has_rgb: layout.prop(props, "temp_color", text=self.rgb_label)

    def execute(self, context):
        obj = context.active_object
        if not obj or not hasattr(obj.data, "materials"): 
            self.report({'WARNING'}, "Active object cannot hold materials")
            return {'CANCELLED'}
            
        props = context.scene.shader_lib_props
        mat_name = os.path.splitext(props.shader_list)[0]
        
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        tree = mat.node_tree
        tree.nodes.clear()
        
        created_nodes = {}
        
        for name, data in self.shader_data.get("nodes", {}).items():
            try:
                node = tree.nodes.new(type=data["type"])
            except Exception:
                continue

            node.name = name
            node.label = data.get("label", "")
            node.location = data.get("location", [0, 0])
            node.width = data.get("width", getattr(node, "width", 140))
            if hasattr(node, "height"): node.height = data.get("height", node.height)
            node.hide = data.get("hide", False)
            node.mute = data.get("mute", False)
            if hasattr(node, "use_custom_color"): node.use_custom_color = data.get("use_custom_color", False)
            if "color" in data and hasattr(node, "color"): node.color = data["color"]
            
            # Properties
            for prop_name, prop_val in data.get("properties", {}).items():
                if hasattr(node, prop_name):
                    try:
                        deserialized = deserialize_value(prop_val)
                        setattr(node, prop_name, deserialized)
                    except Exception:
                        pass
                        
            # Ramps & Curves
            if hasattr(node, "color_ramp") and "color_ramp" in data:
                restore_color_ramp(node.color_ramp, data["color_ramp"])
            if hasattr(node, "mapping") and "curve_mapping" in data:
                restore_curve_mapping(node.mapping, data["curve_mapping"])
                
            # Images
            if "packed_image" in data and self.is_zip:
                img_path = os.path.join(self.extracted_folder, data["packed_image"])
                if os.path.exists(img_path):
                    try: node.image = bpy.data.images.load(img_path)
                    except Exception: pass
            elif data["type"] in ("ShaderNodeTexImage", "ShaderNodeTexEnvironment") and props.temp_texture:
                try: node.image = bpy.data.images.load(bpy.path.abspath(props.temp_texture))
                except Exception: pass
                
            # Dialog Overrides
            if data["type"] == "ShaderNodeValue" and self.has_val:
                try: node.outputs[0].default_value = props.temp_value
                except: pass
            elif data["type"] == "ShaderNodeRGB" and self.has_rgb:
                try: node.outputs[0].default_value = props.temp_color
                except: pass

            created_nodes[name] = node
            
        # Inputs
        for name, data in self.shader_data.get("nodes", {}).items():
            if name not in created_nodes: continue
            node = created_nodes[name]
            
            for key, input_data in data.get("inputs", {}).items():
                val = deserialize_value(input_data["value"]) if isinstance(input_data, dict) else deserialize_value(input_data)
                idx = int(key) if str(key).isdigit() else 0
                sock_id = input_data.get("identifier", "") if isinstance(input_data, dict) else ""
                sock_name = input_data.get("name", "") if isinstance(input_data, dict) else ""
                
                sock = resolve_socket(node, False, idx, sock_id, sock_name)
                if sock and hasattr(sock, "default_value"):
                    try:
                        sock.default_value = val
                    except Exception:
                        pass

        # Links
        for link in self.shader_data.get("links", []):
            if link["from_node"] in created_nodes and link["to_node"] in created_nodes:
                node_from = created_nodes[link["from_node"]]
                node_to = created_nodes[link["to_node"]]

                sock_out = resolve_socket(node_from, True, link.get("from_socket_idx", 0), link.get("from_socket_id", ""), link.get("from_socket_name", ""))
                sock_in = resolve_socket(node_to, False, link.get("to_socket_idx", 0), link.get("to_socket_id", ""), link.get("to_socket_name", ""))

                if sock_out and sock_in:
                    try:
                        tree.links.new(sock_out, sock_in)
                    except Exception:
                        pass

        # Assign Material
        if len(obj.material_slots) == 0:
            obj.data.materials.append(mat)
        else:
            obj.material_slots[obj.active_material_index].material = mat
            
        self.report({'INFO'}, f"Applied Shader: {mat_name}")
        return {'FINISHED'}

class VIEW3D_PT_shader_library(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Shaders'
    bl_label = "JSON & ZIP Shader Library"

    def draw(self, context):
        layout = self.layout
        props = context.scene.shader_lib_props
        
        layout.prop(props, "folder")
        layout.separator()
        
        # CATEGORIES BOX
        box = layout.box()
        box.label(text="Categories (Subfolders):")
        
        row = box.row(align=True)
        row.prop(props, "category_list", text="")
        row.operator("material.refresh_shader_list", icon='FILE_REFRESH', text="")
        
        row = box.row(align=True)
        row.prop(props, "new_category_name", text="")
        row.operator("material.create_category", icon='ADD', text="New")
        
        layout.separator()
        
        # SAVE BOX
        box = layout.box()
        box.label(text="Save Current Shader:")
        box.prop(props, "save_name")
        row = box.row(align=True)
        row.operator("material.save_shader_json", icon='FILE_SCRIPT')
        row.operator("material.save_shader_zip", icon='FILE_ARCHIVE')
        
        layout.separator()
        
        # LOAD BOX
        box = layout.box()
        box.label(text="Load Shader:")
        box.prop(props, "shader_list", text="")
        box.operator("material.load_shader", icon='MATERIAL')

classes = (
    ShaderLibraryProperties,
    MATERIAL_OT_create_category,
    MATERIAL_OT_save_shader_json,
    MATERIAL_OT_save_shader_zip,
    MATERIAL_OT_refresh_shader_list,
    MATERIAL_OT_load_shader,
    VIEW3D_PT_shader_library,
)

def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.shader_lib_props = bpy.props.PointerProperty(type=ShaderLibraryProperties)

def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    del bpy.types.Scene.shader_lib_props

if __name__ == "__main__":
    register()
