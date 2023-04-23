from typing import Optional, Callable, Dict
from loguru import logger
from typing import Callable, Optional, Dict

class _AsyncFillingMachine:
    """Used for parallel variable expansion"""
    def __init__(self, src, addl=None):
        self.src = src
        self.addl = addl

    def __getitem__(self, k):
        async def completer_coro():
            x = await self.src(k, self.addl)
            logger.trace("Filling machine: {k} filled with:\n{x}", k=k, x=x)
            return x
        return completer_coro

    __getattr__ = __getitem__


class _FillingsCatalog:
    def __init__(self):
        self.vendors = {}

    def add_filling(self, filling_name: str, filling_machine_callback: Callable):
        """Add a new filling machine to the fillings catalog"""
        self.vendors[filling_name] = filling_machine_callback
    
# singleton
snack_catalog = _FillingsCatalog()

def filling_machine(additional: Optional[Dict] = None) -> dict:
    fillings_dict = additional.copy() if additional is not None else {}
    for k, v in snack_catalog.vendors.items():
        if k not in fillings_dict:
            # don't overwrite if they had an argument with the same name
            fillings_dict[k] = _AsyncFillingMachine(v, additional)
    return fillings_dict