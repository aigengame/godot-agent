"""The gda harness: the game-side autoload gda-daemon installs into a project.

Bundles the harness GDScript and the Python installer that registers it as a
project autoload (ADR-0018). The harness is inert unless gda-daemon launched the
run, so it does nothing in a human editor run, a plain run, or a shipped build.
"""
