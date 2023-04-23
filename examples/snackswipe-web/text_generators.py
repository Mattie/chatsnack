import asyncio
from chatsnack import Chat, Text

class TextResult:
    def __init__(self, generator_name, text):
        self.generator_name = generator_name
        self.text = text
        self.votes = 0

    def vote(self, like):
        if like:
            self.votes += 1

    def __str__(self):
        return f"{self.generator_name}: {self.text}"



# saved in datafiles/chatsnack/mydaywss.txt
test_prompt = "Passage:\n{text.mydaywss}"
response_prefix = "## CONCISE_SUMMARY ##"
async def text_generator_1():
    c = Chat("""IDENTITY: Professional document summarizer.
      Respond to the user only in the following format:
      (1) Use your expertise to explain, in detail, the top 5 things to consider when making 
      concise summararies of any text document.
      (2) Elaborate on 3 more protips used by the world's best summarizers to
      avoid losing important details and context.
      (3) Now specifically consider the user's input. Use your expertise and your own guidance,
      describe in great detail how an author could apply that wisdom to summarize the user's 
      text properly. What considerations come to mind? What is the user expecting?
      (4) Finally, use everything above to author a concise summary of the user's input that will
      delight them with your summarization skills. Final summary must be prefixed with 
      "## CONCISE_SUMMARY ##" on a line by itself.""")
    result = await c.chat_a(test_prompt)
    result = result.response
    result = result[result.rfind(response_prefix) + len(response_prefix):]
    return TextResult("Default Summarizer", result)

async def text_generator_2():
    from chatsnack.packs import Summarizer
    c = Summarizer
    result = await c.chat_a(test_prompt)
    result = result.response
    my_response_prefix = "CONCISE_SUMMARY:"
    result = result[result.rfind(my_response_prefix) + len(my_response_prefix):]
    return TextResult("Default Summarizer (Built-in)", result)


async def text_generator_3():
    c = Chat("""IDENTITY: Professional document summarizer.
      Respond to the user only in the following format:
      (1) Use your expertise to explain, in detail, the top 5 things to consider when making 
      concise summararies of any text document.
      (2) Elaborate on 3 more protips used by the world's best summarizers to
      avoid losing important details and context.
      (3) Now specifically consider the user's input. Use your expertise and your own guidance,
      describe in great detail how an author could apply that wisdom to summarize the user's 
      text properly. What considerations come to mind? What is the user expecting?
      (4) Finally, use everything above to author a concise summary of the user's input that will
      delight them with your summarization skills. Final summary must be prefixed with 
      "## CONCISE_SUMMARY ##" on a line by itself.""")
    c.engine = "gpt-4"
    result = await c.chat_a(test_prompt)
    result = result.response
    result = result[result.rfind(response_prefix) + len(response_prefix):]
    return TextResult("Default Summarizer (GPT-4)", result)

text_generators = [text_generator_1, text_generator_2, text_generator_3]


def print_results(results):
    votes = {}
    for result in results: 
        if result.generator_name not in votes:
            votes[result.generator_name] = 0
        votes[result.generator_name] += result.votes

    winner = max(votes, key=votes.get)
    margin = votes[winner] - max(v for k, v in votes.items() if k != winner)

    print(f"Winner: {winner} with {votes[winner]} votes")
    print(f"Margin of victory: {margin}")
