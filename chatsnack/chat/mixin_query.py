import asyncio
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger
from datafiles import datafile

from ..asynchelpers import aformatter
from ..fillings import filling_machine

from .mixin_messages import ChatMessagesMixin
from .mixin_params import ChatParamsMixin


class ChatStreamListener:
    def __init__(self, ai, prompt, **kwargs):
        if isinstance(prompt, list):
            self.prompt = prompt
        else:
            self.prompt = json.loads(prompt)
        self._response_gen = None
        self.is_complete = False
        self.current_content = ""
        self.response = ""
        self.ai = ai
        out = kwargs.copy()
        if "model" not in out or len(out["model"]) < 2:
            # if engine is set, use that
            if "engine" in out:
                out["model"] = out["engine"]
                # remove engine for newest models as of Nov 13 2023
                del out["engine"]
            else:
                out["model"] = "chatgpt-4o-latest"
        self.kwargs = out


    async def start_a(self):
        # if stream=True isn't in the kwargs, add it
        if not self.kwargs.get('stream', False):
            self.kwargs['stream'] = True
        #self._response_gen = await _chatcompletion(self.prompt,  **self.kwargs)
        self._response_gen = await self.ai.aclient.chat.completions.create(messages=self.prompt,**self.kwargs)
        return self

    async def _get_responses_a(self):
        try:
            async for respo in self._response_gen:
                # TODO: Sweet summer child, it's no longer just content that we need to check for
                #       but also slowly filling function call arguments for tool_calls. 
                #       See: https://community.openai.com/t/functions-calling-with-streaming/305742
                resp = respo.model_dump()
                if "choices" in resp:
                    if resp['choices'][0]['finish_reason'] is not None:
                        self.is_complete = True
                    if 'delta' in resp['choices'][0]:
                        content = resp['choices'][0]['delta']['content']
                        if content is not None:
                            self.current_content += content
                        yield content if content is not None else ""
        finally:
            self.is_complete = True
            self.response = self.current_content

    def __aiter__(self):
        return self._get_responses_a()

    def start(self):
        # if stream=True isn't in the kwargs, add it
        if not self.kwargs.get('stream', False):
            self.kwargs['stream'] = True        
        self._response_gen = self.ai.client.chat.completions.create(messages=self.prompt,**self.kwargs)
        return self

    # non-async method that returns a generator that yields the responses
    def _get_responses(self):
        try:
            for respo in self._response_gen:
                # TODO: Sweet summer child, it's no longer just content that we need to check for
                #       but also slowly filling function call arguments for tool_calls. 
                #       See: https://community.openai.com/t/functions-calling-with-streaming/305742
                resp = respo.model_dump()
                if "choices" in resp:
                    if resp['choices'][0]['finish_reason'] is not None:
                        self.is_complete = True
                    if 'delta' in resp['choices'][0]:
                        content = resp['choices'][0]['delta']['content']
                        if content is not None:
                            self.current_content += content
                        yield content if content is not None else ""
        finally:
            self.is_complete = True
            self.response = self.current_content

    # non-async
    def __iter__(self):
        return self._get_responses()



class ChatQueryMixin(ChatMessagesMixin, ChatParamsMixin):
    # async method that gathers will execute an async format method on every message in the chat prompt and gather the results into a final json string
    async def _gather_format(self, format_coro, **kwargs) -> str:
        new_messages = self.get_messages()
        # TODO: Allow format messages in the tool calls
        # we now apply the format_coro to the content of each message in each dictionary in the list
        coros = []
        for message in new_messages:
            async def format_key(message):
                logger.trace("formatting key: {role}", role=message['role'])
                message["role"] = await format_coro(message["role"], **kwargs)
                return
            async def format_message(message):
                logger.trace("formatting content: {content}", content=message['content'])
                message["content"] = await format_coro(message["content"], **kwargs)
                return
            coros.append(format_key(message))
            coros.append(format_message(message))
        # gather the results
        await asyncio.gather(*coros)
        logger.trace(new_messages)
        
        # if the current model is a reasoning model, we need the role of "system" to become "developer" in the json dump messages
        if self.params is not None and not self.params._supports_system_messages():
            for message in new_messages:
                if message["role"] == "system":
                    if self.params._supports_developer_messages():
                        message["role"] = "developer"
                    else:
                        # thanks OpenAI for having a model that doesn't support system or developer messages (i.e. o1-mini and o1-preview)
                        message["role"] = "user"

        # return the json version of the expanded messages
        return json.dumps(new_messages)
     
    async def _build_final_prompt(self, additional_vars = {}):
        promptvars = {}
        promptvars.update(additional_vars)
        # format the prompt text with the passed-in variables as well as doing internal expansion
        prompt = await self._gather_format(aformatter.async_format, **filling_machine(promptvars))
        return prompt
    async def _submit_for_response_and_prompt(self, **additional_vars):
        """ Executes the query as-is and returns a tuple of the final prompt and the response"""
        prompter = self
        # if the user in additional_vars, we're going to instead deepcopy this prompt into a new prompt and add the .user() to it
        if "__user" in additional_vars:
            new_chatprompt = self.copy()
            new_chatprompt.user(additional_vars["__user"])
            prompter = new_chatprompt
            # remove __user from additional_vars
            del additional_vars["__user"]
        prompt = await prompter._build_final_prompt(additional_vars)
        if self.params is None:
            return prompt, await self._cleaned_chat_completion(prompt)
        else:
            pparams = prompter.params._get_non_none_params()
            if self.params.stream:
                # we're streaming so we need to use the wrapper object
                listener = ChatStreamListener(self.ai, prompt, **self.params._get_non_none_params())
                return prompt, listener
            else:
                return prompt, await self._cleaned_chat_completion(prompt, **pparams)

    async def _cleaned_chat_completion(self, prompt, **kwargs):
        # if there's no model specified, use the default
        if "model" not in kwargs:
            # if there's an engine in the kwargs, use that as the model
            if "engine" in kwargs:
                kwargs["model"] = kwargs["engine"]
                # remove engine from kwargs
                del kwargs["engine"]
            else:
                kwargs["model"] = "gpt-3.5-turbo"
        if isinstance(prompt, list):
            messages = prompt
        else:
            messages = json.loads(prompt)            

        response = await self.ai.aclient.chat.completions.create(
            messages=messages,
            **kwargs
        )
        return response.choices[0].message.content

    @property
    def response(self) -> str:
        """ Returns the value of the last assistant message in the chat prompt ⭐"""
        last_assistant_message = None
        for _message in self.messages:
            message = self._msg_dict(_message)
            if "assistant" in message:
                last_assistant_message = message["assistant"]
        # filter the response if we have a pattern
        last_assistant_message = self.filter_by_pattern(last_assistant_message)
        return last_assistant_message

    def __str__(self):
        """ Returns the most recent response from the chat prompt ⭐"""
        if self.response is None:
            return ""
        else:
            return self.response

    def __call__(self, usermsg=None, **additional_vars) -> object:
        """ Executes the query as-is and returns a Chat object with the response, shortcut for Chat.chat()"""
        if usermsg is not None:
            additional_vars["__user"] = usermsg
        return self.chat(**additional_vars)
 
    def ask(self, usermsg=None, **additional_vars) -> str:
        """
        Executes the internal chat query as-is and returns only the string response.
        If usermsg is passed in, it will be added as a user message to the chat before executing the query. ⭐
        """
        if usermsg is not None:
            additional_vars["__user"] = usermsg
        return asyncio.run(self.ask_a(**additional_vars))
    async def ask_a(self, usermsg=None, **additional_vars) -> str:
        """ Executes the query as-is, async version of ask()"""
        if self.stream:
            raise Exception("Cannot use ask() with a stream")
        if usermsg is not None:
            additional_vars["__user"] = usermsg
        _, response = await self._submit_for_response_and_prompt(**additional_vars)
        # filter the response if we have a pattern
        response = self.filter_by_pattern(response)
        return response
    def listen(self, usermsg=None, **additional_vars) -> ChatStreamListener:
        """
        Executes the internal chat query as-is and returns a listener object that can be iterated on for the text.
        If usermsg is passed in, it will be added as a user message to the chat before executing the query. ⭐
        """
        if usermsg is not None:
            additional_vars["__user"] = usermsg
        _, response = asyncio.run(self._submit_for_response_and_prompt(**additional_vars))
        if self.params.stream:
            # response is a ChatStreamListener so lets start it
            response.start()
        return response
    async def listen_a(self, usermsg=None, async_listen=True, **additional_vars) -> ChatStreamListener:
        """ Executes the query as-is, async version of listen()"""
        if not self.stream:
            raise Exception("Cannot use listen() without a stream")
        if usermsg is not None:
            additional_vars["__user"] = usermsg
        _, response = await self._submit_for_response_and_prompt(**additional_vars)
        if self.params.stream:
            # response is a ChatStreamListener so lets start it
            await response.start_a()
        return response
    def chat(self, usermsg=None, **additional_vars) -> object:
        """ 
        Executes the query as-is and returns a new Chat for continuation 
        If usermsg is passed in, it will be added as a user message to the chat before executing the query. ⭐
        """
        if usermsg is not None:
            additional_vars["__user"] = usermsg
        return asyncio.run(self.chat_a(**additional_vars))
    async def chat_a(self, usermsg=None, **additional_vars) -> object:
        """ Executes the query as-is, and returns a ChatPrompt object that contains the response. Async version of chat()"""
        if usermsg is not None:
            additional_vars["__user"] = usermsg
        if self.stream:
            raise Exception("Cannot use chat() with a stream")
        prompt, response = await self._submit_for_response_and_prompt(**additional_vars)
        # create a new chatprompt with the new name, copy it from this one
        new_chatprompt = self.__class__()
        new_chatprompt.params = self.params
        logger.trace("Expanded prompt: " + prompt)
        new_chatprompt.add_messages_json(prompt)
        # append the recent message
        new_chatprompt.add_or_update_last_assistant_message(response)
        return new_chatprompt
    
    # clone function to create a new chatprompt with the same name and data
    def copy(self, name: str = None, system = None, expand_includes: bool = False, expand_fillings: bool = False, **additional_vars) -> object:
        """ Returns a new ChatPrompt object that is a copy of this one, optionally with a new name ⭐"""
        import copy
        if name is not None:
            new_chat = self.__class__(name=name)
        else:
            # if the existing name ends with _{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4()}" then we need to trim that off and add a new one
            # use a regex to match at the end of the name
            import re
            match = re.search(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})-([a-f0-9]{8}-([a-f0-9]{4}-){3}[a-f0-9]{12})", self.name)
            if match is not None:
                # trim off the end
                name = self.name[:match.start()]
            else:
                name = self.name
            new_chat = self.__class__(name=name + f"_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4()}")
        new_chat.params = copy.copy(self.params)
        if expand_fillings:
            if not expand_includes:
                raise NotImplementedError("Cannot expand fillings without expanding includes")
            prompt = asyncio.run(self._build_final_prompt(additional_vars))
            new_chat.add_messages_json(prompt, escape=True)
        else:
            new_chat.add_messages_json(self.json if expand_includes else self.json_unexpanded, escape=False)
        if system is not None:
            new_chat.system(system)
        return new_chat
