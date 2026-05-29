from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import default_state
from aiogram.types import Message, CallbackQuery, User
from aiogram.utils.chat_action import ChatActionSender

from database.models import Wishlist, SubscriptionStatus
from handlers.handlers_utils import render_wishlist_template, render_limited_wishlist_template, get_i18n, \
    send_item_info, delete_item_message
from keyboards.keyboard_utils import create_inline_kb

from database.requests import get_or_create_user, get_wishlists, get_friends_wishlists, get_wishlist, \
    delete_wishlist_db, get_subscription, delete_subscription, get_or_create_subscription, update_subscription_status, \
    get_subscription_with_details, get_user_language, get_item
import logging
logger = logging.getLogger(__name__)

# Initialize router for handling messages and callbacks
router = Router()


# Handler for /start command
@router.message(CommandStart(), StateFilter(default_state))
async def process_start_message(message: Message, i18n: dict[str, str]):
    """
    Handles the /start command with wishlist links support
    """
    # Get or create user
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username
    )

    # Send standard welcome message
    keyboard = create_inline_kb(1, i18n, 'btn_my_wishlists', 'friends_wishlist_buttons', 'help_button')

    welcome_msg = await message.answer(
        text=i18n.get('start_message'),
        reply_markup=keyboard,
        message_effect_id="5046509860389126442"
    )

    # Check if start command contains wishlist UUID
    args = message.text.split()
    if len(args) > 1:
        wishlist_uuid = args[1]
        await handle_wishlist_link(message, wishlist_uuid, user, i18n)


async def handle_wishlist_link(message: Message, wishlist_uuid: str, user: User, i18n: dict):
    wishlist = await get_wishlist(wishlist_identifier=wishlist_uuid, with_owner=True)

    if not wishlist:
        await message.answer(i18n.get('wishlist_not_found'))
        return

    # Check if user is the owner
    if wishlist.owner_id == user.id:
        keyboard = create_inline_kb(1, i18n, **{f"view_wishlist_{wishlist.access_uuid}": 'view_wishlist'})
        await message.answer(
            text=i18n.get('wishlist_own_access'),
            reply_markup=keyboard
        )
        return

    # Send notification about shared wishlist
    share_keyboard = create_inline_kb(
        1,
        i18n,
        **{f"view_wishlist_{wishlist.access_uuid}": 'view_wishlist'}
    )

    await message.answer(
        text=i18n.get('wishlist_shared_with_you').format(
            owner_username=wishlist.owner.username,
            wishlist_title=wishlist.title
        ),
        reply_markup=share_keyboard
    )


# Handler for returning to start menu via callback
@router.callback_query(F.data == 'start_message', StateFilter(default_state))
async def process_start_message(callback: CallbackQuery, i18n: dict[str, str]):
    """
    Handles the 'start_message' callback to return to main menu.
    """
    # Recreate the main menu keyboard
    keyboard = create_inline_kb(1, i18n, 'btn_my_wishlists', 'friends_wishlist_buttons', 'help_button')

    # Acknowledge the callback (removes loading animation)
    await callback.answer()

    # Edit the existing message to show main menu
    await callback.message.edit_text(
        text=i18n.get('start_message'),
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith('subscribe_'))
async def subscribe_to_wishlist(callback: CallbackQuery, i18n: dict, state: FSMContext):
    await callback.answer()

    wishlist_id = int(callback.data.split('_')[1])
    wishlist = await get_wishlist(wishlist_id, with_owner=True)

    if not wishlist:
        await callback.answer(i18n.get('wishlist_not_found'), show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)

    # Check if already subscribed
    existing_subscription = await get_subscription(user.id, wishlist.id)
    if existing_subscription:
        if existing_subscription.status == SubscriptionStatus.APPROVED:
            await callback.answer(i18n.get('already_subscribed'), show_alert=True)
            return
        elif existing_subscription.status == SubscriptionStatus.PENDING:
            await callback.answer(i18n.get('subscription_pending'), show_alert=True)
            return

    if wishlist.is_private:
        subscription = await get_or_create_subscription(
            user.id, wishlist.id, wishlist.owner_id, SubscriptionStatus.PENDING
        )
        await callback.answer(i18n.get('subscription_request_sent'), show_alert=True)

        await notify_owner_about_request(callback.bot, wishlist, user, i18n)
    else:
        subscription = await get_or_create_subscription(
            user.id, wishlist.id, wishlist.owner_id, SubscriptionStatus.APPROVED
        )
        await callback.answer(i18n.get('subscribed_success'), show_alert=True)

    # Create a simple object to pass as callback
    from types import SimpleNamespace
    fake_cb = SimpleNamespace()
    fake_cb.message = callback.message
    fake_cb.from_user = callback.from_user
    fake_cb.data = f"view_wishlist_{wishlist.access_uuid}"
    
    async def fake_answer():
        pass
    fake_cb.answer = fake_answer
    
    await view_wishlist(fake_cb, i18n, state)


@router.callback_query(F.data.startswith('unsubscribe_'))
async def unsubscribe_from_wishlist(callback: CallbackQuery, i18n: dict, state: FSMContext):
    await callback.answer()

    await delete_item_message(state)

    wishlist_id = int(callback.data.split('_')[1])
    wishlist = await get_wishlist(wishlist_id, with_owner=True)

    if not wishlist:
        await callback.answer(i18n.get('wishlist_not_found'), show_alert=True)
        return

    user = await get_or_create_user(callback.from_user.id)
    subscription = await get_subscription(user.id, wishlist.id)

    if not subscription:
        await callback.answer(i18n.get('not_subscribed'), show_alert=True)
        return

    await delete_subscription(subscription.id)

    await callback.answer(i18n.get('unsubscribed_success'), show_alert=True)

    # Create a simple object to pass as callback
    from types import SimpleNamespace
    fake_cb = SimpleNamespace()
    fake_cb.message = callback.message
    fake_cb.from_user = callback.from_user
    fake_cb.data = f"view_wishlist_{wishlist.access_uuid}"
    
    async def fake_answer():
        pass
    fake_cb.answer = fake_answer
    
    await view_wishlist(fake_cb, i18n, state)


async def notify_owner_about_request(bot: Bot, wishlist: Wishlist, subscriber: User, i18n: dict):
    keyboard = create_inline_kb(
        2,
        i18n,
        **{
            f"approve_sub_{subscriber.id}_{wishlist.id}": 'btn_approve',
            f"reject_sub_{subscriber.id}_{wishlist.id}": 'btn_reject'
        }
    )

    try:
        await bot.send_message(
            chat_id=wishlist.owner.telegram_id,
            text=i18n.get('wishlist_new_request', '').format(
                username=subscriber.username or subscriber.telegram_id,
                wishlist_title=wishlist.title
            ),
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error notifying owner: {e}")


@router.callback_query(F.data.startswith('approve_sub_'))
async def approve_subscription(callback: CallbackQuery, i18n: dict):
    """Одобряет запрос на подписку"""
    await callback.answer()

    try:
        parts = callback.data.split('_')
        subscriber_id = int(parts[2])
        wishlist_id = int(parts[3])

        # Сначала получаем данные ДО обновления
        subscription = await get_subscription_with_details(subscriber_id, wishlist_id)
        if not subscription:
            await callback.answer(i18n.get('subscription_not_found'), show_alert=True)
            return

        # Сохраняем данные перед обновлением
        wishlist_title = subscription.wishlist.title
        subscriber_tg_id = subscription.subscriber.telegram_id
        subscriber_username = subscription.subscriber.username or subscriber_tg_id

        # Теперь обновляем статус
        await update_subscription_status(subscription.id, SubscriptionStatus.APPROVED)

        # Уведомляем подписчика
        try:
            await callback.bot.send_message(
                chat_id=subscriber_tg_id,
                text=i18n.get('subscription_approved').format(
                    wishlist_title=wishlist_title
                )
            )
        except Exception as e:
            logger.error(f"Error notifying subscriber: {e}")

        # Обновляем сообщение у владельца
        await callback.message.edit_text(
            text=i18n.get('subscription_approved_owner').format(
                username=subscriber_username
            )
        )

    except Exception as e:
        logger.error(f"Error approving subscription: {e}")
        await callback.answer(i18n.get('error_occurred'), show_alert=True)


@router.callback_query(F.data.startswith('reject_sub_'))
async def reject_subscription(callback: CallbackQuery, i18n: dict):
    """Отклоняет запрос на подписку"""
    await callback.answer()

    try:
        parts = callback.data.split('_')
        subscriber_id = int(parts[2])
        wishlist_id = int(parts[3])

        # Сначала получаем данные ДО удаления
        subscription = await get_subscription_with_details(subscriber_id, wishlist_id)
        if not subscription:
            await callback.answer(i18n.get('subscription_not_found'), show_alert=True)
            return

        # Сохраняем данные перед удалением
        wishlist_title = subscription.wishlist.title
        subscriber_tg_id = subscription.subscriber.telegram_id
        subscriber_username = subscription.subscriber.username or subscriber_tg_id

        # Теперь удаляем
        await delete_subscription(subscription.id)

        # Уведомляем подписчика
        try:
            await callback.bot.send_message(
                chat_id=subscriber_tg_id,
                text=i18n.get('subscription_rejected').format(
                    wishlist_title=wishlist_title
                )
            )
        except Exception as e:
            logger.error(f"Error notifying subscriber: {e}")

        # Обновляем сообщение у владельца
        await callback.message.edit_text(
            text=i18n.get('subscription_rejected_owner').format(
                username=subscriber_username
            )
        )

    except Exception as e:
        logger.error(f"Error rejecting subscription: {e}")
        await callback.answer(i18n.get('error_occurred'), show_alert=True)


@router.callback_query(F.data == 'btn_my_wishlists')
async def show_my_wishlist(callback: CallbackQuery, i18n: dict[str, str], state: FSMContext):
    """
    Displays user's wishlists with interactive buttons or empty state if none exist.
    """

    await delete_item_message(state)

    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    user_id = user.id
    wishlists = await get_wishlists(user_id)

    await callback.answer()  # Acknowledge callback

    async with ChatActionSender.typing(bot=callback.bot, chat_id=callback.from_user.id):
        if not wishlists:
            keyboard = create_inline_kb(1, i18n, 'btn_create_wishlist', start_message='back_button')
            await callback.message.edit_text(
                text=i18n.get('my_wishlists_if_none'),
                reply_markup=keyboard
            )
        else:
            wishlists_buttons = {}
            for wishlist in wishlists:
                wishlists_buttons[f'view_wishlist_{wishlist.access_uuid}'] = f'🎁 {wishlist.title}'

            keyboard = create_inline_kb(1, i18n, **wishlists_buttons, btn_create_wishlist='btn_create_wishlist',
                                        start_message='back_button')

            await callback.message.edit_text(
                text=i18n.get('my_wishlists'),
                reply_markup=keyboard
            )


@router.callback_query(F.data == 'friends_wishlist_buttons', StateFilter(default_state))
async def process_friends_wishlist_buttons(callback: CallbackQuery, i18n: dict[str, str]):
    """
    Displays friends' wishlists with sharing status or empty state.
    """
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    user_id = user.id
    friends_wishlists = await get_friends_wishlists(user_id)

    await callback.answer()

    if not friends_wishlists:
        keyboard = create_inline_kb(1, i18n, start_message='back_button')
        await callback.message.edit_text(
            text=i18n.get('friends_wishlists_if_none'),
            reply_markup=keyboard
        )
    else:
        wishlists_buttons = {}
        for wishlist in friends_wishlists:
            wishlists_buttons[f'view_wishlist_{wishlist.access_uuid}'] = f'🎁 {wishlist.title}'

        keyboard = create_inline_kb(1, i18n, **wishlists_buttons,
                                    start_message='back_button')

        await callback.message.edit_text(
            text=i18n.get('friends_wishlists'),
            reply_markup=keyboard
        )


@router.callback_query(F.data.startswith('view_wishlist'), StateFilter(default_state))
async def view_wishlist(callback: CallbackQuery, i18n: dict[str, str], state: FSMContext):
    """
    Displays wishlist using template
    """
    await callback.answer()
    wishlist_uuid = callback.data.split('view_wishlist_')[1]

    wishlist = await get_wishlist(wishlist_identifier=wishlist_uuid, with_items=True, with_owner=True)

    try:
        if not wishlist:
            await callback.message.edit_text(
                text=i18n.get('wishlist_not_found'),
                reply_markup=create_inline_kb(1, i18n, start_message='back_button')
            )
            return

        user = await get_or_create_user(callback.from_user.id)
        subscription = await get_subscription(user.id, wishlist.id)

        is_owner = wishlist.owner_id == user.id
        is_subscribed = subscription and subscription.status == SubscriptionStatus.APPROVED
        is_pending = subscription and subscription.status == SubscriptionStatus.PENDING

        not_allowed = not is_owner and wishlist.is_private and not is_subscribed
        if not_allowed:
            text = await render_limited_wishlist_template(wishlist, i18n, is_pending)

            if is_pending:
                keyboard = create_inline_kb(
                    1,
                    i18n,
                    **{f"view_wishlist_{wishlist.access_uuid}": 'btn_subscription_pending'},
                    friends_wishlist_buttons='back_button'
                )
            else:
                keyboard = create_inline_kb(
                    1,
                    i18n,
                    **{f"subscribe_{wishlist.id}": 'btn_subscribe'},
                    friends_wishlist_buttons='back_button'
                )
        else:
            text = await render_wishlist_template(callback.message, wishlist, user, i18n)

            if is_owner:
                keyboard = create_inline_kb(
                    3,
                    i18n,
                    **{f"add_item_{wishlist.id}": 'btn_add_item',
                       f"edit_wishlist_{wishlist.id}": 'btn_edit',
                       f"delete_wishlist_{wishlist.id}": 'btn_delete_wishlist'},
                    btn_my_wishlists='back_button'
                )
            else:
                if is_subscribed:
                    subscribe_btn = {f"unsubscribe_{wishlist.id}": 'btn_unsubscribe'}
                else:
                    subscribe_btn = {f"subscribe_{wishlist.id}": 'btn_subscribe'}

                keyboard = create_inline_kb(
                    1,
                    i18n,
                    **subscribe_btn,
                    friends_wishlist_buttons='back_button'
                )

        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

        if wishlist.items and not not_allowed:
            item_msg = await send_item_info(callback.message, is_owner=is_owner, current_item=1, wishlist=wishlist, i18n=i18n,
                                 new_msg=True)
            await state.update_data(item_msg=item_msg)

    except Exception as e:
        logger.error(e)


@router.callback_query(F.data.startswith('next_item_'))
async def next_item(callback: CallbackQuery, i18n: dict[str, str]):
    wishlist_id = int(callback.data.split('_')[2])
    current_item = int(callback.data.split('_')[3]) + 1

    wishlist = await get_wishlist(wishlist_id, with_items=True)
    if not wishlist or not wishlist.items:
        return

    user = await get_or_create_user(callback.from_user.id)
    is_owner = True if user.id == wishlist.owner_id else False

    await send_item_info(callback.message, is_owner=is_owner, current_item=current_item, wishlist=wishlist, i18n=i18n,
                         new_msg=False)


@router.callback_query(F.data.startswith('prev_item_'))
async def prev_item(callback: CallbackQuery, i18n: dict[str, str]):
    wishlist_id = int(callback.data.split('_')[2])
    current_item = int(callback.data.split('_')[3]) - 1

    wishlist = await get_wishlist(wishlist_id, with_items=True)
    if not wishlist or not wishlist.items:
        return

    user = await get_or_create_user(callback.from_user.id)
    is_owner = True if user.id == wishlist.owner_id else False

    await send_item_info(callback.message, is_owner=is_owner, current_item=current_item, wishlist=wishlist, i18n=i18n,
                         new_msg=False)


@router.callback_query(F.data.startswith('delete_wishlist'), StateFilter(default_state))
async def delete_wishlist(callback: CallbackQuery, i18n: dict[str, str], state: FSMContext):
    try:
        await delete_item_message(state)

        wishlist_id = int(callback.data.split('delete_wishlist_')[1])

        wishlist = await get_wishlist(wishlist_id)
        user = await get_or_create_user(callback.from_user.id)
        user_id = user.id
        if not wishlist or wishlist.owner_id != user_id:
            await callback.answer(i18n.get('access_denied'), show_alert=True)
            return

        await delete_wishlist_db(wishlist_id)
        keyboard = create_inline_kb(1, i18n, 'btn_my_wishlists')
        await callback.message.edit_text(
            text=i18n.get('wishlist_deleted_success'),
            reply_markup=keyboard
        )
        await callback.answer()
    except (IndexError, ValueError):
        await callback.answer(i18n['invalid_request'], show_alert=True)
    except Exception as e:
        logger.error(f"Error deleting wishlist: {e}")
        await callback.answer(i18n['error_occurred'], show_alert=True)


# Handler for "Help" button click
@router.callback_query(F.data == 'help_button', StateFilter(default_state))
async def process_help_button(callback: CallbackQuery, i18n: dict[str, str]):
    """
    Displays help information with support options.
    """
    # Create help menu keyboard with support option
    keyboard = create_inline_kb(1, i18n, 'support_button', start_message='back_button')

    await callback.answer()

    # Show help message
    await callback.message.edit_text(
        text=i18n.get('help_message'),
        reply_markup=keyboard
    )


# Handler for /help command
@router.message(Command(commands='/help'), StateFilter(default_state))
async def process_help_command(message: Message, i18n: dict[str, str]):
    """
    Handles the /help command via message (alternative to button click).
    """
    # Create help keyboard
    keyboard = create_inline_kb(1, i18n, 'support_button')

    # Send help message
    await message.answer(
        text=i18n.get('help_message'),
        reply_markup=keyboard
    )
