"""Roblox XML model subset. Unsupported formats fail explicitly rather than fabricate meshes."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass
class RbxmPart:
    name: str = ""
    class_name: str = "Part"
    size: tuple = (1., 1., 1.)
    position: tuple = (0., 0., 0.)
    rotation_matrix: tuple = (1., 0., 0., 0., 1., 0., 0., 0., 1.)
    color: tuple = (0.64, 0.64, 0.64)
    material: str = "Plastic"
    attachments: list = field(default_factory=list)


@dataclass
class RbxmModel:
    parts: list = field(default_factory=list)
    meshes: list = field(default_factory=list)
    name: str = ""


def _vector(node, names):
    try:
        return tuple(float(node.findtext(n)) for n in names)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Ungültiger Vektor in {node.tag}") from e


def _cframe(node):
    return (_vector(node, ('X','Y','Z')),
            _vector(node, ('R00','R01','R02','R10','R11','R12','R20','R21','R22')))


def _properties(item):
    props = item.find('Properties')
    return {p.get('name'): p for p in props} if props is not None else {}


class RbxmParser:
    def parse_file(self, path: Path) -> RbxmModel:
        data = Path(path).read_bytes()
        if data.startswith(b'<roblox!'):
            raise NotImplementedError('Binaeres RBXM wird noch nicht unterstuetzt.')
        if data.lstrip().startswith((b'<?xml', b'<roblox')):
            return self._parse_xml(data)
        raise NotImplementedError('Nur RBXMX/XML wird zurzeit unterstuetzt; kein OBJ/glTF/FileMesh.')

    def _parse_xml(self, data: bytes) -> RbxmModel:
        root = ET.fromstring(data)
        if root.tag != 'roblox':
            raise ValueError('Kein Roblox-XML-Dokument')
        model = RbxmModel()
        def walk(item, parent_part=None):
            cls = item.get('class', '')
            p = _properties(item)
            current = parent_part
            if cls in ('Part', 'MeshPart', 'WedgePart', 'CornerWedgePart', 'TrussPart', 'SpawnLocation'):
                current = RbxmPart(name=p['Name'].text or '' if 'Name' in p else '', class_name=cls)
                if 'size' in p or 'Size' in p:
                    current.size = _vector(p.get('size', p.get('Size')), ('X','Y','Z'))
                if 'CFrame' in p:
                    current.position, current.rotation_matrix = _cframe(p['CFrame'])
                if 'Color3uint8' in p:
                    n = int(p['Color3uint8'].text)
                    current.color = ((n >> 16 & 255)/255, (n >> 8 & 255)/255, (n & 255)/255)
                if 'Material' in p:
                    current.material = p['Material'].text or ''
                model.parts.append(current)
            elif cls == 'Attachment' and parent_part is not None:
                name = p['Name'].text or '' if 'Name' in p else ''
                if 'CFrame' in p:
                    pos, rot = _cframe(p['CFrame'])
                else:
                    pos, rot = (0.,0.,0.), (1.,0.,0.,0.,1.,0.,0.,0.,1.)
                parent_part.attachments.append({'name': name, 'position': pos, 'rotation_matrix': rot})
            for child in item.findall('Item'):
                walk(child, current)
        for item in root.findall('Item'):
            walk(item)
        return model

    def parse_filemesh(self, data: bytes) -> dict:
        raise NotImplementedError('Roblox FileMesh ist noch nicht implementiert.')

    def import_into_blender(self, model):
        raise NotImplementedError('Roblox-Asset-Import in Blender ist noch nicht implementiert.')
