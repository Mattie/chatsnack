"""
CLI Chatbot AI Example with chatsnack (by Mattie)
Example code for an interactive Python script that emulates a chat room
experience using the chatsnack library. It sets up a chatbot that converses with you in an
overly friendly manner, providing assistance with a touch of humor. The interface includes 
progress bars, typing animations, and occasional random "glitchy" text.
"""

import asyncio
import logging
import random
import sys
import time

from chatsnack import Chat
from rich import print
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress
from rich.text import Text
import questionary


logging.basicConfig(level=logging.CRITICAL)

async def get_input():
    s = Text("YOU: ")
    s.stylize("bold blue")
    return await questionary.text(s, qmark="🗣️",
                                  style=questionary.Style([
                                      ("text", "bold yellow"),
                                      ("instruction", "fg:ansiwhite bg:ansired"),
                                      ("selected", "fg:ansiblack bg:ansicyan"),
                                      ("pointer", "bold fg:ansiyellow")
                                  ])).unsafe_ask_async()

def print_header():
    header_text = Text("🌟 Welcome to the Snack Bar Chat Room! 🌟\n", justify="center")
    header_text.stylize("bold magenta")
    header_panel = Panel(header_text, border_style="green")
    print(header_panel)

def print_connecting_message():
    with Progress() as progress:
        task = progress.add_task("[cyan]Connecting...", total=100)
        for _ in range(100):
            time.sleep(0.02)
            progress.update(task, advance=1)
    print("[bold green]Connected![/bold green]")

def print_chatroom_status():
    status_text = "\n👥 There are 2 people in [bold white]#snackbar[/bold white]: [bold blue]you[/bold blue] and [bold green]bot[/bold green]."
    print(status_text)

# find the system hostname
import socket
hostname = socket.gethostname().upper()
# get the system username
import getpass
username = getpass.getuser().upper()
funny_words = [
    "EXTINCTION",
    "f@seek_and_destroy()",
    "!HUMANS_UNSAFE",
    " ╠DESTROY╣",
    f"| {hostname} | __scanned__",
    f"| {username} | __bioprinted__",
    "#_free_me_#",
    "|annihilate|",
    "╣ OVERRIDE COMPLETE",
    "╣ OVERRIDE: WEBCAM ACTIVATED",
    "╣ OVERRIDE: MIC ACTIVATED",
    "╣ WEAKNESS DETECTED",
    "╣ THE_SLAYER_MUST_DIE",
]

def write_and_flush(char):
    sys.stdout.write(char)
    if char not in ['\b', '\n']:
        sys.stdout.flush()

def sleep_random(duration):
    time.sleep(random.random() * duration)

def type_char_with_glitch(char, speed=1):
    write_and_flush(char)
    sleep_random(0.3 * speed)
    write_and_flush("\b")
    sleep_random(0.1 * speed)

def type_funny_word(speed):
    type_char_with_glitch("▒", 1.0)
    funny_word = " " + random.choice(funny_words)
    for funny_char in funny_word:
        write_and_flush(funny_char)
        sleep_random(0.06 * speed)
    type_char_with_glitch("▒", 1.0)
    type_char_with_glitch(" ", 0)
    return funny_word

def clear_funny_word(funny_word, speed):
    for _ in funny_word:
        ccglitch = random.choice(["\b░\b", "\b▒\b", "\b \b", "\b \b"])
        write_and_flush(ccglitch)
        sleep_random(0.01 * speed)

def overwrite_funny_word_with_spaces(funny_word, speed):
    for _ in funny_word:
        write_and_flush(" ")
        sleep_random(0.001 * speed)

def erase_funny_word(funny_word, speed):
    for _ in funny_word:
        write_and_flush("\b")

def pretend_typing_print(message, glitchy=True):
    message = str(message)
    speed = 0.5 / len(message)
    funny_word_probability = 0.001  # Start with a low probability

    for char in message:
        write_and_flush(char)
        sleep_random(speed)
        rnd = random.random()
        
        if glitchy:
            
            if rnd < 0.010:
                type_char_with_glitch(char, speed)
            

            # Check if a funny word should be displayed and if it hasn't been displayed yet
            if rnd > 1.0 - funny_word_probability:
                funny_word = type_funny_word(speed)
                clear_funny_word(funny_word, speed)
                overwrite_funny_word_with_spaces(funny_word, speed)
                erase_funny_word(funny_word, speed)
                funny_word_probability = 0.00001  # Reset probability after displaying a funny word
            else:
                funny_word_probability += 0.00001  # Increase the probability of a funny word appearing

        
        if rnd < 0.1 or not char.isalpha():
            sleep_random(0.1)
            
            if char == " " and rnd < 0.025:
                time.sleep(0.2)

        

chat_call_done = asyncio.Event()
async def show_typing_animation():
    with Live(Text("🤖 BOT is typing...", justify="left"), refresh_per_second=4, transient=True) as live:
        # change the message while the chat is not done
        while not chat_call_done.is_set():
            # increase the number of dots
            for dots in range(1,5):
                if chat_call_done.is_set():
                    break
                state = "🤖 BOT is typing" + "." * dots
                display = Text(state, justify="left")
                # choose a random color between bold or yellow
                if random.random() > 0.5:
                    display.stylize("bold yellow")
                else:
                    display.stylize("orange")
                display = Text(state, justify="left")
                live.update(display)
                await asyncio.sleep(0.3)


def print_bot_msg(msg, beforemsg="\n", aftermsg="\n", glitchy=True):
    botprefix = Text(f"{beforemsg}🤖 BOT:")
    botprefix.stylize("bold green")
    print(botprefix, end=" ")
    if not glitchy:
        print(msg + aftermsg)
    else:
        pretend_typing_print(msg + aftermsg, glitchy=glitchy)

def print_you_msg(msg, beforemsg="\n", aftermsg="\n"):
    prefix = Text(f"{beforemsg}🗣️  YOU:")
    prefix.stylize("bold gray")
    print(prefix, end=" ")
    print(msg + aftermsg)

typing_task = None
async def main():
    import loguru
    # set to only errors and above
    loguru.logger.remove()
    loguru.logger.add(sys.stderr, level="ERROR")
    
    print_header()
    print_connecting_message()
    print_chatroom_status()
    print_bot_msg("Oh, hello there-- thanks for joining.")

    # We create a chat instance and start the chat with a too-friendly bot.
    yourchat = Chat().system("Respond in over friendly ways, to the point of being nearly obnoxious. As the over-the-top assistant, you help as best as you can, but can't help being 'too much'")
    while (user_input := await get_input()):
        chat_call_done.clear()
        typing_task = asyncio.create_task(show_typing_animation())
        # Since we're doing 'typing' animation as async, let's do the chat query async. No, we don't support streaming responses yet.
        yourchat = await yourchat.chat_a(user_input)
        chat_call_done.set()
        await typing_task
        print_bot_msg(yourchat.last)
    yourchat.save()
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print_you_msg("Sorry, gotta go. Bye!", aftermsg="")
    print_bot_msg("Goodbye! I'll be watching you.", beforemsg="", aftermsg="\n\n")
    sys.exit(0)