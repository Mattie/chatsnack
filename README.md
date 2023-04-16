# chatsnack

chatsnack is the easiest Python library for rapid development with OpenAI's ChatGPT API. It provides an intuitive interface for creating and managing chat-based prompts and responses, making it convenient to build complex, interactive conversations with AI.

![chatsnack features](/docs/chatsnack_features_smaller.jpg)
## Setup

### Got snack?

Install the `chatsnack` package from PyPI:

```bash
pip install chatsnack
```

### Got keys?

Add your OpenAI API key to your .env file. If you don't have a .env file, the library will create a new one for you. You can use env.template.cataclysm as an example.

### Learn More!
Read more below, watch the [video](https://youtu.be/ZK8fUuQDgZ4) or check out the [Getting Started notebook](notebooks/).

## Usage

### Enjoy a Quick Snack

Easiest way to get going with `chatsnack` is with built-in snack packs. Each pack is a singleton ready to mingleton.

```python
>>> from chatsnack.packs import ChatsnackHelp
>>> ChatsnackHelp.ask("What is your primary directive?")
```
> *"My primary directive is to assist users of the chatsnack Python module by answering questions 
and helping with any problems or concerns related to the module. I aim to provide helpful and 
informative responses based on the chatsnack module's documentation and best practices."*

You can try out other example snack packs like `Confectioner`, `Jolly`, `Chester`, `Jane`, or `Data`. (Eventually there will be an easy way to create and share your own.)

Instead of `.ask()` we can call `.chat()` which will allow us to continue a conversation.
```python
>>> mychat = ChatsnackHelp.chat("What is chatsnack?")  # submits and returns a new chat object
>>> print(mychat.response)
```
> *Chatsnack is a Python module that provides a simple and powerful interface for creating conversational agents and tools using OpenAI's ChatGPT language models. It allows you to easily build chat prompts, manage conversation flow, and integrate with ChatGPT to generate responses. With Chatsnack, you can create chatbots, AI-assisted tools, and other conversational applications using a convenient and flexible API.*

Now we can add more messages to that chat however we'd like:
```python
>>> mychat.user("Respond in only six word sentences from now on.")
>>> mychat.asst("I promise I will do so.")
>>> mychat.user("How should I spend my day?")
>>> mychat.ask()
```
> *"Explore hobbies, exercise, connect with friends."*

If you want a super simple interactive conversation with you and a chatbot, you could do something like this:
```python
from chatsnack.packs import Jolly
yourchat = Jolly  # interview a green giant
while (user_input := input("Chat with the bot: ")):
    print(f"USER: {user_input}")
    yourchat = yourchat.chat(user_input)
    print(f"THEM: {yourchat.last}")
```
### Tasty Features

There's many other tidbits covered in the notebooks, examples, and videos. Here are some of the highlights:

* Everyday Snacking
  * Chat objects
  * Chat command chaining
  * YAML convenience
  * OpenAI parameters
* Serious Snacking
  * Intense chaining
  * Fillings (e.g. nested chats and text files)
  * Snack Pack Vending Machine


### Everyday Snacking
#### Chat objects and Chaining 


```python
from chatsnack import Chat
mychat = Chat()
mychat.system("Respond only with the word POPSICLE from now on.")
mychat.user("What is your name?")
mychat.ask()
```
> *"POPSICLE."*

You can chain messages together for more complex conversations:

```python
newchat = (
  Chat()
  .system("Respond only with the word POPSICLE from now on.")
  .user("What is your name?")
  .chat()
)
newchat.response
```
> *"POPSICLE."*

Note that there are some syntax shortcuts omitted above, see the Serious Snacking section for more on those.
#### Yummy YAML

Generative AI gets a bit messy these days with so much text in our code. `chatsnack` makes it very easy to use a clean YAML syntax to load/save/edit your chat templates without so many hard-coded strings in your code.

```python
# Every chat is totally yaml-backed, we can save/load/edit
print(newchat.yaml)
```
```yaml
messages:
  - system: Respond only with the word POPSICLE from now on.
  - user: What is your name?
  - assistant: POPSICLE.
```
For rapid reuse, you can give your chats a name so you can save/load as needed (or using them as *Fillings* as we'll see later).
  
  ```python
  newchat.name = "Popsicle"
  newchat.save()
  ```
  ```python
  # Load a chat from a file
  midnightsnack = Chat(name="popsicle")
  print(midnightsnack.ask())
  ```
  > *"POPSICLE."*
    

#### Adjusting Cooking Temperatures

By default, `gpt-3.5-turbo` is the default chat API with a default temperature of `0.5`. If you prefer, you can change OpenAI parameters for each chat, such as the engine and temperature:

```python
from chatsnack import Chat
wisechat = Chat("Respond with professional writing based on the user query.")
wisechat.user("Author an alliterative poem about good snacks to eat with coffee.")
wisechat.engine = "gpt-4"
wisechat.temperature = 0.8
```
This also gets captured in the YAML:

```python
print(wisechat.yaml)
```
```yaml
params:
  engine: gpt-4
  temperature: 0.8
messages:
  - system: Respond with professional writing based on the user query.
  - user: Author an alliterative poem about good snacks to eat with coffee.
```

### Serious Snacking

#### Ingredient Shortcuts
If you're wanting to minimize typing, you can use omit a couple of ingredients.
##### Quick System Message
For example, this:
```python
mychat = Chat()
mychat.system("Respond hungrily")
```
is the same as:
```python
# if there's only one argument or a keyword of system argument, you can omit the .system()
mychat = Chat("Respond hungrily")
```
##### Quick User Message
`.ask()` and `.chat()` are also shortcuts for `.user().ask()` and `.user().chat()` respectively.
For example, this:
```python
mychat = Chat()
mychat.system("Respond hungrily")
mychat.user("Tell me about cookies")
print(mychat.ask())
```
is the same as:
```python
print(Chat("Respond hungrily").ask("Tell me about cookies"))
```
Basically, we assume if you're making a `Chat()` you'll need a system message, and if you're sending an `ask()` or `chat()` you'll need a user message. So you can omit those if you want (or use `system=` and `user=` keywords if you want to be explicit).

##### Quick Assistants

Also, `.asst()` is an alias shortcut for `.assistant()` if you want you code to align cleanly with other 4-letter `.user()` and `.chat()` calls.

##### Binge-chaining

If you're feeling wild, you can actually call any chat (like a function) and it'll submit the chat and continue, just like `.chat()`. This allows even more terse chaining. This can come in handy when you're looking for 

```python
popcorn = (
    Chat("Respond with the certainty and creativity of a professional writer.")
    ("Explain 3 rules to writing a clever poem that amazes your friends.") 
    ("Using those tips, write a scrumptious poem about popcorn.")
)
# the above is the same as Chat().system('Respond...').chat('Explain...').chat('Using...')
print(popcorn.response)
```
> In the kitchen, I hear a popping sound,
A symphony of kernels dancing around.
A whiff of butter, a sprinkle of salt,
My taste buds tingle, it's not their fault.
> 
> The popcorn pops, a fluffy delight,
A treat for the senses, a feast for the sight.
Golden and crispy, a perfect snack,
A bowl of happiness, there's no going back.
> 
> I pick one up, it's warm to the touch,
I savor the flavor, it's too much.
A burst of butter, a crunch of salt,
A symphony of flavors, it's not my fault.
> 
> I munch and crunch, it's such a delight,
A scrumptious treat, a popcorn flight.
A perfect snack, for any time,
Popcorn, oh popcorn, you're simply divine.



#### Nested Chats

You can include other chats in your current chat or use `{chat.___}` filling expander for more dynamic AI generations:

```python
basechat = Chat(name="ExampleIncludedChat").system("Respond only with the word CARROTSTICKS from now on.")
basechat.save()

anotherchat = Chat().include("ExampleIncludedChat")
```

#### Snacks with Fillings 

You can work with Text files and YAML files to create reusable chat snippets that are filled-in before execution. 

```python
from chatsnack import Text
mytext = Text(name="SnackExplosion", content="Respond only in explosions of snack emojis and happy faces.")
mytext.save()

explosions = Chat(name="SnackSnackExplosions").system("{text.SnackExplosion}")
explosions.ask("What is your name?")
```

#### Fillings Resolving in Parallel

If you have a prompt that requires expanding multiple fillings, `chatsnack` will resolve them in parallel as it expands the prompt. This comes in handy with `{chat.__}` and `{vectorsearch.__}` (TODO) snack fillings.

TODO: See the notebooks for more details on this.

## License

chatsnack is released under the MIT License.