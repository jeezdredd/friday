import importlib
import logging
import pkgutil

from friday.tools.registry import Tool, ToolRegistry, registry, tool

__all__ = ["Tool", "ToolRegistry", "load_all", "registry", "tool"]

log = logging.getLogger(__name__)

_loaded = False


def load_all() -> ToolRegistry:
    """Импортирует все модули из friday/tools/, чтобы сработали декораторы @tool.
    Модули с префиксом "_" пропускаются (удобно для черновиков)."""
    global _loaded
    if not _loaded:
        for mod in pkgutil.iter_modules(__path__):
            if mod.name.startswith("_") or mod.name == "registry":
                continue
            importlib.import_module(f"{__name__}.{mod.name}")
            log.debug("Loaded tools module %s", mod.name)
        _loaded = True
    return registry
