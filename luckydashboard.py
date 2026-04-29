import asyncio
import websockets
import re
import signal
import sys
import time
import requests
from datetime import datetime, timezone
import glob, os, gzip,json

from flask import Flask, jsonify, request, render_template, Response
import threading

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

DEFAULT_MINER_DATA = {
    'best_session': 0.0,
    'shares': 0,
    'current_shares': 0,
    'last_diff' : 0.0,
    'best_diff': 0.0,
    'pool_diff': 0.0,
    'current_pool_diff_session': 0.0,
    'current_session': 0
}
DEFAULT_MINER_INFO = {
    'uptimeSeconds': 0,
    'stratumURL': 'bitcoin.viabtc.io',
    'stratumPort': '3333',
    'power': 0.0,
    'temp': 0,
    'hashRate': 0.0,
    'sharesAccepted': 0,
    'bestDiff': 0.0,
}

MINERS = [
    {
        "name": "Lucky Miner LV06",
        "ip": "192.168.1.80",
        "id": 0,
        "enabled": False,
        "miner_data": {
            **DEFAULT_MINER_DATA
        },
        "miner_info": {
            **DEFAULT_MINER_INFO
        }
    },
    {
        "name": "BitAxe-1 Gamma 601",
        "ip": "192.168.1.108",
        "id": 1,
        "enabled": True,
        "miner_data": {
            **DEFAULT_MINER_DATA
        },
        "miner_info": {
            **DEFAULT_MINER_INFO
        }
    },
    {
        "name": "BitAxe-2 Gamma 601",
        "ip": "192.168.1.109",
        "id": 2,
        "enabled": True,
        "miner_data": {
            **DEFAULT_MINER_DATA
        },
        "miner_info": {
            **DEFAULT_MINER_INFO
        }
    }
]



def run_flask(network=True):
    if network:
        app.run(host="0.0.0.0", port=8081)
    else:
        app.run(host="127.0.0.1", port=8081)

@app.route("/")
def index():
    return render_template("index.html")

initialized = False
current_file = None
last_position = 0
cached_data = []

def iso_to_unix(ts_str):
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except AttributeError:
        # python 3.6 or lower
        dt = datetime.strptime(ts_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)  
    return int(dt.timestamp())


def get_all_logs():
    files = glob.glob("luckyminer.*.log")
    return sorted(files, key=os.path.getmtime)

def process_line(line: str):
    if not line:
        print("Empty line, skipping...")
        return None

    try:
        parts = line.strip().split()
        if not parts:
            raise ValueError
        if len(parts) == 3:
            ts, miner_id, value = parts
        elif len(parts) == 2:
            ts, value = parts
            miner_id = 0
        else:
            raise ValueError

        return {
            "t": iso_to_unix(ts),
            "m": int(miner_id),
            "d": float(value)
        }
    except ValueError as e:
        print(e)
        print(f"Invalid line: {line}")
        return None


def load_all_data():
    global cached_data, current_file, last_position

    files = get_all_logs()
    data = []

    for file in files:
        with open(file) as f:
            for line in f:
                item = process_line(line)
                if item:
                    data.append(item)

    if files:
        current_file = files[-1]

        with open(current_file) as f:
            f.seek(0, os.SEEK_END)
            last_position = f.tell()

    print(f"Loaded {len(data)} shares!")
    return data


def update_incremental():
    global current_file, last_position, cached_data

    files = get_all_logs()
    if not files:
        return cached_data

    latest_file = files[-1]

    # 📁 Caso 1: sigue siendo el mismo fichero
    if latest_file == current_file:
        with open(current_file) as f:
            f.seek(last_position)
            new_lines = f.readlines()
            last_position = f.tell()

    # 📁 Caso 2: fichero nuevo (rotación)
    else:
        new_lines = []

        # leer lo que faltaba del fichero anterior
        if current_file:
            with open(current_file) as f:
                f.seek(last_position)
                new_lines += f.readlines()

        # leer nuevo fichero entero
        with open(latest_file) as f:
            new_lines += f.readlines()
            last_position = f.tell()

        current_file = latest_file

    # procesar nuevas líneas
    for line in new_lines:
        item = process_line(line)
        if item:
            cached_data.append(item)

    return cached_data


def get_history(add_miner):
    global initialized, cached_data

    since_ts = request.args.get("t", type=int)
    if not initialized:
        cached_data = load_all_data()
        initialized = True
    else:
        update_incremental()

    # limitar para no saturar frontend
    #return jsonify(cached_data[-5000:])

    compact = []
    if since_ts is None:
        compact = cached_data
    else:
        for item in reversed(cached_data):
            if item["t"] <= since_ts:
                break
            if add_miner:
                compact.append({
                    "t": item["t"],
                    "m": item["m"],
                    "d": item["d"]
                })
            else:
                compact.append({
                    "t": item["t"],
                    "d": item["d"]
                })
        compact.reverse()

    raw = json.dumps(compact, separators=(",", ":")).encode("utf-8")

    accept_encoding = request.headers.get("Accept-Encoding", "")
    if "gzip" in accept_encoding.lower():
        compressed = gzip.compress(raw, compresslevel=5)
        response = Response(compressed, mimetype="application/json")
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(compressed))
    else:
        response = Response(raw, mimetype="application/json")
        response.headers["Content-Length"] = str(len(raw))

    response.headers["Vary"] = "Accept-Encoding"
    return response

@app.route("/history")
def history():
    return get_history(add_miner=False)
@app.route("/v2/history")
def v2_history():
    return get_history(add_miner=True)

def data_get_miner(miner_item):
    miner_data = miner_item['miner_data']
    miner_info = miner_item['miner_info']

    hashrate = calculate_hashrate(miner_data['current_shares'],
                                    miner_data['pool_diff'],
                                    miner_data['current_pool_diff_session'])
    ret = {
        'Miner id': miner_item['id'],
        'Miner name': miner_item['name'],
        'Timestamp': miner_info.get('timestamp', 0),
        'Uptime': human_readable_timediff(miner_info['uptimeSeconds']),
        'Pool': f"{miner_info['stratumURL']}:{miner_info['stratumPort']}",
        'Power': f"{human_readable_diff(miner_info['power'])}w",
        'Temp': f"{miner_info['temp']}C",
        'Reported Hashrate': human_readable_hashrate(miner_info['hashRate']*10**9),
        'Total shares': miner_info['sharesAccepted'],
        'Best diff ever': miner_info['bestDiff'],
        'Best diff': human_readable_diff(miner_data['best_diff']),
        'Last diff': human_readable_diff(miner_data['last_diff']),
        'Pool diff': human_readable_diff(miner_data['pool_diff']),
        'Shares': miner_data['shares'],
        'Hashrate': human_readable_hashrate(hashrate),
        'Current session': human_readable_timediff(miner_data['current_session'])
    }

    return ret

@app.route("/data", methods=["GET"])
def data_get():
    return jsonify(data_get_miner(MINERS[0]))

@app.route("/v2/data", methods=["GET"])
def v2_data_get():
    return jsonify({ "items": [ data_get_miner(miner) for miner in MINERS if miner['enabled']]})


def sigint_signal(sig, frame):
    print("")
    print(f"{datetime.now()}: Ctrl+C, exiting...")
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_signal)

current_diff_pattern = re.compile(r"asic_result: Nonce difficulty (\d+\.?\d*) of (\d+\.?\d*)")
current_diff_pattern2 = re.compile(r"asic_result:.*?diff\s+(\d+\.?\d*)\s+of\s+(\d+\.?\d*)")

def print_data(miner_data, miner_info):
    # data1 = f"Wifi status: {miner_info['wifiStatus']}"
    data1 = f"Uptime: {human_readable_timediff(miner_info['uptimeSeconds'])}"
    data1 += f"    Pool: {miner_info['stratumURL']}:{miner_info['stratumPort']}"
    data1 += f"    Power: {human_readable_diff(miner_info['power'])}w"
    data1 += f"    Temp: {miner_info['temp']}C"
    data1 += f"    Hashrate: {human_readable_hashrate(miner_info['hashRate']*10**9)}"
    data1 += f"    Total shares: {miner_info['sharesAccepted']}"
    data1 += f"    Best diff ever: {miner_info['bestDiff']}                       \n"

    hashrate = calculate_hashrate(miner_data['current_shares'], miner_data['pool_diff'], miner_data['current_pool_diff_session'])
    data2 = f"Best diff: {human_readable_diff(miner_data['best_diff'])}"
    data2 += f"    Last diff: {human_readable_diff(miner_data['last_diff'])}"
    data2 += f"    Pool diff: {human_readable_diff(miner_data['pool_diff'])}"
    data2 += f"    Shares: {miner_data['shares']}"
    data2 += f"    Hashrate: {human_readable_hashrate(hashrate)}"
    data2 += f"    Current session: {human_readable_timediff(miner_data['current_session'])}                       \n"

    # sys.stdout.write("\033[F\033[F")
    # sys.stdout.write("\033[K\033[K")
    sys.stdout.write(data1)
    sys.stdout.write(data2)
    sys.stdout.flush()

def human_readable_hashrate(hashrate):
    '''Returns a human readable representation of hashrate.'''

    if hashrate < 1000:
        return '%.2f H/s' % hashrate
    if hashrate < 1000000:
        return '%.2f kH/s' % (hashrate / 1000)
    if hashrate < 1000000000:
        return '%.2f MH/s' % (hashrate / 1000000)

    return '%.2f GH/s' % (hashrate / 1000000000)

def human_readable_diff(diff):
    '''Returns a human readable representation of hashrate.'''

    if diff < 1000:
        return '%.2f' % diff
    if diff < 1000000:
        return '%.2fK' % (diff / 1000)
    if diff < 1000000000:
        return '%.2fM' % (diff / 1000000)

    return '%.2fG' % (diff / 1000000000)

def human_readable_timediff(secs):
    hours = int(secs // 3600)
    mins = int((secs % 3600) // 60)
    secs = int(secs % 60)

    return f"{hours:02d}h {mins:02d}m {secs:02d}s"


def update_session(start_time, start_time_change_pool_diff, best_session) -> dict:
    end_time = time.time()
    if end_time - start_time > best_session:
        best_session = end_time - start_time

    return {
        'current_session': end_time - start_time,
        'current_pool_diff_session': end_time - start_time_change_pool_diff,
        'best_session': best_session
    }
def calculate_hashrate(shares, pool_diff, time_t):
    # calculate hashrate for current pool_diff in one second:
    # print(f"\n\n\nshares: {shares}, pool_diff: {pool_diff}, time: {time_t}")
    if time_t > 0:
        return pool_diff * 2**32 * shares / time_t
    else:
        return 0.0

def update_miner_info(url: str) -> dict:
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
    except Exception:
        return {**DEFAULT_MINER_INFO}

async def listen_miner(miner, queue):
    miner_id = miner['id']
    miner_ip = miner['ip']
    miner_name = miner['name']
    url_websocket = f"ws://{miner_ip}/api/ws"
    url_info =f"http://{miner_ip}/api/system/info"

    start_time = time.time()
    reconnect_delay = 2
    reconnect_delay_max = 30

    miner['miner_info'] = {**update_miner_info(url_info), 'timestamp': int(start_time)}
    miner_info = miner['miner_info']
    while True:
        miner['miner_data'] = { **miner['miner_data'],
            'current_session': 0.0,
            'current_shares': 0,
            'pool_diff': 1000.0,
            'current_pool_diff_session': 0.0
        }
        miner_data = miner['miner_data']
        try:
            print(f"[{utc_now()}] [{miner_name} ({miner_id})] Conectando a {url_websocket}...")
            async with websockets.connect(
                url_websocket,
                ping_interval=15,
                ping_timeout=10,
                open_timeout=10,
                close_timeout=5,
                max_size=2**20,
            ) as websocket:
                print(f"[{utc_now()}] [{miner_name} ({miner_id})] Conectado")
                reconnect_delay = 2
                miner_data['start_time_change_pool_diff'] = time.time()
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=60)
                    except asyncio.TimeoutError:
                        print(f"[{utc_now()}] [{miner_name} ({miner_id})] 60s sin mensajes -> forzando reconexión")
                        break
                    miner_info['timestamp'] = int(time.time())
                    found_diff = current_diff_pattern.search(message)
                    if not found_diff:
                        found_diff = current_diff_pattern2.search(message)
                    if found_diff:
                        miner_data['last_diff'] = float(found_diff.group(1))
                        if miner_data['last_diff'] > miner_data['best_diff']:
                            miner_data['best_diff'] = miner_data['last_diff']
                        if float(found_diff.group(2)) != miner_data['pool_diff']:
                            miner_data['pool_diff'] = float(found_diff.group(2))
                            miner_data['current_shares'] = 0
                            miner_data['start_time_change_pool_diff'] = time.time()
                        if miner_data['last_diff'] > miner_data['pool_diff']:
                            miner_data['shares'] += 1
                            miner_data['current_shares'] += 1

                            miner_info = miner['miner_info'] = {**miner_info, **update_miner_info(url_info), "timestamp": miner_info['timestamp']}

                        if miner_data['last_diff'] >= 10000:
                            # dt = datetime.fromtimestamp(time.time(), tz=timezone.utc)
                            # lucky_log.write(f"{dt.strftime('%Y-%m-%dT%H:%M:%SZ')} {data['last_diff']}\n")
                            # lucky_log.flush()
                            await queue.put((miner_info['timestamp'], miner_id, miner_data['last_diff']))

                    miner_data = miner['miner_data'] = { **miner_data, **update_session(start_time, miner_data['start_time_change_pool_diff'], miner_data['best_session'])}
                    print_data(miner_data, miner_info)

        except websockets.ConnectionClosedOK as e:
            print(f"[{utc_now()}] [{miner_name} ({miner_id})] Conexión cerrada normalmente: code={e.code} reason={e.reason}")

        except websockets.ConnectionClosedError as e:
            print(f"[{utc_now()}] [{miner_name} ({miner_id})] Conexión cerrada con error: code={e.code} reason={e.reason}")

        except OSError as e:
            print(f"[{utc_now()}] [{miner_name} ({miner_id})] Error de red / socket: {e}")

        except asyncio.TimeoutError:
            print(f"[{utc_now()}] [{miner_name} ({miner_id})] Timeout general de conexión")

        except Exception as e:
            print(f"[{utc_now()}] [{miner_name} ({miner_id})] Error inesperado: {type(e).__name__}: {e}")

        print(f"[{utc_now()}] [{miner_name} ({miner_id})] Reintentando en {reconnect_delay}s...")
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, reconnect_delay_max)


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def utc(timestamp):
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

async def writer_task(queue):
    with open(f"luckyminer.{time.time()}.log", 'w', buffering=1) as miner_log:
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                break

            try:
                timestamp, miner_id, difficulty = item
                miner_log.write(f"{utc(timestamp)} {miner_id} {difficulty}\n")
                miner_log.flush()
            except Exception as e:
                print(f"[{utc_now()}] [writer] Error escribiendo log: {e}")
            finally:
                queue.task_done()


async def main():
    queue = asyncio.Queue()

    writer = asyncio.create_task(writer_task(queue))
    listeners = [
        asyncio.create_task(listen_miner(miner, queue))
        for miner in MINERS if miner['enabled']
    ]

    await asyncio.gather(writer, *listeners)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Ctrl+C, exiting...")


    # asyncio.get_event_loop().run_until_complete(get_logs())
    # threading.Thread(target=run_flask).start()

    # print(load_all_data())
    # run_flask(network = False)
