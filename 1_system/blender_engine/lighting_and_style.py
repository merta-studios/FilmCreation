"""Nostalgisch-realistisches Licht: Nishita-Himmel, Golden Hour, Regen, Nebel, AgX.

Ein "Mood" ist ein komplettes Licht-Setup: Himmelsphysik, Sonne, Zusatzlichter
(Fenster, Laternen), Volumen-Dunst, Partikel (Regen/Staub/Blaetter), Farb-Look,
Vignette und Belichtung. Shots waehlen nur den Namen - der Rest ist hier definiert.

Verfuegbare Stimmungen
----------------------
``golden_hour``      warmes Gegenlicht, lange Schatten, Staub in der Luft
``rainy_dusk``       blaue, regennasse Daemmerung mit warmen Fenstern und Laternen
``foggy_morning``    nebliger Morgen, milchiges Licht, leise Hoffnung
``hopeful_dawn``     zartes Morgenlicht fuer das gute Ende
``overcast_school``  flaches, graues Tageslicht (Schulhof, Ausgrenzung)
``night_street``     Nacht mit Neonschildern, nassen Strassen, tiefen Schatten
``warm_interior``    warmes Innenraumlicht (Zuhause, Kueche, Kinderzimmer)
``cold_room``        kaltes Krankenzimmer/Amt, harte Schatten

Technik
-------
* Cycles mit OptiX/CUDA-Unterstuetzung, OpenImageDenoise, adaptivem Sampling.
* Nishita-Sky (physikalischer Himmel) plus Sonne mit passender Farbe/Staerke.
* Volumetrischer Dunst als Welt-Volumen (God-Rays durch Fenster und Baeume).
* AgX-Color-Management mit filmspezifischem Look, Belichtung und Vignette.
* Kameranahe Partikel als echte Objekt-Partikel (Regen, Staub, Blaetter).
"""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from typing import Optional

try:
    import bpy  # type: ignore
    from mathutils import Vector  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    Vector = None  # type: ignore
    HAS_BPY = False

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

textures = importlib.import_module("1_system.blender_engine.roblox_textures")

#: Mood-Daten (auch ohne Blender nutzbar fuer Validierung/Doku)
MOODS: dict[str, dict] = {
    "golden_hour": dict(
        sun_elevation=6.0, sun_rotation=125.0, sun_strength=4.6, sun_color="#FFD3A1",
        sky_strength=0.9, fog_density=0.0028, exposure=0.15, look="AgX - Medium High Contrast",
        particles="dust", practicals=0.35, description="Warmes Gegenlicht, lange Schatten"),
    "rainy_dusk": dict(
        sun_elevation=-2.5, sun_rotation=250.0, sun_strength=0.7, sun_color="#8FA6C8",
        sky_strength=0.55, fog_density=0.006, exposure=0.45, look="AgX - Medium High Contrast",
        particles="rain", practicals=1.0, description="Blaue, regennasse Daemmerung"),
    "foggy_morning": dict(
        sun_elevation=3.0, sun_rotation=70.0, sun_strength=1.5, sun_color="#DCE6F0",
        sky_strength=0.8, fog_density=0.014, exposure=0.55, look="AgX - Base Contrast",
        particles="mist", practicals=0.25, description="Nebliger Morgen, milchiges Licht"),
    "hopeful_dawn": dict(
        sun_elevation=9.0, sun_rotation=95.0, sun_strength=3.4, sun_color="#FFC9A0",
        sky_strength=1.05, fog_density=0.004, exposure=0.2, look="AgX - Medium High Contrast",
        particles="dust", practicals=0.2, description="Zartes Morgenlicht fuer das Happy End"),
    "overcast_school": dict(
        sun_elevation=32.0, sun_rotation=200.0, sun_strength=1.2, sun_color="#C9D2DC",
        sky_strength=1.25, fog_density=0.004, exposure=0.1, look="AgX - Base Contrast",
        particles=None, practicals=0.1, description="Flaches, graues Tageslicht"),
    "night_street": dict(
        sun_elevation=-8.0, sun_rotation=300.0, sun_strength=0.12, sun_color="#6E86B8",
        sky_strength=0.32, fog_density=0.007, exposure=0.9, look="AgX - Medium High Contrast",
        particles="rain", practicals=1.4, description="Nacht mit Neonschildern und nassen Strassen"),
    "warm_interior": dict(
        sun_elevation=14.0, sun_rotation=140.0, sun_strength=1.1, sun_color="#FFB774",
        sky_strength=0.5, fog_density=0.0016, exposure=0.3, look="AgX - Medium High Contrast",
        particles="dust", practicals=1.2, description="Warmes Innenraumlicht"),
    "cold_room": dict(
        sun_elevation=22.0, sun_rotation=210.0, sun_strength=1.6, sun_color="#D6E2F0",
        sky_strength=0.9, fog_density=0.0022, exposure=0.25, look="AgX - Base Contrast",
        particles=None, practicals=0.5, description="Kaltes Zimmer, harte Schatten"),
}

MOOD_NAMES = tuple(MOODS)


def require_bpy() -> None:
    if not HAS_BPY:
        raise RuntimeError("Licht-Setup braucht Blender (bpy).")


def mood_spec(mood: str) -> dict:
    if mood not in MOODS:
        raise KeyError(f"Unbekannte Lichtstimmung '{mood}'. Erlaubt: {', '.join(MOOD_NAMES)}")
    return MOODS[mood]


# --------------------------------------------------------------------------- #
# Grundsetup
# --------------------------------------------------------------------------- #
def setup_render(scene, samples: int = 96, denoise: bool = True, device: str = "GPU",
                 adaptive: bool = True, max_bounces: int = 8):
    """Cycles-Render konfigurieren (GPU mit CPU-Fallback, Denoising, AgX)."""
    require_bpy()
    scene.render.engine = "CYCLES"
    cycles = scene.cycles
    cycles.samples = int(samples)
    cycles.use_adaptive_sampling = bool(adaptive)
    cycles.adaptive_threshold = 0.02
    cycles.use_denoising = bool(denoise)
    cycles.max_bounces = int(max_bounces)
    cycles.diffuse_bounces = 4
    cycles.glossy_bounces = 4
    cycles.transmission_bounces = 6
    cycles.volume_bounces = 2
    cycles.transparent_max_bounces = 8
    cycles.caustics_reflective = False
    cycles.caustics_refractive = False
    if denoise:
        for attribute, value in (("denoiser", "OPENIMAGEDENOISE"),):
            try:
                setattr(cycles, attribute, value)
            except (AttributeError, TypeError):
                pass
    device = (device or "GPU").upper()
    if device in ("GPU", "CUDA", "OPTIX"):
        preferences = bpy.context.preferences.addons.get("cycles")
        if preferences is not None:
            cprefs = preferences.preferences
            for backend in ("OPTIX", "CUDA"):
                try:
                    cprefs.compute_device_type = backend
                    cprefs.get_devices()
                    gpus = [d for d in cprefs.devices if d.type in ("CUDA", "OPTIX")]
                    if gpus:
                        for gpu in cprefs.devices:
                            gpu.use = gpu.type in ("CUDA", "OPTIX")
                        scene.cycles.device = "GPU"
                        return backend
                except (AttributeError, TypeError, RuntimeError):
                    continue
    scene.cycles.device = "CPU"
    return "CPU"


def setup_color(scene, look: str = "AgX - Medium High Contrast", exposure: float = 0.0,
                view_transform: str = "AgX"):
    require_bpy()
    scene.view_settings.view_transform = view_transform
    try:
        scene.view_settings.look = look
    except TypeError:
        scene.view_settings.look = "None"
    scene.view_settings.exposure = float(exposure)
    scene.view_settings.gamma = 1.0
    scene.render.film_transparent = False


def setup_sky(scene, sun_elevation: float = 6.0, sun_rotation: float = 125.0,
              strength: float = 0.9, dust_density: float = 1.6,
              air_density: float = 1.25, ozone: float = 1.0):
    """Physikalischer Nishita-Himmel (Blender 3.x/4.x)."""
    require_bpy()
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(sun_elevation)
    sky.sun_rotation = math.radians(sun_rotation)
    sky.sun_disc = True
    for attribute, value in (("altitude", 50.0), ("air_density", air_density),
                             ("dust_density", dust_density), ("ozone_density", ozone)):
        try:
            setattr(sky, attribute, value)
        except (AttributeError, TypeError):
            pass
    links.new(sky.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = float(strength)
    links.new(background.outputs["Background"], output.inputs["Surface"])
    return world


def add_sun(scene, strength: float = 4.0, color: str = "#FFD3A1",
            elevation: float = 6.0, rotation: float = 125.0, angle_deg: float = 1.2):
    """Sonnenlicht passend zum Himmelsstand (weiche Schatten durch Winkeldurchmesser)."""
    require_bpy()
    existing = bpy.data.objects.get("Sonne")
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)
    light_data = bpy.data.lights.new("Sonne", type="SUN")
    light_data.energy = float(strength)
    light_data.color = textures.rgb_to_linear(textures.brickcolor(color))
    light_data.angle = math.radians(angle_deg)
    light_data.angle = min(light_data.angle, math.radians(10.0))
    sun = bpy.data.objects.new("Sonne", light_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(90.0 - elevation), 0.0, math.radians(rotation))
    return sun


def add_volumetric_fog(scene, density: float = 0.003, color: str = "#C9D6E3",
                       anisotropy: float = 0.4):
    """Dunst als Welt-Volumen - erzeugt God-Rays und Tiefenstaffelung."""
    require_bpy()
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    output = next((n for n in nodes if n.type == "OUTPUT_WORLD"), None)
    if output is None:
        output = nodes.new("ShaderNodeOutputWorld")
    volume = nodes.new("ShaderNodeVolumePrincipled")
    volume.inputs["Density"].default_value = float(density)
    volume.inputs["Anisotropy"].default_value = float(anisotropy)
    if "Color" in volume.inputs:
        volume.inputs["Color"].default_value = textures.brickcolor_rgba(color)
    links.new(volume.outputs["Volume"], output.inputs["Volume"])
    return volume


def add_practical_lights(scene, locations, intensity: float = 1.0,
                         color: str = "#FFC978", radius: float = 0.4,
                         name_prefix: str = "Praxis"):
    """Zusaetzliche Waermelichter (Fenster, Laternen, Kerzen) an gegebenen Punkten."""
    require_bpy()
    created = []
    for index, location in enumerate(locations):
        light_data = bpy.data.lights.new(f"{name_prefix}_{index}", type="POINT")
        light_data.energy = 55.0 * intensity
        light_data.color = textures.rgb_to_linear(textures.brickcolor(color))
        light_data.shadow_soft_size = radius
        obj = bpy.data.objects.new(f"{name_prefix}_{index}", light_data)
        obj.location = location
        scene.collection.objects.link(obj)
        created.append(obj)
    return created


def add_area_window_light(scene, location, rotation, size=(2.0, 1.5),
                          energy: float = 220.0, color: str = "#FFD9A8"):
    """Fensterlicht als flaechige Lichtquelle (weiche Innenraum-Schatten)."""
    require_bpy()
    light_data = bpy.data.lights.new("Fensterlicht", type="AREA")
    light_data.energy = float(energy)
    light_data.color = textures.rgb_to_linear(textures.brickcolor(color))
    light_data.shape = "RECTANGLE"
    light_data.size, light_data.size_y = size
    obj = bpy.data.objects.new("Fensterlicht", light_data)
    obj.location = location
    obj.rotation_euler = tuple(math.radians(a) for a in rotation)
    scene.collection.objects.link(obj)
    return obj


# --------------------------------------------------------------------------- #
# Partikel (Regen, Staub, Blaetter, Nebel)
# --------------------------------------------------------------------------- #
def add_particles(scene, kind: str = "rain", count: int = 2500,
                  area: tuple[float, float, float] = (30.0, 30.0, 14.0),
                  center=(0, 0, 0), collection=None, seed: int = 7):
    """Erzeugt Wetter-Partikel als echte Objekte (Cycles-freundlich, animiert)."""
    require_bpy()
    collection = collection or scene.collection
    settings = {
        "rain": dict(size=(0.012, 0.012, 0.55), material=("water", 0.03), speed=-26.0,
                     lifetime=26, color="#B9D6E8", emission=0.0),
        "dust": dict(size=(0.02, 0.02, 0.02), material=("classic_foil", 0.4), speed=0.35,
                     lifetime=200, color="#FFF1CF", emission=1.2),
        "leaves": dict(size=(0.14, 0.09, 0.01), material=("classic_wood", 0.8), speed=-4.0,
                       lifetime=180, color="#A05F35", emission=0.0),
        "mist": dict(size=(0.6, 0.6, 0.6), material=("classic_foam", 0.9), speed=0.08,
                     lifetime=240, color="#E8F0F6", emission=0.15),
    }.get(kind)
    if settings is None:
        return None
    texture_key, roughness = settings["material"]
    if texture_key not in textures.TEXTURE_CATALOG:
        texture_key = "water"
    # Emitter
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(center[0], center[1],
                                                        center[2] + area[2] / 2))
    emitter = bpy.context.object
    emitter.name = f"Wetter_{kind}"
    emitter.scale = (area[0], area[1], 1.0)
    for link in list(emitter.users_collection):
        link.objects.unlink(emitter)
    collection.objects.link(emitter)
    emitter.show_instancer_for_render = False
    emitter.show_instancer_for_viewport = False

    # Instanz-Objekt
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    instance = bpy.context.object
    instance.name = f"Wetter_{kind}_tropfen"
    instance.scale = settings["size"]
    for link in list(instance.users_collection):
        link.objects.unlink(instance)
    collection.objects.link(instance)
    material = bpy.data.materials.new(f"wetter_{kind}_mat")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    rgba = textures.brickcolor_rgba(settings["color"])
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = roughness
        if settings["emission"] and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = rgba[:3] + (1.0,)
            bsdf.inputs["Emission Strength"].default_value = settings["emission"]
        if kind == "rain" and "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = 0.55
    material.blend_method = "BLEND"
    instance.data.materials.append(material)
    instance.hide_render = False

    particle_data = bpy.data.particles.new(f"Wetter_{kind}_system")
    particle_data.count = int(count)
    particle_data.frame_start = 1
    particle_data.frame_end = int(max(2, scene.frame_end))
    particle_data.lifetime = settings["lifetime"]
    particle_data.emit_from = "FACE"
    particle_data.physics_type = "NEWTON"
    particle_data.normal_factor = settings["speed"]
    particle_data.factor_random = abs(settings["speed"]) * 0.25
    particle_data.effector_weights.gravity = 0.04 if kind != "rain" else 0.6
    particle_data.render_type = "OBJECT"
    particle_data.instance_object = instance
    particle_data.particle_size = 1.0
    particle_data.size_random = 0.6
    particle_data.use_rotations = True
    particle_data.rotation_mode = "NONE"
    modifier = emitter.modifiers.new("Wetter", "PARTICLE_SYSTEM")
    modifier.particle_system.settings = particle_data
    modifier.particle_system.seed = int(seed)
    return emitter


# --------------------------------------------------------------------------- #
# Komplettes Mood-Setup
# --------------------------------------------------------------------------- #
def apply_mood(scene, mood: str, practical_locations: Optional[list] = None,
               particles: Optional[str] = "auto", fog_multiplier: float = 1.0,
               sun_override: Optional[dict] = None):
    """Setzt Himmel, Sonne, Dunst, Partikel, Farb-Look und Belichtung."""
    require_bpy()
    spec = mood_spec(mood)
    setup_sky(scene, spec["sun_elevation"], spec["sun_rotation"], spec["sky_strength"])
    sun_params = dict(strength=spec["sun_strength"], color=spec["sun_color"],
                      elevation=spec["sun_elevation"], rotation=spec["sun_rotation"])
    if sun_override:
        sun_params.update(sun_override)
    add_sun(scene, **sun_params)
    add_volumetric_fog(scene, spec["fog_density"] * fog_multiplier)
    setup_color(scene, spec["look"], spec["exposure"])
    chosen = spec["particles"] if particles == "auto" else particles
    if chosen:
        add_particles(scene, chosen, collection=scene.collection)
    if practical_locations:
        add_practical_lights(scene, practical_locations,
                             intensity=max(0.15, spec["practicals"]))
    return spec


def add_vignette(scene, strength: float = 0.35, softness: float = 0.45):
    """Sanfte Vignette + leichter Bloom ueber den Compositor (nach dem Render)."""
    require_bpy()
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    layers = tree.nodes.new("CompositorNodeRLayers")
    glare = tree.nodes.new("CompositorNodeGlare")
    glare.glare_type = "FOG_GLOW"
    glare.quality = "HIGH"
    glare.threshold = 0.85
    glare.mix = -0.85
    glare.size = 7
    ellipse = tree.nodes.new("CompositorNodeEllipseMask")
    ellipse.width, ellipse.height = 0.92, 0.92
    blur = tree.nodes.new("CompositorNodeBlur")
    blur.filter_type = "GAUSS"
    blur.size_x = blur.size_y = int(180 * softness + 60)
    mix = tree.nodes.new("CompositorNodeMixRGB")
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = float(strength)
    composite = tree.nodes.new("CompositorNodeComposite")
    tree.links.new(layers.outputs["Image"], glare.inputs["Image"])
    tree.links.new(ellipse.outputs["Mask"], blur.inputs["Image"])
    tree.links.new(glare.outputs["Image"], mix.inputs[1])
    tree.links.new(blur.outputs["Image"], mix.inputs[2])
    tree.links.new(mix.outputs[0], composite.inputs["Image"])
    return tree


def enable_motion_blur(scene, shutter: float = 0.35):
    """Bewegungsunschaerfe - verstaerkt das Gefuehl einer echten Kamera."""
    require_bpy()
    scene.render.use_motion_blur = True
    scene.render.motion_blur_shutter = float(shutter)


def setup_depth_of_field(camera, focus_point, fstop: float = 2.8):
    """Filmsiche Tiefenschaerfe auf einen Punkt richten."""
    require_bpy()
    camera.data.dof.use_dof = True
    camera.data.dof.focus_distance = max(0.2, float(focus_point))
    camera.data.dof.aperture_fstop = max(0.7, float(fstop))


def summary(mood: str) -> dict:
    spec = dict(mood_spec(mood))
    spec["mood"] = mood
    return spec
