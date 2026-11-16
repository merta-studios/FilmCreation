"""Filmspezifische Zusatz-Animationen ergaenzend zur Systembibliothek.

``register(lib)`` wird beim Laden des Films aufgerufen. Die Clips hier gehoeren
nur zu diesem Film. Verfuegbar bleiben trotzdem alle Animationen aus
``1_system/blender_engine/custom_animations.py`` (walk_sad, hug_a, cry_cover_face ...).

Schreibweise:
    lib.new("name", duration=<frames>, loop=<bool>, description="...")
    lib.key("<Bone>", {frame: (x_grad, y_grad, z_grad), ...})
    lib.face(frame, "gesicht")
"""


def register(lib):
    # Mika steht am Fenster und traut sich nicht zu klopfen
    lib.new("mika_zoegert", duration=48, loop=True,
            description="Mika hebt die Hand, zaehlt, senkt sie wieder")
    lib.key("RightUpperArm", {0: (2, 0, -4), 12: (-34, 0, -10), 24: (-30, 0, -12),
                              36: (2, 0, -4), 48: (2, 0, -4)})
    lib.key("RightLowerArm", {0: (4, 0, 0), 12: (36, 0, 0), 24: (40, 0, 0),
                              36: (4, 0, 0), 48: (4, 0, 0)})
    lib.key("Head", {0: (10, 0, -2), 12: (4, 0, -6), 24: (12, 0, -2), 48: (10, 0, -2)})
    lib.face(0, "shy")
    lib.face(24, "sad")

    # Mutter schaut aus dem Fenster in die Stadt
    lib.new("mutter_fenster", duration=96, loop=True,
            description="Ruhiges Schauen, Hand an der Scheibe")
    lib.key("Head", {0: (6, 0, 8), 32: (4, 0, -6), 64: (8, 0, 4), 96: (6, 0, 8)})
    lib.key("RightUpperArm", {0: (-18, 0, -8), 48: (-20, 0, -10), 96: (-18, 0, -8)})
    lib.key("RightLowerArm", {0: (46, 0, 0), 48: (50, 0, 0), 96: (46, 0, 0)})
    lib.key("UpperTorso", {0: (3, 0, 0), 48: (4, 0, 0), 96: (3, 0, 0)})

    # Dankbares, stilles Nicken am Ende
    lib.new("dankbar_nicken", duration=60, loop=False,
            description="Zwei langsame Nicker, Augen geschlossen")
    lib.key("Head", {0: (0, 0, 0), 15: (16, 0, 0), 30: (2, 0, 0), 45: (12, 0, 0),
                     60: (0, 0, 0)})
    lib.key("UpperTorso", {0: (0, 0, 0), 30: (3, 0, 0), 60: (0, 0, 0)})
    lib.face(0, "hopeful")
    lib.face(30, "happy")
