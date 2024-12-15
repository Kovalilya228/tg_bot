import logging
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from jira import JIRA
from datetime import datetime
from dotenv import load_dotenv

# Настройки
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
JIRA_URL = os.getenv('JIRA_URL')
JIRA_USERNAME = os.getenv('JIRA_USERNAME')
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')


# Список разрешенных пользователей (Telegram ID)
ALLOWED_USERS = [771853550, 719405515]

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

# Функция для получения информации о проектах из Jira
def get_jira_projects():
    jira = JIRA(basic_auth=(JIRA_USERNAME, JIRA_API_TOKEN), options={'server': JIRA_URL})
    projects = jira.projects()
    return projects

# Функция для проверки доступа пользователя
def check_access(user_id):
    return user_id in ALLOWED_USERS

# Функция для обработки команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if check_access(user_id):
        keyboard = [[InlineKeyboardButton("Проекты", callback_data="projects")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Привет! Я бот, который может выгружать информацию о проектах из Jira. Используйте кнопку "Проекты" для получения списка проектов.', reply_markup=reply_markup)
    else:
        await update.message.reply_text('У вас нет доступа к этому боту.')

# Функция для обработки команды /projects
async def projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.callback_query.from_user.id if update.callback_query else update.message.from_user.id
    if check_access(user_id):
        projects = get_jira_projects()
        keyboard = []
        for project in projects:
            keyboard.append([InlineKeyboardButton(project.name, callback_data=project.key)])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.message.reply_text('Выберите проект:', reply_markup=reply_markup)
        else:
            await update.message.reply_text('Выберите проект:', reply_markup=reply_markup)
    else:
        if update.callback_query:
            await update.callback_query.message.reply_text('У вас нет доступа к этой команде.')
        else:
            await update.message.reply_text('У вас нет доступа к этой команде.')

# Функция для обработки нажатий на кнопки
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    logger.info(f"Button pressed with data: {query.data}")

    if query.data == "projects":
        await projects(update, context)
    elif query.data == "view_info":
        project_key = context.user_data.get('project_key')
        if project_key:
            user_info = load_user_info(project_key)
            message = format_user_info(user_info)
            keyboard = [[InlineKeyboardButton("Изменить информацию", callback_data="edit_info")], [InlineKeyboardButton("Назад к проекту", callback_data=project_key)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=message, reply_markup=reply_markup)
    elif query.data == "edit_info":
        project_key = context.user_data.get('project_key')
        if project_key:
            await query.edit_message_text(text="Выберите действие:", reply_markup=get_survey_keyboard())
    else:
        project_key = query.data
        if project_key not in ["stage", "completed", "planned", "achieved", "problems", "result"]:
            context.user_data['project_key'] = project_key
            jira = JIRA(basic_auth=(JIRA_USERNAME, JIRA_API_TOKEN), options={'server': JIRA_URL})
            try:
                project = jira.project(project_key)
            except Exception as e:
                logger.error(f"Ошибка при получении проекта: {e}")
                await query.edit_message_text(text="Проект не найден. Пожалуйста, попробуйте снова.")
                return

            # Получение информации о сроках проекта
            issues = jira.search_issues(f'project={project_key} AND issuetype=Task', maxResults=100)
            planned_start_dates = [issue.fields.created for issue in issues if issue.fields.created]
            actual_start_dates = [issue.fields.created for issue in issues if issue.fields.status.name == 'In Progress']
            planned_end_dates = [issue.fields.duedate for issue in issues if issue.fields.duedate]
            actual_end_dates = [issue.fields.resolutiondate for issue in issues if issue.fields.resolutiondate]

            planned_start_date = min(planned_start_dates) if planned_start_dates else 'N/A'
            actual_start_date = min(actual_start_dates) if actual_start_dates else 'N/A'
            planned_end_date = max(planned_end_dates) if planned_end_dates else 'N/A'
            actual_end_date = max(actual_end_dates) if actual_end_dates else 'N/A'

            # Получение ключевых этапов (milestones) из раздела "timeline"
            milestones = jira.search_issues(f'project={project_key} AND issuetype=Epic', maxResults=100)
            key_milestones = [f"{issue.fields.summary}: {issue.fields.duedate}" for issue in milestones]

            # Получение контрольных точек из задач в разделе "board"
            control_points = jira.search_issues(f'project={project_key} AND issuetype=Task', maxResults=100)
            control_points_keys = [f"{issue.fields.summary}: {issue.fields.duedate}" for issue in control_points]

            message = (
                f"Ключ проекта: \n{project.key}\n\n"
                f"Название проекта: \n{project.name}\n\n"
                f"ID проекта: \n{project.id}\n\n"
                f"Планируемая дата начала: \n{format_date(planned_start_date)}\n\n"
                f"Актуальная дата начала: \n{format_date(actual_start_date)}\n\n"
                f"Планируемая дата окончания: \n{format_date(planned_end_date)}\n\n"
                f"Актуальная дата окончания: \n{format_date(actual_end_date)}\n\n"
                f"Ключевые этапы:\n{'\n'.join(key_milestones) if key_milestones else 'N/A'}\n\n"
                f"Контрольные точки:\n{'\n'.join(control_points_keys) if control_points_keys else 'N/A'}"
            )
            keyboard = [[InlineKeyboardButton("Просмотреть пользовательскую информацию", callback_data="view_info")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=message, reply_markup=reply_markup)
        else:
            questions = {
                'stage': 'На каком этапе выполнения находится проект на данный момент?',
                'completed': 'Что было сделано на данном этапе?',
                'planned': 'Что планируется сделать в ближайшие 1-2 недели?',
                'achieved': 'Удалось ли осуществить задуманное?',
                'problems': 'Если нет, то какие проблемы возникли, и как решили проблему?',
                'result' : 'Что получилось в результате данного этапа?'
            }
            query = update.callback_query
            await query.answer()

            logger.info(f"Survey response received with data: {query.data}")

            if query.data in ["stage", "completed", "planned", "achieved", "problems", "result"]:
                question = query.data
                context.user_data['question'] = question
                
                await query.edit_message_text(text=f"Пожалуйста, ответьте на вопрос: {questions[question]}")
            else:
                logger.error(f"Unexpected callback data: {query.data}")
                await query.edit_message_text(text="Произошла ошибка. Пожалуйста, попробуйте снова.")

# Функция для сохранения ответа в файл
def save_answer_to_file(project_key, question, answer):
    file_path = f"{project_key}_survey.json"
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                data = json.load(file)
        else:
            data = {}

        data[question] = answer

        with open(file_path, 'w') as file:
            json.dump(data, file, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных в файл: {e}")

# Функция для загрузки пользовательской информации из файла
def load_user_info(project_key):
    file_path = f"{project_key}_survey.json"
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            data = json.load(file)
    else:
        data = {}
    return data

# Функция для форматирования пользовательской информации
def format_user_info(user_info):
    questions = {
                'stage': 'На каком этапе выполнения находится проект на данный момент?',
                'completed': 'Что было сделано на данном этапе?',
                'planned': 'Что планируется сделать в ближайшие 1-2 недели?',
                'achieved': 'Удалось ли осуществить задуманное?',
                'problems': 'Если нет, то какие проблемы возникли, и как решили проблему?',
                'result' : 'Что получилось в результате данного этапа?'
            }
    message = "Текущая пользовательская информация:\n\n"
    for question, answer in user_info.items():
        message += f"{questions[question]}\n- {answer}\n\n"
    return message

# Функция для обработки текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if check_access(user_id):
        question = context.user_data.get('question')
        project_key = context.user_data.get('project_key')
        if question and project_key:
            answer = update.message.text
            save_answer_to_file(project_key, question, answer)
            await update.message.reply_text(f"Ответ на вопрос сохранен.")

            # Загрузка обновленных данных пользователя
            user_info = load_user_info(project_key)
            message = format_user_info(user_info)
            keyboard = [[InlineKeyboardButton("Изменить информацию", callback_data="edit_info")], [InlineKeyboardButton("Назад к проекту", callback_data=project_key)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(text=message, reply_markup=reply_markup)

            context.user_data.pop('question')
        else:
            await update.message.reply_text("Пожалуйста, выберите проект и вопрос.")

# Функция для получения клавиатуры с вопросами анкеты
def get_survey_keyboard():
    keyboard = [
        [InlineKeyboardButton("На каком этапе выполнения находится проект на данный момент?", callback_data="stage")],
        [InlineKeyboardButton("Что было сделано на данном этапе?", callback_data="completed")],
        [InlineKeyboardButton("Что планируется сделать в ближайшие 1-2 недели?", callback_data="planned")],
        [InlineKeyboardButton("Удалось ли осуществить задуманное?", callback_data="achieved")],
        [InlineKeyboardButton("Если нет, то какие проблемы возникли, и как решили проблему?", callback_data="problems")],
        [InlineKeyboardButton("Что получилось в результате данного этапа?", callback_data="result")],
    ]
    return InlineKeyboardMarkup(keyboard)

def format_date(date_str):
    try:
        # Парсинг строки даты в объект datetime
        date_obj = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%f%z')
        # Форматирование даты в формате DD:MM:YYYY
        formatted_date = date_obj.strftime('%d-%m-%Y')
        return formatted_date
    except ValueError:
        return date_str  # Возвращаем исходную строку, если формат не соответствует

def main() -> None:
    # Создание ApplicationBuilder и добавление обработчиков
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("projects", projects))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()