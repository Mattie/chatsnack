# Snackchat Web-based chatbot app example
#
# pip install chatsnack[examples]
# be sure there's a .env file in the same directory as app.py with your OpenAI API key as OPENAI_API_KEY = "YOUR_KEY_HERE"
# python .\app.py
# open http://localhost:5000


from flask import Flask, render_template, request, jsonify
from chatsnack import Chat
from chatsnack.packs import ChatsnackHelp, Jolly, Jane, Data, Confectioner, Chester
from flask import Flask, render_template, request, session
import re

app = Flask(__name__)
app.secret_key = "CHANGE_ME_OR_YOUR_SESSIONS_WILL_BE_INSECURE"

bots = {
    "help": ChatsnackHelp,
    "emoji": Chat().system("{text.EmojiBotSystem}"),
    "confectioner": Confectioner,
    "jane": Jane,
    "data": Data,
    "jolly": Jolly,
    "chester": Chester,
}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat_old", methods=["POST"])
def chat_old():
    user_input = request.form["user_input"]
    bot_choice = request.form["bot_choice"]

    bot = bots.get(bot_choice, ChatsnackHelp)
    chat_output = bot.chat(user_input)
    response = chat_output.response

    return jsonify({"response": response})

@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.form.get('user_input')
    bot_choice = request.form.get('bot_choice')
    
    response = None
    try:
        if 'chat_output' not in session or bot_choice != session['bot_choice']:
            session['bot_choice'] = bot_choice
            bot = bots.get(bot_choice, ChatsnackHelp)
            chat_output = bot
        else:
            chat_output = Chat.objects.get_or_none(session['chat_output'])
            if chat_output is None:
                bot = bots.get(bot_choice, ChatsnackHelp)
                chat_output = bot

        chat_output = chat_output.chat(user_input)
        chat_output.save()

        session['chat_output'] = chat_output.name
    except Exception as e:
        print(e)
        error_name = e.__class__.__name__
        response = "I'm sorry, I ran into an error. ({})".format(error_name)
        raise e

    response = chat_output.response if response is None else response
    # if the response has "\n" then convert all of them to <br>
    response = response.replace("\n", "<br>")
    # if the response has "```" followed by another "```" later then convert to <pre>
    if "```" in response:
        response = re.sub(r"```(.*?)```", r"<pre>\1</pre>", response, flags=re.DOTALL)

    return jsonify({"response": response})

@app.route('/start_new', methods=['POST'])
def start_new():
    session.pop('chat_output', None)
    session.pop('bot_choice', None)
    return render_template('index.html')


if __name__ == "__main__":
    app.run(debug=True)

