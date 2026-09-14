from io import BytesIO
import json
import logging
import os
from pathlib import Path
import secrets
from datetime import datetime, timezone
from decimal import Decimal

import qrcode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)


LOGGER = logging.getLogger(__name__)

WELCOME_MESSAGE = """🏦 — PRIME PANEL BOT✨ — 🏦
🎉 Hello, {first_name}!
🔑 Powered by PRIME PANEL BOT✨
— 🏦 Direct deals with every supplier
— 💧 Instant delivery after payment
— 🎁 Guaranteed discounted prices
— 📞 24/7 admin support
Tap any button below to begin.
💰 Your Balance: ₹{balance}"""


PRODUCTS = (
    "DRIP CLIENT APKMOD — NON ROOT",
    "PRIME HOOK APKMOD — NON ROOT",
    "SILENT CHEAT APKMOD — NON ROOT",
    "HG CHEAT APKMOD — NON ROOT",
    "BALA MOD APKMOD — NON ROOT",
    "ABCD NON ROOT PANEL",
    "X RAGE MAIN ID — NON ROOT",
    "PATO BLUE APKMOD — NON ROOT",
    "PATO ORANGE APKMOD — NON ROOT",
    "SKB APKMOD SAFE — NON ROOT",
    "DRIP CLIENT PROXY — NON ROOT",
    "AIM HACK MAIN ID — NON ROOT",
    "MOCO PANEL MAIN ID — NON ROOT",
    "DRIP-CLIENT WIRE — NON ROOT",
    "MAFIA PROXY MAIN ID — NON ROOT",
    "RAPID CORE ROOT INJECTOR",
    "SILENT CHEAT ROOT BRUTAL",
    "SILENT CHEAT ROOT SAFE",
    "SKB ROOT DEVICE INJECTOR",
    "HEXX - BLADE INJECTOR",
    "JITU MOD ROOT DEVICE",
    "UNSEEN MOD ROOT DEVICE",
    "ANGRY MOD ROOT DEVICE",
    "HAXXCKER PRO INJECTOR",
    "DRIP CLIENT ROOT",
)

SHOP_MESSAGE = "🛒 Shop\n\nSelect a product below:"
BOT_PERSISTENCE_PATH = Path(__file__).resolve().parent / "bot_persistence.pkl"
UPI_ID = "9891884735@ptsbi"
UPI_PAYEE_NAME = "Anita"
PRODUCT_PLANS_PATH = Path(__file__).resolve().parent / "product_plans.json"
ADMIN_TELEGRAM_IDS = {7402924194, 8357170127}
ADMIN_PLAN_FLOW_KEY = "admin_plan_flow"
REFERRAL_SIGNUP_REWARD_USD = Decimal("0.10")
REFERRAL_COMMISSION_RATE = Decimal("0.05")
BALANCE_INR_PER_USD = Decimal("90")
REFERRAL_IDS_KEY = "referral_ids"
REFERRAL_COMMISSION_USD_KEY = "referral_commission_usd"
REFERRAL_WITHDRAWN_USD_KEY = "referral_withdrawn_usd"
PROFILE_MEMBER_SINCE_KEY = "member_since"
PROFILE_TIER_KEY = "tier"
PROFILE_ORDERS_KEY = "orders"
PROFILE_TOTAL_SPENT_KEY = "total_spent"
BALANCE_AMOUNTS = {
    1: 90,
    2: 180,
    3: 270,
    4: 360,
    5: 450,
    10: 900,
    15: 1350,
    20: 1800,
    50: 4500,
}
LUCKY_SPIN_MESSAGE = """🎰 ━━ LUCKY SPIN ━━ 🎰
🎁 Possible Rewards:
├ 💰 Free Balance: Up to $0.03(₹3.00)
├ 🎟️ Discount Coupon: 10% Off
└ 🍀 Better Luck Tomorrow
━━━━━━━━━━━━━━━━━━━━━━
💡 You can spin once per day!
Click the button below to try your luck!"""
LUCKY_ALREADY_SPUN_MESSAGE = "❌ You already spun today!"
LUCKY_SPIN_DATE_KEY = "lucky_spin_date"
LUCKY_REWARDS = (
    {"message": "💰 Free Balance: ₹3.00", "balance": 3},
    {"message": "🎟️ Discount Coupon: 10% Off", "coupon": "10%"},
    {"message": "🍀 Better Luck Tomorrow"},
)


def build_start_keyboard() -> InlineKeyboardMarkup:
    """Create the PRIME PANEL BOT action menu."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛒 Shop", callback_data="shop")],
            [
                InlineKeyboardButton("💰 Add Balance", callback_data="add_balance"),
                InlineKeyboardButton("👑 My Orders", callback_data="orders"),
            ],
            [
                InlineKeyboardButton("👑 My Profile", callback_data="profile"),
                InlineKeyboardButton("🔗 Referral", callback_data="referral"),
            ],
            [
                InlineKeyboardButton("📖 How To", callback_data="how_to"),
                InlineKeyboardButton("🎁 Lucky", callback_data="lucky"),
            ],
        ]
    )


def ensure_user_state(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    """Initialize only missing profile fields in the existing persistent user data."""
    if user is None or context.user_data is None:
        return
    context.user_data.setdefault(
        PROFILE_MEMBER_SINCE_KEY,
        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    context.user_data.setdefault(PROFILE_TIER_KEY, "Bronze")
    context.user_data.setdefault(PROFILE_ORDERS_KEY, [])
    context.user_data.setdefault(PROFILE_TOTAL_SPENT_KEY, 0)


def format_usd_inr(usd_value: Decimal | int | float | str) -> tuple[str, str]:
    """Format one USD value and its fixed INR display equivalent."""
    usd = Decimal(str(usd_value)).quantize(Decimal("0.01"))
    inr = (usd * BALANCE_INR_PER_USD).quantize(Decimal("0.01"))
    return f"{usd:.2f}", f"{inr:.2f}"


def get_referral_stats(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> dict[str, Decimal | int]:
    """Read referral totals and earnings from persistent bot/user state."""
    bot_data = context.bot_data
    referrals = bot_data.get("referrals", {})
    referred_ids = referrals.get(str(user_id), [])
    total_referrals = len(referred_ids)
    active_referrals = sum(
        1
        for referred_id in referred_ids
        if bot_data.get("referral_activity", {}).get(str(referred_id), False)
    )
    signup_earned = REFERRAL_SIGNUP_REWARD_USD * total_referrals
    commission_earned = Decimal(
        str(
            bot_data.get("referral_commissions", {}).get(
                str(user_id),
                context.user_data.get(REFERRAL_COMMISSION_USD_KEY, 0),
            )
        )
    )
    available = signup_earned + commission_earned - Decimal(
        str(
            bot_data.get("referral_withdrawals", {}).get(
                str(user_id),
                context.user_data.get(REFERRAL_WITHDRAWN_USD_KEY, 0),
            )
        )
    )
    return {
        "total_referrals": total_referrals,
        "active_referrals": active_referrals,
        "signup_earned": signup_earned,
        "commission_earned": commission_earned,
        "total_earned": signup_earned + commission_earned,
        "available": max(Decimal("0"), available),
    }


def record_referral_start(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, args: list[str]
) -> None:
    """Record a new referral only once for a user who opened a referral link."""
    if not args or context.user_data is None:
        return
    payload = args[0].strip()
    if not payload.startswith("ref_"):
        return
    try:
        referrer_id = int(payload.removeprefix("ref_"))
    except ValueError:
        return
    if referrer_id == user_id or context.user_data.get("referrer_id"):
        return

    referrals = context.bot_data.setdefault("referrals", {})
    referred_ids = referrals.setdefault(str(referrer_id), [])
    if user_id not in referred_ids:
        referred_ids.append(user_id)
    context.user_data["referrer_id"] = referrer_id


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Resolve the current bot username for a real Telegram referral link."""
    cached_username = context.bot_data.get("bot_username")
    if cached_username:
        return cached_username
    bot_user = await context.bot.get_me()
    if not bot_user.username:
        raise RuntimeError("The Telegram bot username is unavailable.")
    context.bot_data["bot_username"] = bot_user.username
    return bot_user.username


async def build_referral_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> str:
    """Build referral content from the current Telegram user and saved stats."""
    user = update.effective_user
    ensure_user_state(context, user)
    stats = get_referral_stats(context, user.id)
    bot_username = await get_bot_username(context)
    signup_earned, signup_earned_inr = format_usd_inr(stats["signup_earned"])
    commission_earned, commission_earned_inr = format_usd_inr(
        stats["commission_earned"]
    )
    total_earned, total_earned_inr = format_usd_inr(stats["total_earned"])
    available, available_inr = format_usd_inr(stats["available"])
    referral_link = f"https://t.me/{bot_username}?start=ref_{user.id}"

    return f"""🎁 REFERRAL PROGRAM

✅ Status: ACTIVE
💰 Earn 5% commission on purchases!
🎁 Earn $0.10 (₹9.00) per signup!

━━━━━━━━━━━━━━━━━━━━━━
━━━━━━━━━━

📊 YOUR STATS:

├ 👥 Total Referrals: {stats["total_referrals"]}
├ 🛒 Active (Purchased): {stats["active_referrals"]}
├ 🎁 Signup Earned: ${signup_earned} (₹{signup_earned_inr})
├ 💵 Commission Earned: ${commission_earned} (₹{commission_earned_inr})
├ 📊 Total Earned: ${total_earned} (₹{total_earned_inr})
└ 💰 Available: ${available} (₹{available_inr})

━━━━━━━━━━━━━━━━━━━━━━
━━━━━━━━━━

🔗 Your Referral Link:

{referral_link}

📱 How it works:

1. Share your link
2. Friend joins using your link
3. When they purchase, you earn 5%!
4. Exchange to balance or withdraw!

💡 Example: Friend buys $5.00
(₹450.00) → You get $0.25 (₹22.50)"""


def build_referral_keyboard() -> InlineKeyboardMarkup:
    """Create the referral page controls."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 View Balance", callback_data="referral_balance")],
            [InlineKeyboardButton("⬅️ Back to Shop", callback_data="back_to_shop")],
        ]
    )


def build_profile_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> str:
    """Build the profile page from persistent user data."""
    user = update.effective_user
    ensure_user_state(context, user)
    stats = get_referral_stats(context, user.id)
    orders = context.user_data.get(PROFILE_ORDERS_KEY, [])
    total_orders = len(orders) if isinstance(orders, list) else int(orders or 0)
    total_spent = context.user_data.get(PROFILE_TOTAL_SPENT_KEY, 0)
    return f"""👑 Your Profile
━━━━━━━━━━━━━━━━━━━━

🆔 ID: {user.id}
🏷️ Type: {"Admin" if is_admin_user(user) else "User"}
🏅 Tier: {context.user_data.get(PROFILE_TIER_KEY, "Bronze")}
📅 Member Since: {context.user_data.get(PROFILE_MEMBER_SINCE_KEY)}

💰 Balance: ₹{get_user_balance(context)}
🛍️ Total Orders: {total_orders}
💵 Total Spent: ₹{total_spent}
⭐ Referrals: {stats["total_referrals"]}

🔑 Want to see your purchased keys? Tap
"My Key" from the main menu."""


def build_profile_keyboard() -> InlineKeyboardMarkup:
    """Create profile navigation controls."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔑 My Key", callback_data="my_key")],
            [InlineKeyboardButton("👆 Back", callback_data="back_to_panel")],
        ]
    )


def build_key_message(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Show saved purchased keys without inventing keys for new users."""
    keys = context.user_data.get("purchased_keys", [])
    if not keys:
        return "🔑 My Key\n\nNo purchased keys yet."
    return "🔑 My Key\n\n" + "\n".join(f"• {key}" for key in keys)


def build_key_keyboard() -> InlineKeyboardMarkup:
    """Create My Key navigation controls."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back to Profile", callback_data="profile")]]
    )


def build_shop_keyboard() -> InlineKeyboardMarkup:
    """Create one ordered button for every product in the catalogue."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    product,
                    callback_data=f"product:{index}",
                )
            ]
            for index, product in enumerate(PRODUCTS)
        ]
        + [[InlineKeyboardButton("🔙 Back", callback_data="back_to_panel")]]
    )


def is_admin_user(user) -> bool:
    """Return whether a Telegram user has product-plan admin access."""
    return bool(user and user.id in ADMIN_TELEGRAM_IDS)


def load_product_plans() -> dict[str, list[dict[str, str]]]:
    """Load per-product plans without creating a second user-balance store."""
    if not PRODUCT_PLANS_PATH.exists():
        return {}

    try:
        with PRODUCT_PLANS_PATH.open("r", encoding="utf-8") as plans_file:
            stored_plans = json.load(plans_file)
    except json.JSONDecodeError as error:
        raise RuntimeError("product_plans.json contains invalid JSON.") from error

    if not isinstance(stored_plans, dict):
        raise RuntimeError("product_plans.json must contain a product-to-plans object.")
    return stored_plans


def save_product_plans(plans: dict[str, list[dict[str, str]]]) -> None:
    """Atomically save the independent plan lists for each product."""
    temporary_path = PRODUCT_PLANS_PATH.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as plans_file:
        json.dump(plans, plans_file, ensure_ascii=False, indent=2)
        plans_file.write("\n")
    temporary_path.replace(PRODUCT_PLANS_PATH)


def get_product_plans(product_index: int) -> list[dict[str, str]]:
    """Return only the saved plans belonging to one product."""
    plans = load_product_plans().get(str(product_index), [])
    if not isinstance(plans, list):
        raise RuntimeError(f"Plans for product {product_index} must be a list.")
    return plans


def format_plan_price(price: str | int | float) -> str:
    """Format an admin-entered INR price without changing its stored value."""
    numeric_price = Decimal(str(price))
    if numeric_price == numeric_price.to_integral_value():
        return f"{numeric_price:.0f}"
    return f"{numeric_price:.2f}"


def build_product_message(product_index: int, admin_view: bool = False) -> str:
    """Build the product plan list shown to users and admins."""
    product = PRODUCTS[product_index]
    plans = get_product_plans(product_index)
    plan_lines = [
        f"• {plan['duration']} — ₹{format_plan_price(plan['price'])}"
        for plan in plans
    ]
    visible_plans = "\n".join(plan_lines) if plan_lines else "No plans available yet."
    message = f"🛒 {product}\n\nAvailable Plans:\n{visible_plans}"
    if admin_view:
        message += "\n\nAdmin Plan Management:"
    return message


def build_product_keyboard(
    product_index: int, admin_view: bool = False
) -> InlineKeyboardMarkup:
    """Create user-only or admin plan-management controls for one product."""
    rows: list[list[InlineKeyboardButton]] = []
    plans = get_product_plans(product_index)
    if admin_view:
        rows.append(
            [
                InlineKeyboardButton(
                    "➕ Add Plan",
                    callback_data=f"admin_add_plan:{product_index}",
                )
            ]
        )
        for plan in plans:
            plan_id = plan["id"]
            plan_label = (
                f"{plan['duration']} — ₹{format_plan_price(plan['price'])}"
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        f"✏️ Edit {plan_label}",
                        callback_data=f"admin_edit_plan:{product_index}:{plan_id}",
                    ),
                    InlineKeyboardButton(
                        f"🗑️ Delete {plan_label}",
                        callback_data=f"admin_delete_plan:{product_index}:{plan_id}",
                    ),
                ]
            )
    else:
        # Every customer plan is a real payment option. Tapping it opens
        # a QR whose UPI amount is exactly this plan's INR price.
        for plan_index, plan in enumerate(plans):
            rows.append(
                [
                    InlineKeyboardButton(
                        f"🛒 {plan['duration']} — ₹{format_plan_price(plan['price'])}",
                        callback_data=f"plan:{product_index}:{plan_index}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")])
    return InlineKeyboardMarkup(rows)


def build_admin_plan_prompt_keyboard() -> InlineKeyboardMarkup:
    """Create the cancel control for an admin plan input prompt."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Cancel", callback_data="admin_cancel_plan")]]
    )


def parse_product_index(value: str) -> int | None:
    """Parse a callback product index and reject values outside the catalogue."""
    try:
        product_index = int(value)
    except ValueError:
        return None
    return product_index if 0 <= product_index < len(PRODUCTS) else None


def find_plan(product_index: int, plan_id: str) -> dict[str, str] | None:
    """Find a plan only within its own product's plan list."""
    return next(
        (plan for plan in get_product_plans(product_index) if plan["id"] == plan_id),
        None,
    )


def new_plan_id(product_index: int) -> str:
    """Create a plan ID scoped to its product's plan collection."""
    return f"{product_index}-{secrets.token_hex(6)}"


def build_balance_keyboard() -> InlineKeyboardMarkup:
    """Create the fixed USD-to-INR amount selection menu."""
    amount_buttons = [
        InlineKeyboardButton(
            f"💵 Add ${usd} (₹{inr})",
            callback_data=f"balance:{usd}",
        )
        for usd, inr in BALANCE_AMOUNTS.items()
    ]
    rows = [
        amount_buttons[index : index + 2]
        for index in range(0, len(amount_buttons), 2)
    ]
    rows.append(
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_panel")]
    )
    return InlineKeyboardMarkup(rows)


def build_add_balance_message(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Render Add Balance from the existing per-user balance storage."""
    stored_balance = Decimal(str(get_user_balance(context)))
    balance_usd = stored_balance.quantize(Decimal("0.01"))
    balance_inr = (stored_balance * Decimal("90")).quantize(Decimal("0.01"))

    return f"""💰 ━━ ADD BALANCE ━━ 💰

💳 Current Balance: ${balance_usd:.2f} (₹{balance_inr:.2f})

━━━━━━━━━━━━━━━━━━━━━━

💳 Available Payment Methods:

🇮🇳 Paytm/UPI (INR)
🪙 Binance/Crypto (USD)

✅ Use balance for purchases!

━━━━━━━━━━━━━━━━━━━━━━

Select amount to deposit."""


def build_lucky_keyboard() -> InlineKeyboardMarkup:
    """Create the Lucky Spin action menu."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎰 Spin Now!", callback_data="spin_now")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_panel")],
        ]
    )


def build_lucky_back_keyboard() -> InlineKeyboardMarkup:
    """Create the Back button for Lucky Spin result screens."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_panel")]]
    )


def get_lucky_spin_day() -> str:
    """Use one consistent UTC calendar day for the once-daily restriction."""
    return datetime.now(timezone.utc).date().isoformat()


def has_spun_lucky_today(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check the current user's once-per-day Lucky Spin state."""
    return (context.user_data or {}).get(LUCKY_SPIN_DATE_KEY) == get_lucky_spin_day()


def spin_lucky_reward(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Apply the existing-style reward outcomes and return the result text."""
    reward = secrets.choice(LUCKY_REWARDS)
    user_data = context.user_data
    if user_data is None:
        raise RuntimeError("Lucky Spin requires user data persistence.")
    user_data[LUCKY_SPIN_DATE_KEY] = get_lucky_spin_day()

    if reward.get("balance"):
        user_data["balance"] = get_user_balance(context) + reward["balance"]
    if reward.get("coupon"):
        user_data["discount_coupon"] = reward["coupon"]

    return reward["message"]


async def show_lucky_page(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show the Lucky Spin page or the daily-limit message."""
    if has_spun_lucky_today(context):
        await query.edit_message_text(
            LUCKY_ALREADY_SPUN_MESSAGE,
            reply_markup=build_lucky_back_keyboard(),
        )
        return

    await query.edit_message_text(
        LUCKY_SPIN_MESSAGE,
        reply_markup=build_lucky_keyboard(),
    )


def build_back_to_shop_keyboard() -> InlineKeyboardMarkup:
    """Create the navigation button shown after selecting a product."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")]]
    )


def build_payment_keyboard(
    payment_uri: str, inr_amount: int
) -> InlineKeyboardMarkup:
    """Create payment actions without crediting balance from a button click."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ I have paid",
                    callback_data=f"payment_paid:{inr_amount}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancel Payment",
                    callback_data=f"payment_cancel:{inr_amount}",
                )
            ],
        ]
    )


def build_back_to_panel_keyboard() -> InlineKeyboardMarkup:
    """Create the navigation button shown on a regular submenu."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back", callback_data="back_to_panel")]]
    )


def build_payment_uri(inr_amount: int | float | Decimal | str) -> str:
    """Build a fresh exact-amount UPI URI, including decimal plan prices."""
    amount = Decimal(str(inr_amount)).quantize(Decimal("0.01"))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("UPI amount must be a positive INR value.")
    amount_text = f"{amount:.2f}".rstrip("0").rstrip(".")
    return (
        f"upi://pay?pa={UPI_ID}&pn={UPI_PAYEE_NAME}"
        f"&am={amount_text}&cu=INR"
    )


def generate_payment_qr(payment_uri: str) -> BytesIO:
    """Generate a PNG QR image for one fixed-amount UPI URI."""
    qr_code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr_code.add_data(payment_uri)
    qr_code.make(fit=True)
    image = qr_code.make_image(fill_color="black", back_color="white")

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    image_buffer.name = "upi-payment-qr.png"
    return image_buffer


def payment_caption(inr_amount: int) -> str:
    """Create the requested payment screen caption."""
    return (
        "💳 ━━ PAYMENT ━━ 💳\n\n"
        f"💰 Amount: ₹{inr_amount}\n\n"
        "📲 Scan the QR below to pay\n\n"
        f"UPI ID: {UPI_ID}"
    )


async def show_balance_menu(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Return to the fixed amount menu from text or photo payment screens."""
    if query.message is not None and query.message.photo:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=build_add_balance_message(context),
            reply_markup=build_balance_keyboard(),
        )
        return

    await query.edit_message_text(
        build_add_balance_message(context),
        reply_markup=build_balance_keyboard(),
    )


async def show_payment_screen(
    query, context: ContextTypes.DEFAULT_TYPE, inr_amount: int
) -> None:
    """Replace the amount menu with a QR-based payment screen."""
    payment_uri = build_payment_uri(inr_amount)
    qr_image = generate_payment_qr(payment_uri)

    if query.message is None:
        return

    await query.message.delete()
    await context.bot.send_photo(
        chat_id=query.message.chat_id,
        photo=qr_image,
        caption=payment_caption(inr_amount),
        reply_markup=build_payment_keyboard(payment_uri, inr_amount),
    )


async def show_product_payment_screen(
    query, context: ContextTypes.DEFAULT_TYPE, product_index: int, plan_index: int
) -> None:
    """Show an exact-price QR for a selected product plan."""
    plans = get_product_plans(product_index)
    if not (0 <= plan_index < len(plans)):
        await query.edit_message_text(
            "❌ This plan is no longer available.",
            reply_markup=build_back_to_shop_keyboard(),
        )
        return

    plan = plans[plan_index]
    amount = Decimal(str(plan["price"]))
    payment_uri = build_payment_uri(amount)
    qr_image = generate_payment_qr(payment_uri)
    if query.message is None:
        return

    product_name = PRODUCTS[product_index]
    caption = (
        "💳 ━━ PAYMENT ━━ 💳\n\n"
        f"🛒 {product_name}\n"
        f"📅 Plan: {plan['duration']}\n"
        f"💰 Exact Amount: ₹{format_plan_price(plan['price'])}\n\n"
        "📲 Scan this QR to pay the exact amount.\n"
        f"UPI ID: {UPI_ID}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ I have paid",
                    callback_data=f"product_paid:{product_index}:{plan_index}",
                )
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"product_cancel:{product_index}")],
        ]
    )
    await query.message.delete()
    await context.bot.send_photo(
        chat_id=query.message.chat_id,
        photo=qr_image,
        caption=caption,
        reply_markup=keyboard,
    )


async def begin_admin_plan_flow(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    product_index: int,
    plan: dict[str, str] | None = None,
) -> None:
    """Start the duration-then-price input flow for an admin."""
    flow = {
        "action": action,
        "product_index": product_index,
        "step": "duration",
    }
    if plan is not None:
        flow["plan_id"] = plan["id"]
    context.user_data[ADMIN_PLAN_FLOW_KEY] = flow

    if action == "edit" and plan is not None:
        prompt = (
            f"✏️ Edit Plan\n\n"
            f"Current duration: {plan['duration']}\n"
            f"Current price: ₹{format_plan_price(plan['price'])}\n\n"
            "Send the new duration/time (for example: 12 HOURS)."
        )
    else:
        prompt = (
            "➕ Add Plan\n\n"
            "Send the plan duration/time (for example: 12 HOURS)."
        )
    await query.edit_message_text(
        prompt,
        reply_markup=build_admin_plan_prompt_keyboard(),
    )


async def admin_plan_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Accept admin-entered duration and INR price for a product plan."""
    flow = (context.user_data or {}).get(ADMIN_PLAN_FLOW_KEY)
    if not flow or update.message is None:
        return

    if not is_admin_user(update.effective_user):
        context.user_data.pop(ADMIN_PLAN_FLOW_KEY, None)
        return

    text = update.message.text.strip()
    if flow["step"] == "duration":
        if not text or len(text) > 100:
            await update.message.reply_text(
                "Please send a valid duration/time up to 100 characters.",
                reply_markup=build_admin_plan_prompt_keyboard(),
            )
            return

        flow["duration"] = text
        flow["step"] = "price"
        await update.message.reply_text(
            "Now send the plan price in INR (for example: 15).",
            reply_markup=build_admin_plan_prompt_keyboard(),
        )
        return

    if flow["step"] != "price":
        context.user_data.pop(ADMIN_PLAN_FLOW_KEY, None)
        return

    try:
        price = Decimal(text.replace("₹", "").replace(",", "").strip())
    except Exception:
        price = Decimal("0")

    if not price.is_finite() or price <= 0:
        await update.message.reply_text(
            "Please send a valid INR price greater than 0.",
            reply_markup=build_admin_plan_prompt_keyboard(),
        )
        return

    product_index = flow["product_index"]
    plans = load_product_plans()
    product_plans = plans.setdefault(str(product_index), [])
    stored_price = format_plan_price(price)

    if flow["action"] == "add":
        product_plans.append(
            {
                "id": new_plan_id(product_index),
                "duration": flow["duration"],
                "price": stored_price,
            }
        )
    else:
        plan = next(
            (
                saved_plan
                for saved_plan in product_plans
                if saved_plan["id"] == flow.get("plan_id")
            ),
            None,
        )
        if plan is None:
            context.user_data.pop(ADMIN_PLAN_FLOW_KEY, None)
            await update.message.reply_text(
                "That plan no longer exists.",
                reply_markup=build_product_keyboard(product_index, True),
            )
            return
        plan["duration"] = flow["duration"]
        plan["price"] = stored_price

    save_product_plans(plans)
    context.user_data.pop(ADMIN_PLAN_FLOW_KEY, None)
    await update.message.reply_text(
        build_product_message(product_index, admin_view=True),
        reply_markup=build_product_keyboard(product_index, admin_view=True),
    )


def build_panel_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Build the main panel message for a command or a back navigation."""
    user = update.effective_user
    ensure_user_state(context, user)
    first_name = user.first_name if user and user.first_name else "there"
    return WELCOME_MESSAGE.format(
        first_name=first_name,
        balance=get_user_balance(context),
    )


def get_user_balance(context: ContextTypes.DEFAULT_TYPE) -> int | float:
    """Return the user's stored balance, defaulting to zero for new users."""
    return (context.user_data or {}).get("balance", 0)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the PRIME PANEL BOT welcome panel."""
    if update.message is None:
        return

    ensure_user_state(context, update.effective_user)
    record_referral_start(
        context,
        update.effective_user.id,
        list(context.args or []),
    )
    await update.message.reply_text(
        build_panel_message(update, context),
        reply_markup=build_start_keyboard(),
    )


BUTTON_MESSAGES = {
    # Keep the original callback actions available.
    "about": "This bot is ready for your next feature.",
    "help": "Use /start at any time to open this menu again.",
    # PRIME PANEL BOT menu actions.
    "shop": "🛒 Shop\n\nChoose a product to continue.",
    "add_balance": "💰 Add Balance\n\nBalance top-up options will appear here.",
    "orders": "👑 My Orders\n\nYour orders will appear here.",
    "profile": "👑 My Profile\n\nYour profile details will appear here.",
    "referral": "🔗 Referral\n\nYour referral link will appear here.",
    "how_to": "📖 How To\n\nSelect an option from the PRIME PANEL BOT menu to begin.",
    "lucky": "🎁 Lucky\n\nYour lucky offer will appear here.",
}


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle both the existing callbacks and the PRIME PANEL BOT buttons."""
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    ensure_user_state(context, update.effective_user)
    callback_data = query.data or ""
    if callback_data == "back_to_panel":
        context.user_data.pop(ADMIN_PLAN_FLOW_KEY, None)
        await query.edit_message_text(
            build_panel_message(update, context),
            reply_markup=build_start_keyboard(),
        )
        return

    if callback_data == "add_balance":
        await query.edit_message_text(
            build_add_balance_message(context),
            reply_markup=build_balance_keyboard(),
        )
        return

    if callback_data == "referral":
        await query.edit_message_text(
            await build_referral_message(update, context),
            reply_markup=build_referral_keyboard(),
        )
        return

    if callback_data == "referral_balance":
        await query.edit_message_text(
            (
                f"💰 Current Balance: ₹{get_user_balance(context)}\n\n"
                "Your saved balance is available for purchases."
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Back to Referral", callback_data="referral"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ Back to Shop", callback_data="back_to_shop"
                        )
                    ],
                ]
            ),
        )
        return

    if callback_data == "profile":
        await query.edit_message_text(
            build_profile_message(update, context),
            reply_markup=build_profile_keyboard(),
        )
        return

    if callback_data == "my_key":
        await query.edit_message_text(
            build_key_message(context),
            reply_markup=build_key_keyboard(),
        )
        return

    if callback_data == "lucky":
        await show_lucky_page(query, context)
        return

    if callback_data == "spin_now":
        if has_spun_lucky_today(context):
            await query.edit_message_text(
                LUCKY_ALREADY_SPUN_MESSAGE,
                reply_markup=build_lucky_back_keyboard(),
            )
            return

        reward_message = spin_lucky_reward(context)
        await query.edit_message_text(
            f"🎰 LUCKY SPIN RESULT\n\n{reward_message}",
            reply_markup=build_lucky_back_keyboard(),
        )
        return

    if callback_data == "back_to_balance":
        await show_balance_menu(query, context)
        return

    if callback_data.startswith("payment_cancel:"):
        await show_balance_menu(query, context)
        return

    if callback_data.startswith("payment_paid:"):
        try:
            inr_amount = int(callback_data.removeprefix("payment_paid:"))
        except ValueError:
            inr_amount = 0
        if inr_amount in BALANCE_AMOUNTS.values() and query.message is not None:
            if query.message.photo:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=(
                        f"✅ Payment submitted for verification.\n\n"
                        f"Amount: ₹{inr_amount}\n"
                        "Your balance will update after the payment is confirmed."
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "💰 Add Balance",
                                    callback_data="add_balance",
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    "⬅️ Back to Menu",
                                    callback_data="back_to_panel",
                                )
                            ],
                        ]
                    ),
                )
            else:
                await query.edit_message_text(
                    (
                        f"✅ Payment submitted for verification.\n\n"
                        f"Amount: ₹{inr_amount}\n"
                        "Your balance will update after the payment is confirmed."
                    ),
                    reply_markup=build_back_to_panel_keyboard(),
                )
            return

    if callback_data.startswith("balance:"):
        try:
            usd_amount = int(callback_data.removeprefix("balance:"))
        except ValueError:
            usd_amount = -1

        inr_amount = BALANCE_AMOUNTS.get(usd_amount)
        if inr_amount is not None:
            await show_payment_screen(query, context, inr_amount)
            return

    if callback_data == "shop":
        await query.edit_message_text(
            SHOP_MESSAGE,
            reply_markup=build_shop_keyboard(),
        )
        return

    if callback_data == "back_to_shop":
        context.user_data.pop(ADMIN_PLAN_FLOW_KEY, None)
        await query.edit_message_text(
            SHOP_MESSAGE,
            reply_markup=build_shop_keyboard(),
        )
        return

    if callback_data.startswith("product_cancel:"):
        try:
            product_index = int(callback_data.removeprefix("product_cancel:"))
        except ValueError:
            product_index = -1
        if 0 <= product_index < len(PRODUCTS) and query.message is not None:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=build_product_message(product_index),
                reply_markup=build_product_keyboard(product_index),
            )
        return

    if callback_data.startswith("product_paid:"):
        parts = callback_data.split(":")
        if len(parts) == 3:
            try:
                product_index = int(parts[1])
                plan_index = int(parts[2])
            except ValueError:
                product_index = plan_index = -1
            plans = get_product_plans(product_index) if 0 <= product_index < len(PRODUCTS) else []
            if 0 <= plan_index < len(plans):
                plan = plans[plan_index]
                await query.edit_message_caption(
                    caption=(
                        "✅ Payment submitted for verification.\n\n"
                        f"🛒 {PRODUCTS[product_index]}\n"
                        f"📅 Plan: {plan['duration']}\n"
                        f"💰 Amount: ₹{format_plan_price(plan['price'])}\n\n"
                        "Your order will be processed after payment is confirmed."
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 Back to Shop", callback_data="back_to_shop")]]
                    ),
                )
        return

    if callback_data.startswith("plan:"):
        parts = callback_data.split(":")
        if len(parts) == 3:
            try:
                product_index = int(parts[1])
                plan_index = int(parts[2])
            except ValueError:
                product_index = plan_index = -1
            if 0 <= product_index < len(PRODUCTS) and plan_index >= 0:
                await show_product_payment_screen(query, context, product_index, plan_index)
        return

    if callback_data.startswith("product:"):
        product_index = parse_product_index(callback_data.removeprefix("product:"))
        if product_index is not None:
            admin_view = is_admin_user(update.effective_user)
            await query.edit_message_text(
                build_product_message(product_index, admin_view=admin_view),
                reply_markup=build_product_keyboard(
                    product_index, admin_view=admin_view
                ),
            )
            return

    if callback_data.startswith("admin_"):
        if not is_admin_user(update.effective_user):
            return

        if callback_data == "admin_cancel_plan":
            flow = context.user_data.pop(ADMIN_PLAN_FLOW_KEY, None)
            if flow:
                product_index = flow.get("product_index")
                if isinstance(product_index, int) and 0 <= product_index < len(PRODUCTS):
                    await query.edit_message_text(
                        build_product_message(product_index, admin_view=True),
                        reply_markup=build_product_keyboard(
                            product_index, admin_view=True
                        ),
                    )
                    return
            await query.edit_message_text(
                build_panel_message(update, context),
                reply_markup=build_start_keyboard(),
            )
            return

        parts = callback_data.split(":")
        if len(parts) < 2:
            return
        product_index = parse_product_index(parts[1])
        if product_index is None:
            return

        if parts[0] == "admin_add_plan":
            await begin_admin_plan_flow(
                query,
                context,
                action="add",
                product_index=product_index,
            )
            return

        if parts[0] == "admin_edit_plan" and len(parts) == 3:
            plan = find_plan(product_index, parts[2])
            if plan is not None:
                await begin_admin_plan_flow(
                    query,
                    context,
                    action="edit",
                    product_index=product_index,
                    plan=plan,
                )
            return

        if parts[0] == "admin_delete_plan" and len(parts) == 3:
            plans = load_product_plans()
            product_plans = plans.get(str(product_index), [])
            updated_plans = [
                plan for plan in product_plans if plan["id"] != parts[2]
            ]
            if len(updated_plans) != len(product_plans):
                plans[str(product_index)] = updated_plans
                save_product_plans(plans)
            await query.edit_message_text(
                build_product_message(product_index, admin_view=True),
                reply_markup=build_product_keyboard(
                    product_index, admin_view=True
                ),
            )
            return

    await query.edit_message_text(
        BUTTON_MESSAGES.get(callback_data, "That option is not available."),
        reply_markup=build_back_to_panel_keyboard(),
    )


def get_bot_token() -> str:
    """Read the token from the environment without providing a fallback."""
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Add your Telegram bot token as the BOT_TOKEN "
            "environment variable before starting the bot."
        )
    return token


def main() -> None:
    """Build and run the bot with long polling."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    persistence = PicklePersistence(
        filepath=str(BOT_PERSISTENCE_PATH),
        update_interval=5,
    )
    application = (
        Application.builder()
        .token(get_bot_token())
        .persistence(persistence)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_click))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, admin_plan_message)
    )

    LOGGER.info("PRIME PANEL BOT is starting.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()