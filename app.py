"""Compatibility entry point for launch scripts and imports."""
from fluid_server import *  # noqa: F401,F403

if __name__ == "__main__":
    import runpy
    runpy.run_module("fluid_server", run_name="__main__")
