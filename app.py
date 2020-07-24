import os
import re
import json
from flask import Flask, request
import telegram
import requests
import textract
import redis
from random import shuffle
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, ReplyKeyboardRemove
from question_generator import generateQuestions 

global bot, TOKEN, URL

TOKEN = os.environ.get('bot_token')
URL = os.environ.get('URL')
bot = telegram.Bot(token=TOKEN)

redis_client = redis.StrictRedis(
    host="localhost", port=os.environ.get('REDIS_PORT') , db=0, decode_responses=True)

app = Flask(__name__)

@app.route('/setwebhook', methods=['GET', 'POST'])
def set_webhook():
    s = bot.setWebhook('{URL}{HOOK}'.format(
        URL=os.environ.get('URL'), HOOK=TOKEN))
    if s:
        return "webhook setup ok"
    else:
        return "webhook setup failed"


@app.route("/{}".format(TOKEN), methods=["POST"])
def respond():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    chat_id = update.message.chat.id
    message_id = update.message.message_id

    current_quiz_index = redis_client.get("{}-quiz-index".format(chat_id))
    print("current quiz index {}".format(current_quiz_index))
    print(redis_client.lrange("{}-answers".format(chat_id), 0, -1))
    if(current_quiz_index):
        current_quiz_index = int(current_quiz_index)
        if(update.message.text):
            text = update.message.text.encode("utf-8").decode()
            if(is_command_message(text)):
                handle_command_messages(text, chat_id, message_id)
            else:
                text = update.message.text.encode("utf-8").decode()
                quiz = json.loads(redis_client.get("{}-quiz".format(chat_id)))
                previous_question_answer = update.message.text.encode(
                    "utf-8").decode()
                redis_client.rpush(
                    "{}-answers".format(chat_id), previous_question_answer)
                if(current_quiz_index == len(quiz)):
                    return_quiz_result(chat_id)
                    clear_quiz_session(chat_id)
                    clear_keyboard(chat_id)
                else:
                    quiz_question_set = quiz[current_quiz_index]
                    return_next_question(chat_id, quiz_question_set)
                    redis_client.set(
                        "{}-quiz-index".format(chat_id), current_quiz_index + 1)
        elif(update.message.document):
            reply_keyboard_markup = get_markup(["Yes", "No"])
            bot.sendMessage(chat_id, "Hey, you haven't finished answering all the questions on this quiz. Would you like to quit your current quiz?",
                    reply_markup=reply_keyboard_markup)
        else:
            pass
    else:
        if(update.message.document):
            current_quiz_index = 0
            file_id = update.message.document.file_id
            file_content = get_file_content(chat_id, file_id)
            quiz = get_quizset_from_file_content(file_content)
            redis_client.set("{}-quiz".format(chat_id), json.dumps(quiz))
            quiz_question_set = quiz[current_quiz_index]
            return_next_question(chat_id, quiz_question_set)
            redis_client.set("{}-quiz-index".format(chat_id),
                             current_quiz_index + 1)
        elif update.message.text:
            text = update.message.text.encode("utf-8").decode()
            if(is_command_message(text)):
                handle_command_messages(text, chat_id, message_id)

    return 'ok'


def clear_keyboard(chat_id): 
    bot.sendMessage(chat_id,"I'll be available whenever you need me",reply_markup = ReplyKeyboardRemove())

def return_quiz_result(chat_id):
    user_answers = redis_client.lrange("{}-answers".format(chat_id), 0, -1)
    no_of_correct_questions = 0
    quiz = json.loads(redis_client.get("{}-quiz".format(chat_id)))
    for i in range(len(quiz)):
        if(user_answers[i] == quiz[i]["answer"]):
            no_of_correct_questions += 1
    bot.sendMessage(chat_id, "You got {} questions right".format(
        no_of_correct_questions))


def clear_quiz_session(chat_id):
    redis_client.delete("{}-answers".format(chat_id))
    redis_client.delete("{}-quiz".format(chat_id))
    redis_client.delete("{}-quiz-index".format(chat_id))


def is_command_message(text):
    return text.startswith('/')

def return_next_question(chat_id, quiz_question_set):
    question_text = quiz_question_set["question"]
    option_list = quiz_question_set["distractors"]
    option_list.append(quiz_question_set["answer"])
    shuffle(option_list)
    response_message = get_message(question_text, option_list)
    reply_keyboard_markup = get_markup(option_list)
    bot.sendMessage(chat_id, response_message,
                    reply_markup=reply_keyboard_markup)


def get_quizset_from_file_content(file_content):
    return generateQuestions(file_content, 5)

def handle_command_messages(text, chat_id, message_id):
    if(text == "/start"):
        handle_start_response(chat_id, message_id)
    elif (text == "/help"):
        handle_help_response(chat_id, message_id)


def handle_start_response(chat_id, message_id):
    welcome_message = "Welcome to QuizBot. I can help you generate quizzes from documents. Send a document and I'll help you generate questions from it"
    bot.sendMessage(
        chat_id=chat_id, text=welcome_message, reply_to_message_id=message_id
    )


def handle_help_response(chat_id, message_id):
    welcome_message = "Welcome to QuizBot. I can help you generate quizzes from documents. Send a document and I'll help you generate questions from it"
    bot.sendMessage(
        chat_id=chat_id, text=welcome_message, reply_to_message_id=message_id
    )


def get_markup(option_list):
    keyboard = [InlineKeyboardButton(text=x) for x in option_list]
    return ReplyKeyboardMarkup(keyboard=[keyboard], resize_keyboard=False)


def get_message(question_text, option_list):
    alphabet = list("ABCDEFGH")
    text = "{}\n\nSelect an option:\n".format(question_text)
    return text + "\n".join(["{}. {}".format(alphabet[i], option_list[i])
                             for i in range(len(option_list))])


def get_file_content(chat_id, file_id):
    try:
        file_name = "{}.pdf".format(chat_id)
        file_info = requests.get(
            "https://api.telegram.org/bot{}/getFile?file_id={}".format(TOKEN, file_id)).json()
        file_path_info = file_info['result']['file_path']
        file_content = requests.get(
            "https://api.telegram.org/file/bot{}/{}".format(TOKEN, file_path_info))
        with open('{}.pdf'.format(chat_id), 'wb') as f:
            f.write(file_content.content)
        file_content = get_content_from_pdf(file_name)
        os.remove(file_name)
        return file_content
    except:
        pass


def get_content_from_pdf(file_path):
    text = textract.process(file_path).decode("utf-8")
    return re.sub("\n|\r", "",  text)

@app.route('/')
def index():
    return 'Server running'

if __name__ == '__main__':
    app.run(threaded=True)
