"""Render the built-in vertical demo using Blender's Python API.

Run with Blender's Python: blender -b -t 2 --python ... -- --output ...
or with the bpy Python wheel: python -m 1_system.blender_engine.scene_builder ...
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

PALETTE = {
    'skin': (0.95, .72, .36, 1), 'shirt_blue': (.22,.38,.48,1),
    'shirt_green': (.31,.43,.33,1), 'shirt_red': (.55,.28,.28,1),
    'pants': (.11,.15,.21,1), 'road': (.12,.14,.16,1),
    'walk': (.39,.37,.32,1), 'brick': (.43,.20,.16,1),
    'plaster': (.62,.51,.37,1), 'roof': (.18,.14,.13,1),
    'wood': (.25,.15,.08,1), 'leaf': (.18,.30,.19,1),
    'glass': (1,.65,.25,1), 'white': (.9,.84,.70,1),
    'metal': (.14,.16,.17,1), 'grass': (.19,.27,.17,1),
}
_MATERIALS = {}


def material(name, emission=0):
    key = (name, emission)
    if key not in _MATERIALS:
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = PALETTE[name]
        mat.use_nodes = True
        shader = mat.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = PALETTE[name]
        shader.inputs['Roughness'].default_value = .7
        if emission:
            shader.inputs['Emission Color'].default_value = PALETTE[name]
            shader.inputs['Emission Strength'].default_value = emission
        _MATERIALS[key] = mat
    return _MATERIALS[key]


def block(name, loc, scale, color, rotation=(0,0,0), emission=0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material(color, emission))
    bevel = obj.modifiers.new('soft corners', 'BEVEL')
    bevel.width = .03
    bevel.segments = 2
    obj.modifiers.new('weighted normals', 'WEIGHTED_NORMAL')
    return obj


def cylinder(name, loc, radius, depth, color):
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=radius, depth=depth, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material(color))
    return obj


def text(name, content, loc, size=.35, color='white'):
    curve = bpy.data.curves.new(name, 'FONT')
    curve.body = content
    curve.align_x = 'CENTER'
    curve.size = size
    curve.extrude = .005
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (math.pi/2, 0, 0)
    obj.data.materials.append(material(color, 0.4))
    return obj


def make_character(name, x, y, shirt, number, frames):
    # Fifteen independent R15-style blocks; the animation below moves them, but
    # this is not a Roblox-compatible skeletal rig or a licensed avatar import.
    parts = [
        ('Head', (0,0,2.25), (.58,.52,.57), 'skin'),
        ('UpperTorso', (0,0,1.67), (.76,.45,.55), shirt),
        ('LowerTorso', (0,0,1.23), (.72,.43,.32), shirt),
        ('LeftUpperArm', (-.53,0,1.68), (.26,.32,.48), shirt),
        ('LeftLowerArm', (-.53,0,1.27), (.23,.28,.37), 'skin'),
        ('LeftHand', (-.53,0,1.02), (.23,.27,.15), 'skin'),
        ('RightUpperArm', (.53,0,1.68), (.26,.32,.48), shirt),
        ('RightLowerArm', (.53,0,1.27), (.23,.28,.37), 'skin'),
        ('RightHand', (.53,0,1.02), (.23,.27,.15), 'skin'),
        ('LeftUpperLeg', (-.2,0,.89), (.33,.37,.38), 'pants'),
        ('LeftLowerLeg', (-.2,0,.49), (.30,.34,.42), 'pants'),
        ('LeftFoot', (-.2,-.08,.13), (.32,.48,.22), 'pants'),
        ('RightUpperLeg', (.2,0,.89), (.33,.37,.38), 'pants'),
        ('RightLowerLeg', (.2,0,.49), (.30,.34,.42), 'pants'),
        ('RightFoot', (.2,-.08,.13), (.32,.48,.22), 'pants'),
    ]
    for part, p, dims, color in parts:
        obj = block(name+'_'+part, (x+p[0], y+p[1], p[2]), dims, color)
        # Gentle, deterministic breathing/weight shift, not a walk cycle.
        base = obj.location.copy()
        for frame in sorted(set(range(1, frames + 1, 48)) | {frames}):
            phase = math.sin(frame/48*math.pi + x)
            obj.location = (base.x + .014*phase, base.y, base.z + .008*phase)
            obj.keyframe_insert(data_path='location', frame=frame)
    for dx in (-.13, .13):
        block(name+'_eye', (x+dx, y-.27, 2.30), (.065,.018,.09), 'metal')
    block(name+'_mouth', (x,y-.276,2.13), (.15,.015,.025), 'metal')
    text(name+'_counter', number, (x,y-.03,2.95), .26)


def build_map():
    block('ground', (0,2,-.18), (32,45,.3), 'grass')
    block('road', (0,2,0), (5,35,.08), 'road', (0,0,.08))
    block('walk_left', (-3.1,2,.05), (1.4,35,.12), 'walk', (0,0,.08))
    block('walk_right', (3.1,2,.05), (1.4,35,.12), 'walk', (0,0,.08))
    for side in (-1,1):
        for row in range(5):
            y = row*6 - 4
            x = side*(6.0 + (row%2)*.6)
            height = 4.5 + row%3
            block(f'house_{side}_{row}', (x,y,height/2), (4,4,height), 'brick' if row%2 else 'plaster')
            block(f'roof_{side}_{row}', (x,y,height+.18), (4.4,4.4,.35), 'roof')
            for z in (1.5,3.2):
                for dx in (-.9,.9):
                    block('window', (x+dx,y-2.04,z), (.8,.08,1.0), 'glass', emission=.5)
            cylinder('lamp_post', (side*3.4,y,2.1), .065, 4.2, 'metal')
            block('lamp', (side*3.4,y,4.2), (.35,.35,.35), 'glass', emission=3)
            cylinder('tree_trunk', (side*9,y+2,1.0), .20, 2, 'wood')
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.3, location=(side*9,y+2,3))
            bpy.context.object.data.materials.append(material('leaf'))
    text('town_sign', 'SCHRITTSTADT', (0,7,4.3), .6)
    block('sign_back', (0,7.1,4.5), (5,.2,.9), 'wood')


def camera(shot, frames):
    bpy.ops.object.camera_add()
    cam = bpy.context.object
    bpy.context.scene.camera = cam
    cam.data.lens = 37
    cam.data.dof.use_dof = True
    cam.data.dof.focus_distance = 9
    cam.data.dof.aperture_fstop = 5.6
    positions = {
        1: ((4,-12,6), (2.4,-10,4.8)),
        2: ((-1.2,-9,3.0), (-.8,-7.5,2.7)),
        3: ((3,-8,3.4), (1.8,-7.2,2.8)),
        4: ((0,-7,2.8), (1.5,-10,4.0)),
    }
    start, end = positions[shot]
    target = Vector((0,0,1.8))
    for frame, pos in ((1,start), (max(2,frames),end)):
        cam.location = pos
        cam.rotation_euler = (target - cam.location).to_track_quat('-Z','Y').to_euler()
        cam.keyframe_insert('location', frame=frame)
        cam.keyframe_insert('rotation_euler', frame=frame)
    return cam


def build_scene(shot, frames, width, height, samples):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    _MATERIALS.clear()
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.fps = 24
    scene.frame_start, scene.frame_end = 1, frames
    scene.world.color = (.22,.25,.32)
    bpy.ops.object.light_add(type='SUN', location=(0,-5,10))
    sun = bpy.context.object
    sun.data.energy = 2.0
    sun.data.color = (1,.76,.55)
    sun.rotation_euler = (.5,-.5,-.4)
    build_map()
    make_character('Mika', 0,0, 'shirt_blue', '0920', frames)
    make_character('Mara', -1.5, .7, 'shirt_green', '0012', frames)
    make_character('Lina', 1.5,.7, 'shirt_red', '6210', frames)
    camera(shot, frames)
    return scene


def main():
    argv = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument('--shot', type=int, choices=(1,2,3,4), default=1)
    p.add_argument('--frames', type=int, default=48)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--width', type=int, default=540)
    p.add_argument('--height', type=int, default=960)
    p.add_argument('--samples', type=int, default=16)
    p.add_argument('--still', action='store_true')
    args = p.parse_args(argv)
    if args.frames < 2 or args.width <= 0 or args.height <= 0 or args.samples < 1:
        p.error('Ungültige Renderparameter')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scene = build_scene(args.shot, args.frames, args.width, args.height, args.samples)
    scene.render.filepath = str(args.output.resolve())
    if args.still:
        scene.render.image_settings.file_format = 'PNG'
        scene.frame_set(max(1, args.frames//2))
        bpy.ops.render.render(write_still=True)
    else:
        scene.render.image_settings.file_format = 'FFMPEG'
        scene.render.ffmpeg.format = 'MPEG4'
        scene.render.ffmpeg.codec = 'H264'
        scene.render.ffmpeg.constant_rate_factor = 'HIGH'
        bpy.ops.render.render(animation=True)

if __name__ == '__main__':
    main()
