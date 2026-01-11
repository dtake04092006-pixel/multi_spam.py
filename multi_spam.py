# PHIÊN BẢN NÂNG CẤP: MULTI-MODE (TIM + PRINT + BOTH) - TƯƠNG THÍCH NGƯỢC
import discord, asyncio, threading, time, os, re, requests, json, random, traceback, uuid
from flask import Flask, request, render_template_string, jsonify
from dotenv import load_dotenv
from datetime import datetime, timedelta
from waitress import serve

load_dotenv()

# --- CẤU HÌNH ---
main_tokens = os.getenv("MAIN_TOKENS", "").split(",")
tokens = os.getenv("TOKENS", "").split(",")
karuta_id, karibbit_id = "646937666251915264", "1311684840462225440"
elizabeth_id = "1406076473609293854"  # Bot Elizabeth để đọc Print
BOT_NAMES = ["xsyx", "sofa", "dont", "ayaya", "owo", "astra", "singo", "dia pox", "clam", "rambo", "domixi", "dogi", "sicula", "mo turn", "jan taru", "kio sama"]
acc_names = [f"Bot-{i:02d}" for i in range(1, 21)]

# --- BIẾN TRẠNG THÁI & KHÓA ---
servers = []
bot_states = {
    "reboot_settings": {}, "active": {}, "watermelon_grab": {}, "health_stats": {},
}
stop_events = {"reboot": threading.Event()}
server_start_time = time.time()

# --- BIẾN CHIA SẺ THÔNG TIN GIỮA CÁC BOT ---
shared_drop_info = {
    "print_data": None,
    "message_id": None,
    "timestamp": 0,
    "lock": threading.Lock()
}

# --- QUẢN LÝ BOT THREAD-SAFE ---
class ThreadSafeBotManager:
    def __init__(self):
        self._bots = {}
        self._rebooting = set()
        self._lock = threading.RLock()

    def add_bot(self, bot_id, bot_data):
        with self._lock:
            self._bots[bot_id] = bot_data
            print(f"[Bot Manager] ✅ Added bot {bot_id}", flush=True)

    def remove_bot(self, bot_id):
        with self._lock:
            bot_data = self._bots.pop(bot_id, None)
            if bot_data and bot_data.get('instance'):
                bot = bot_data['instance']
                loop = bot_data['loop']
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(bot.close(), loop)
                print(f"[Bot Manager] 🗑️ Removed and requested cleanup for bot {bot_id}", flush=True)
            return bot_data

    def get_bot_data(self, bot_id):
        with self._lock:
            return self._bots.get(bot_id)

    def get_all_bots_data(self):
        with self._lock:
            return list(self._bots.items())

    def get_main_bots_info(self):
        with self._lock:
            return [(bot_id, data) for bot_id, data in self._bots.items() if bot_id.startswith('main_')]
            
    def get_sub_bots_info(self):
        with self._lock:
            return [(bot_id, data) for bot_id, data in self._bots.items() if bot_id.startswith('sub_')]

    def is_rebooting(self, bot_id):
        with self._lock:
            return bot_id in self._rebooting

    def start_reboot(self, bot_id):
        with self._lock:
            if self.is_rebooting(bot_id): return False
            self._rebooting.add(bot_id)
            return True

    def end_reboot(self, bot_id):
        with self._lock:
            self._rebooting.discard(bot_id)

bot_manager = ThreadSafeBotManager()

# --- HÀM GỬI LỆNH ASYNC TỪ LUỒNG ĐỒNG BỘ ---
def send_message_from_sync(bot_id, channel_id, content):
    bot_data = bot_manager.get_bot_data(bot_id)
    if not bot_data: return
    
    bot = bot_data['instance']
    loop = bot_data['loop']

    async def _send():
        try:
            channel = bot.get_channel(int(channel_id))
            if channel:
                await channel.send(content)
        except Exception as e:
            print(f"[Async Send] ❌ Lỗi khi gửi tin nhắn từ {bot_id}: {e}", flush=True)

    if loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_send(), loop)
        try:
            future.result(timeout=10)
        except Exception as e:
            print(f"[Async Send] ❌ Lỗi khi chờ kết quả gửi tin: {e}", flush=True)

# --- LƯU & TẢI CÀI ĐẶT (TƯƠNG THÍCH NGƯỢC) ---
def save_settings():
    api_key, bin_id = os.getenv("JSONBIN_API_KEY"), os.getenv("JSONBIN_BIN_ID")
    settings_data = {'servers': servers, 'bot_states': bot_states, 'last_save_time': time.time()}
    if api_key and bin_id:
        headers = {'Content-Type': 'application/json', 'X-Master-Key': api_key}
        url = f"https://api.jsonbin.io/v3/b/{bin_id}"
        try:
            req = requests.put(url, json=settings_data, headers=headers, timeout=15)
            if req.status_code == 200:
                print("[Settings] ✅ Đã lưu cài đặt lên JSONBin.io.", flush=True)
                return
        except Exception as e:
            print(f"[Settings] ❌ Lỗi JSONBin, đang lưu local: {e}", flush=True)
    try:
        with open('backup_settings.json', 'w') as f:
            json.dump(settings_data, f, indent=2)
        print("[Settings] ✅ Đã lưu backup cài đặt locally.", flush=True)
    except Exception as e:
        print(f"[Settings] ❌ Lỗi khi lưu backup local: {e}", flush=True)

def load_settings():
    global servers, bot_states
    api_key, bin_id = os.getenv("JSONBIN_API_KEY"), os.getenv("JSONBIN_BIN_ID")
    
    def load_from_dict(settings):
        try:
            servers.clear()
            servers.extend(settings.get('servers', []))
            loaded_bot_states = settings.get('bot_states', {})
            for key, value in loaded_bot_states.items():
                if key in bot_states and isinstance(value, dict):
                    bot_states[key].update(value)
                elif key not in bot_states:
                    bot_states[key] = value
            return True
        except Exception as e:
            print(f"[Settings] ❌ Lỗi parse settings: {e}", flush=True)
            return False

    if api_key and bin_id:
        try:
            headers = {'X-Master-Key': api_key}
            url = f"https://api.jsonbin.io/v3/b/{bin_id}/latest"
            req = requests.get(url, headers=headers, timeout=15)
            if req.status_code == 200 and load_from_dict(req.json().get("record", {})):
                print("[Settings] ✅ Đã tải cài đặt từ JSONBin.io.", flush=True)
                return
        except Exception as e:
            print(f"[Settings] ⚠️ Lỗi tải từ JSONBin: {e}", flush=True)
    try:
        with open('backup_settings.json', 'r') as f:
            if load_from_dict(json.load(f)):
                print("[Settings] ✅ Đã tải cài đặt từ backup file.", flush=True)
                return
    except FileNotFoundError:
        print("[Settings] ⚠️ Không tìm thấy backup file, dùng cài đặt mặc định.", flush=True)
    except Exception as e:
        print(f"[Settings] ⚠️ Lỗi tải backup: {e}", flush=True)

# --- CHUYỂN ĐỔI DỮ LIỆU CŨ SANG MỚI ---
def migrate_old_settings():
    """Tự động chuyển đổi cấu hình cũ (heart_threshold) sang Multi-Mode"""
    print("[Migration] 🔄 Đang kiểm tra và chuyển đổi cấu hình cũ...", flush=True)
    
    migrated_count = 0
    for server in servers:
        for i in range(len(main_tokens)):
            bot_num = i + 1
            
            # Kiểm tra xem đã có cấu hình mới chưa
            mode1_key = f'mode_1_active_{bot_num}'
            mode2_key = f'mode_2_active_{bot_num}'
            mode3_key = f'mode_3_active_{bot_num}'
            
            # Nếu chưa có mode nào -> Chuyển đổi từ cũ
            if mode1_key not in server and mode2_key not in server and mode3_key not in server:
                # Mặc định bật Mode 1 (Tim)
                server[mode1_key] = True
                server[mode2_key] = False
                server[mode3_key] = False
                
                # Chuyển đổi ngưỡng tim cũ
                old_min = server.get(f'heart_threshold_{bot_num}', 50)
                old_max = server.get(f'max_heart_threshold_{bot_num}', 99999)
                
                server[f'heart_min_{bot_num}'] = old_min
                server[f'heart_max_{bot_num}'] = old_max
                server[f'print_min_{bot_num}'] = 1
                server[f'print_max_{bot_num}'] = 1000
                
                # Cấu hình Mode 3
                server[f'm3_heart_min_{bot_num}'] = 50
                server[f'm3_heart_max_{bot_num}'] = 99999
                server[f'm3_print_min_{bot_num}'] = 1
                server[f'm3_print_max_{bot_num}'] = 1000
                
                migrated_count += 1
                print(f"[Migration] ✅ Chuyển đổi Bot {bot_num} trong server '{server.get('name')}'", flush=True)
    
    if migrated_count > 0:
        print(f"[Migration] 🎉 Đã chuyển đổi {migrated_count} cấu hình cũ sang Multi-Mode!", flush=True)
        save_settings()
    else:
        print("[Migration] ℹ️ Không có cấu hình cũ nào cần chuyển đổi.", flush=True)

# --- HÀM TRỢ GIÚP ---
def get_bot_name(bot_id_str):
    try:
        parts = bot_id_str.split('_')
        b_type, b_index = parts[0], int(parts[1])
        if b_type == 'main':
            return BOT_NAMES[b_index - 1] if 0 < b_index <= len(BOT_NAMES) else f"MAIN_{b_index}"
        return acc_names[b_index] if b_index < len(acc_names) else f"SUB_{b_index+1}"
    except (IndexError, ValueError):
        return bot_id_str.upper()

# ==============================================================================
# <<< LOGIC NHẶT - PHIÊN BẢN MULTI-MODE (TIM + PRINT + BOTH) >>>
# ==============================================================================
async def scan_and_share_drop_info(bot, msg, channel_id):
    """Bot 1 quét thông tin Print và chia sẻ cho tất cả bot khác"""
    
    with shared_drop_info["lock"]:
        shared_drop_info["print_data"] = None
        shared_drop_info["message_id"] = msg.id
        shared_drop_info["timestamp"] = time.time()
    
    print(f"[SCAN] 🔍 Bot 1 đang quét thông tin drop...", flush=True)
    
    # Tải lại tin nhắn
    try:
        msg = await msg.channel.fetch_message(msg.id)
    except Exception as e:
        print(f"[SCAN] ⚠️ Lỗi fetch message: {e}", flush=True)
        return
    
    # QUÉT SỐ SAU DẤU THĂNG (#) TỪ ELIZABETH
    print_data = None
    try:
        async for msg_item in msg.channel.history(limit=5):
            if msg_item.author.id == int(elizabeth_id) and msg_item.created_at > msg.created_at:
                if not msg_item.embeds: continue
                desc = msg_item.embeds[0].description
                if not desc: continue

                lines = desc.split('\n')
                results = []
                
                for idx, line in enumerate(lines[:4]):  # Tối đa 4 thẻ
                    # Tìm số sau dấu #
                    match = re.search(r'#(\d+)', line)
                    if match:
                        card_number = int(match.group(1))
                        results.append((idx, card_number))
                        print(f"[SCAN] 🔷 Thẻ {idx+1}: #{card_number}", flush=True)
                
                if results:
                    print_data = results
                    print(f"[SCAN] 🔷 Đọc được Print: {print_data}", flush=True)
                    break
    except Exception as e:
        print(f"[SCAN] ⚠️ Lỗi đọc Print: {e}", flush=True)
    
    # Lưu vào shared memory
    with shared_drop_info["lock"]:
        shared_drop_info["print_data"] = print_data
    
    print(f"[SCAN] ✅ Bot 1 hoàn tất quét. Dữ liệu đã được chia sẻ.", flush=True)

async def handle_grab(bot, msg, bot_num):
    """Logic nhặt thẻ Multi-Mode - ĐÃ FIX TƯƠNG THÍCH NGƯỢC"""
    
    channel_id = msg.channel.id
    target_server = next((s for s in servers if str(s.get('main_channel_id')).strip() == str(channel_id)), None)
    
    if not target_server:
        return

    auto_grab = target_server.get(f'auto_grab_enabled_{bot_num}', False)
    watermelon_grab_enabled = bot_states["watermelon_grab"].get(f'main_{bot_num}', False)
    
    if not auto_grab and not watermelon_grab_enabled:
        return

    # --- NHẶT WATERMELON/SOCOLA ---
    if watermelon_grab_enabled:
        await asyncio.sleep(5.0)
        try:
            target_message = await msg.channel.fetch_message(msg.id)
            for reaction in target_message.reactions:
                emoji_name = reaction.emoji if isinstance(reaction.emoji, str) else reaction.emoji.name
                
                if '🎀' in emoji_name:
                    await target_message.add_reaction("🎀")
                    print(f"[GRAB | Bot {bot_num}] ✅ NHẶT KẸO (🎀) THÀNH CÔNG!", flush=True)
                    break 
                elif '🍫' in emoji_name:
                    await target_message.add_reaction("🍫")
                    print(f"[GRAB | Bot {bot_num}] ✅ NHẶT SOCOLA (🍫) THÀNH CÔNG!", flush=True)
                    break 
        except Exception as e:
            print(f"[GRAB | Bot {bot_num}] ❌ Lỗi khi nhặt vật phẩm: {e}", flush=True)

    # --- NHẶT THẺ (MULTI-MODE) ---
    if not auto_grab:
        return

    # CHỈ BOT 1 QUÉT - CÁC BOT KHÁC CHỜ
    if bot_num == 1:
        await scan_and_share_drop_info(bot, msg, channel_id)
        await asyncio.sleep(0.3)
    else:
        await asyncio.sleep(random.uniform(0.5, 0.8))
    
    # Lấy dữ liệu chia sẻ
    with shared_drop_info["lock"]:
        if shared_drop_info["message_id"] != msg.id:
            return
        print_data = shared_drop_info["print_data"]
    
    # Lấy mode đang bật
    mode1_active = target_server.get(f'mode_1_active_{bot_num}')
    mode2_active = target_server.get(f'mode_2_active_{bot_num}')
    mode3_active = target_server.get(f'mode_3_active_{bot_num}')

    # TƯƠNG THÍCH NGƯỢC: Nếu chưa có mode nào -> tự động bật Mode 1
    if mode1_active is None and mode2_active is None and mode3_active is None:
        print(f"[AUTO-FIX] ⚠️ Bot {bot_num}: Phát hiện Data cũ. Tự động kích hoạt Mode 1.", flush=True)
        mode1_active = True
        target_server[f'mode_1_active_{bot_num}'] = True
    else:
        mode1_active = bool(mode1_active)
        mode2_active = bool(mode2_active)
        mode3_active = bool(mode3_active)

    # Lấy ngưỡng (tương thích cả key cũ và mới)
    heart_min = target_server.get(f'heart_min_{bot_num}') or target_server.get(f'heart_threshold_{bot_num}', 50)
    heart_max = target_server.get(f'heart_max_{bot_num}') or target_server.get(f'max_heart_threshold_{bot_num}', 99999)
    print_min = target_server.get(f'print_min_{bot_num}', 1)
    print_max = target_server.get(f'print_max_{bot_num}', 1000)
    
    candidates = [] 

    # --- MODE 3: BOTH (TIM + PRINT) ---
    if mode3_active and print_data:
        m3_h_min = target_server.get(f'm3_heart_min_{bot_num}', 50)
        m3_h_max = target_server.get(f'm3_heart_max_{bot_num}', 99999)
        m3_p_min = target_server.get(f'm3_print_min_{bot_num}', 1)
        m3_p_max = target_server.get(f'm3_print_max_{bot_num}', 1000)

        # Cần lấy tim để so sánh
        try:
            channel = bot.get_channel(int(channel_id))
            heart_data = None
            for _ in range(5):
                await asyncio.sleep(0.5)
                async for msg_item in channel.history(limit=5):
                    if msg_item.author.id == int(karibbit_id) and msg_item.id > msg.id:
                        if not msg_item.embeds: continue
                        desc = msg_item.embeds[0].description
                        if not desc or '♡' not in desc: continue

                        lines = desc.split('\n')[:4]
                        heart_data = [int(re.search(r'♡(\d+)', line).group(1)) if re.search(r'♡(\d+)', line) else 0 for line in lines]
                        break
                if heart_data:
                    break
            
            if heart_data:
                valid_cards = []
                print_dict = {idx: val for idx, val in print_data}
                for idx, hearts in enumerate(heart_data):
                    if idx in print_dict:
                        print_val = print_dict[idx]
                        if (m3_h_min <= hearts <= m3_h_max) and (m3_p_min <= print_val <= m3_p_max):
                            valid_cards.append((idx, hearts, print_val))
                
                if valid_cards:
                    best = min(valid_cards, key=lambda x: (x[2], -x[1])) 
                    best_idx, best_hearts, best_print = best
                    emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"][best_idx]
                    candidates.append((3, emoji, 0.5, f"Mode 3 [Both] - H:{best_hearts} P:#{best_print}"))
        except Exception as e:
            print(f"[GRAB | Bot {bot_num}] ⚠️ Lỗi Mode 3: {e}", flush=True)
            
    # --- MODE 2: PRINT ---
    if mode2_active and print_data:
        valid_prints = [(idx, val) for idx, val in print_data if print_min <= val <= print_max]
        if valid_prints:
            best_idx, best_print = min(valid_prints, key=lambda x: x[1])
            emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"][best_idx]
            candidates.append((2, emoji, 0.7, f"Mode 2 [Print] - Print #{best_print}"))

    # --- MODE 1: TIM (GIỮ NGUYÊN LOGIC CŨ) ---
    if mode1_active:
        try:
            channel = bot.get_channel(int(channel_id))
            if channel:
                for _ in range(7):
                    await asyncio.sleep(0.5)
                    async for msg_item in channel.history(limit=5):
                        if msg_item.author.id == int(karibbit_id) and msg_item.id > msg.id:
                            if not msg_item.embeds: continue
                            desc = msg_item.embeds[0].description
                            if not desc or '♡' not in desc: continue

                            lines = desc.split('\n')[:3]
                            heart_numbers = [int(re.search(r'♡(\d+)', line).group(1)) if re.search(r'♡(\d+)', line) else 0 for line in lines]
                            
                            valid_cards = [(idx, hearts) for idx, hearts in enumerate(heart_numbers) if heart_min <= hearts <= heart_max]
                            
                            if valid_cards:
                                max_index, max_num = max(valid_cards, key=lambda x: x[1])
                                delays = {1: [0.2, 1.1, 2], 2: [0.7, 1.8, 2.4], 3: [0.7, 1.8, 2.4], 4: [0.8, 1.9, 2.5]}
                                bot_delays = delays.get(bot_num, [0.9, 2.0, 2.6])
                                emoji = ["1️⃣", "2️⃣", "3️⃣"][max_index]
                                delay = bot_delays[max_index]
                                
                                candidates.append((1, emoji, delay, f"Mode 1 [Heart] - Hearts {max_num}"))
                                
                                print(f"[GRAB | Bot {bot_num}] 🎯 Mode 1: Tìm thấy thẻ {max_num}♡.", flush=True)
                                raise StopAsyncIteration
                    if candidates:
                        break
        
        except StopAsyncIteration:
            pass
        except Exception as e:
            print(f"[GRAB | Bot {bot_num}] ❌ Lỗi Mode 1: {e}", flush=True)
            
    # --- QUYẾT ĐỊNH ---
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_choice = candidates[0]
        priority, emoji, delay, reason = best_choice
        
        print(f"[GRAB | Bot {bot_num}] 🎯 Chọn: {reason} (Priority {priority})", flush=True)
        
        async def grab_action():
            await asyncio.sleep(delay)
            try:
                await msg.add_reaction(emoji)
                ktb_id = target_server.get('ktb_channel_id')
                if ktb_id:
                    ktb = bot.get_channel(int(ktb_id))
                    if ktb: await ktb.send("kt fs")
                print(f"[GRAB | Bot {bot_num}] ✅ NHẶT THẺ THÀNH CÔNG!", flush=True)
            except Exception as e:
                print(f"[GRAB] Lỗi react: {e}", flush=True)
        
        asyncio.create_task(grab_action())
    else:
        active_modes = []
        if mode1_active: active_modes.append("Mode 1")
        if mode2_active: active_modes.append("Mode 2")
        if mode3_active: active_modes.append("Mode 3")
        print(f"[DEBUG] Bot {bot_num}: Đã quét xong nhưng không nhặt. (Modes bật: {active_modes})", flush=True)

# --- HỆ THỐNG REBOOT & HEALTH CHECK (GIỮ NGUYÊN) ---
def check_bot_health(bot_data, bot_id):
    try:
        stats = bot_states["health_stats"].setdefault(bot_id, {'consecutive_failures': 0, 'last_check': 0})
        stats['last_check'] = time.time()
        
        if not bot_data or not bot_data.get('instance'):
            stats['consecutive_failures'] += 1
            return False

        bot = bot_data['instance']
        is_connected = bot.is_ready() and not bot.is_closed()
        
        if is_connected:
            stats['consecutive_failures'] = 0
        else:
            stats['consecutive_failures'] += 1
            print(f"[Health Check] ⚠️ Bot {bot_id} not connected - failures: {stats['consecutive_failures']}", flush=True)
            
        return is_connected
    except Exception as e:
        print(f"[Health Check] ❌ Exception in health check for {bot_id}: {e}", flush=True)
        bot_states["health_stats"].setdefault(bot_id, {})['consecutive_failures'] = \
            bot_states["health_stats"][bot_id].get('consecutive_failures', 0) + 1
        return False

def handle_reboot_failure(bot_id):
    settings = bot_states["reboot_settings"].setdefault(bot_id, {'delay': 3600, 'enabled': True})
    failure_count = settings.get('failure_count', 0) + 1
    settings['failure_count'] = failure_count
    
    backoff_multiplier = min(2 ** failure_count, 8)
    base_delay = settings.get('delay', 3600)
    next_try_delay = max(600, base_delay / backoff_multiplier) * backoff_multiplier

    settings['next_reboot_time'] = time.time() + next_try_delay
    
    print(f"[Safe Reboot] 🔴 Failure #{failure_count} for {bot_id}. Thử lại sau {next_try_delay/60:.1f} phút.", flush=True)
    if failure_count >= 5:
        settings['enabled'] = False
        print(f"[Safe Reboot] ❌ Tắt auto-reboot cho {bot_id} sau 5 lần thất bại.", flush=True)

def safe_reboot_bot(bot_id):
    if not bot_manager.start_reboot(bot_id):
        print(f"[Safe Reboot] ⚠️ Bot {bot_id} đã đang trong quá trình reboot. Bỏ qua.", flush=True)
        return False

    print(f"[Safe Reboot] 🔄 Bắt đầu reboot bot {bot_id}...", flush=True)
    try:
        match = re.match(r"main_(\d+)", bot_id)
        if not match: raise ValueError("Định dạng bot_id không hợp lệ cho reboot.")
        
        bot_index = int(match.group(1)) - 1
        if not (0 <= bot_index < len(main_tokens)): raise IndexError("Bot index ngoài phạm vi danh sách token.")

        token = main_tokens[bot_index].strip()
        bot_name = get_bot_name(bot_id)

        print(f"[Safe Reboot] 🧹 Cleaning up old bot instance for {bot_name}", flush=True)
        old_bot_data = bot_manager.remove_bot(bot_id)
        if old_bot_data and old_bot_data.get('thread'):
             old_bot_data['thread'].join(timeout=15)

        settings = bot_states["reboot_settings"].get(bot_id, {})
        failure_count = settings.get('failure_count', 0)
        wait_time = random.uniform(20, 40) + min(failure_count * 30, 300)
        print(f"[Safe Reboot] ⏳ Chờ {wait_time:.1f}s để cleanup...", flush=True)
        time.sleep(wait_time)

        print(f"[Safe Reboot] 🔧 Creating new bot thread for {bot_name}", flush=True)
        new_bot_is_ready = threading.Event()
        new_thread = threading.Thread(target=initialize_and_run_bot, args=(token, bot_id, True, new_bot_is_ready), daemon=True)
        new_thread.start()
        ready_in_time = new_bot_is_ready.wait(timeout=60)
        
        if not ready_in_time:
             raise Exception("Bot mới không sẵn sàng trong 60 giây.")

        new_bot_data = bot_manager.get_bot_data(bot_id)
        if not new_bot_data:
             raise Exception("Không tìm thấy dữ liệu bot mới trong manager sau khi khởi động.")
        new_bot_data['thread'] = new_thread

        settings.update({
            'next_reboot_time': time.time() + settings.get('delay', 3600),
            'failure_count': 0, 'last_reboot_time': time.time()
        })
        bot_states["health_stats"][bot_id]['consecutive_failures'] = 0
        print(f"[Safe Reboot] ✅ Reboot thành công {bot_name}", flush=True)
        return True
    except Exception as e:
        print(f"[Safe Reboot] ❌ Reboot thất bại cho {bot_id}: {e}", flush=True)
        traceback.print_exc()
        handle_reboot_failure(bot_id)
        return False
    finally:
        bot_manager.end_reboot(bot_id)

def auto_reboot_loop():
    print("[Safe Reboot] 🚀 Khởi động luồng tự động reboot.", flush=True)
    last_global_reboot_time = 0
    consecutive_system_failures = 0
    while not stop_events["reboot"].is_set():
        try:
            now = time.time()
            min_global_interval = 600
            if now - last_global_reboot_time < min_global_interval:
                stop_events["reboot"].wait(60)
                continue
            bot_to_reboot = None
            highest_priority_score = -1
            reboot_settings_copy = dict(bot_states["reboot_settings"].items())
            for bot_id, settings in reboot_settings_copy.items():
                if not settings.get('enabled', False) or bot_manager.is_rebooting(bot_id): continue
                next_reboot_time = settings.get('next_reboot_time', 0)
                if now < next_reboot_time: continue
                health_stats = bot_states["health_stats"].get(bot_id, {})
                failure_count = health_stats.get('consecutive_failures', 0)
                time_overdue = now - next_reboot_time
                priority_score = (failure_count * 1000) + time_overdue
                if priority_score > highest_priority_score:
                    highest_priority_score = priority_score
                    bot_to_reboot = bot_id
            if bot_to_reboot:
                print(f"[Safe Reboot] 🎯 Chọn reboot bot: {bot_to_reboot} (priority: {highest_priority_score:.1f})", flush=True)
                if safe_reboot_bot(bot_to_reboot):
                    last_global_reboot_time = now
                    consecutive_system_failures = 0
                    wait_time = random.uniform(300, 600)
                    print(f"[Safe Reboot] ⏳ Chờ {wait_time:.0f}s trước khi tìm bot reboot tiếp theo.", flush=True)
                    stop_events["reboot"].wait(wait_time)
                else:
                    consecutive_system_failures += 1
                    backoff_time = min(120 * (2 ** consecutive_system_failures), 1800)
                    print(f"[Safe Reboot] ❌ Reboot thất bại. Hệ thống backoff: {backoff_time}s", flush=True)
                    stop_events["reboot"].wait(backoff_time)
            else:
                stop_events["reboot"].wait(60)
        except Exception as e:
            print(f"[Safe Reboot] ❌ Lỗi nghiêm trọng trong reboot loop: {e}", flush=True)
            traceback.print_exc()
            stop_events["reboot"].wait(120)

# --- HỆ THỐNG SPAM (GIỮ NGUYÊN) ---
def enhanced_spam_loop():
    print("[Enhanced Spam] 🚀 Khởi động hệ thống spam tối ưu (đa luồng)...", flush=True)
    server_pair_index = 0
    delay_between_pairs = 2
    delay_within_pair = 1.5
    max_threads = 4

    while True:
        try:
            active_spam_servers = [s for s in servers if s.get('spam_enabled') and s.get('spam_channel_id') and s.get('spam_message')]
            active_bots = [bot_id for bot_id, data in bot_manager.get_sub_bots_info() if bot_states["active"].get(bot_id) and data.get('instance')]
            
            if not active_spam_servers or not active_bots:
                time.sleep(5)
                continue

            if server_pair_index * 2 >= len(active_spam_servers):
                server_pair_index = 0
            
            start_index = server_pair_index * 2
            current_server_pair = active_spam_servers[start_index:start_index + 2]
            
            if not current_server_pair:
                server_pair_index = 0
                continue
            
            bot_groups = []
            bots_per_group = max(1, (len(active_bots) + max_threads - 1) // max_threads)
            for i in range(0, len(active_bots), bots_per_group):
                bot_groups.append(active_bots[i:i + bots_per_group])
        
            spam_threads = []
            for group_index, bot_group in enumerate(bot_groups):
                def group_spam_action(bots_in_group=bot_group, servers_pair=current_server_pair, group_id=group_index):
                    try:
                        server1 = servers_pair[0]
                        for bot_id in bots_in_group:
                            send_message_from_sync(bot_id, server1['spam_channel_id'], server1['spam_message'])
                            time.sleep(0.1)

                        if len(servers_pair) > 1:
                            time.sleep(delay_within_pair)
                            server2 = servers_pair[1]
                            for bot_id in bots_in_group:
                                send_message_from_sync(bot_id, server2['spam_channel_id'], server2['spam_message'])
                                time.sleep(0.02)
                    except Exception as e:
                        print(f"[Enhanced Spam] ❌ Lỗi nhóm {group_id}: {e}", flush=True)
                
                thread = threading.Thread(target=group_spam_action, daemon=True)
                spam_threads.append(thread)
                thread.start()

            for thread in spam_threads:
                thread.join()
            
            server_pair_index += 1
            time.sleep(delay_between_pairs)
            
        except Exception as e:
            print(f"[Enhanced Spam] ❌ Lỗi nghiêm trọng: {e}", flush=True)
            traceback.print_exc()
        
        time.sleep(10)

def ultra_optimized_spam_loop():
    print("[Ultra Spam] 🚀 Khởi động spam siêu tối ưu - 1 luồng duy nhất...", flush=True)
    server_pair_index = 0
    delay_between_pairs = 1.5
    delay_within_pair = 0.8
    while True:
        try:
            active_spam_servers = [s for s in servers if s.get('spam_enabled') and s.get('spam_channel_id') and s.get('spam_message')]
            active_bots = [bot_id for bot_id, data in bot_manager.get_sub_bots_info() if bot_states["active"].get(bot_id) and data.get('instance')]
            if not active_spam_servers or not active_bots:
                time.sleep(5)
                continue

            if server_pair_index * 2 >= len(active_spam_servers):
                server_pair_index = 0
            
            start_index = server_pair_index * 2
            current_server_pair = active_spam_servers[start_index:start_index + 2]
            
            if not current_server_pair:
                server_pair_index = 0
                continue
            
            server1 = current_server_pair[0]
            for bot_id in active_bots:
                send_message_from_sync(bot_id, server1['spam_channel_id'], server1['spam_message'])
                time.sleep(0.01)

            if len(current_server_pair) > 1:
                time.sleep(delay_within_pair)
                server2 = current_server_pair[1]
                for bot_id in active_bots:
                    send_message_from_sync(bot_id, server2['spam_channel_id'], server2['spam_message'])
                    time.sleep(0.01)

            server_pair_index += 1
            time.sleep(delay_between_pairs)
            
        except Exception as e:
            print(f"[Ultra Spam] ❌ Lỗi nghiêm trọng: {e}", flush=True)
            traceback.print_exc()
            time.sleep(10)

def start_optimized_spam_system(mode="optimized"):
    print(f"[Spam System] 🔄 Khởi động hệ thống spam ở chế độ '{mode}'...", flush=True)
    if mode == "ultra":
        spam_thread = threading.Thread(target=ultra_optimized_spam_loop, daemon=True)
    else:
        spam_thread = threading.Thread(target=enhanced_spam_loop, daemon=True)
    spam_thread.start()
    print(f"[Spam System] ✅ Hệ thống spam '{mode}' đã khởi động!", flush=True)

def periodic_task(interval, task_func, task_name):
    print(f"[{task_name}] 🚀 Khởi động luồng định kỳ.", flush=True)
    while True:
        time.sleep(interval)
        try: task_func()
        except Exception as e: print(f"[{task_name}] ❌ Lỗi: {e}", flush=True)

def health_monitoring_check():
    all_bots = bot_manager.get_all_bots_data()
    for bot_id, bot_data in all_bots:
        check_bot_health(bot_data, bot_id)

# --- KHỞI TẠO BOT ---
def initialize_and_run_bot(token, bot_id_str, is_main, ready_event=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = discord.Client(self_bot=True)

    try:
        bot_identifier = int(bot_id_str.split('_')[1])
    except (IndexError, ValueError):
        print(f"[Bot Init] ⚠️ Không thể phân tích ID cho bot: {bot_id_str}. Sử dụng giá trị mặc định.", flush=True)
        bot_identifier = 99

    @bot.event
    async def on_ready():
        try:
            print(f"[Bot] ✅ Đăng nhập: {bot.user.id} ({get_bot_name(bot_id_str)}) - {bot.user.name}", flush=True)
            stats = bot_states["health_stats"].setdefault(bot_id_str, {})
            stats.update({'created_time': time.time(), 'consecutive_failures': 0})
            if ready_event: ready_event.set()
        except Exception as e:
            print(f"[Bot] ❌ Error in on_ready for {bot_id_str}: {e}", flush=True)

    @bot.event
    async def on_message(msg, bot_num=bot_identifier):
        if not is_main:
            return

        try:
            if msg.author.id == int(karuta_id) and "dropping" in msg.content.lower():
                await handle_grab(bot, msg, bot_num)
        except Exception as e:
            print(f"[Bot] ❌ Error in on_message for {bot_id_str} (Bot {bot_num}): {e}\n{traceback.format_exc()}", flush=True)

    try:
        bot_manager.add_bot(bot_id_str, {'instance': bot, 'loop': loop, 'thread': threading.current_thread()})
        loop.run_until_complete(bot.start(token))
    except discord.errors.LoginFailure:
        print(f"[Bot] ❌ Login thất bại cho {get_bot_name(bot_id_str)}. Token có thể không hợp lệ.", flush=True)
        if ready_event: ready_event.set()
        bot_manager.remove_bot(bot_id_str)
    except Exception as e:
        print(f"[Bot] ❌ Lỗi khi chạy bot {bot_id_str}: {e}", flush=True)
        if ready_event: ready_event.set()
        bot_manager.remove_bot(bot_id_str)
    finally:
        loop.close()

# --- FLASK APP & GIAO DIỆN (NÂNG CẤP) ---
app = Flask(__name__)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shadow Master Control - Multi Mode</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0f0f13; color: #f0f0f0; font-family: sans-serif; padding: 20px; }
        .header { text-align: center; margin-bottom: 20px; }
        .header h1 { color: #ffd700; text-shadow: 0 0 10px rgba(255, 215, 0, 0.5); }
        
        .master-panel {
            background: linear-gradient(135deg, #2c003e, #000000);
            border: 2px solid #ffd700;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 30px;
            box-shadow: 0 0 20px rgba(255, 215, 0, 0.2);
        }
        .master-title {
            text-align: center; color: #ffd700; font-weight: bold;
            margin-bottom: 15px; text-transform: uppercase;
            border-bottom: 1px solid #444; padding-bottom: 10px; font-size: 1.2em;
        }
        
        .master-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px;
        }
        
        .master-bot-card {
            background: rgba(255,255,255,0.05);
            padding: 10px; border-radius: 8px; border: 1px solid #555;
        }
        .master-bot-name { color: #00ff00; font-weight: bold; margin-bottom: 5px; text-align: center; display: block; }
        
        .btn { padding: 8px 15px; border: none; border-radius: 4px; cursor: pointer; color: white; font-weight: bold; }
        .btn-sync { background: #ffd700; color: #000; width: 100%; margin-top: 15px; font-size: 1.1em; transition: 0.3s; }
        .btn-sync:hover { background: #ffea00; box-shadow: 0 0 15px #ffd700; }
        
        .btn-add { background: #006400; margin-bottom: 20px; }
        .btn-del { background: #8b0000; float: right; font-size: 0.8em; padding: 2px 8px; }

        .server-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; }
        .panel { background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 8px; }
        .panel h2 { color: #aaa; font-size: 1.1em; margin-bottom: 10px; border-bottom: 1px solid #333; padding-bottom: 5px; }

        input { background: #333; border: 1px solid #555; color: white; padding: 5px; width: 100%; border-radius: 4px; }
        .input-group { margin-bottom: 8px; }
        
        .bot-card { background: #222; padding: 10px; margin-top: 10px; border-radius: 6px; border: 1px solid #444; }
        
        .mode-selector { display: flex; gap: 5px; margin-bottom: 5px; }
        .mode-btn { flex: 1; padding: 5px; background: #333; border: 1px solid #555; color: #888; cursor: pointer; font-size: 0.8em; }
        
        .mode-btn.active-1 { background: #ff4444; color: white; border-color: red; }
        .mode-btn.active-2 { background: #4444ff; color: white; border-color: blue; }
        .mode-btn.active-3 { background: #ffd700; color: black; border-color: gold; font-weight: bold; }

        .range-row { display: flex; gap: 5px; align-items: center; margin-bottom: 5px; }
        .range-row label { width: 20px; font-size: 0.9em; }
        
        .m3-config { background: rgba(255,215,0,0.05); padding: 5px; border: 1px solid #555; margin-top: 5px; border-radius: 4px; }
        .m3-label { font-size: 0.7em; color: #ffd700; text-align: center; }

        .toggle-grab { width: 100%; padding: 6px; margin-top: 5px; background: #333; color: #666; border: none; cursor: pointer; }
        .toggle-grab.active { background: #006400; color: white; }
        
        .status-panel { background: #1a1a1a; border: 1px solid #333; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>👑 SHADOW MASTER CONTROL - MULTI MODE</h1>
        <div style="color: #888; font-size: 0.9em;">Uptime: <span id="uptime">Loading...</span></div>
    </div>
    
<div class="master-panel">
    <div class="master-title"><i class="fas fa-sliders-h"></i> BẢNG ĐIỀU KHIỂN TỔNG (MASTER)</div>
    <div class="master-grid">
        {% for bot in main_bots %}
        <div class="master-bot-card" id="master-bot-{{ bot.id }}">
            <span class="master-bot-name">{{ bot.name }}</span>
            <div class="mode-selector">
                <button class="mode-btn" onclick="toggleMasterMode(this, '1')">❤️ Tim</button>
                <button class="mode-btn" onclick="toggleMasterMode(this, '2')">🔷 Print</button>
                <button class="mode-btn" onclick="toggleMasterMode(this, '3')">⭐ Both</button>
            </div>
            <input type="hidden" class="master-mode-1" value="false">
            <input type="hidden" class="master-mode-2" value="false">
            <input type="hidden" class="master-mode-3" value="false">

            <div class="range-row">
                <label>❤️</label>
                <input type="number" class="master-h-min" value="50" placeholder="Min">
                <input type="number" class="master-h-max" value="99999" placeholder="Max">
            </div>
            <div class="range-row">
                <label>🔷</label>
                <input type="number" class="master-p-min" value="1" placeholder="Min">
                <input type="number" class="master-p-max" value="1000" placeholder="Max">
            </div>

            <div class="m3-config">
                <div class="m3-label">MODE 3 CONFIG</div>
                <div class="range-row">
                    <input type="number" class="master-m3-h-min" value="50" placeholder="❤️ Min">
                    <input type="number" class="master-m3-h-max" value="99999" placeholder="Max">
                </div>
                <div class="range-row">
                    <input type="number" class="master-m3-p-min" value="1" placeholder="🔷 Min">
                    <input type="number" class="master-m3-p-max" value="1000" placeholder="Max">
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    <button class="btn btn-sync" onclick="syncAll()"><i class="fas fa-sync-alt"></i> ĐỒNG BỘ CẤU HÌNH XUỐNG TẤT CẢ SERVER</button>
</div>

<div style="text-align:center; margin-bottom: 20px;">
    <button id="add-server-btn" class="btn btn-add"><i class="fas fa-plus"></i> Add New Server</button>
    <button id="master-grab-toggle" class="btn" style="background: #006400;"><i class="fas fa-power-off"></i> Toggle All RUNNING</button>
</div>

<div class="server-grid">
    {% for server in servers %}
    <div class="panel" data-server-id="{{ server.id }}">
        <h2>
            <i class="fas fa-server"></i> {{ server.name }}
            <button class="btn btn-del delete-server"><i class="fas fa-trash"></i></button>
        </h2>
        <div class="input-group"><input type="text" class="channel-input" data-field="main_channel_id" value="{{ server.main_channel_id or '' }}" placeholder="Main Channel ID"></div>
        <div class="input-group"><input type="text" class="channel-input" data-field="ktb_channel_id" value="{{ server.ktb_channel_id or '' }}" placeholder="KTB Channel ID"></div>
        <div class="input-group"><input type="text" class="channel-input" data-field="spam_channel_id" value="{{ server.spam_channel_id or '' }}" placeholder="Spam Channel ID"></div>
        <div class="input-group"><textarea class="spam-message" rows="2" placeholder="Spam Message">{{ server.spam_message or '' }}</textarea></div>
        <button type="button" class="broadcast-toggle btn">{{ 'DISABLE SPAM' if server.spam_enabled else 'ENABLE SPAM' }}</button>
        
        {% for bot in main_bots %}
        <div class="bot-card">
            <div style="font-weight:bold; color:#ddd; font-size:0.9em; margin-bottom:5px;">{{ bot.name }}</div>
            
            <div class="mode-selector">
                <button class="mode-btn {{ 'active-1' if server['mode_1_active_' + bot.id] else '' }}" onclick="toggleMode(this, '1', '{{ bot.id }}', '{{ server.id }}')">❤️</button>
                <button class="mode-btn {{ 'active-2' if server['mode_2_active_' + bot.id] else '' }}" onclick="toggleMode(this, '2', '{{ bot.id }}', '{{ server.id }}')">🔷</button>
                <button class="mode-btn {{ 'active-3' if server['mode_3_active_' + bot.id] else '' }}" onclick="toggleMode(this, '3', '{{ bot.id }}', '{{ server.id }}')">⭐</button>
            </div>
            
            <div class="range-row"><label>❤️</label> <input type="number" class="heart-min" value="{{ server['heart_min_' + bot.id] or 50 }}"> <input type="number" class="heart-max" value="{{ server['heart_max_' + bot.id] or 99999 }}"></div>
            <div class="range-row"><label>🔷</label> <input type="number" class="print-min" value="{{ server['print_min_' + bot.id] or 1 }}"> <input type="number" class="print-max" value="{{ server['print_max_' + bot.id] or 1000 }}"></div>

            <div class="m3-config">
                <div class="range-row"><input type="number" class="m3-h-min" value="{{ server['m3_heart_min_' + bot.id] or 50 }}"> <input type="number" class="m3-h-max" value="{{ server['m3_heart_max_' + bot.id] or 99999 }}"></div>
                <div class="range-row"><input type="number" class="m3-p-min" value="{{ server['m3_print_min_' + bot.id] or 1 }}"> <input type="number" class="m3-p-max" value="{{ server['m3_print_max_' + bot.id] or 1000 }}"></div>
            </div>

            <button class="toggle-grab {% if server['auto_grab_enabled_' + bot.id] %}active{% endif %}" data-bot="{{ bot.id }}">
                {{ 'RUNNING' if server['auto_grab_enabled_' + bot.id] else 'STOPPED' }}
            </button>
        </div>
        {% endfor %}
    </div>
    {% endfor %}
</div>

<script>
    const startTime = {{ start_time }};
    setInterval(() => {
        const elapsed = Math.floor(Date.now() / 1000 - startTime);
        const h = Math.floor(elapsed / 3600).toString().padStart(2, '0');
        const m = Math.floor((elapsed % 3600) / 60).toString().padStart(2, '0');
        const s = (elapsed % 60).toString().padStart(2, '0');
        document.getElementById('uptime').textContent = `${h}:${m}:${s}`;
    }, 1000);

    async function post(url, data) {
        await fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
        location.reload();
    }

    function toggleMasterMode(btn, mode) {
        btn.classList.toggle('active-' + mode);
        const parent = btn.closest('.master-bot-card');
        const input = parent.querySelector('.master-mode-' + mode);
        input.value = btn.classList.contains('active-' + mode) ? "true" : "false";
    }

    function syncAll() {
        if(!confirm('Bạn có chắc muốn áp dụng cấu hình này cho TẤT CẢ SERVER không?')) return;
        const botsConfig = [];
        document.querySelectorAll('.master-bot-card').forEach(card => {
            const botId = card.id.replace('master-bot-', '');
            botsConfig.push({
                id: botId,
                mode1: card.querySelector('.master-mode-1').value === "true",
                mode2: card.querySelector('.master-mode-2').value === "true",
                mode3: card.querySelector('.master-mode-3').value === "true",
                h_min: card.querySelector('.master-h-min').value,
                h_max: card.querySelector('.master-h-max').value,
                p_min: card.querySelector('.master-p-min').value,
                p_max: card.querySelector('.master-p-max').value,
                m3_h_min: card.querySelector('.master-m3-h-min').value,
                m3_h_max: card.querySelector('.master-m3-h-max').value,
                m3_p_min: card.querySelector('.master-m3-p-min').value,
                m3_p_max: card.querySelector('.master-m3-p-max').value
            });
        });
        post('/api/sync_master_config', { bots: botsConfig });
    }

    function toggleMode(btn, mode, botId, serverId) {
        const activeClass = 'active-' + mode;
        const isActive = btn.classList.toggle(activeClass);
        fetch('/api/toggle_bot_mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ server_id: serverId, bot_id: botId, mode: mode, active: isActive })
        });
    }

    document.getElementById('add-server-btn').addEventListener('click', () => {
        const name = prompt("Server Name:");
        if(name) post('/api/add_server', {name: name});
    });

    document.querySelectorAll('.delete-server').forEach(btn => {
        btn.addEventListener('click', () => {
            if(confirm('Delete?')) post('/api/delete_server', { server_id: btn.closest('.panel').dataset.serverId });
        });
    });

    document.querySelectorAll('.channel-input, .spam-message').forEach(inp => {
        inp.addEventListener('change', () => {
            const sid = inp.closest('.panel').dataset.serverId;
            const field = inp.dataset.field || 'spam_message';
            fetch('/api/update_server_field', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({server_id: sid, [field]: inp.value}) });
        });
    });

    document.querySelectorAll('.broadcast-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const sid = btn.closest('.panel').dataset.serverId;
            const msg = btn.closest('.panel').querySelector('.spam-message').value;
            post('/api/broadcast_toggle', {server_id: sid, message: msg});
        });
    });

    document.querySelectorAll('.toggle-grab').forEach(btn => {
        btn.addEventListener('click', () => {
            const card = btn.closest('.bot-card');
            const serverId = btn.closest('.panel').dataset.serverId;
            const botId = btn.dataset.bot;
            const heartMin = card.querySelector('.heart-min').value;
            const heartMax = card.querySelector('.heart-max').value;
            const printMin = card.querySelector('.print-min').value;
            const printMax = card.querySelector('.print-max').value;
            const m3_h_min = card.querySelector('.m3-h-min').value;
            const m3_h_max = card.querySelector('.m3-h-max').value;
            const m3_p_min = card.querySelector('.m3-p-min').value;
            const m3_p_max = card.querySelector('.m3-p-max').value;
            
            post('/api/harvest_toggle', {
                server_id: serverId, node: botId,
                heart_min: heartMin, heart_max: heartMax,
                print_min: printMin, print_max: printMax,
                m3_heart_min: m3_h_min, m3_heart_max: m3_h_max,
                m3_print_min: m3_p_min, m3_print_max: m3_p_max
            });
        });
    });

    document.getElementById('master-grab-toggle').addEventListener('click', () => {
        if(confirm('Toggle ALL bots RUNNING?')) post('/api/toggle_all_grab', {});
    });
</script>
</body>
</html>
"""

@app.route("/")
def index():
    main_bots = [{"id": str(i+1), "name": f"Main Bot {i+1}"} for i in range(len(main_tokens))]
    return render_template_string(HTML_TEMPLATE, servers=servers, main_bots=main_bots, start_time=server_start_time)

@app.route("/api/add_server", methods=['POST'])
def api_add_server():
    name = request.json.get('name')
    if not name: return jsonify({'status': 'error'}), 400
    new_server = {"id": f"server_{uuid.uuid4().hex}", "name": name}
    main_bots_count = len([t for t in main_tokens if t.strip()])
    for i in range(main_bots_count):
        bot_num = i + 1
        new_server[f'auto_grab_enabled_{bot_num}'] = False
        new_server[f'mode_1_active_{bot_num}'] = True
        new_server[f'mode_2_active_{bot_num}'] = False
        new_server[f'mode_3_active_{bot_num}'] = False
        new_server[f'heart_min_{bot_num}'] = 50
        new_server[f'heart_max_{bot_num}'] = 99999
        new_server[f'print_min_{bot_num}'] = 1
        new_server[f'print_max_{bot_num}'] = 1000
        new_server[f'm3_heart_min_{bot_num}'] = 50
        new_server[f'm3_heart_max_{bot_num}'] = 99999
        new_server[f'm3_print_min_{bot_num}'] = 1
        new_server[f'm3_print_max_{bot_num}'] = 1000
    servers.append(new_server)
    save_settings()
    return jsonify({'status': 'success', 'reload': True})

@app.route("/api/delete_server", methods=['POST'])
def api_delete_server():
    server_id = request.json.get('server_id')
    servers[:] = [s for s in servers if s.get('id') != server_id]
    save_settings()
    return jsonify({'status': 'success', 'reload': True})

@app.route("/api/update_server_field", methods=['POST'])
def api_update_server_field():
    data = request.json
    server = next((s for s in servers if s.get('id') == data.get('server_id')), None)
    if not server: return jsonify({'status': 'error'}), 404
    for key, value in data.items():
        if key != 'server_id': server[key] = value
    save_settings()
    return jsonify({'status': 'success'})

@app.route("/api/toggle_bot_mode", methods=['POST'])
def api_toggle_bot_mode():
    data = request.json
    server = next((s for s in servers if s.get('id') == data.get('server_id')), None)
    if not server: return jsonify({'status': 'error'}), 404
    bot_id = data.get('bot_id')
    mode = data.get('mode')
    active = data.get('active')

    key = f'mode_{mode}_active_{bot_id}'
    server[key] = active

    save_settings()
    return jsonify({'status': 'success'})

@app.route("/api/harvest_toggle", methods=['POST'])
def api_harvest_toggle():
    data = request.json
    server = next((s for s in servers if s.get('id') == data.get('server_id')), None)
    if not server: return jsonify({'status': 'error'}), 400
    node = str(data.get('node'))
    grab_key = f'auto_grab_enabled_{node}'
    server[grab_key] = not server.get(grab_key, False)

    server[f'heart_min_{node}'] = int(data.get('heart_min', 50))
    server[f'heart_max_{node}'] = int(data.get('heart_max', 99999))
    server[f'print_min_{node}'] = int(data.get('print_min', 1))
    server[f'print_max_{node}'] = int(data.get('print_max', 1000))
    server[f'm3_heart_min_{node}'] = int(data.get('m3_heart_min', 50))
    server[f'm3_heart_max_{node}'] = int(data.get('m3_heart_max', 99999))
    server[f'm3_print_min_{node}'] = int(data.get('m3_print_min', 1))
    server[f'm3_print_max_{node}'] = int(data.get('m3_print_max', 1000))

    save_settings()
    return jsonify({'status': 'success', 'reload': True})

@app.route("/api/broadcast_toggle", methods=['POST'])
def api_broadcast_toggle():
    data = request.json
    server = next((s for s in servers if s.get('id') == data.get('server_id')), None)
    if not server: return jsonify({'status': 'error'}), 404
    server['spam_enabled'] = not server.get('spam_enabled', False)
    server['spam_message'] = data.get("message", "").strip()
    if server['spam_enabled'] and (not server['spam_message'] or not server.get('spam_channel_id')):
        server['spam_enabled'] = False
        return jsonify({'status': 'error', 'message': f'Cần có message/channel spam.'})
    save_settings()
    return jsonify({'status': 'success', 'reload': True})

@app.route("/api/toggle_all_grab", methods=['POST'])
def api_toggle_all_grab():
    any_disabled = False
    for server in servers:
        for i in range(len(main_tokens)):
            bot_num = i + 1
            if not server.get(f'auto_grab_enabled_{bot_num}', False):
                any_disabled = True
                break
    new_state = any_disabled
    for server in servers:
        for i in range(len(main_tokens)):
            bot_num = i + 1
            server[f'auto_grab_enabled_{bot_num}'] = new_state

    save_settings()
    return jsonify({'status': 'success', 'reload': True})

@app.route("/api/sync_master_config", methods=['POST'])
def api_sync_master_config():
    data = request.json
    bots_config = data.get('bots', [])
    for server in servers:
        for config in bots_config:
            bot_id = config['id']
            
            server[f'mode_1_active_{bot_id}'] = config['mode1']
            server[f'mode_2_active_{bot_id}'] = config['mode2']
            server[f'mode_3_active_{bot_id}'] = config['mode3']
            
            server[f'heart_min_{bot_id}'] = int(config['h_min'])
            server[f'heart_max_{bot_id}'] = int(config['h_max'])
            server[f'print_min_{bot_id}'] = int(config['p_min'])
            server[f'print_max_{bot_id}'] = int(config['p_max'])
            
            server[f'm3_heart_min_{bot_id}'] = int(config['m3_h_min'])
            server[f'm3_heart_max_{bot_id}'] = int(config['m3_h_max'])
            server[f'm3_print_min_{bot_id}'] = int(config['m3_p_min'])
            server[f'm3_print_max_{bot_id}'] = int(config['m3_p_max'])
            
    save_settings()
    return jsonify({'status': 'success', 'reload': True})

@app.route("/api/watermelon_toggle", methods=['POST'])
def api_watermelon_toggle():
    node = request.json.get('node')
    if node not in bot_states["watermelon_grab"]: return jsonify({'status': 'error'}), 404
    bot_states["watermelon_grab"][node] = not bot_states["watermelon_grab"].get(node, False)
    save_settings()
    return jsonify({'status': 'success'})

@app.route("/api/bot_reboot_toggle", methods=['POST'])
def api_bot_reboot_toggle():
    data = request.json
    bot_id, delay = data.get('bot_id'), int(data.get("delay", 3600))
    if not re.match(r"main_\d+", bot_id): return jsonify({'status': 'error'}), 400
    settings = bot_states["reboot_settings"].get(bot_id)
    if not settings: return jsonify({'status': 'error'}), 400
    settings.update({'enabled': not settings.get('enabled', False), 'delay': delay, 'failure_count': 0})
    if settings['enabled']:
        settings['next_reboot_time'] = time.time() + delay
    save_settings()
    return jsonify({'status': 'success'})

@app.route("/api/toggle_bot_state", methods=['POST'])
def api_toggle_bot_state():
    target = request.json.get('target')
    if target in bot_states["active"]:
        bot_states["active"][target] = not bot_states["active"][target]
        save_settings()
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 404

@app.route("/status")
def status_endpoint():
    now = time.time()
    def get_bot_status_list(bot_info_list, type_prefix):
        status_list = []
        for bot_id, data in bot_info_list:
            failures = bot_states["health_stats"].get(bot_id, {}).get('consecutive_failures', 0)
            health_status = 'bad' if failures >= 3 else 'warning' if failures > 0 else 'good'
            status_list.append({
                "name": get_bot_name(bot_id), "status": data.get('instance') is not None, "reboot_id": bot_id,
                "is_active": bot_states["active"].get(bot_id, False), "type": type_prefix, "health_status": health_status,
                "is_rebooting": bot_manager.is_rebooting(bot_id)
            })
        return sorted(status_list, key=lambda x: int(x['reboot_id'].split('_')[1]))

    bot_statuses = {
        "main_bots": get_bot_status_list(bot_manager.get_main_bots_info(), "main"),
        "sub_accounts": get_bot_status_list(bot_manager.get_sub_bots_info(), "sub")
    }
    reboot_settings_copy = bot_states["reboot_settings"].copy()
    for bot_id, settings in reboot_settings_copy.items():
        settings['countdown'] = max(0, settings.get('next_reboot_time', 0) - now) if settings.get('enabled') else 0
    return jsonify({'bot_reboot_settings': reboot_settings_copy, 'bot_statuses': bot_statuses, 'server_start_time': server_start_time, 'servers': servers, 'watermelon_grab_states': bot_states["watermelon_grab"]})

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print("🚀 Shadow Master Control - Multi Mode Edition Starting...", flush=True)
    load_settings()
    migrate_old_settings()  # Tự động chuyển đổi cấu hình cũ
    bot_threads = []

    # Khởi tạo bot chính
    for i, token in enumerate(t for t in main_tokens if t.strip()):
        bot_num = i + 1
        bot_id = f"main_{bot_num}"
        thread = threading.Thread(target=initialize_and_run_bot, args=(token.strip(), bot_id, True), daemon=True)
        bot_threads.append(thread)
        bot_states["active"].setdefault(bot_id, True)
        bot_states["watermelon_grab"].setdefault(bot_id, False)
        bot_states["reboot_settings"].setdefault(bot_id, {'enabled': False, 'delay': 3600, 'next_reboot_time': 0, 'failure_count': 0})
        bot_states["health_stats"].setdefault(bot_id, {'consecutive_failures': 0})

    # Khởi tạo bot phụ
    for i, token in enumerate(t for t in tokens if t.strip()):
        bot_id = f"sub_{i}"
        thread = threading.Thread(target=initialize_and_run_bot, args=(token.strip(), bot_id, False), daemon=True)
        bot_threads.append(thread)
        bot_states["active"].setdefault(bot_id, True)
        bot_states["health_stats"].setdefault(bot_id, {'consecutive_failures': 0})

    for t in bot_threads:
        t.start()
        delay = random.uniform(3, 5) 
        print(f"[Bot Init] ⏳ Waiting for {delay:.2f} seconds before starting next bot...", flush=True)
        time.sleep(delay)

    print("🔧 Starting background threads...", flush=True)
    threading.Thread(target=periodic_task, args=(1800, save_settings, "Save"), daemon=True).start()
    threading.Thread(target=periodic_task, args=(300, health_monitoring_check, "Health"), daemon=True).start()

    start_optimized_spam_system(mode="optimized") 

    threading.Thread(target=auto_reboot_loop, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Web Server running at http://0.0.0.0:{port}", flush=True)
    print("✅ System fully operational - Multi Mode Edition!", flush=True)

    serve(app, host="0.0.0.0", port=port)
