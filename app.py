import os
from flask import Flask, request
import telegram


global bot
global TOKEN
TOKEN = os.environ.get('bot_token')
bot = telegram.Bot(token=TOKEN)

app = Flask(__name__)

@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    # we use the bot object to link the bot to our app which live
    # in the link provided by URL
    s = bot.setWebhook('{URL}{HOOK}'.format(URL=os.environ.get('URL'), HOOK=TOKEN))
    # something to let us know things work
    if s:
        return "webhook setup ok"
    else:
        return "webhook setup failed"


@app.route("/{}".format(TOKEN), methods=["POST"])
def respond():
    # retrieve the message in JSON and then transform it to Telegram object
    update = telegram.Update.de_json(request.get_json(force=True), bot)

    chat_id = update.message.chat.id
    msg_id = update.message.message_id

    # Telegram understands UTF-8, so encode text for unicode compatibility
    text = update.message.text.encode("utf-8").decode()
    # for debugging purposes only
    print("got text message :", text)
    # the first time you chat with the bot AKA the welcoming message
    if text == "/start":
        handleStartResponse(chat_id, message_id)
    else:
        handleUnavailableFeatureResponse(chat_id, message_id)


def handleStartResponse(chat_id, message_id):
    welcome_message = "Welcome to QuizBot, I can help you generate quizzes from documents"
    bot.sendMessage(
        chat_id=chat_id, text=welcome_message, reply_to_message_id=message_id
    )


def handleUnavailableFeatureResponse(chat_id, message_id):
    response_message = "Feature coming soon"
    bot.sendMessage(
        chat_id=chat_id, text=welcome_message, reply_to_message_id=message_id
    )


@app.route('/')
def index():
    return 'Server running'
if __name__ == '__main__':
    # note the threaded arg which allow
    # your app to have more than one thread
    app.run(threaded=True)
