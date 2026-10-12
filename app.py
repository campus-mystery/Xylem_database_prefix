from flask import Flask, render_template, request, Response
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
import time
import json
import os

app = Flask(__name__, template_folder='.')

# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://results.xylemlearning.com/wp-admin/admin-ajax.php"

EXAM_CLASS = "JEE"
EXAM_YEAR = "GIB-27SEP2026"

TOTAL_DIGITS = 10

# Updated to use a relative path compatible with Render's Linux environment
OUTPUT_FILE = Path("results-95.txt")

WORKERS = 50
BATCH_SIZE = 1000
REQUEST_TIMEOUT = 15

# ============================================================
# THREAD-LOCAL HTTP SESSION
# ============================================================

thread_local = threading.local()

def get_session():
    if not hasattr(thread_local, "session"):
        session = requests.Session()
        session.headers.update({
            "User-Agent": "AuthorizedResultClient/1.0",
            "Accept": "text/html,application/json,*/*",
        })
        thread_local.session = session
    return thread_local.session


# ============================================================
# CHECK ONE ROLL NUMBER
# ============================================================

def check_roll(roll_number):
    session = get_session()

    data = {
        "action": "jsrmsp_student_result_view",
        "examclass": EXAM_CLASS,
        "examyear": EXAM_YEAR,
        "examroll": str(roll_number),
    }

    try:
        response = session.post(
            API_URL,
            data=data,
            timeout=REQUEST_TIMEOUT
        )

        status = response.status_code
        text = response.text.strip()

        if status != 200:
            return {
                "roll": roll_number,
                "status": "error",
                "message": f"HTTP {status}"
            }

        if not text:
            return {
                "roll": roll_number,
                "status": "error",
                "message": "Empty response"
            }

        if (
            "Checking your browser before redirecting" in text
            or "anubis_challenge" in text
            or "/.within.website/" in text
        ):
            return {
                "roll": roll_number,
                "status": "blocked",
                "message": "Backend request was blocked by Anubis"
            }

        if "Result not found or not published yet" in text:
            return {
                "roll": roll_number,
                "status": "not_found",
                "message": None
            }

        return {
            "roll": roll_number,
            "status": "found",
            "message": None
        }

    except requests.Timeout:
        return {
            "roll": roll_number,
            "status": "error",
            "message": "Request timeout"
        }

    except requests.RequestException as e:
        return {
            "roll": roll_number,
            "status": "error",
            "message": str(e)
        }


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/run', methods=['GET', 'POST'])
def run_checker():
    roll_prefix = request.form.get('roll_prefix') or request.args.get('roll_prefix', '')
    roll_prefix = roll_prefix.strip()

    def generate():
        try:
            prefix_str = str(roll_prefix)
            remaining_digits = TOTAL_DIGITS - len(prefix_str)

            if remaining_digits < 0:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Prefix length cannot exceed 10 digits.'})}\n\n"
                return

            start_roll = int(prefix_str + "0" * remaining_digits)
            end_roll = int(prefix_str + "9" * remaining_digits) + 1
            total = end_roll - start_roll

            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

            yield f"data: {json.dumps({'type': 'start', 'total': total, 'start_roll': start_roll, 'end_roll': end_roll - 1, 'prefix': prefix_str})}\n\n"

            start_time = time.time()
            checked = 0
            found = 0
            not_found = 0
            errors = 0
            blocked = 0

            with OUTPUT_FILE.open("w", encoding="utf-8") as output:
                for batch_start in range(start_roll, end_roll, BATCH_SIZE):
                    batch_end = min(batch_start + BATCH_SIZE, end_roll)

                    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                        futures = [
                            executor.submit(check_roll, roll)
                            for roll in range(batch_start, batch_end)
                        ]

                        for future in as_completed(futures):
                            try:
                                result = future.result()
                            except Exception as e:
                                checked += 1
                                errors += 1
                                continue

                            checked += 1
                            roll = result["roll"]
                            status = result["status"]

                            if status == "found":
                                found += 1
                                output.write(f"{roll}\n")
                                output.flush()
                            elif status == "not_found":
                                not_found += 1
                            elif status == "blocked":
                                blocked += 1
                            else:
                                errors += 1

                            yield f"data: {json.dumps({'type': 'progress', 'checked': checked, 'total': total, 'found': found, 'not_found': not_found, 'errors': errors, 'blocked': blocked, 'roll': roll, 'status': status})}\n\n"

            elapsed = time.time() - start_time
            yield f"data: {json.dumps({'type': 'finish', 'checked': checked, 'found': found, 'not_found': not_found, 'errors': errors, 'blocked': blocked, 'time': round(elapsed, 2), 'output': str(OUTPUT_FILE)})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
