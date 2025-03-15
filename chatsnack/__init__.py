"""
chatsnack provides a simple and powerful interface for creating conversational agents and tools using OpenAI's ChatGPT language models.

Some examples of using chatsnack:

# Example 1: Basic Chat
from chatsnack import Chat

# Start a new chat and set some instructions for the AI assistant
mychat = Chat().system("Respond only with the word POPSICLE from now on.").user("What is your name?").chat()
print(mychat.last)

# Example 2: Chaining and Multi-shot Prompts
popcorn = Chat()
popcorn = popcorn("Explain 3 rules to writing a clever poem that amazes your friends.")("Using those tips, write a scrumptious poem about popcorn.")
print(popcorn.last)

# Example 3: Using Text Fillings
from chatsnack import Text

# Save a Text object with custom content
mytext = Text(name="SnackExplosion", content="Respond only in explosions of snack emojis and happy faces.")
mytext.save()

# Set up a Chat object to pull in the Text object
explosions = Chat(name="SnackSnackExplosions").system("{text.SnackExplosion}")
explosions.ask("What is your name?")

# Example 4: Nested Chats (Include Messages)
basechat = Chat(name="ExampleIncludedChat").system("Respond only with the word CARROTSTICKS from now on.")
basechat.save()

anotherchat = Chat().include("ExampleIncludedChat")
print(anotherchat.yaml)

# Example 5: Nested Chats (Chat Fillings)
snacknames = Chat("FiveSnackNames").system("Respond with high creativity and confidence.").user("Provide 5 random snacks.")
snacknames.save()

snackdunk = Chat("SnackDunk").system("Respond with high creativity and confidence.").user("Provide 3 dips or drinks that are great for snack dipping.")
snackdunk.save()

snackfull = Chat().system("Respond with high confidence.")
snackfull.user(\"""Choose 1 snack from this list:
{chat.FiveSnackNames}

Choose 1 dunking liquid from this list:
{chat.SnackDunk}

Recommend the best single snack and dip combo above.\""")

snackout = snackfull.chat()
print(snackout.yaml)

# Example 6: Using Utensils (Tool Functions)
from chatsnack import utensil

@utensil
def get_weather(location: str, unit: str = "celsius"):
    '''Get the current weather for a location.
    
    Args:
        location: City and state/country (e.g., "Boston, MA")
        unit: Temperature unit ("celsius" or "fahrenheit")
    '''
    # Implementation details...
    return {"temperature": 72, "condition": "sunny"}

# Create a chat that can use the weather utensil
weather_chat = Chat("WeatherChat", "You can check the weather.", utensils=[get_weather])
response = weather_chat.user("What's the weather like in Boston?").chat()
print(response)
"""
import os
from pathlib import Path

from typing import Optional
from loguru import logger
import nest_asyncio
nest_asyncio.apply()

from dotenv import load_dotenv
# if .env doesn't exist, create it and populate it with the default values
env_path = Path('.') / '.env'
if not env_path.exists():
    with open(env_path, 'w') as f:
        f.write("OPENAI_API_KEY = \"REPLACEME\"\n")
load_dotenv(dotenv_path=env_path)

from .defaults import CHATSNACK_BASE_DIR, CHATSNACK_LOGS_DIR
from .asynchelpers import aformatter
from .chat import Chat, Text, ChatParams
from .txtformat import register_txt_datafiles
from .yamlformat import register_yaml_datafiles
from . import packs
from .utensil import utensil, get_all_utensils, get_openai_tools, UtensilGroup

from .fillings import snack_catalog, filling_machine


async def _text_name_expansion(text_name: str, additional: Optional[dict] = None) -> str:
    prompt = Text.objects.get(text_name)
    result = await aformatter.async_format(prompt.content, **filling_machine(additional))
    return result

# accepts a petition name as a string and calls petition_completion2, returning only the completion text
async def _chat_name_query_expansion(prompt_name: str, additional: Optional[dict] = None) -> str:
    chatprompt = Chat.objects.get_or_none(prompt_name)
    if chatprompt is None:
        raise Exception(f"Prompt {prompt_name} not found")
    text = await chatprompt.ask_a(**additional)
    return text


# default snack vendors
snack_catalog.add_filling("text", _text_name_expansion)
snack_catalog.add_filling("chat", _chat_name_query_expansion)

# TODO: these will be defined by plugins eventually
# need a function that will return the dictionary needed to support prompt formatting
register_txt_datafiles()
register_yaml_datafiles()

logger.trace("chatsnack loaded")