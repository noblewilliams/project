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

redis_client = redis.StrictRedis.from_url(
    url=os.environ.get('REDIS_URL'), decode_responses=True)

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

    quiz_started = redis_client.hget(
        "{}-context".format(chat_id), "quiz-started")
    intent_index = redis_client.hget(
        "{}-context".format(chat_id), "intent-index")

    if(quiz_started):
        next_question_set_index = int(intent_index) - 1
        if(update.message.text):
            text = update.message.text.encode("utf-8").decode()
            if(is_command_message(text)):
                handle_command_messages(text, chat_id, message_id)
            else:
                quiz = json.loads(redis_client.get("{}-quiz".format(chat_id)))
                redis_client.rpush(
                    "{}-answers".format(chat_id), text)
                if next_question_set_index == len(quiz):
                    return_answer_feedback(
                        chat_id, next_question_set_index - 1, text)
                    return_quiz_result(chat_id)
                    clear_quiz_session(chat_id)
                    clear_keyboard(chat_id)
                else:
                    quiz_question_set = quiz[next_question_set_index]
                    return_answer_feedback(
                        chat_id, next_question_set_index - 1, text)
                    return_next_question(chat_id, quiz_question_set)
                    redis_client.hset(
                        "{}-context".format(chat_id), "intent-index", int(intent_index) + 1
                    )
        elif(update.message.document):
            reply_keyboard_markup = get_markup(["Yes", "No"])
            bot.sendMessage(chat_id, "Hey, you haven't finished answering all the questions on this quiz. Would you like to quit your current quiz?",
                            reply_markup=reply_keyboard_markup)
        else:
            bot.sendMessage(
                chat_id, "Sorry, I can't understand the file format you just sent.🙃")
    else:
        if(update.message.document):
            file_id = update.message.document.file_id
            file_content = get_file_content(chat_id, file_id)
            redis_client.hset("{}-context".format(chat_id),
                              "file-content", file_content)
            redis_client.hset("{}-context".format(chat_id), "intent-index", 1)
            get_number_of_questions(chat_id)

        elif update.message.text:
            text = update.message.text.encode("utf-8").decode()
            if is_command_message(text):
                handle_command_messages(text, chat_id, message_id)
            elif asked_for_number_of_questions(intent_index):
                if text.isdigit():
                    number_of_questions = int(text)
                    redis_client.hset(
                        "{}-context".format(chat_id), "intent-index", 2)
                    file_content = redis_client.hget(
                        "{}-context".format(chat_id), "file-content")
                    quiz = get_quizset_from_file_content(
                        file_content, number_of_questions)
                    initialize_quiz(chat_id, quiz)
                    quiz_question_set = quiz[0]
                    return_next_question(chat_id, quiz_question_set)
                else:
                    bot.sendMessage(
                        chat_id, "Sorry, you have entered an invalid number. Please type in a valid number")
    return 'ok'


def clear_keyboard(chat_id):
    bot.sendMessage(chat_id, "I'll be available whenever you need me",
                    reply_markup=ReplyKeyboardRemove())



def asked_for_number_of_questions(intent_index):
    return intent_index == "1"


def return_answer_feedback(chat_id, question_index, user_answer):
    quiz = json.loads(redis_client.get("{}-quiz".format(chat_id)))
    correct_answer = quiz[question_index]["answer"]
    if user_answer == correct_answer:
        bot.sendMessage(chat_id, "Yay!! You got the question right ✅")
    else:
        bot.sendMessage(
            chat_id, "Sorry, you got this question wrong ❌\n\nThe correct answer is: {}".format(correct_answer))


def return_quiz_result(chat_id):
    user_answers = redis_client.lrange("{}-answers".format(chat_id), 0, -1)
    no_of_correct_questions = 0
    quiz = json.loads(redis_client.get("{}-quiz".format(chat_id)))
    for i in range(len(quiz)):
        if(user_answers[i] == quiz[i]["answer"]):
            no_of_correct_questions += 1
    bot.sendMessage(chat_id, "You got {} questions out of {} questions".format(
        no_of_correct_questions, len(quiz)))


def clear_quiz_session(chat_id):
    redis_client.delete("{}-answers".format(chat_id))
    redis_client.delete("{}-quiz".format(chat_id))
    redis_client.delete("{}-context".format(chat_id))


def initialize_quiz(chat_id, quiz):
    redis_client.hset("{}-context".format(chat_id), "quiz-started", 1)
    redis_client.set("{}-quiz".format(chat_id), json.dumps(quiz))


def get_number_of_questions(chat_id):
    bot.sendMessage(chat_id, "File Received ✅")
    bot.sendMessage(
        chat_id, "How many questions would you like me to generate for you?")


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


def get_quizset_from_file_content(file_content, number_of_questions):
    return generateQuestions(file_content, number_of_questions)


def handle_command_messages(text, chat_id, message_id):
    if(text == "/start"):
        handle_start_response(chat_id, message_id)
    elif (text == "/help"):
        handle_help_response(chat_id, message_id)
    elif (text == "/cancel"):
        clear_user_sesssion(chat_id, message_id)


def handle_start_response(chat_id, message_id):
    welcome_message = "Welcome to QuizBot. I can help you generate quizzes from documents. Send a document and I'll help you generate questions from it"
    bot.sendMessage(
        chat_id=chat_id, text=welcome_message, reply_to_message_id=message_id
    )


def clear_user_sesssion(chat_id, message_id):
    clear_quiz_session(chat_id)
    bot.sendMessage(
        chat_id=chat_id, text="Session cleared ✅", reply_to_message_id=message_id
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
