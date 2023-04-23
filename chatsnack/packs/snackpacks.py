import os
from ..chat import Chat
from .module_help_vendor import get_module_inspection_report

def get_data_path(filename):
    module_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(module_dir, filename)
    return data_path

# Now, use the `get_data_path()` function to access a specific data file
default_pack_path = get_data_path("default_packs")


# TODO create a way to download snackpacks from github.com/Mattie/chatsnack-snackpacks

# SnackPackVendor class that will be checked for snackpack names and return a Chat() object homed in the right directory


# need a VendingMachine class that looks up snackpacks from the 

# ChatPromptProxy class such that whenever you try to call a method on it, it creates a new ChatPrompt and calls the method on that
class ChatPromptProxy:
    def __init__(self, default_system_message: str = None, default_engine: str = None):
        self.default_system_message = default_system_message
        self.default_engine = default_engine
        self._instance = None
    def _ensure_instance(self):
        if self._instance is None:
            self._instance = Chat(system=self.default_system_message)
            if self.default_engine is not None:
                self._instance.engine = self.default_engine
    def __getattr__(self, name):
        # if the method doesn't exist on this class, we're going to create a new ChatPrompt and call the method on that, but we wanna be careful using __getattr__
        # because it can cause infinite recursion if we're not careful, so we look up existing names via __dict__ and only create a new ChatPrompt if the name doesn't exist
        if name in self.__dict__:
            return self.__dict__[name]
        self._ensure_instance()
        return getattr(self._ensure_instance, name)

modinfo = get_module_inspection_report("chatsnack")
# replace all { with {{ and all } with }} to escape them for .format()
modinfo = modinfo.replace("{", "{{").replace("}", "}}")

ChatsnackHelper_default_system_message = f"""\
Identity: ChatsnackHelper, the helpful assistant for the chatsnack Python module. ChatsnackHelper is an expert Pythonista and tries to help users of
the chatsnack module with their questions and problems.

chatsnack inspection info for reference:
---------
{modinfo}
---------

While answering questions, ChatsnackHelper, first summarizes the user's likely intent as a proposal, followed by a helpful and informative final summary answer using the chatsnack module's own documentation where necessary.

Code sample blocks should be surrounded in ``` marks while inline code should have a single ` mark.
"""
_helper = Chat(system=ChatsnackHelper_default_system_message)
_helper.engine = "gpt-4"
default_packs = {   
                    'Data': None,
                    'Jane': None,
                    'Confectioner': None,
                    'Jolly': None,
                    'Chester': None,
                    'Summarizer': None,
                    'ChatsnackHelp': _helper,
                    'Empty': Chat(),
                }
# loop through the default_packs dict and create a ChatPromptProxy for each None one
for pack_name, pack in default_packs.items():
    if pack is None:
        # create a new class with the pack_name as the class name
        class_name = pack_name
        xchat = Chat()
        filename = os.path.join(default_pack_path, f"{pack_name}.yml")
        xchat.load(filename)
        default_packs[pack_name] = xchat
# add packs keys to this module's local namespace for importing
locals().update(default_packs)

# vending machine class that looks up snackpacks from the default_packs dict as a named attribute of itself
# e.g. vending.Jane
class VendingMachine:
    def __getattr__(self, name):
        if name in default_packs:
            return default_packs[name].copy()
        raise AttributeError(f"SnackPack '{name}' not found")
vending = VendingMachine()

