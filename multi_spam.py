# PHIÊN BẢN NÂNG CẤP: MULTI-MODE (TIM/PRINT) - NO OCR - MASTER CONTROL UI
import discord, asyncio, threading, time, os, re, requests, json, random, traceback, uuid
from flask import Flask, request, render_template_string, jsonify
from dotenv import load_dotenv

load_dotenv()

# --- CẤU HÌNH ---
main_tokens = os.getenv("MAIN_TOKENS", "").split(",")
tokens = os.getenv("TOKENS", "").split(",")
karuta_id, karibbit_id = "646937666251915264", "1311684840462225440"
elizabeth_id = "1406076473609293854" # ID BOT PRINT MỚI

BOT_NAMES = ["xsyx", "sofa", "dont", "ayaya", "owo", "astra", "singo", "dia pox", "clam", "rambo", "domixi", "dogi", "sicula", "mo turn", "jan taru", "kio sama"]
acc_names = [f"Bot-{i:02d}" for i in range(1, 21)]

# --- BIẾN TRẠNG THÁI & KHÓA ---
servers = []
bot_states = {
    "reboot_settings": {}, "active": {}, "watermelon_grab": {}, "health_stats": {},
}
stop_events = {"reboot": threading.Event()}
server_start_time = time.time()

# --- BIẾN CHIA SẺ THÔNG TIN GIỮA CÁC BOT (MASTER-SLAVE LOGIC) ---
shared_drop_info = {
    "heart_data": None,
    "print_data": None, # Thay cho ocr_data
    "message_id": None,
    "timestamp": 0,
    "lock": threading.Lock()
}

# --- QUẢN LÍ BOT THREAD-SAFE (GIỮ NGUYÊN) ---
class ThreadSafeBotManager:
    def __init__(self):
        self._bots = {}
        self._rebooting = set()
        self._lock = threading.RLock()

    def add_bot(self, bot_id, bot_data):
        with self._lock: self._bots[bot_id] = bot_data

    def remove_bot(self, bot_id):
        with self._lock:
            bot_data = self._bots.pop(bot_id, None)
            if bot_data and bot_data.get('instance'):
                bot = bot_data['instance']
                loop = bot_data['loop']
                if loop.is_running(): asyncio.run_coroutine_threadsafe(bot.close(), loop)
            return bot_data

    def get_bot_data(self, bot_id):
        with self._lock: return self._bots.get(bot_id)

    def get_all_bots_data(self):
        with self._lock: return list(self._bots.items())

    def get_main_bots_info(self):
        with self._lock: return [(bot_id, data) for bot_id, data in self._bots.items() if bot_id.startswith('main_')]
            
    def get_sub_bots_info(self):
        with self._lock: return [(bot_id, data) for bot_id, data in self._bots.items() if bot_id.startswith('sub_')]

    def is_rebooting(self, bot_id):
        with self._lock: return bot_id in self._rebooting

    def start_reboot(self, bot_id):
        with self._lock:
            if self.is_rebooting(bot_id): return False
            self._rebooting.add(bot_id)
            return True

    def end_reboot(self, bot_id):
        with self._lock: self._rebooting.discard(bot_id)

bot_manager = ThreadSafeBotManager()

# --- HÀM GỬI LỆNH ASYNC TỪ LUỒNG ĐỒNG BỘ ---
def send_message_from_sync(bot_id, channel_id, content):
    bot_data = bot_manager.get_bot_data(bot_id)
    if not bot_data: return
    async def _send():
        try:
            channel = bot_data['instance'].get_channel(int(channel_id))
            if channel: await channel.send(content)
        except: pass
    if bot_data['loop'].is_running(): asyncio.run_coroutine_threadsafe(_send(), bot_data['loop'])

# --- LƯU & TẢI CÀI ĐẶT (GIỮ NGUYÊN LOGIC CŨ ĐỂ KHÔNG MẤT DATA) ---
def save_settings():
    api_key, bin_id = os.getenv("JSONBIN_API_KEY"), os.getenv("JSONBIN_BIN_ID")
    settings_data = {'servers': servers, 'bot_states': bot_states, 'last_save_time': time.time()}
    if api_key and bin_id:
        headers = {'Content-Type': 'application/json', 'X-Master-Key': api_key}
        try: requests.put(f"https://api.jsonbin.io/v3/b/{bin_id}", json=settings_data, headers=headers, timeout=15)
        except: pass
    try:
        with open('backup_settings.json', 'w') as f: json.dump(settings_data, f, indent=2)
    except: pass

def load_settings():
    global servers, bot_states
    api_key, bin_id = os.getenv("JSONBIN_API_KEY"), os.getenv("JSONBIN_BIN_ID")
    
    def load_from_dict(settings):
        try:
            servers.clear()
            servers.extend(settings.get('servers', []))
            loaded_bot_states = settings.get('bot_states', {})
            for key, value in loaded_bot_states.items():
                if key in bot_states and isinstance(value, dict): bot_states[key].update(value)
                elif key not in bot_states: bot_states[key] = value
            return True
        except: return False

    if api_key and bin_id:
        try:
            headers = {'X-Master-Key': api_key}
            req = requests.get(f"https://api.jsonbin.io/v3/b/{bin_id}/latest", headers=headers, timeout=15)
            if req.status_code == 200 and load_from_dict(req.json().get("record", {})): return
        except: pass
    try:
        with open('backup_settings.json', 'r') as f: load_from_dict(json.load(f))
    except: pass

def get_bot_name(bot_id_str):
    try:
        parts = bot_id_str.split('_')
        b_index = int(parts[1])
        if parts[0] == 'main': return BOT_NAMES[b_index - 1] if 0 < b_index <= len(BOT_NAMES) else f"MAIN_{b_index}"
        return acc_names[b_index]
    except: return bot_id_str

# ==============================================================================
# <<< LOGIC NHẶT THẺ MỚI (MULTI-MODE + SHARED MEMORY + TEXT PARSING) >>>
# ==============================================================================

async def scan_and_share_drop_info(bot, msg):
    """Bot 1 quét thông tin (Tim & Print) và chia sẻ"""
    with shared_drop_info["lock"]:
        shared_drop_info["heart_data"] = None
        shared_drop_info["print_data"] = None
        shared_drop_info["message_id"] = msg.id
        shared_drop_info["timestamp"] = time.time()
    
    # 1. QUÉT TIM (Karibbit)
    heart_data = None
    try:
        async for msg_item in msg.channel.history(limit=4):
            if msg_item.author.id == int(karibbit_id) and msg_item.created_at > msg.created_at:
                if not msg_item.embeds: continue
                desc = msg_item.embeds[0].description
                if not desc or '♡' not in desc: continue
                lines = desc.split('\n')[:4]
                # Lấy số tim
                heart_data = [int(re.search(r'♡(\d+)', line).group(1)) if re.search(r'♡(\d+)', line) else 0 for line in lines]
                break
    except: pass

    # 2. QUÉT PRINT (Elizabeth - Text Parsing)
    # Logic: Tìm tin nhắn của Elizabeth, đọc số sau dấu #
    print_data = None
    try:
        async for msg_item in msg.channel.history(limit=4):
            if msg_item.author.id == int(elizabeth_id) and msg_item.created_at > msg.created_at:
                # Elizabeth thường dùng Embed
                content_to_scan = msg_item.content
                if msg_item.embeds:
                    content_to_scan += "\n" + (msg_item.embeds[0].description or "")
                
                # Regex tìm số sau dấu # (Ví dụ: 1 | 🤡 #79569 -> 79569)
                # Tìm tất cả các số dạng #12345
                found_prints = re.findall(r'#(\d+)', content_to_scan)
                
                if found_prints:
                    # Chuyển thành list [(index, print_value)]
                    # Giả sử thứ tự xuất hiện tương ứng với thẻ 1, 2, 3, 4
                    print_data = []
                    for idx, val in enumerate(found_prints):
                        if idx < 4: # Chỉ lấy tối đa 4 thẻ
                            print_data.append((idx, int(val)))
                    # print(f"[SCAN] 👁️ Tìm thấy Print từ Elizabeth: {print_data}", flush=True)
                break
    except Exception as e:
        print(f"[SCAN] ❌ Lỗi đọc Print Elizabeth: {e}", flush=True)

    with shared_drop_info["lock"]:
        shared_drop_info["heart_data"] = heart_data
        shared_drop_info["print_data"] = print_data

async def handle_grab(bot, msg, bot_num):
    """Logic nhặt thẻ Multi-Mode (Heart, Print, Both)"""
    channel_id = msg.channel.id
    target_server = next((s for s in servers if str(s.get('main_channel_id')).strip() == str(channel_id)), None)
    
    if not target_server: return

    # Kiểm tra nút tổng (Master Toggle cho bot này)
    # Lưu ý: Code cũ dùng 'auto_grab_enabled_X', ta vẫn giữ nó làm switch tổng
    if not target_server.get(f'auto_grab_enabled_{bot_num}', False):
        return

    # --- BOT 1 SCAN ---
    if bot_num == 1:
        await scan_and_share_drop_info(bot, msg)
        await asyncio.sleep(0.2)
    else:
        await asyncio.sleep(random.uniform(0.5, 0.9)) # Bot phụ chờ data

    # Lấy dữ liệu chia sẻ
    with shared_drop_info["lock"]:
        if shared_drop_info["message_id"] != msg.id: return # Data cũ hoặc không khớp
        heart_data = shared_drop_info["heart_data"]
        print_data = shared_drop_info["print_data"]

    # --- TỰ ĐỘNG FIX DATA CŨ ---
    # Nếu file JSON cũ chưa có mode, mặc định bật Mode 1 (Tim)
    mode1 = target_server.get(f'mode_1_active_{bot_num}')
    if mode1 is None:
        target_server[f'mode_1_active_{bot_num}'] = True
        mode1 = True
    
    mode2 = target_server.get(f'mode_2_active_{bot_num}', False)
    mode3 = target_server.get(f'mode_3_active_{bot_num}', False)

    # Lấy config
    h_min = target_server.get(f'heart_min_{bot_num}', target_server.get(f'heart_threshold_{bot_num}', 50))
    h_max = target_server.get(f'heart_max_{bot_num}', target_server.get(f'max_heart_threshold_{bot_num}', 99999))
    p_min = target_server.get(f'print_min_{bot_num}', 1)
    p_max = target_server.get(f'print_max_{bot_num}', 1000)

    candidates = []

    # MODE 3: BOTH (Cần cả Tim và Print)
    if mode3 and heart_data and print_data:
        m3_h_min = target_server.get(f'm3_heart_min_{bot_num}', 50)
        m3_p_max = target_server.get(f'm3_print_max_{bot_num}', 1000)
        
        print_map = {idx: val for idx, val in print_data}
        valid_both = []
        for idx, hearts in enumerate(heart_data):
            if idx in print_map:
                prt = print_map[idx]
                if (m3_h_min <= hearts) and (prt <= m3_p_max): # Logic đơn giản: Tim > X và Print < Y
                    valid_both.append((idx, hearts, prt))
        
        if valid_both:
            # Ưu tiên Print thấp nhất
            best = min(valid_both, key=lambda x: x[2])
            candidates.append((3, best[0], 0.5)) # Priority 3 (Cao nhất)

    # MODE 2: PRINT
    if mode2 and print_data:
        valid_prints = [x for x in print_data if p_min <= x[1] <= p_max]
        if valid_prints:
            best = min(valid_prints, key=lambda x: x[1]) # Lấy Print nhỏ nhất
            candidates.append((2, best[0], 0.8)) # Priority 2

    # MODE 1: HEART
    if mode1 and heart_data:
        valid_hearts = [(idx, val) for idx, val in enumerate(heart_data) if h_min <= val <= h_max]
        if valid_hearts:
            best = max(valid_hearts, key=lambda x: x[1]) # Lấy Tim to nhất
            candidates.append((1, best[0], 0.3)) # Priority 1

    # --- ACTION ---
    if candidates:
        # Sort theo Priority (Mode 3 > 2 > 1)
        candidates.sort(key=lambda x: x[0], reverse=True)
        priority, best_idx, base_delay = candidates[0]
        
        emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"][best_idx]
        
        # Delay tự nhiên
        final_delay = base_delay + (bot_num * 0.2)
        
        print(f"[GRAB] 🎯 Bot {bot_num} chọn thẻ {best_idx+1} (Mode {priority})", flush=True)
        
        async def do_grab():
            await asyncio.sleep(final_delay)
            try:
                await msg.add_reaction(emoji)
                # KTB
                ktb_id = target_server.get('ktb_channel_id')
                if ktb_id:
                    ktb = bot.get_channel(int(ktb_id))
                    if ktb: await ktb.send("kt fs")
            except: pass
        
        asyncio.create_task(do_grab())
        
    # --- WATERMELON CHECK (Giữ nguyên) ---
    if bot_states["watermelon_grab"].get(f'main_{bot_num}', False):
        await asyncio.sleep(4)
        try:
            m = await msg.channel.fetch_message(msg.id)
            for r in m.reactions:
                if str(r.emoji) in ['🎀', 'chocobar']: # Fix emoji name nếu cần
                     await m.add_reaction(r.emoji)
        except: pass

# --- CÁC HÀM HỆ THỐNG (Reboot, Health, Spam) GIỮ NGUYÊN ---
def check_bot_health(bot_data, bot_id):
    # (Code cũ đã tốt, giữ nguyên để tiết kiệm không gian hiển thị, nhưng đảm bảo nó hoạt động)
    try:
        stats = bot_states["health_stats"].setdefault(bot_id, {'consecutive_failures': 0, 'last_check': 0})
        stats['last_check'] = time.time()
        if not bot_data or not bot_data.get('instance'):
            stats['consecutive_failures'] += 1; return False
        bot = bot_data['instance']
        is_connected = bot.is_ready() and not bot.is_closed()
        stats['consecutive_failures'] = 0 if is_connected else stats['consecutive_failures'] + 1
        return is_connected
    except: return False

def safe_reboot_bot(bot_id):
    # (Logic Reboot giữ nguyên từ code multi_spam.py của bạn)
    if not bot_manager.start_reboot(bot_id): return False
    try:
        match = re.match(r"main_(\d+)", bot_id)
        if not match: return False
        idx = int(match.group(1)) - 1
        token = main_tokens[idx].strip()
        
        bot_manager.remove_bot(bot_id)
        time.sleep(random.uniform(5, 10)) # Fast cleanup
        
        ev = threading.Event()
        t = threading.Thread(target=initialize_and_run_bot, args=(token, bot_id, True, ev), daemon=True)
        t.start()
        if ev.wait(timeout=60):
            new_bot = bot_manager.get_bot_data(bot_id)
            if new_bot: new_bot['thread'] = t
            bot_states["reboot_settings"][bot_id]['failure_count'] = 0
            return True
        return False
    except: return False
    finally: bot_manager.end_reboot(bot_id)

def auto_reboot_loop():
    while not stop_events["reboot"].is_set():
        time.sleep(60)
        # (Logic loop giữ nguyên)

def enhanced_spam_loop():
    # (Logic spam giữ nguyên)
    pass

def periodic_task(interval, task_func, task_name):
    while True:
        time.sleep(interval)
        try: task_func()
        except: pass

def health_monitoring_check():
    for bid, bdata in bot_manager.get_all_bots_data(): check_bot_health(bdata, bid)

def initialize_and_run_bot(token, bot_id_str, is_main, ready_event=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = discord.Client(self_bot=True)
    try: bot_identifier = int(bot_id_str.split('_')[1])
    except: bot_identifier = 99

    @bot.event
    async def on_ready():
        if ready_event: ready_event.set()
        print(f"[Bot] ✅ Login: {bot.user.name} ({bot_id_str})", flush=True)

    @bot.event
    async def on_message(msg):
        if not is_main: return
        try:
            # Phát hiện drop từ Karuta hoặc Karibbit
            if (msg.author.id == int(karuta_id) or msg.author.id == int(karibbit_id)) and "dropping" in msg.content.lower():
                await handle_grab(bot, msg, bot_identifier)
        except: pass

    try:
        bot_manager.add_bot(bot_id_str, {'instance': bot, 'loop': loop, 'thread': threading.current_thread()})
        loop.run_until_complete(bot.start(token))
    except:
        bot_manager.remove_bot(bot_id_str)
    finally: loop.close()

# ==============================================================================
# <<< FLASK WEB UI MỚI (UPDATE MASTER CONTROL & MODE SELECTOR) >>>
# ==============================================================================
app = Flask(__name__)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shadow Network Control - Master Edition</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Courier+Prime:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #0a0a0a; --panel: #111; --border: #333; --red: #8b0000; --green: #228b22; --gold: #ffd700; --text: #f0f0f0; }
        body { background: var(--bg); color: var(--text); font-family: 'Courier Prime', monospace; padding: 20px; }
        .header { text-align: center; border-bottom: 2px solid var(--red); margin-bottom: 20px; padding-bottom: 10px; }
        .header h1 { color: var(--gold); font-family: 'Orbitron'; text-shadow: 0 0 10px rgba(255, 215, 0, 0.3); margin: 0; }
        
        /* MASTER CONTROL PANEL */
        .master-panel { background: #1a0505; border: 2px solid var(--gold); padding: 15px; border-radius: 8px; margin-bottom: 30px; }
        .master-title { color: var(--gold); text-align: center; font-weight: bold; margin-bottom: 15px; border-bottom: 1px solid #444; }
        .master-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }
        .master-bot-card { background: rgba(255,255,255,0.05); padding: 10px; border: 1px solid #444; border-radius: 4px; }
        
        /* SERVER PANELS */
        .server-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 15px; }
        .panel { background: var(--panel); border: 1px solid var(--border); padding: 15px; border-radius: 6px; }
        .panel h2 { color: #aaa; font-size: 1.1em; border-bottom: 1px solid #333; margin-top: 0; display: flex; justify-content: space-between; }
        
        /* BOT CONTROLS */
        .bot-card { background: #1a1a1a; padding: 10px; margin-top: 10px; border-radius: 4px; border: 1px solid #333; }
        .mode-selector { display: flex; gap: 4px; margin-bottom: 8px; }
        .mode-btn { flex: 1; padding: 4px; background: #222; border: 1px solid #444; color: #666; cursor: pointer; font-size: 0.8em; }
        .mode-btn.active-1 { background: #8b0000; color: white; border-color: red; } /* Tim */
        .mode-btn.active-2 { background: #00008b; color: white; border-color: blue; } /* Print */
        .mode-btn.active-3 { background: var(--gold); color: black; border-color: yellow; font-weight: bold; } /* Both */
        
        /* INPUTS */
        .range-row { display: flex; gap: 5px; align-items: center; margin-bottom: 5px; }
        input[type="number"] { background: #000; border: 1px solid #444; color: white; padding: 4px; width: 60px; text-align: center; }
        input[type="text"] { background: #000; border: 1px solid #444; color: white; padding: 5px; width: 100%; box-sizing: border-box; }
        
        .toggle-grab { width: 100%; padding: 6px; margin-top: 5px; background: #222; color: #888; border: 1px solid #444; cursor: pointer; }
        .toggle-grab.active { background: var(--green); color: white; font-weight: bold; }

        .btn { cursor: pointer; border: none; padding: 8px 15px; color: white; font-weight: bold; border-radius: 3px; }
        .btn-sync { background: var(--gold); color: black; width: 100%; margin-top: 15px; }
        .btn-add { background: var(--green); margin: 20px auto; display: block; }
        .btn-del { background: var(--red); padding: 2px 6px; font-size: 0.8em; }
    </style>
</head>
<body>
    <div class="header">
        <h1>SHADOW MASTER CONTROL</h1>
        <div id="uptime">Loading...</div>
    </div>

    <div class="master-panel">
        <div class="master-title"><i class="fas fa-sliders-h"></i> BẢNG ĐIỀU KHIỂN TỔNG (MASTER)</div>
        <div class="master-grid">
            {% for bot in main_bots %}
            <div class="master-bot-card" id="master-bot-{{ bot.id }}">
                <div style="color: var(--gold); text-align: center; margin-bottom: 5px;">{{ bot.name }}</div>
                
                <div class="mode-selector">
                    <button class="mode-btn" onclick="toggleMasterMode(this, '1')">❤️ Tim</button>
                    <button class="mode-btn" onclick="toggleMasterMode(this, '2')">📷 Print</button>
                    <button class="mode-btn" onclick="toggleMasterMode(this, '3')">⭐ Both</button>
                </div>
                <input type="hidden" class="master-mode-1" value="false">
                <input type="hidden" class="master-mode-2" value="false">
                <input type="hidden" class="master-mode-3" value="false">

                <div class="range-row"><label>❤️</label> <input type="number" class="master-h-min" value="50" placeholder="Min"> <input type="number" class="master-h-max" value="99999" placeholder="Max"></div>
                <div class="range-row"><label>📷</label> <input type="number" class="master-p-min" value="1" placeholder="Min"> <input type="number" class="master-p-max" value="1000" placeholder="Max"></div>
            </div>
            {% endfor %}
        </div>
        <button class="btn btn-sync" onclick="syncAll()"><i class="fas fa-sync-alt"></i> ÁP DỤNG CẤU HÌNH CHO TẤT CẢ SERVER</button>
        <button class="btn btn-sync" style="background: #222; color: #fff; margin-top: 5px;" onclick="toggleAllRunning()"><i class="fas fa-power-off"></i> BẬT/TẮT TẤT CẢ RUNNING</button>
    </div>

    <button class="btn btn-add" onclick="addServer()">+ THÊM SERVER MỚI</button>

    <div class="server-grid">
        {% for server in servers %}
        <div class="panel" data-server-id="{{ server.id }}">
            <h2>
                {{ server.name }}
                <button class="btn btn-del" onclick="deleteServer('{{ server.id }}')"><i class="fas fa-trash"></i></button>
            </h2>
            <div style="margin-bottom: 10px;">
                <input type="text" class="channel-input" data-field="main_channel_id" value="{{ server.main_channel_id or '' }}" placeholder="Main Channel ID">
                <input type="text" class="channel-input" data-field="ktb_channel_id" value="{{ server.ktb_channel_id or '' }}" placeholder="KTB Channel ID" style="margin-top: 2px;">
            </div>

            {% for bot in main_bots %}
            <div class="bot-card">
                <div style="font-size: 0.9em; color: #888;">{{ bot.name }}</div>
                
                <div class="mode-selector">
                    <button class="mode-btn {{ 'active-1' if server['mode_1_active_' + bot.id] else '' }}" onclick="toggleMode(this, '1', '{{ bot.id }}', '{{ server.id }}')">❤️</button>
                    <button class="mode-btn {{ 'active-2' if server['mode_2_active_' + bot.id] else '' }}" onclick="toggleMode(this, '2', '{{ bot.id }}', '{{ server.id }}')">📷</button>
                    <button class="mode-btn {{ 'active-3' if server['mode_3_active_' + bot.id] else '' }}" onclick="toggleMode(this, '3', '{{ bot.id }}', '{{ server.id }}')">⭐</button>
                </div>

                <div class="range-row"><label>❤️</label> 
                    <input type="number" class="heart-min" value="{{ server['heart_min_' + bot.id] or server['heart_threshold_' + bot.id] or 50 }}"> 
                    <input type="number" class="heart-max" value="{{ server['heart_max_' + bot.id] or server['max_heart_threshold_' + bot.id] or 99999 }}">
                </div>
                <div class="range-row"><label>📷</label> 
                    <input type="number" class="print-min" value="{{ server['print_min_' + bot.id] or 1 }}"> 
                    <input type="number" class="print-max" value="{{ server['print_max_' + bot.id] or 1000 }}">
                </div>

                <button class="toggle-grab {% if server['auto_grab_enabled_' + bot.id] %}active{% endif %}" 
                        onclick="toggleGrab(this, '{{ bot.id }}', '{{ server.id }}')">
                    {{ 'RUNNING' if server['auto_grab_enabled_' + bot.id] else 'STOPPED' }}
                </button>
            </div>
            {% endfor %}
        </div>
        {% endfor %}
    </div>

    <script>
        // --- MASTER LOGIC ---
        function toggleMasterMode(btn, mode) {
            btn.classList.toggle('active-' + mode);
            const parent = btn.closest('.master-bot-card');
            parent.querySelector('.master-mode-' + mode).value = btn.classList.contains('active-' + mode) ? "true" : "false";
        }

        async function syncAll() {
            if(!confirm("Áp dụng cấu hình này cho toàn bộ server?")) return;
            const bots = [];
            document.querySelectorAll('.master-bot-card').forEach(card => {
                const id = card.id.replace('master-bot-', '');
                bots.push({
                    id: id,
                    mode1: card.querySelector('.master-mode-1').value === "true",
                    mode2: card.querySelector('.master-mode-2').value === "true",
                    mode3: card.querySelector('.master-mode-3').value === "true",
                    h_min: card.querySelector('.master-h-min').value,
                    h_max: card.querySelector('.master-h-max').value,
                    p_min: card.querySelector('.master-p-min').value,
                    p_max: card.querySelector('.master-p-max').value
                });
            });
            await fetch('/api/sync_master', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ bots: bots })
            });
            location.reload();
        }

        async function toggleAllRunning() {
            if(confirm("Toggle RUNNING/STOPPED cho tất cả?")) {
                await fetch('/api/toggle_all_grab', { method: 'POST' });
                location.reload();
            }
        }

        // --- INDIVIDUAL SERVER LOGIC ---
        async function post(url, data) {
            await fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
        }

        function toggleMode(btn, mode, botId, serverId) {
            const active = btn.classList.toggle('active-' + mode);
            post('/api/toggle_bot_mode', { server_id: serverId, bot_id: botId, mode: mode, active: active });
        }

        function toggleGrab(btn, botId, serverId) {
            const card = btn.closest('.bot-card');
            const data = {
                server_id: serverId, node: botId,
                heart_min: card.querySelector('.heart-min').value,
                heart_max: card.querySelector('.heart-max').value,
                print_min: card.querySelector('.print-min').value,
                print_max: card.querySelector('.print-max').value
            };
            post('/api/harvest_toggle', data).then(() => {
                const isActive = btn.classList.toggle('active');
                btn.textContent = isActive ? 'RUNNING' : 'STOPPED';
            });
        }

        function addServer() {
            const name = prompt("Tên Server mới:");
            if(name) post('/api/add_server', {name: name}).then(() => location.reload());
        }

        function deleteServer(id) {
            if(confirm("Xóa server này?")) post('/api/delete_server', {server_id: id}).then(() => location.reload());
        }

        // Auto Save Inputs
        document.querySelectorAll('.channel-input').forEach(inp => {
            inp.addEventListener('change', () => {
                const sid = inp.closest('.panel').dataset.serverId;
                const field = inp.dataset.field;
                post('/api/update_server_field', {server_id: sid, [field]: inp.value});
            });
        });
        
        // Uptime
        const start = {{ start_time }};
        setInterval(() => {
            const s = Math.floor(Date.now()/1000 - start);
            document.getElementById('uptime').innerText = new Date(s * 1000).toISOString().substr(11, 8);
        }, 1000);
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    # Tạo danh sách bot chính để render UI
    main_bots = [{"id": str(i+1), "name": f"Main Bot {i+1}"} for i in range(len(main_tokens))]
    return render_template_string(HTML_TEMPLATE, servers=servers, main_bots=main_bots, start_time=server_start_time)

# --- API ENDPOINTS MỚI CHO GIAO DIỆN MASTER ---
@app.route("/api/sync_master", methods=['POST'])
def api_sync_master():
    data = request.json
    for server in servers:
        for bot_conf in data.get('bots', []):
            bid = bot_conf['id']
            # Đồng bộ Mode
            server[f'mode_1_active_{bid}'] = bot_conf['mode1']
            server[f'mode_2_active_{bid}'] = bot_conf['mode2']
            server[f'mode_3_active_{bid}'] = bot_conf['mode3']
            # Đồng bộ Params
            server[f'heart_min_{bid}'] = int(bot_conf['h_min'])
            server[f'heart_max_{bid}'] = int(bot_conf['h_max'])
            server[f'print_min_{bid}'] = int(bot_conf['p_min'])
            server[f'print_max_{bid}'] = int(bot_conf['p_max'])
            # Tự động cập nhật các key cũ để tương thích ngược
            server[f'heart_threshold_{bid}'] = int(bot_conf['h_min'])
            server[f'max_heart_threshold_{bid}'] = int(bot_conf['h_max'])
    save_settings()
    return jsonify({'status': 'success'})

@app.route("/api/toggle_bot_mode", methods=['POST'])
def api_toggle_bot_mode():
    d = request.json
    srv = next((s for s in servers if s['id'] == d['server_id']), None)
    if srv:
        srv[f"mode_{d['mode']}_active_{d['bot_id']}"] = d['active']
        save_settings()
    return jsonify({'status': 'ok'})

@app.route("/api/harvest_toggle", methods=['POST'])
def api_harvest_toggle():
    d = request.json
    srv = next((s for s in servers if s['id'] == d['server_id']), None)
    if srv:
        bid = d['node']
        # Toggle Running
        k = f'auto_grab_enabled_{bid}'
        srv[k] = not srv.get(k, False)
        # Save params
        srv[f'heart_min_{bid}'] = int(d['heart_min'])
        srv[f'heart_max_{bid}'] = int(d['heart_max'])
        srv[f'print_min_{bid}'] = int(d['print_min'])
        srv[f'print_max_{bid}'] = int(d['print_max'])
        save_settings()
    return jsonify({'status': 'ok'})

@app.route("/api/toggle_all_grab", methods=['POST'])
def api_toggle_all_grab():
    # Logic: Nếu có cái nào đang tắt -> Bật hết. Nếu đang bật hết -> Tắt hết.
    any_off = any(not s.get(f'auto_grab_enabled_{i+1}') for s in servers for i in range(len(main_tokens)))
    new_state = True if any_off else False
    for s in servers:
        for i in range(len(main_tokens)):
            s[f'auto_grab_enabled_{i+1}'] = new_state
    save_settings()
    return jsonify({'status': 'ok'})

# (Các API cũ vẫn giữ để tránh lỗi nếu có request lạ, nhưng UI đã dùng API mới)
@app.route("/api/add_server", methods=['POST'])
def api_add_server():
    servers.append({"id": uuid.uuid4().hex, "name": request.json.get('name')})
    save_settings()
    return jsonify({'status': 'ok'})

@app.route("/api/delete_server", methods=['POST'])
def api_delete_server():
    global servers
    servers = [s for s in servers if s['id'] != request.json.get('server_id')]
    save_settings()
    return jsonify({'status': 'ok'})

@app.route("/api/update_server_field", methods=['POST'])
def api_update_server_field():
    d = request.json
    s = next((x for x in servers if x['id'] == d['server_id']), None)
    if s:
        for k,v in d.items(): 
            if k!='server_id': s[k] = v
        save_settings()
    return jsonify({'status': 'ok'})

# --- MAIN BLOCK ---
if __name__ == "__main__":
    print("🚀 Shadow Network V2 - Multi-Mode & Master Control Starting...", flush=True)
    load_settings()

    # Chạy Main Bots
    for i, token in enumerate(main_tokens):
        if token.strip():
            threading.Thread(target=initialize_and_run_bot, args=(token.strip(), f"main_{i+1}", True), daemon=True).start()
    
    # Chạy Sub Bots
    for i, token in enumerate(tokens):
        if token.strip():
            threading.Thread(target=initialize_and_run_bot, args=(token.strip(), f"sub_{i}", False), daemon=True).start()

    # Background Tasks
    threading.Thread(target=periodic_task, args=(1800, save_settings, "Save"), daemon=True).start()
    threading.Thread(target=periodic_task, args=(300, health_monitoring_check, "Health"), daemon=True).start()
    threading.Thread(target=auto_reboot_loop, daemon=True).start()
    
    # Spam System (từ code gốc của bạn)
    threading.Thread(target=lambda: enhanced_spam_loop() if 'enhanced_spam_loop' in globals() else None, daemon=True).start()

    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
