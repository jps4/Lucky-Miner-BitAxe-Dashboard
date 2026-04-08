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

ip = "192.168.1.80"
url_websocket = f"ws://{ip}/api/ws"
lucky_info_url =f"http://{ip}/api/system/info"
data = {
    'best_diff': 0.0,
    'best_session': 0.0,
    'shares': 0,
    'last_diff' : 0.0,
    'best_diff': 0.0,
    'pool_diff': 0.0
}
lucky_info = {}


def run_flask():
   app.run(host="0.0.0.0", port=8080)
   #app.run(host="127.0.0.1", port=8081)

@app.route("/")
def index():
    return render_template("index.html")

initialized = False
current_file = None
last_position = 0
cached_data = []

def iso_to_unix(ts_str):
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    return int(dt.timestamp())


def get_all_logs():
    files = glob.glob("luckyminer.*.log")
    return sorted(files, key=os.path.getmtime)


def load_all_data():
    global cached_data, current_file, last_position

    files = get_all_logs()
    data = []

    for file in files:
        with open(file) as f:
            for line in f:
                try:
                    ts, value = line.strip().split()
                    data.append({
                        "t": iso_to_unix(ts),
                        "d": float(value)
                    })
                except ValueError:
                    pass

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
        try:
            ts, value = line.strip().split()
            cached_data.append({
                "t": iso_to_unix(ts),
                "d": float(value)
            })
        except:
            continue

    return cached_data


@app.route("/history")
def history():
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
            compact.append({"t": item["t"], "d": item["d"]})
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

    raw = json.dumps(cached_data).encode("utf-8")
    gzipped = gzip.compress(raw)

    response = Response(gzipped, mimetype="application/json")
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(gzipped))
    response.headers["Vary"] = "Accept-Encoding"
    return response


@app.route("/data", methods=["GET"])
def data_get():
    global data, lucky_info

    hashrate = calculate_hashrate(data['current_shares'], data['pool_diff'], data['current_pool_diff_session'])
    ret = {
        'Timestamp': int(time.time()),
        'Uptime': human_readable_timediff(lucky_info['uptimeSeconds']),
        'Pool': f"{lucky_info['stratumURL']}:{lucky_info['stratumPort']}",
        'Power': f"{human_readable_diff(lucky_info['power'])}w",
        'Temp': f"{lucky_info['temp']}C",
        'Reported Hashrate': human_readable_hashrate(lucky_info['hashRate']*10**9),
        'Total shares': lucky_info['sharesAccepted'],
        'Best diff ever': lucky_info['bestDiff'],
        'Best diff': human_readable_diff(data['best_diff']),
        'Last diff': human_readable_diff(data['last_diff']),
        'Pool diff': human_readable_diff(data['pool_diff']),
        'Shares': data['shares'],
        'Hashrate': human_readable_hashrate(hashrate),
        'Current session': human_readable_timediff(data['current_session'])
    }

    return jsonify(ret)


def sigint_signal(sig, frame):
    print("")
    print(f"{datetime.now()}: Ctrl+C, exiting...")
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_signal)

current_diff_pattern = re.compile(r"asic_result: Nonce difficulty (\d+\.?\d*) of (\d+\.?\d*)")

def print_data(data, lucky_info):
    # data1 = f"Wifi status: {lucky_info['wifiStatus']}"
    data1 = f"Uptime: {human_readable_timediff(lucky_info['uptimeSeconds'])}"
    data1 += f"    Pool: {lucky_info['stratumURL']}:{lucky_info['stratumPort']}"
    data1 += f"    Power: {human_readable_diff(lucky_info['power'])}w"
    data1 += f"    Temp: {lucky_info['temp']}C"
    data1 += f"    Hashrate: {human_readable_hashrate(lucky_info['hashRate']*10**9)}"
    data1 += f"    Total shares: {lucky_info['sharesAccepted']}"
    data1 += f"    Best diff ever: {lucky_info['bestDiff']}                       \n"

    hashrate = calculate_hashrate(data['current_shares'], data['pool_diff'], data['current_pool_diff_session'])
    data2 = f"Best diff: {human_readable_diff(data['best_diff'])}"
    data2 += f"    Last diff: {human_readable_diff(data['last_diff'])}"
    data2 += f"    Pool diff: {human_readable_diff(data['pool_diff'])}"
    data2 += f"    Shares: {data['shares']}"
    data2 += f"    Hashrate: {human_readable_hashrate(hashrate)}"
    data2 += f"    Current session: {human_readable_timediff(data['current_session'])}                       \n"

    sys.stdout.write("\033[F\033[F")
    sys.stdout.write("\033[K\033[K")
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

def update_lucky_info(url: str) -> dict:
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        return {}

async def get_logs():
    global data, lucky_info
    lucky_info = update_lucky_info(lucky_info_url)
    start_time = time.time()

    with open(f"luckyminer.{time.time()}.log", 'w') as lucky_log:
        while True:
            data = { **data,
                'current_session': 0.0,
                'current_shares': 0,
                'pool_diff': 1000.0,
                'current_pool_diff_session': 0.0
            }

            print("")
            print("")

            try:
                async with websockets.connect(url_websocket) as websocket:
                    # print(f"Conectado al WebSocket en {url_websocket}")
                    
                    start_time_change_pool_diff = time.time()
                    try:
                        while True:
                            message = await websocket.recv()
                            #lucky_log.write(message)
                            found_diff = current_diff_pattern.search(message)
                            if found_diff:
                                data['last_diff'] = float(found_diff.group(1))
                                if data['last_diff'] > data['best_diff']:
                                    data['best_diff'] = data['last_diff']
                                if float(found_diff.group(2)) != data['pool_diff']:
                                    data['pool_diff'] = float(found_diff.group(2))
                                    data['current_shares'] = 0
                                    start_time_change_pool_diff = time.time()
                                if data['last_diff'] > data['pool_diff']:
                                    data['shares'] += 1
                                    data['current_shares'] += 1

                                    lucky_info = {**lucky_info, **update_lucky_info(lucky_info_url)}

                                if data['last_diff'] >= 10000:
                                    dt = datetime.fromtimestamp(time.time(), tz=timezone.utc)
                                    lucky_log.write(f"{dt.strftime('%Y-%m-%dT%H:%M:%SZ')} {data['last_diff']}\n")
                                    lucky_log.flush()

                            data = { **data, **update_session(start_time, start_time_change_pool_diff, data['best_session'])}
                            print_data(data, lucky_info)
                    except KeyboardInterrupt:
                        await websocket.close()
                        raise
            except websockets.ConnectionClosed as e:
                print("websockets.ConnectionClosed exception")
            except KeyboardInterrupt:
                print("Ctrl+C, exiting...")
            except Exception as e:
                print(e)



if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.get_event_loop().run_until_complete(get_logs())

#    threading.Thread(target=run_flask).start()


