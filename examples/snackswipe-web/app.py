# Snackchat Web-based Prompt Tester app example
#
# pip install chatsnack[examples]
# be sure there's a .env file in the same directory as app.py with your OpenAI API key as OPENAI_API_KEY = "YOUR_KEY_HERE"
# python .\app.py
# open http://localhost:5000

import asyncio
import random
from uuid import uuid4
from flask import Flask, render_template, request, jsonify, session
from text_generators import text_generators, TextResult
from flask_session import Session
from collections import deque
import json
import threading

class TextResultEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, TextResult):
            return obj.__dict__
        return super(TextResultEncoder, self).default(obj)

app = Flask(__name__)
app.secret_key = "super%^$@^!@!secretkey%^$@^%@!"
app.config['SESSION_TYPE'] = 'filesystem'
app.json_encoder = TextResultEncoder
Session(app)

@app.route('/')
def index():
    problem_statement = "Your problem statement here."
    return render_template('index.html', problem_statement=problem_statement)

user_queues = {}

@app.route('/start-generation', methods=['POST'])
def start_generation():
    num_tests = int(request.form['num_tests'])
    text_generators_copy = text_generators.copy()
    random.shuffle(text_generators_copy)
    user_id = str(uuid4())
    session['user_id'] = user_id
    user_queues[user_id] = deque()
    threading.Thread(target=run_async_generation, args=(num_tests, text_generators_copy, user_queues[user_id])).start()
    return jsonify({"status": "started"})

def run_async_generation(num_tests, text_generators_copy, results_queue):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(fill_results_queue(num_tests, text_generators_copy, results_queue))
    loop.close()
    
@app.route('/fetch-text', methods=['POST'])
def fetch_text():
    user_id = session.get('user_id', None)
    results_queue = user_queues.get(user_id, None)
    if results_queue:
        result = results_queue.popleft()
        # if result is a dict
        if isinstance(result, dict) and "status" in result and result["status"] == "completed":
            del user_queues[user_id]
            return jsonify({"status": "completed"})
        return jsonify(result)
    else:
        return jsonify({"status": "waiting"})

# Update this function to accept the results_queue as an argument
async def fill_results_queue(num_tests, text_generators_copy, results_queue):
    async for result in async_text_generation(num_tests, text_generators_copy):
        results_queue.append(result)
    # Add a special result to indicate that the generation is complete
    results_queue.append({"status": "completed"})

# @app.route('/generate-text', methods=['POST'])
# async def generate_text():
#     num_tests = int(request.form['num_tests'])
#     text_generators_copy = text_generators.copy()
#     random.shuffle(text_generators_copy)
#     results = []
#     async for result in async_text_generation(num_tests, text_generators_copy):
#         results.append(result)
#     return jsonify(results)

# async def async_text_generation(num_tests, text_generators):
#     #tasks = [text_gen() for text_gen in text_generators]
#     current_tasks = []
#     # for every num_tests we want the same tasks to be added back to the list
#     for _ in range(num_tests):
#         # extend current_tasks with another copy
#         current_tasks.extend([text_gen() for text_gen in text_generators])

#     for _ in range(num_tests):
#         while current_tasks:
#             done, pending = await asyncio.wait(current_tasks, return_when=asyncio.FIRST_COMPLETED)
#             for task in done:
#                 yield task.result()
#             current_tasks = list(pending)

# import asyncio

async def async_text_generation(num_tests, text_generators):
    priority_generators = text_generators[:2]
    background_generators = text_generators[2:]
    
    priority_tasks = []
    background_tasks = []

    for _ in range(num_tests):
        priority_tasks.extend([text_gen() for text_gen in priority_generators])
        background_tasks.extend([text_gen() for text_gen in background_generators])

    while priority_tasks:
        done, pending = await asyncio.wait(priority_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            yield task.result()
        priority_tasks = list(pending)

    while background_tasks:
        done, pending = await asyncio.wait(background_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            yield task.result()
        background_tasks = list(pending)


if __name__ == '__main__':
    app.run(debug=True)
