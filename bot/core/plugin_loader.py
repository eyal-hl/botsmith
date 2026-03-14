"""Dynamic loader for Tier 2 Python plugin skills."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from bot import config

logger = logging.getLogger(__name__)


@dataclass
class PluginContext:
    """Context passed to plugin execute() functions."""
    http: Any  # httpx.AsyncClient
    memory: str
    chat_id: int

    async def send_message(self, text: str, parse_mode: str | None = None) -> None:
        """Provided at runtime by the caller."""
        raise NotImplementedError


@dataclass
class LoadedPlugin:
    name: str
    trigger: dict
    execute: Callable
    module: Any


_plugins: dict[str, LoadedPlugin] = {}


def load_all_plugins() -> dict[str, LoadedPlugin]:
    """Load all .py files from plugins/ directory."""
    global _plugins
    _plugins.clear()

    for path in config.PLUGINS_DIR.glob("*.py"):
        if path.name.startswith("_"):
            continue
        try:
            plugin = _load_plugin_file(path)
            _plugins[plugin.name] = plugin
            logger.info("Loaded plugin: %s (trigger: %s)", plugin.name, plugin.trigger)
        except Exception as e:
            logger.error("Failed to load plugin %s: %s", path.name, e)

    logger.info("Loaded %d plugins total", len(_plugins))
    return _plugins


def _load_plugin_file(path: Path) -> LoadedPlugin:
    """Load a single plugin file and validate its interface."""
    name = path.stem
    module_name = f"plugins.{name}"

    # Remove from sys.modules if previously loaded (for hot-reload)
    if module_name in sys.modules:
        del sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Validate interface
    if not hasattr(module, "TRIGGER"):
        raise AttributeError(f"Plugin {name} missing TRIGGER dict")
    if not hasattr(module, "execute"):
        raise AttributeError(f"Plugin {name} missing execute() function")
    if not callable(module.execute):
        raise TypeError(f"Plugin {name}.execute is not callable")

    return LoadedPlugin(
        name=name,
        trigger=module.TRIGGER,
        execute=module.execute,
        module=module,
    )


def get_plugin(name: str) -> LoadedPlugin | None:
    return _plugins.get(name)


def get_all_plugins() -> dict[str, LoadedPlugin]:
    return _plugins.copy()


def reload_plugin(name: str) -> LoadedPlugin | None:
    """Hot-reload a single plugin from disk."""
    path = config.PLUGINS_DIR / f"{name}.py"
    if not path.exists():
        _plugins.pop(name, None)
        return None
    try:
        plugin = _load_plugin_file(path)
        _plugins[name] = plugin
        logger.info("Reloaded plugin: %s", name)
        return plugin
    except Exception as e:
        logger.error("Failed to reload plugin %s: %s", name, e)
        return None
