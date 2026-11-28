"""Descubrimiento automático de indicadores: importa cada módulo del paquete."""
import importlib
import pkgutil

from src.analytics.base import REGISTRY, AnalysisContext, Indicator, register, run_indicators

for _mod in pkgutil.iter_modules(__path__):
    if _mod.name not in ("base",) and not _mod.name.startswith("_"):
        importlib.import_module(f"{__name__}.{_mod.name}")

__all__ = ["REGISTRY", "AnalysisContext", "Indicator", "register", "run_indicators"]
