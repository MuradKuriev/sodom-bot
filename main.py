import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
import os
from getpass import getpass
import pymysql
from datetime import datetime

from pyexpat.errors import messages
from transliterate import translit

from transliterate import translit
# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


TELEGRAM_TOKEN = ''
PAYMENTS_TOKEN = ''
# 1395243934 - admin
ADMIN_ID = 5408719356 #2
DATABASE_URL = "mkuriecw.beget.tech"
DATABASE_USER = "mkuriecw_bot"
DATABASE_PASSWORD = "3SVSJZBx&dNZ"
DATABASE_NAME = "mkuriecw_bot"

def check_payment_token():
    if not PAYMENTS_TOKEN:
        logger.error("PAYMENTS_TOKEN is not set")
        return False
    
    if PAYMENTS_TOKEN.startswith('TEST'):
        logger.info("Using TEST payment token")
    elif PAYMENTS_TOKEN.startswith(':'):
        logger.info("Using live payment token")
    else:
        logger.error(f"Invalid payment token format: {PAYMENTS_TOKEN}")
        return False
    
    return True

def connect_db():
    try:
        connection = pymysql.connect(
            host=DATABASE_URL,
            port=3306,
            user=DATABASE_USER,
            password=DATABASE_PASSWORD,
            database=DATABASE_NAME
        )
        return connection
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None


def conn():
    try:
        connection = pymysql.connect(
            host=DATABASE_URL,
            port=3306,
            user=DATABASE_USER,
            password=DATABASE_PASSWORD,
            database=DATABASE_NAME
        )
        conn = connection.cursor()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users (id int auto_increment primary key, name varchar(60), phone varchar(16), id_telegram int unique)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS categories (id int auto_increment primary key, name varchar(60), code varchar(60))")

        # Check if categories exist, if not, add them
        conn.execute("SELECT COUNT(*) FROM categories")
        count = conn.fetchone()[0]
        if count == 0:
            for category in Categories:
                code_url = translit(category, 'ru', reversed=True).lower().replace(' ', '_')
                conn.execute("INSERT INTO categories (name, code) VALUES (%s, %s)", (category, code_url))
            connection.commit()

        conn.execute("CREATE TABLE IF NOT EXISTS products (id int auto_increment primary key, "
                     "name varchar(60), img varchar(255), category_id int, price decimal(10,2), foreign key (category_id) references categories(id))")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS order_items (id int auto_increment primary key, product_id int, quantity int, total decimal(10,2)," \
            "foreign key(product_id) references products(id))")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS orders (id int auto_increment primary key, user_id int, items_id int, create_data datetime null, status varchar(20), address varchar(255), comment text, summa decimal(10,2)," \
            "foreign key (user_id) references users(id), foreign key(items_id) references order_items(id))")

        # Создаем таблицу для корзины пользователей
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cart (id int auto_increment primary key, user_id int, product_id int, quantity int, " \
            "foreign key (user_id) references users(id), foreign key (product_id) references products(id))")

        # Создаем таблицу для заявок обратной связи
        conn.execute(
            "CREATE TABLE IF NOT EXISTS feedback (id int auto_increment primary key, user_id int, message text, status varchar(20), created_at datetime, " \
            "foreign key (user_id) references users(id))")

        conn.close()
        connection.close()
    except Exception as e:
        logger.error(f"Database initialization error: {e}")


Categories = [
    'Пиломатериалы',
    'Отделочные',
    'Специализированные',
    'Дополнительные товары'
]

bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# Состояния для добавления товара
class ProductStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_category = State()
    waiting_for_price = State()
    waiting_for_image = State()


# Состояния для редактирования товара
class EditProductStates(StatesGroup):
    waiting_for_product_id = State()
    waiting_for_field = State()
    waiting_for_new_value = State()


# Состояния для оформления заказа
class OrderStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_address = State()
    waiting_for_comment = State()
    confirmation = State()


# Состояния для обратной связи
class FeedbackStates(StatesGroup):
    waiting_for_message = State()


class ToolStates(StatesGroup):
    adding_name = State()
    adding_price = State()
    deleting = State()


async def main_menu():
    builder = ReplyKeyboardBuilder()
    buttons = [
        "🗨️ Обратная связь",
        "👉 Каталог",
        "🧺 Корзина",
        "ℹ️ Помощь"
    ]
    for button in buttons:
        builder.add(types.KeyboardButton(text=button))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


async def admin_menu():
    builder = ReplyKeyboardBuilder()
    buttons = [
        "🗨️ Заявки",
        "👉 Добавить товар",
        "✏️ Редактировать товар",
        "🧺 Заказы",
        "📊 Статистика",
        "🔙 Главное меню"
    ]
    for button in buttons:
        builder.add(types.KeyboardButton(text=button))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


async def cancel_button():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)


# Проверка и регистрация пользователя
async def register_user(user_id, username):
    connection = connect_db()
    if not connection:
        return None

    cursor = connection.cursor()

    try:
        # Проверяем, существует ли пользователь
        cursor.execute("SELECT id FROM users WHERE id_telegram = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            # Если пользователя нет, добавляем его
            cursor.execute("INSERT INTO users (name, id_telegram) VALUES (%s, %s)", (username, user_id))
            connection.commit()
            user_db_id = cursor.lastrowid
        else:
            user_db_id = user[0]

        return user_db_id
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        return None
    finally:
        cursor.close()
        connection.close()


# Получение ID пользователя из базы данных
async def get_user_db_id(user_id):
    connection = connect_db()
    if not connection:
        return None

    cursor = connection.cursor()

    try:
        cursor.execute("SELECT id FROM users WHERE id_telegram = %s", (user_id,))
        user = cursor.fetchone()

        if user:
            return user[0]
        return None
    except Exception as e:
        logger.error(f"Error getting user ID: {e}")
        return None
    finally:
        cursor.close()
        connection.close()


# Проверка, является ли пользователь администратором
def is_admin(user_id):
    return user_id == ADMIN_ID


@dp.message(lambda message: message.text == "👉 Каталог")
async def catalogs(message: types.Message):
    # Регистрируем пользователя, если он еще не зарегистрирован

    await register_user(message.from_user.id, message.from_user.first_name)

    markup = ReplyKeyboardBuilder()
    for category in Categories:
        markup.row(types.KeyboardButton(text=category))
    markup.row(types.KeyboardButton(text="🔙 Назад"))
    await message.answer('Выберите категорию наших товаров', reply_markup=markup.as_markup(resize_keyboard=True))


@dp.message(lambda message: message.text in Categories)
async def category_products(message: types.Message, state: FSMContext):
    # Проверяем, находится ли пользователь в состоянии выбора категории для товара
    current_state = await state.get_state()
    if current_state == "ProductStates:waiting_for_category":
        # Если да, то обрабатываем выбор категории для добавления товара
        await process_product_category(message, state)
        return

    # Иначе показываем товары в выбранной категории
    category_name = message.text

    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await main_menu())
        return

    cursor = connection.cursor()

    try:
        # Получаем ID категории
        cursor.execute("SELECT id FROM categories WHERE name = %s", (category_name,))
        category = cursor.fetchone()

        if not category:
            # Если категории нет в базе, добавляем ее
            code_url = translit(category_name, 'ru', reversed=True).lower().replace(' ', '_')
            cursor.execute("INSERT INTO categories (name, code) VALUES (%s, %s)", (category_name, code_url))
            connection.commit()
            category_id = cursor.lastrowid
        else:
            category_id = category[0]

        # Получаем товары из этой категории
        cursor.execute("SELECT id, name, price FROM products WHERE category_id = %s", (category_id,))
        products = cursor.fetchall()

        if not products:
            await message.answer(f"В категории '{category_name}' пока нет товаров.", reply_markup=await main_menu())
            return

        # Создаем клавиатуру с товарами
        markup = ReplyKeyboardBuilder()
        for product in products:
            markup.row(types.KeyboardButton(text=f"{product[1]} - {product[2]} руб."))
            # markup.row(types.KeyboardButton(text=f"Товар: {product[1]} - {product[2]} руб."))
        markup.row(types.KeyboardButton(text="🔙 Назад"))

        await message.answer(f"Товары в категории '{category_name}':",
                             reply_markup=markup.as_markup(resize_keyboard=True))
    except Exception as e:
        logger.error(f"Error showing category products: {e}")
        await message.answer("Произошла ошибка при получении товаров. Попробуйте позже.",
                             reply_markup=await main_menu())
    finally:
        cursor.close()
        connection.close()


# @dp.message(lambda message: " - " in message.text and "руб." in message.text)

@dp.message(lambda m: m.text and " - " in m.text and "руб." in m.text and m.text.count(" - ") == 1)
async def product_selected(message: types.Message):
    product_info = message.text.split(" - ")[0]

    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await main_menu())
        return

    cursor = connection.cursor()

    try:
        # Находим товар по названию
        cursor.execute("SELECT id, name, price, img, category_id FROM products WHERE name = %s", (product_info,))
        product = cursor.fetchone()

        if not product:
            await message.answer("Товар не найден.", reply_markup=await main_menu())
            return

        # Получаем название категории
        cursor.execute("SELECT name FROM categories WHERE id = %s", (product[4],))
        category = cursor.fetchone()

        # Создаем инлайн-клавиатуру с выбором количества
        inline_markup = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="1", callback_data=f"add_to_cart:{product[0]}:1"),
                    types.InlineKeyboardButton(text="2", callback_data=f"add_to_cart:{product[0]}:2"),
                    types.InlineKeyboardButton(text="3", callback_data=f"add_to_cart:{product[0]}:3"),
                    types.InlineKeyboardButton(text="5", callback_data=f"add_to_cart:{product[0]}:5"),
                ]
            ]
        )

        # Отправляем информацию о товаре
        product_text = f"📦 <b>{product[1]}</b>\n\n"
        product_text += f"💰 Цена: {product[2]} руб.\n"
        product_text += f"🏷️ Категория: {category[0]}\n"
        if product[3] != '':
            photo = FSInputFile(product[3])
            await message.answer_photo(photo=photo, caption=product_text, parse_mode="HTML", reply_markup=inline_markup)
        else:
            await message.answer(product_text, parse_mode="HTML", reply_markup=inline_markup)
    except Exception as e:
        logger.error(f"Error showing product: {e}")
        await message.answer("Произошла ошибка при получении информации о товаре. Попробуйте позже.",
                             reply_markup=await main_menu())
    finally:
        cursor.close()
        connection.close()


@dp.callback_query(lambda c: c.data.startswith("add_to_cart:"))
async def add_to_cart(callback_query: types.CallbackQuery):
    # --- НОВОЕ: регистрация пользователя с try/except
    try:
        user_id = await get_user_db_id(callback_query.from_user.id)
        if not user_id:
            user_id = await register_user(
                callback_query.from_user.id,
                callback_query.from_user.first_name
            )
            if not user_id:
                raise RuntimeError("Не удалось зарегистрировать пользователя")
    except Exception as e:
        await callback_query.answer(
            f"Ошибка регистрации пользователя: {e}\nПожалуйста, введите /start и повторите попытку."
        )
        return

        cursor = connection.cursor()

        cursor.execute("SELECT id, quantity FROM cart WHERE user_id = %s AND product_id = %s", (user_id, product_id))
        cart_item = cursor.fetchone()

        if cart_item:
            new_quantity = cart_item[1] + quantity
            cursor.execute("UPDATE cart SET quantity = %s WHERE id = %s", (new_quantity, cart_item[0]))
        else:
            cursor.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, %s)",
                           (user_id, product_id, quantity))

        connection.commit()

        cursor.execute("SELECT name FROM products WHERE id = %s", (product_id,))
        product_name = cursor.fetchone()[0]

        await callback_query.answer(f"Добавлено: {quantity} шт. '{product_name}' в корзину!")
    except Exception as e:
        logger.error(f"Error adding to cart: {e}")
        await callback_query.answer("Ошибка при добавлении товара.")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'connection' in locals(): connection.close()


@dp.message(lambda m: m.text == "🧺 Корзина")
async def show_cart(message: types.Message):
    try:
        user_id = await get_user_db_id(message.from_user.id)
        if not user_id:
            user_id = await register_user(
                message.from_user.id,
                message.from_user.first_name
            )
            if not user_id:
                raise RuntimeError("Не удалось зарегистрировать пользователя")
    except Exception as e:
        await message.answer(
            f"Ошибка регистрации пользователя: {e}\nПожалуйста, введите /start и повторите попытку."
        )
        return

    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await main_menu())
        return

    cursor = connection.cursor()

    try:
        # Получаем содержимое корзины
        cursor.execute("""
            SELECT c.id, p.name, p.price, c.quantity, (p.price * c.quantity) as total
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))

        cart_items = cursor.fetchall()

        if not cart_items:
            await message.answer("Ваша корзина пуста.", reply_markup=await main_menu())
            return

        # Формируем сообщение с содержимым корзины
        cart_text = "🧺 <b>Ваша корзина:</b>\n\n"
        total_sum = 0

        for item in cart_items:
            cart_text += f"• {item[1]} - {item[2]} руб. x {item[3]} = {item[4]} руб.\n"
            total_sum += item[4]

        cart_text += f"\n<b>Итого: {total_sum} руб.</b>"

        # Создаем инлайн-клавиатуру для управления корзиной
        inline_markup = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="Оформить заказ", callback_data="checkout"),
                    types.InlineKeyboardButton(text="Очистить корзину", callback_data="clear_cart")
                ]
            ]
        )

        await message.answer(cart_text, parse_mode="HTML", reply_markup=inline_markup)
    except Exception as e:
        logger.error(f"Error showing cart: {e}")
        await message.answer("Произошла ошибка при получении корзины. Попробуйте позже.",
                             reply_markup=await main_menu())
    finally:
        cursor.close()
        connection.close()


@dp.callback_query(lambda c: c.data == "clear_cart")
async def clear_cart(callback_query: types.CallbackQuery):
    user_id = await get_user_db_id(callback_query.from_user.id)

    if not user_id:
        await callback_query.answer("Ошибка: пользователь не найден.")
        return

    connection = connect_db()
    if not connection:
        await callback_query.answer("Ошибка подключения к базе данных. Попробуйте позже.")
        return

    cursor = connection.cursor()

    try:
        # Удаляем все товары из корзины пользователя
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        connection.commit()

        await callback_query.answer("Корзина очищена!")
        await callback_query.message.edit_text("Ваша корзина пуста.", reply_markup=None)
    except Exception as e:
        logger.error(f"Error clearing cart: {e}")
        await callback_query.answer("Произошла ошибка при очистке корзины.")
    finally:
        cursor.close()
        connection.close()


@dp.callback_query(lambda c: c.data == "checkout")
async def start_checkout(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        user_id = await get_user_db_id(callback_query.from_user.id)
        if not user_id:
            user_id = await register_user(
                callback_query.from_user.id,
                callback_query.from_user.first_name
            )
            if not user_id:
                raise RuntimeError("Не удалось зарегистрировать пользователя")
    except Exception as e:
        await callback_query.answer(
            f"Ошибка регистрации пользователя: {e}\nПожалуйста, введите /start и повторите попытку."
        )
        return
    # Сохраняем ID пользователя в состоянии
    await state.update_data(user_db_id=user_id)

    # Запрашиваем имя пользователя
    await callback_query.message.answer(
        "Для оформления заказа, пожалуйста, укажите ваше полное имя:",
        reply_markup=await cancel_button()
    )

    # Устанавливаем состояние ожидания имени
    await state.set_state(OrderStates.waiting_for_name)


@dp.message(OrderStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Оформление заказа отменено.", reply_markup=await main_menu())
        return

    # Сохраняем имя в состоянии
    await state.update_data(name=message.text)

    # Запрашиваем номер телефона
    await message.answer(
        "Укажите ваш номер телефона для связи:",
        reply_markup=await cancel_button()
    )

    # Устанавливаем состояние ожидания телефона
    await state.set_state(OrderStates.waiting_for_phone)


@dp.message(OrderStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Оформление заказа отменено.", reply_markup=await main_menu())
        return

    # Сохраняем телефон в состоянии
    await state.update_data(phone=message.text)

    # Запрашиваем адрес доставки
    await message.answer(
        "Укажите адрес доставки:",
        reply_markup=await cancel_button()
    )

    # Устанавливаем состояние ожидания адреса
    await state.set_state(OrderStates.waiting_for_address)


@dp.message(OrderStates.waiting_for_address)
async def process_address(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Оформление заказа отменено.", reply_markup=await main_menu())
        return

    # Сохраняем адрес в состоянии
    await state.update_data(address=message.text)

    # Запрашиваем комментарий к заказу
    await message.answer(
        "Добавьте комментарий к заказу (или напишите 'нет'):",
        reply_markup=await cancel_button()
    )

    # Устанавливаем состояние ожидания комментария
    await state.set_state(OrderStates.waiting_for_comment)


@dp.message(OrderStates.waiting_for_comment)
async def process_comment(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Оформление заказа отменено.", reply_markup=await main_menu())
        return

    # Сохраняем комментарий в состоянии
    comment = message.text if message.text.lower() != "нет" else ""
    await state.update_data(comment=comment)

    # Получаем все данные из состояния
    data = await state.get_data()
    user_db_id = data["user_db_id"]

    # Получаем содержимое корзины для подтверждения
    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await main_menu())
        await state.clear()
        return

    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT p.name, p.price, c.quantity, (p.price * c.quantity) as total
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_db_id,))

        cart_items = cursor.fetchall()

        if not cart_items:
            await state.clear()
            await message.answer("Ваша корзина пуста. Заказ не может быть оформлен.", reply_markup=await main_menu())
            return

        # Формируем сообщение для подтверждения заказа
        confirmation_text = "📋 <b>Подтвердите ваш заказ:</b>\n\n"
        confirmation_text += f"👤 Имя: {data['name']}\n"
        confirmation_text += f"📞 Телефон: {data['phone']}\n"
        confirmation_text += f"🏠 Адрес: {data['address']}\n"

        if data['comment']:
            confirmation_text += f"💬 Комментарий: {data['comment']}\n"

        confirmation_text += "\n<b>Товары:</b>\n"
        total_sum = 0

        for item in cart_items:
            confirmation_text += f"• {item[0]} - {item[1]} руб. x {item[2]} = {item[3]} руб.\n"
            total_sum += item[3]

        confirmation_text += f"\n<b>Итого: {total_sum} руб.</b>"

        # Сохраняем общую сумму в состоянии
        await state.update_data(total_sum=total_sum)

        # Создаем инлайн-клавиатуру для подтверждения заказа
        inline_markup = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_order"),
                    types.InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_order")
                ]
            ]
        )

        await message.answer(confirmation_text, parse_mode="HTML", reply_markup=inline_markup)
        await state.set_state(OrderStates.confirmation)
    except Exception as e:
        logger.error(f"Error processing order comment: {e}")
        await message.answer("Произошла ошибка при оформлении заказа. Попробуйте позже.",
                             reply_markup=await main_menu())
        await state.clear()
    finally:
        cursor.close()
        connection.close()


async def save_order_to_db(data, user_db_id, status="Новый"):
    """Сохраняет заказ в базе данных"""
    logger.info(f"Saving order to database for user_db_id: {user_db_id}, status: {status}")
    
    connection = connect_db()
    if not connection:
        logger.error("Database connection failed")
        return False
        
    cursor = connection.cursor()
    
    try:
        # Обновляем информацию о пользователе
        cursor.execute(
            "UPDATE users SET name = %s, phone = %s WHERE id = %s",
            (data['name'], data['phone'], user_db_id)
        )
        
        # Получаем товары из корзины
        cursor.execute("""
            SELECT c.product_id, p.price, c.quantity, (p.price * c.quantity) as total
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_db_id,))
        
        cart_items = cursor.fetchall()
        
        if not cart_items:
            logger.warning(f"No items in cart for user_db_id: {user_db_id}")
            return False
            
        # Создаем записи для каждого товара в заказе
        order_items_ids = []
        for item in cart_items:
            cursor.execute(
                "INSERT INTO order_items (product_id, quantity, total) VALUES (%s, %s, %s)",
                (item[0], item[2], item[3])
            )
            order_items_ids.append(cursor.lastrowid)
            
        # Создаем заказ
        for item_id in order_items_ids:
            cursor.execute(
                "INSERT INTO orders (user_id, items_id, create_data, status, address, comment, summa) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_db_id, item_id, datetime.now(), status, data['address'], data['comment'], data['total_sum'])
            )
            
        # Очищаем корзину пользователя
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_db_id,))
        
        connection.commit()
        logger.info(f"Order successfully saved for user_db_id: {user_db_id}")
        
        # Отправляем уведомление администратору
        admin_notification = f"🔔 <b>Новый заказ!</b>\n\n"
        admin_notification += f"👤 Имя: {data['name']}\n"
        admin_notification += f"📞 Телефон: {data['phone']}\n"
        admin_notification += f"🏠 Адрес: {data['address']}\n"
        
        if data['comment']:
            admin_notification += f"💬 Комментарий: {data['comment']}\n"
            
        admin_notification += f"\n<b>Сумма заказа: {data['total_sum']} руб.</b>"
        admin_notification += f"\n<b>Статус: {status}</b>"
        
        asyncio.create_task(bot.send_message(ADMIN_ID, admin_notification, parse_mode="HTML"))
        
        return True
        
    except Exception as e:
        import traceback
        logger.error(f"Error saving order to database: {e}")
        logger.error(traceback.format_exc())
        
        try:
            connection.rollback()
        except:
            pass
            
        return False
        
    finally:
        cursor.close()
        connection.close()

@dp.callback_query(F.data == "confirm_order")
async def confirm_order(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        logger.info(f"Confirm order callback received from user {callback_query.from_user.id}")
        
        # Проверяем состояние
        current_state = await state.get_state()
        logger.info(f"Current state: {current_state}")
        
        if current_state != "OrderStates:confirmation":
            logger.warning(f"Unexpected state for confirm_order: {current_state}")
            await callback_query.answer("Ошибка: неверное состояние заказа.")
            return
            
        # Получаем все данные из состояния
        data = await state.get_data()
        logger.info(f"State data: {data}")
        
        user_db_id = data.get("user_db_id")
        if not user_db_id:
            logger.error("user_db_id not found in state data")
            await callback_query.answer("Ошибка: данные пользователя не найдены.")
            return
            
        total_sum = data.get('total_sum')
        if not total_sum:
            logger.error("total_sum not found in state data")
            await callback_query.answer("Ошибка: сумма заказа не найдена.")
            return
            
        # Преобразуем сумму в копейки для API Telegram
        total_sum_kopecks = int(total_sum * 100)
        logger.info(f"Total sum in kopecks: {total_sum_kopecks}")
        
        # Проверяем, включены ли платежи
        if not payment_enabled:
            logger.error("Payments are disabled due to invalid token")
            await callback_query.message.answer(
                "Оплата временно недоступна. Ваш заказ принят без оплаты.",
                reply_markup=await main_menu()
            )
            
            # Сохраняем заказ без оплаты
            await save_order_to_db(data, user_db_id, "Новый (без оплаты)")
            await state.clear()
            return
            
        # Создаем уникальный идентификатор заказа
        order_id = f"order_{user_db_id}_{int(datetime.now().timestamp())}"
        logger.info(f"Generated order_id: {order_id}")
        
        # Сохраняем order_id в состоянии
        await state.update_data(order_id=order_id)
        
        # Формируем название и описание для счета
        title = 'Оплата заказа в Telegram-магазине «СодомЛес Ассистент»'
        description = f'Оплата заказа на сумму {total_sum} руб.'
        
        # Создаем счет для оплаты
        prices = [LabeledPrice(label="Товары", amount=total_sum_kopecks)]
        
        logger.info(f"Sending invoice to user {callback_query.from_user.id}")
        await bot.send_invoice(
            chat_id=callback_query.from_user.id, 
            title=title,
            description=description, 
            payload=order_id,
            provider_token=PAYMENTS_TOKEN,
            currency='RUB',
            prices=prices,
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False
        )
        
        # Отвечаем на callback, чтобы убрать индикатор загрузки
        await callback_query.answer()
        
        # Отправляем сообщение о необходимости оплаты
        await callback_query.message.answer(
            "Для завершения оформления заказа, пожалуйста, оплатите счет выше.",
            reply_markup=await main_menu()
        )
        
    except Exception as e:
        import traceback
        logger.error(f"Error in confirm_order: {e}")
        logger.error(traceback.format_exc())
        
        await callback_query.answer("Произошла ошибка.")
        await callback_query.message.answer(
            "Произошла ошибка при создании счета для оплаты. Пожалуйста, попробуйте позже.",
            reply_markup=await main_menu()
        )
        await state.clear()
        
@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery, state: FSMContext):
    try:
        logger.info(f"Pre-checkout query received: {pre_checkout_query.id}")
        
        # Здесь можно проверить наличие товаров и т.д.
        # Для простоты просто подтверждаем платеж
        
        logger.info(f"Approving pre-checkout query: {pre_checkout_query.id}")
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
        
    except Exception as e:
        import traceback
        logger.error(f"Error in pre_checkout_query: {e}")
        logger.error(traceback.format_exc())
        
        try:
            await bot.answer_pre_checkout_query(
                pre_checkout_query.id,
                ok=False,
                error_message="Произошла ошибка при обработке платежа. Пожалуйста, попробуйте позже."
            )
        except Exception as e2:
            logger.error(f"Error answering pre_checkout_query: {e2}")

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message, state: FSMContext):
    try:
        payment_info = message.successful_payment
        logger.info(f"Successful payment received: {payment_info.telegram_payment_charge_id}")
        
        # Получаем данные заказа из состояния
        data = await state.get_data()
        logger.info(f"State data for successful payment: {data}")
        
        user_db_id = data.get("user_db_id")
        if not user_db_id:
            logger.error("user_db_id not found in state data")
            await message.answer("Ошибка: данные пользователя не найдены.", reply_markup=await main_menu())
            await state.clear()
            return
            
        # Сохраняем заказ в базе данных
        order_saved = await save_order_to_db(data, user_db_id, "Оплачен")
        
        if order_saved:
            # Отправляем подтверждение пользователю
            await message.answer(
                f"✅ Ваш заказ на сумму {payment_info.total_amount / 100} {payment_info.currency} успешно оплачен!\n"
                f"Наш менеджер свяжется с вами в ближайшее время для уточнения деталей доставки.",
                reply_markup=await main_menu()
            )
        else:
            # Если не удалось сохранить заказ
            await message.answer(
                f"✅ Ваш платеж на сумму {payment_info.total_amount / 100} {payment_info.currency} успешно принят!\n"
                f"Однако возникла ошибка при сохранении заказа. Пожалуйста, свяжитесь с администратором.",
                reply_markup=await main_menu()
            )
            
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        import traceback
        logger.error(f"Error in successful_payment handler: {e}")
        logger.error(traceback.format_exc())
        
        await message.answer(
            "Произошла ошибка при обработке платежа. Пожалуйста, свяжитесь с администратором.",
            reply_markup=await main_menu()
        )
        await state.clear()

# Обработчик успешного платежа
@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message, state: FSMContext):
    try:
        payment_info = message.successful_payment
        
        # Получаем данные заказа из состояния
        data = await state.get_data()
        
        if not data.get("order_pending"):
            await message.answer("Ошибка: данные заказа не найдены.", reply_markup=await main_menu())
            await state.clear()
            return
            
        user_db_id = data["user_db_id"]
        
        connection = connect_db()
        if not connection:
            await message.answer("Ошибка подключения к базе данных. Попробуйте позже.",
                                reply_markup=await main_menu())
            await state.clear()
            return
            
        cursor = connection.cursor()
        
        try:
            # Обновляем информацию о пользователе
            cursor.execute(
                "UPDATE users SET name = %s, phone = %s WHERE id = %s",
                (data['name'], data['phone'], user_db_id)
            )
            
            # Получаем товары из корзины
            cursor.execute("""
                SELECT c.product_id, p.price, c.quantity, (p.price * c.quantity) as total
                FROM cart c
                JOIN products p ON c.product_id = p.id
                WHERE c.user_id = %s
            """, (user_db_id,))
            
            cart_items = cursor.fetchall()
            
            # Создаем записи для каждого товара в заказе
            order_items_ids = []
            for item in cart_items:
                cursor.execute(
                    "INSERT INTO order_items (product_id, quantity, total) VALUES (%s, %s, %s)",
                    (item[0], item[2], item[3])
                )
                order_items_ids.append(cursor.lastrowid)
                
            # Создаем заказ
            for item_id in order_items_ids:
                cursor.execute(
                    "INSERT INTO orders (user_id, items_id, create_data, status, address, comment, summa) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (user_db_id, item_id, datetime.now(), "Оплачен", data['address'], data['comment'], data['total_sum'])
                )
                
            # Очищаем корзину пользователя
            cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_db_id,))
            
            connection.commit()
            
            # Отправляем уведомление администратору
            admin_notification = f"🔔 <b>Новый оплаченный заказ!</b>\n\n"
            admin_notification += f"👤 Имя: {data['name']}\n"
            admin_notification += f"📞 Телефон: {data['phone']}\n"
            admin_notification += f"🏠 Адрес: {data['address']}\n"
            
            if data['comment']:
                admin_notification += f"💬 Комментарий: {data['comment']}\n"
                
            admin_notification += f"\n<b>Сумма заказа: {data['total_sum']} руб.</b>"
            admin_notification += f"\n<b>✅ Заказ оплачен!</b>"
            
            await bot.send_message(ADMIN_ID, admin_notification, parse_mode="HTML")
            
            # Отправляем подтверждение пользователю
            await message.answer(
                f"✅ Ваш заказ на сумму {payment_info.total_amount / 100} {payment_info.currency} успешно оплачен!\n"
                f"Наш менеджер свяжется с вами в ближайшее время для уточнения деталей доставки.",
                reply_markup=await main_menu()
            )
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            import traceback
            logger.error(f"Error processing payment: {e}")
            logger.error(traceback.format_exc())
            await message.answer("Произошла ошибка при обработке заказа. Пожалуйста, свяжитесь с администратором.",
                                reply_markup=await main_menu())
            await state.clear()
        finally:
            cursor.close()
            connection.close()
            
    except Exception as e:
        logger.error(f"Error in successful_payment handler: {e}")
        await message.answer("Произошла ошибка при обработке платежа. Пожалуйста, свяжитесь с администратором.",
                            reply_markup=await main_menu())
        await state.clear()


@dp.callback_query(F.data == "cancel_order")
async def cancel_order(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        logger.info(f"Cancel order callback received from user {callback_query.from_user.id}")
        
        await state.clear()
        await callback_query.answer("Заказ отменен")
        await callback_query.message.answer("Оформление заказа отменено.", reply_markup=await main_menu())
        
    except Exception as e:
        logger.error(f"Error in cancel_order: {e}")
        
        await callback_query.answer("Произошла ошибка.")
        await callback_query.message.answer("Произошла ошибка при отмене заказа.", reply_markup=await main_menu())
        await state.clear()


@dp.message(lambda message: message.text == "🗨️ Обратная связь")
async def feedback_start(message: types.Message, state: FSMContext):
    await message.answer(
        "Пожалуйста, напишите ваше сообщение или вопрос:",
        reply_markup=await cancel_button()
    )
    await state.set_state(FeedbackStates.waiting_for_message)


@dp.message(FeedbackStates.waiting_for_message)
async def process_feedback(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отправка сообщения отменена.", reply_markup=await main_menu())
        return

    user_id = await get_user_db_id(message.from_user.id)
    if not user_id:
        user_id = await register_user(message.from_user.id, message.from_user.first_name)
        if not user_id:
            await message.answer("Произошла ошибка при регистрации. Попробуйте позже.", reply_markup=await main_menu())
            await state.clear()
            return

    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await main_menu())
        await state.clear()
        return

    cursor = connection.cursor()

    try:
        # Сохраняем сообщение в базе данных
        cursor.execute(
            "INSERT INTO feedback (user_id, message, status, created_at) VALUES (%s, %s, %s, %s)",
            (user_id, message.text, "Новое", datetime.now())
        )
        connection.commit()

        # Отправляем уведомление администратору
        admin_notification = f"📩 <b>Новое сообщение от пользователя!</b>\n\n"
        admin_notification += f"👤 Пользователь: {message.from_user.first_name} (@{message.from_user.username if message.from_user.username else 'без username'})\n"
        admin_notification += f"💬 Сообщение: {message.text}\n"

        await bot.send_message(ADMIN_ID, admin_notification, parse_mode="HTML")

        await state.clear()
        await message.answer("✅ Ваше сообщение успешно отправлено! Наш менеджер свяжется с вами в ближайшее время.",
                             reply_markup=await main_menu())
    except Exception as e:
        logger.error(f"Error saving feedback: {e}")
        await message.answer("Произошла ошибка при отправке сообщения. Пожалуйста, попробуйте позже.",
                             reply_markup=await main_menu())
        await state.clear()
    finally:
        cursor.close()
        connection.close()


# Админские функции

@dp.message(lambda message: message.text == "👉 Добавить товар" and message.from_user.id == ADMIN_ID)
async def add_product_start(message: types.Message, state: FSMContext):
    # Проверяем, не находится ли пользователь уже в каком-то состоянии
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        logger.info(f"Clearing previous state: {current_state}")

    await message.answer(
        "Введите название товара:",
        reply_markup=await cancel_button()
    )
    await state.set_state(ProductStates.waiting_for_name)
    logger.info(f"Set state to ProductStates.waiting_for_name for user {message.from_user.id}")


@dp.message(ProductStates.waiting_for_name)
async def process_product_name(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        logger.info(f"Product addition canceled by user {message.from_user.id}")
        await message.answer("Добавление товара отменено.", reply_markup=await admin_menu())
        return

    await state.update_data(name=message.text)
    logger.info(f"Product name saved: {message.text}")

    # Создаем клавиатуру с категориями
    markup = ReplyKeyboardBuilder()
    for category in Categories:
        markup.row(types.KeyboardButton(text=category))
    markup.row(types.KeyboardButton(text="❌ Отмена"))

    await message.answer(
        "Выберите категорию товара:",
        reply_markup=markup.as_markup(resize_keyboard=True)
    )
    await state.set_state(ProductStates.waiting_for_category)
    logger.info(f"Set state to ProductStates.waiting_for_category for user {message.from_user.id}")


@dp.message(ProductStates.waiting_for_category)
async def process_product_category(message: types.Message, state: FSMContext):
    logger.info(f"Processing category selection: {message.text}")

    if message.text == "❌ Отмена":
        await state.clear()
        logger.info(f"Product addition canceled by user {message.from_user.id}")
        await message.answer("Добавление товара отменено.", reply_markup=await admin_menu())
        return

    if message.text not in Categories:
        logger.warning(f"Invalid category selected: {message.text}")
        await message.answer("Пожалуйста, выберите категорию из списка.")
        return

    # Get or create category ID
    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await admin_menu())
        await state.clear()
        return

    cursor = connection.cursor()

    try:
        # Check if category exists
        cursor.execute("SELECT id FROM categories WHERE name = %s", (message.text,))
        category = cursor.fetchone()

        if not category:
            # If category doesn't exist, create it
            code_url = translit(message.text, 'ru', reversed=True).lower().replace(' ', '_')
            cursor.execute("INSERT INTO categories (name, code) VALUES (%s, %s)", (message.text, code_url))
            connection.commit()
            category_id = cursor.lastrowid
            logger.info(f"Created new category: {message.text} with ID {category_id}")
        else:
            category_id = category[0]
            logger.info(f"Using existing category: {message.text} with ID {category_id}")

        # Save category ID in state
        await state.update_data(category=message.text, category_id=category_id)

        await message.answer(
            "Введите цену товара (только число):",
            reply_markup=await cancel_button()
        )
        await state.set_state(ProductStates.waiting_for_price)
        logger.info(f"Set state to ProductStates.waiting_for_price for user {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error processing category: {e}")
        await message.answer(f"Произошла ошибка при обработке категории: {str(e)}", reply_markup=await admin_menu())
        await state.clear()
    finally:
        cursor.close()
        connection.close()


@dp.message(ProductStates.waiting_for_price)
async def process_product_price(message: types.Message, state: FSMContext):
    logger.info(f"Processing price: {message.text}")

    if message.text == "❌ Отмена":
        await state.clear()
        logger.info(f"Product addition canceled by user {message.from_user.id}")
        await message.answer("Добавление товара отменено.", reply_markup=await admin_menu())
        return

    try:
        price = float(message.text)
        if price <= 0:
            raise ValueError("Цена должна быть положительным числом")

        await state.update_data(price=price)
        logger.info(f"Price saved: {price}")

        await message.answer(
            "Отправьте изображение товара (или напишите 'нет', если изображения нет):",
            reply_markup=await cancel_button()
        )
        await state.set_state(ProductStates.waiting_for_image)
        logger.info(f"Set state to ProductStates.waiting_for_image for user {message.from_user.id}")
    except ValueError:
        logger.warning(f"Invalid price format: {message.text}")
        await message.answer("Пожалуйста, введите корректную цену (только число).")


@dp.message(ProductStates.waiting_for_image)
async def process_product_image(message: types.Message, state: FSMContext):
    logger.info(f"Processing image input. Has photo: {bool(message.photo)}, Text: {message.text}")

    if message.text == "❌ Отмена":
        await state.clear()
        logger.info(f"Product addition canceled by user {message.from_user.id}")
        await message.answer("Добавление товара отменено.", reply_markup=await admin_menu())
        return

    data = await state.get_data()
    img_path = ""
    photo = message.photo[-1]

    if photo:
        # If user sent a photo, save its file_id

        file_id = message.photo[-1].file_id
        #
        # img_path = f"images/{file_id}.jpg"
        # logger.info(f"Image path saved: {img_path}")

        file = await bot.get_file(photo.file_id)
        file_path = file.file_path

        photo_path = f'{photo.file_id}.jpg'  # убедитесь, что file_id определён корректно
        img_path = os.path.join('images', photo_path)

        await bot.download_file(file_path, destination=img_path)

    elif message.text and message.text.lower() != "нет":
        logger.warning(f"Invalid image input: {message.text}")
        await message.answer("Пожалуйста, отправьте изображение или напишите 'нет'.")
        return

    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await admin_menu())
        await state.clear()
        return

    cursor = connection.cursor()

    try:
        # Get category_id from state
        category_id = data.get('category_id')

        if not category_id:
            # If category_id is not in state, get it from database
            cursor.execute("SELECT id FROM categories WHERE name = %s", (data['category'],))
            category = cursor.fetchone()

            if not category:
                # If category doesn't exist, create it
                code_url = translit(data['category'], 'ru', reversed=True).lower().replace(' ', '_')
                cursor.execute("INSERT INTO categories (name, code) VALUES (%s, %s)", (data['category'], code_url))
                connection.commit()
                category_id = cursor.lastrowid
                logger.info(f"Created new category: {data['category']} with ID {category_id}")
            else:
                category_id = category[0]
                logger.info(f"Using existing category: {data['category']} with ID {category_id}")

        # Add product with proper error handling
        cursor.execute(
            "INSERT INTO products (name, img, category_id, price) VALUES (%s, %s, %s, %s)",
            (data['name'], img_path, category_id, data['price'])
        )
        connection.commit()

        product_id = cursor.lastrowid
        logger.info(f"Product added successfully: ID={product_id}, Name={data['name']}, Category ID={category_id}")

        # Clear state before responding
        await state.clear()

        await message.answer(
            f"✅ Товар '{data['name']}' успешно добавлен в категорию '{data['category']}'!",
            reply_markup=await admin_menu()
        )
    except Exception as e:
        logger.error(f"Error adding product: {e}")
        await message.answer(f"Произошла ошибка при добавлении товара: {str(e)}", reply_markup=await admin_menu())
        await state.clear()
    finally:
        cursor.close()
        connection.close()


@dp.message(lambda message: message.text == "✏️ Редактировать товар" and message.from_user.id == ADMIN_ID)
async def edit_product_start(message: types.Message, state: FSMContext):
    # Проверяем, не находится ли пользователь уже в каком-то состоянии
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()

    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await admin_menu())
        return

    cursor = connection.cursor()

    try:
        # Получаем список всех товаров
        cursor.execute("SELECT id, name, price FROM products ORDER BY name")
        products = cursor.fetchall()

        if not products:
            await message.answer("В базе данных нет товаров для редактирования.", reply_markup=await admin_menu())
            return

        # Сохраняем список товаров в состоянии
        await state.update_data(products=products)

        # Формируем сообщение со списком товаров
        products_text = "Выберите ID товара для редактирования:\n\n"
        for product in products:
            products_text += f"ID: {product[0]} - {product[1]} - {product[2]} руб.\n"

        await message.answer(
            products_text,
            reply_markup=await cancel_button()
        )
        await state.set_state(EditProductStates.waiting_for_product_id)
    except Exception as e:
        logger.error(f"Error listing products: {e}")
        await message.answer("Произошла ошибка при получении списка товаров.", reply_markup=await admin_menu())
    finally:
        cursor.close()
        connection.close()


@dp.message(EditProductStates.waiting_for_product_id)
async def process_product_id(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Редактирование товара отменено.", reply_markup=await admin_menu())
        return

    try:
        product_id = int(message.text)

        connection = connect_db()
        if not connection:
            await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await admin_menu())
            await state.clear()
            return

        cursor = connection.cursor()

        try:
            # Проверяем, существует ли товар с таким ID
            cursor.execute("SELECT id, name, price, category_id FROM products WHERE id = %s", (product_id,))
            product = cursor.fetchone()

            if not product:
                await message.answer("Товар с указанным ID не найден. Пожалуйста, введите корректный ID.")
                return

            # Сохраняем ID товара в состоянии
            await state.update_data(product_id=product_id, product_name=product[1])

            # Создаем клавиатуру с полями для редактирования
            markup = ReplyKeyboardBuilder()
            markup.row(types.KeyboardButton(text="Название"))
            markup.row(types.KeyboardButton(text="Цена"))
            markup.row(types.KeyboardButton(text="Категория"))
            markup.row(types.KeyboardButton(text="❌ Отмена"))

            await message.answer(
                f"Выбран товар: {product[1]} - {product[2]} руб.\n\nВыберите поле для редактирования:",
                reply_markup=markup.as_markup(resize_keyboard=True)
            )
            await state.set_state(EditProductStates.waiting_for_field)
        except Exception as e:
            logger.error(f"Error getting product: {e}")
            await message.answer("Произошла ошибка при получении информации о товаре.", reply_markup=await admin_menu())
            await state.clear()
        finally:
            cursor.close()
            connection.close()
    except ValueError:
        await message.answer("Пожалуйста, введите корректный ID товара (только число).")


@dp.message(EditProductStates.waiting_for_field)
async def process_field_selection(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Редактирование товара отменено.", reply_markup=await admin_menu())
        return

    valid_fields = ["Название", "Цена", "Категория"]
    if message.text not in valid_fields:
        await message.answer("Пожалуйста, выберите поле из списка.")
        return

    await state.update_data(field=message.text.lower())

    if message.text == "Категория":
        # Создаем клавиатуру с категориями
        markup = ReplyKeyboardBuilder()
        for category in Categories:
            markup.row(types.KeyboardButton(text=category))
        markup.row(types.KeyboardButton(text="❌ Отмена"))

        await message.answer(
            "Выберите новую категорию:",
            reply_markup=markup.as_markup(resize_keyboard=True)
        )
    else:
        await message.answer(
            f"Введите новое значение для поля '{message.text}':",
            reply_markup=await cancel_button()
        )

    await state.set_state(EditProductStates.waiting_for_new_value)


@dp.message(EditProductStates.waiting_for_new_value)
async def process_new_value(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Редактирование товара отменено.", reply_markup=await admin_menu())
        return

    data = await state.get_data()
    field = data['field']
    product_id = data['product_id']
    product_name = data['product_name']

    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await admin_menu())
        await state.clear()
        return

    cursor = connection.cursor()

    try:
        if field == "название":
            cursor.execute("UPDATE products SET name = %s WHERE id = %s", (message.text, product_id))
            update_message = f"Название товара изменено на '{message.text}'."

        elif field == "цена":
            try:
                price = float(message.text)
                if price <= 0:
                    raise ValueError("Цена должна быть положительным числом")

                cursor.execute("UPDATE products SET price = %s WHERE id = %s", (price, product_id))
                update_message = f"Цена товара изменена на {price} руб."
            except ValueError:
                await message.answer("Пожалуйста, введите корректную цену (только число).")
                return

        elif field == "категория":
            if message.text not in Categories:
                await message.answer("Пожалуйста, выберите категорию из списка.")
                return

            # Получаем или создаем категорию
            cursor.execute("SELECT id FROM categories WHERE name = %s", (message.text,))
            category = cursor.fetchone()

            if not category:
                code_url = translit(message.text, 'ru', reversed=True).lower().replace(' ', '_')
                cursor.execute("INSERT INTO categories (name, code) VALUES (%s, %s)", (message.text, code_url))
                connection.commit()
                category_id = cursor.lastrowid
            else:
                category_id = category[0]

            cursor.execute("UPDATE products SET category_id = %s WHERE id = %s", (category_id, product_id))
            update_message = f"Категория товара изменена на '{message.text}'."

        connection.commit()

        # Clear state before responding
        await state.clear()

        await message.answer(f"✅ {update_message}", reply_markup=await admin_menu())
    except Exception as e:
        logger.error(f"Error updating product: {e}")
        await message.answer("Произошла ошибка при обновлении товара.", reply_markup=await admin_menu())
        await state.clear()
    finally:
        cursor.close()
        connection.close()


@dp.message(lambda message: message.text == "🗨️ Заявки" and message.from_user.id == ADMIN_ID)
async def show_feedback_requests(message: types.Message):
    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await admin_menu())
        return

    cursor = connection.cursor()

    try:
        # Получаем список заявок обратной связи
        cursor.execute("""
            SELECT f.id, u.name, u.phone, u.id_telegram, f.message, f.created_at
            FROM feedback f
            JOIN users u ON f.user_id = u.id
            WHERE f.status = 'Новое'
            ORDER BY f.created_at DESC
        """)

        feedback_requests = cursor.fetchall()

        if not feedback_requests:
            await message.answer("Новых заявок обратной связи нет.", reply_markup=await admin_menu())
            return

        # Формируем сообщение со списком заявок
        for request in feedback_requests:
            feedback_text = f"📩 <b>Заявка #{request[0]}</b>\n\n"
            feedback_text += f"👤 Имя: {request[1] or 'Не указано'}\n"
            feedback_text += f"📞 Телефон: {request[2] or 'Не указано'}\n"
            feedback_text += f"🆔 Telegram ID: {request[3]}\n"
            feedback_text += f"📅 Дата: {request[5].strftime('%d.%m.%Y %H:%M')}\n\n"
            feedback_text += f"💬 Сообщение: {request[4]}\n"

            # Создаем инлайн-клавиатуру для ответа на заявку
            inline_markup = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(text="✅ Обработано",
                                                   callback_data=f"feedback_processed:{request[0]}"),
                        types.InlineKeyboardButton(text="📞 Ответить", callback_data=f"feedback_reply:{request[3]}")
                    ]
                ]
            )

            await message.answer(feedback_text, parse_mode="HTML", reply_markup=inline_markup)
    except Exception as e:
        logger.error(f"Error showing feedback requests: {e}")
        await message.answer("Произошла ошибка при получении заявок.", reply_markup=await admin_menu())
    finally:
        cursor.close()
        connection.close()


@dp.callback_query(lambda c: c.data.startswith("feedback_processed:"))
async def mark_feedback_processed(callback_query: types.CallbackQuery):
    feedback_id = int(callback_query.data.split(":")[1])

    connection = connect_db()
    if not connection:
        await callback_query.answer("Ошибка подключения к базе данных. Попробуйте позже.")
        return

    cursor = connection.cursor()

    try:
        cursor.execute("UPDATE feedback SET status = 'Обработано' WHERE id = %s", (feedback_id,))
        connection.commit()
        await callback_query.answer("Заявка помечена как обработанная!")
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.error(f"Error updating feedback status: {e}")
        await callback_query.answer("Произошла ошибка при обновлении статуса заявки.")
    finally:
        cursor.close()
        connection.close()


@dp.message(lambda message: message.text == "🧺 Заказы" and message.from_user.id == ADMIN_ID)
async def show_orders(message: types.Message):
    connection = connect_db()
    if not connection:
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.", reply_markup=await admin_menu())
        return

    cursor = connection.cursor()

    try:
        # Получаем список заказов
        cursor.execute("""
            SELECT o.id, u.name, u.phone, o.create_data, o.status, o.summa
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.status = 'Новый'
            ORDER BY o.create_data DESC
        """)

        orders = cursor.fetchall()

        if not orders:
            await message.answer("Новых заказов нет.", reply_markup=await admin_menu())
            return

        # Формируем сообщение со списком заказов
        for order in orders:
            order_text = f"🛒 <b>Заказ #{order[0]}</b>\n\n"
            order_text += f"👤 Имя: {order[1] or 'Не указано'}\n"
            order_text += f"📞 Телефон: {order[2] or 'Не указано'}\n"
            order_text += f"📅 Дата: {order[3].strftime('%d.%m.%Y %H:%M')}\n"
            order_text += f"💰 Сумма: {order[5]} руб.\n"

            # Создаем инлайн-клавиатуру для управления заказом
            inline_markup = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(text="✅ Обработан", callback_data=f"order_processed:{order[0]}"),
                        types.InlineKeyboardButton(text="❌ Отменить", callback_data=f"order_canceled:{order[0]}")
                    ],
                    [
                        types.InlineKeyboardButton(text="📋 Подробности", callback_data=f"order_details:{order[0]}")
                    ]
                ]
            )

            await message.answer(order_text, parse_mode="HTML", reply_markup=inline_markup)
    except Exception as e:
        logger.error(f"Error showing orders: {e}")
        await message.answer("Произошла ошибка при получении заказов.", reply_markup=await admin_menu())
    finally:
        cursor.close()
        connection.close()


@dp.callback_query(lambda c: c.data.startswith("order_details:"))
async def show_order_details(callback_query: types.CallbackQuery):
    order_id = int(callback_query.data.split(":")[1])

    connection = connect_db()
    if not connection:
        await callback_query.answer("Ошибка подключения к базе данных. Попробуйте позже.")
        return

    cursor = connection.cursor()

    try:
        # Получаем информацию о заказе
        cursor.execute("""
            SELECT o.id, u.name, u.phone, o.create_data, o.status, o.address, o.comment, o.summa, o.items_id
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.id = %s
        """, (order_id,))

        order = cursor.fetchone()

        if not order:
            await callback_query.answer("Заказ не найден.")
            return

        # Получаем товары в заказе
        cursor.execute("""
            SELECT p.name, oi.quantity, oi.total
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.id = %s
        """, (order[8],))

        order_items = cursor.fetchall()

        # Формируем подробное сообщение о заказе
        details_text = f"🛒 <b>Заказ #{order[0]}</b>\n\n"
        details_text += f"👤 Имя: {order[1] or 'Не указано'}\n"
        details_text += f"📞 Телефон: {order[2] or 'Не указано'}\n"
        details_text += f"📅 Дата: {order[3].strftime('%d.%m.%Y %H:%M')}\n"
        details_text += f"🏠 Адрес: {order[5]}\n"

        if order[6]:
            details_text += f"💬 Комментарий: {order[6]}\n"

        details_text += f"\n<b>Товары:</b>\n"

        for item in order_items:
            details_text += f"• {item[0]} x {item[1]} = {item[2]} руб.\n"

        details_text += f"\n<b>Итого: {order[7]} руб.</b>"

        await callback_query.message.answer(details_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error getting order details: {e}")
        await callback_query.answer("Произошла ошибка при получении деталей заказа.")
    finally:
        cursor.close()
        connection.close()


@dp.callback_query(lambda c: c.data.startswith("order_processed:"))
async def mark_order_processed(callback_query: types.CallbackQuery):
    order_id = int(callback_query.data.split(":")[1])

    connection = connect_db()
    if not connection:
        await callback_query.answer("Ошибка подключения к базе данных. Попробуйте позже.")
        return

    cursor = connection.cursor()

    try:
        cursor.execute("UPDATE orders SET status = 'Обработан' WHERE id = %s", (order_id,))
        connection.commit()
        await callback_query.answer("Заказ помечен как обработанный!")
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
        await callback_query.answer("Произошла ошибка при обновлении статуса заказа.")
    finally:
        cursor.close()
        connection.close()


@dp.callback_query(lambda c: c.data.startswith("order_canceled:"))
async def mark_order_canceled(callback_query: types.CallbackQuery):
    order_id = int(callback_query.data.split(":")[1])

    connection = connect_db()
    if not connection:
        await callback_query.answer("Ошибка подключения к базе данных. Попробуйте позже.")
        return

    cursor = connection.cursor()

    try:
        cursor.execute("UPDATE orders SET status = 'Отменен' WHERE id = %s", (order_id,))
        connection.commit()
        await callback_query.answer("Заказ отменен!")
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
        await callback_query.answer("Произошла ошибка при обновлении статуса заказа.")
    finally:
        cursor.close()
        connection.close()


@dp.message(lambda message: message.text == "🔙 Главное меню")
async def back_to_main_menu(message: types.Message, state: FSMContext):
    # Clear any active state
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        logger.info(f"Cleared state {current_state} for user {message.from_user.id}")

    if is_admin(message.from_user.id):
        await message.answer("Вы вернулись в главное меню.", reply_markup=await admin_menu())
    else:
        await message.answer("Вы вернулись в главное меню.", reply_markup=await main_menu())


@dp.message(lambda message: message.text == "🔙 Назад")
async def back_button(message: types.Message, state: FSMContext):
    # Clear any active state
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        logger.info(f"Cleared state {current_state} for user {message.from_user.id}")

    await message.answer("Вы вернулись в главное меню.", reply_markup=await main_menu())


@dp.message(Command('catalog'))
async def catalog_command(message: types.Message):
    await catalogs(message)


@dp.message(Command(commands=['start', 'help']))
async def send_welcome(message: types.Message, state: FSMContext):
    # Clear any active state
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        logger.info(f"Cleared state {current_state} for user {message.from_user.id}")

    if is_admin(message.from_user.id):
        await message.answer(f"Добро пожаловать, {message.from_user.first_name}, администратор!",
                             reply_markup=await admin_menu())
    else:
        await register_user(message.from_user.id, message.from_user.first_name)
        await message.answer(
            f"Добро пожаловать, {message.from_user.first_name}, в наш магазин \r\n СодомЛес Ассистент!\r\n Введите /catalog для просмотра товаров."
            , reply_markup=await main_menu())


@dp.message(lambda message: message.text == "ℹ️ Помощь")
async def show_help(message: types.Message):
    help_text = """
        <b>📚 Справочная информация:</b>
        <b>👉 Каталог</b> - список наших категорий и товаров
        <b>🗨️ Обратная связь</b> - если не нашли, что искали можно оставить сообщение менеджеру и он с вами свяжется
        <b>🧺 Корзина</b> - Выбранные ваши товары.
        <b>ℹ️ Помощь</b> - показать это справочное сообщение.
        Для начала работы просто выберите нужное действие из меню.
    """
    await message.answer(help_text, parse_mode='HTML')


@dp.message()
async def unknown_message(message: types.Message, state: FSMContext):
    print(message.text)
    # Check if user is in any state
    current_state = await state.get_state()
    if current_state is not None:
        logger.info(f"User {message.from_user.id} sent message '{message.text}' while in state {current_state}")
        # Let the state handlers handle the message
        return

    await message.answer("Я не понимаю эту команду. Пожалуйста, используйте меню.")

# Состояние для ответа на заявку обратной связи
class AdminReplyState(StatesGroup):
    waiting_for_message = State()

# Обработчик нажатия на кнопку "Ответить"
@dp.callback_query(lambda c: c.data.startswith("feedback_reply:"))
async def reply_to_feedback(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        # Получаем ID пользователя из callback_data
        user_telegram_id = int(callback_query.data.split(":")[1])
        
        # Сохраняем ID пользователя в состоянии
        await state.update_data(reply_to_user_id=user_telegram_id)
        
        # Отвечаем на callback, чтобы убрать индикатор загрузки
        await callback_query.answer()
        
        # Запрашиваем текст ответа
        await callback_query.message.answer(
            "Введите текст ответа пользователю:",
            reply_markup=await cancel_button()
        )
        
        # Устанавливаем состояние ожидания текста ответа
        await state.set_state(AdminReplyState.waiting_for_message)
        
    except Exception as e:
        logger.error(f"Error starting reply to feedback: {e}")
        await callback_query.answer("Произошла ошибка при подготовке ответа.")

# Обработчик ввода текста ответа
@dp.message(AdminReplyState.waiting_for_message)
async def process_admin_reply(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отправка ответа отменена.", reply_markup=await admin_menu())
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    user_telegram_id = data.get("reply_to_user_id")
    
    if not user_telegram_id:
        await message.answer("Ошибка: ID пользователя не найден.", reply_markup=await admin_menu())
        await state.clear()
        return
    
    try:
        # Отправляем сообщение пользователю
        await bot.send_message(
            user_telegram_id,
            f"<b>Ответ от администратора:</b>\n\n{message.text}",
            parse_mode="HTML"
        )
        
        # Отправляем подтверждение администратору
        await message.answer(
            f"✅ Ваш ответ успешно отправлен пользователю.",
            reply_markup=await admin_menu()
        )
        
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error sending reply to user: {e}")
        await message.answer(
            f"❌ Ошибка при отправке ответа пользователю: {str(e)}",
            reply_markup=await admin_menu()
        )
        await state.clear()
        
        
async def main():
    conn()
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
