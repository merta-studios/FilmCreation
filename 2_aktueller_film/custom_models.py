"""Kleine eigene Requisiten fuer 'In dieser Stadt leuchtet dein Name'."""


def namenlaterne(world, pos=(0, 0, 0), rotation=(0, 0, 0), **params):
    """Hohe Strassenlaterne mit einer kleinen Tafel fuer einen Namen."""
    x, y, z = pos
    world.cylinder("namenlaterne_mast", (x, y, z + 2.2), 0.12, 4.4,
                   color="#635F62", texture="metal", vertices=12)
    world.block("namenlaterne_arm", (x + 0.62, y, z + 4.25), (1.35, 0.12, 0.12),
                color="#635F62", texture="metal")
    world.block("namenlaterne_kappe", (x + 1.18, y, z + 4.12), (0.72, 0.5, 0.18),
                color="#4A4038", texture="metal")
    world.ball("namenlaterne_licht", (x + 1.18, y, z + 3.9), 0.22,
                color="#FFC978", texture="neon")
    world.sign("namenlaterne_schild", (x, y - 0.2, z + 3.0), "DEIN NAME",
               size=0.18, width=1.15, height=0.36, font="inter",
               color="#FFF1CF", board_color="#27462D", board_texture="metal",
               border=False)
    return None


MODELS = {"namenlaterne": namenlaterne}
