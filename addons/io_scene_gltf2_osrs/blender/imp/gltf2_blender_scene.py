# Copyright 2018-2021 The glTF-Blender-IO authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import bpy
import bmesh
from mathutils import Matrix, Vector
from .gltf2_blender_node import BlenderNode
from .gltf2_blender_animation import BlenderAnimation
from .gltf2_blender_vnode import VNode, compute_vnodes
from ..com.gltf2_blender_extras import set_extras
from io_scene_gltf2.io.imp.gltf2_io_user_extensions import import_user_extensions


class BlenderScene():
    """Blender Scene."""
    def __new__(cls, *args, **kwargs):
        raise RuntimeError("%s should not be instantiated" % cls)

    @staticmethod
    def create(gltf):
        """Scene creation."""
        scene = bpy.context.scene
        gltf.blender_scene = scene.name
        if bpy.context.collection.name in bpy.data.collections: # avoid master collection
            gltf.blender_active_collection = bpy.context.collection.name
        if scene.render.engine not in ['CYCLES', 'BLENDER_EEVEE']:
            scene.render.engine = "BLENDER_EEVEE"

        if gltf.data.scene is not None:
            import_user_extensions('gather_import_scene_before_hook', gltf, gltf.data.scenes[gltf.data.scene], scene)
            pyscene = gltf.data.scenes[gltf.data.scene]
            set_extras(scene, pyscene.extras)

        compute_vnodes(gltf)

        gltf.display_current_node = 0  # for debugging
        BlenderNode.create_vnode(gltf, 'root')

        # for material in gltf.material_cache:
        #     if material.node_tree:
        #         print("material:" + str(material.name))
        #         for x in material.node_tree.nodes:
        #             if x.type == 'TEX_IMAGE':
        #                 if not ("Specular" in x.image.name):
        #                     checksum = sum(x.image.pixels)
        #                     x.image.name = str(int(checksum))
        #                     # change png
        #                     print(" texture: " + str(x.image.name))
        #     if vnode.type == VNode.Object:


        # User extensions before scene creation
        gltf_scene = None
        if gltf.data.scene is not None:
            gltf_scene = gltf.data.scenes[gltf.data.scene]
        import_user_extensions('gather_import_scene_after_nodes_hook', gltf, gltf_scene, scene)

        BlenderScene.create_animations(gltf)

        # User extensions after scene creation
        gltf_scene = None
        if gltf.data.scene is not None:
            gltf_scene = gltf.data.scenes[gltf.data.scene]
        import_user_extensions('gather_import_scene_after_animation_hook', gltf, gltf_scene, scene)

        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        BlenderScene.select_imported_objects(gltf)
        BlenderScene.set_active_object(gltf)

        mesh_objects = {}
        for ob in bpy.data.objects:
            if ob.type == 'MESH':
                if "tiles" in ob.name or "type" in ob.name:
                    continue
                name = ob.name.split(".")[0]
                id = name.split("_")[1]
                type = ob.parent.name.split("_")[2]
                rotatstring = name.split("_")[4]
                if (type, id, rotatstring) not in mesh_objects.keys():
                    mesh_objects[(type, id, rotatstring)] = []
                mesh_objects[(type, id, rotatstring)].append(ob)

        for key in mesh_objects.keys():
            meshlist = mesh_objects[key]
            for mesh in meshlist:
                me = mesh.data
                mw = mesh.matrix_world
                origin = sum((v.co for v in me.vertices), Vector()) / len(me.vertices)
                T = Matrix.Translation(-origin)
                me.transform(T)
                mw.translation = mw @ origin

        for key in mesh_objects.keys():
            meshlist = mesh_objects[key]
            for i in range(1, len(meshlist)):
                mesh_obj = meshlist[i]

                location = mesh_obj.location.copy()
                parent = mesh_obj.parent
                o = bpy.data.objects.new(mesh_obj.name, None)
                bpy.context.scene.collection.objects.link(o)
                o.location = location
                o.parent = parent

                mesh_data = mesh_obj.data
                mesh_obj.data = None
                bpy.data.meshes.remove(mesh_data)


    @staticmethod
    def create_animations(gltf):
        """Create animations."""

        # Use a class here, to be able to pass data by reference to hook (to be able to change them inside hook)
        class IMPORT_animation_options:
            def __init__(self, restore_first_anim: bool = True):
                self.restore_first_anim = restore_first_anim

        animation_options = IMPORT_animation_options()
        import_user_extensions('gather_import_animations', gltf, gltf.data.animations, animation_options)

        if gltf.data.animations:
            # NLA tracks are added bottom to top, so create animations in
            # reverse so the first winds up on top
            for anim_idx in reversed(range(len(gltf.data.animations))):
                BlenderAnimation.anim(gltf, anim_idx)

            # Restore first animation
            if animation_options.restore_first_anim:
                anim_name = gltf.data.animations[0].track_name
                BlenderAnimation.restore_animation(gltf, anim_name)

    @staticmethod
    def select_imported_objects(gltf):
        """Select all (and only) the imported objects."""
        if bpy.ops.object.select_all.poll():
           bpy.ops.object.select_all(action='DESELECT')

        for vnode in gltf.vnodes.values():
            if vnode.type == VNode.Object:
                vnode.blender_object.select_set(state=True)

    @staticmethod
    def set_active_object(gltf):
        """Make the first root object from the default glTF scene active.
        If no default scene, use the first scene, or just any root object.
        """
        vnode = None

        if gltf.data.scene is not None:
            pyscene = gltf.data.scenes[gltf.data.scene]
            if pyscene.nodes:
                vnode = gltf.vnodes[pyscene.nodes[0]]

        if not vnode:
            for pyscene in gltf.data.scenes or []:
                if pyscene.nodes:
                    vnode = gltf.vnodes[pyscene.nodes[0]]
                    break

        if not vnode:
            vnode = gltf.vnodes['root']
            if vnode.type == VNode.DummyRoot:
                if not vnode.children:
                    return  # no nodes
                vnode = gltf.vnodes[vnode.children[0]]

        if vnode.type == VNode.Bone:
            vnode = gltf.vnodes[vnode.bone_arma]

        bpy.context.view_layer.objects.active = vnode.blender_object
