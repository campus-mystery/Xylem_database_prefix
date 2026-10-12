from flask import Flask, render_template_string, request, Response
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import json
import os

app = Flask(__name__)

# ============================================================
# CONFIGURATION (UNCHANGED)[span_0](start_span)[span_0](end_span)
# ============================================================

API_URL = "https://results.xylemlearning.com/wp-admin/admin-ajax.php"

EXAM_CLASS = "JEE"
EXAM_YEAR = "GIB-27SEP2026"

TOTAL_DIGITS = 10

WORKERS = 50
BATCH_SIZE = 1000
REQUEST_TIMEOUT = 15

# ============================================================
# HTML TEMPLATE (EMBEDDED)
# ============================================================

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Xylem Result Checker</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen flex items-center justify-center p-3 sm:p-4">
    <div class="max-w-xl w-full bg-slate-800 p-4 sm:p-6 rounded-xl shadow-lg border border-slate-700">
        <h1 class="text-xl sm:text-2xl font-bold mb-4 text-center text-cyan-400">Xylem Result Checker</h1>
        
        <form id="checker-form" class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-1 text-slate-300">Roll Prefix</label>
                <input type="text" id="roll_prefix" required placeholder="e.g. 2026" 
                    class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-base focus:outline-none focus:border-cyan-500">
            </div>
            <button type="submit" id="submit-btn" 
                class="w-full bg-cyan-600 hover:bg-cyan-500 font-semibold py-2.5 rounded-lg transition text-base">
                Start Checking
            </button>
        </form>

        <div id="progress-container" class="mt-6 hidden space-y-4">
            <div class="grid grid-cols-2 gap-2 sm:gap-4 text-xs sm:text-sm">
                <div class="bg-slate-900 p-2.5 sm:p-3 rounded-lg border border-slate-700">Total: <span id="lbl-total" class="font-bold">0</span></div>
                <div class="bg-slate-900 p-2.5 sm:p-3 rounded-lg border border-slate-700">Checked: <span id="lbl-checked" class="font-bold">0</span></div>
                <div class="bg-slate-900 p-2.5 sm:p-3 rounded-lg border border-slate-700 text-green-400">Found: <span id="lbl-found" class="font-bold">0</span></div>
                <div class="bg-slate-900 p-2.5 sm:p-3 rounded-lg border border-slate-700 text-red-400">Errors: <span id="lbl-errors" class="font-bold">0</span></div>
            </div>
            
            <div class="w-full bg-slate-900 rounded-full h-2.5 overflow-hidden">
                <div id="progress-bar" class="bg-cyan-500 h-2.5 w-0 transition-all duration-150"></div>
            </div>
            
            <div id="status-text" class="text-xs text-slate-400 font-mono truncate">Status: Idle</div>

            <!-- Found Roll Numbers Display Box -->
            <div class="space-y-1">
                <label class="block text-xs font-medium text-green-400">Found Roll Numbers (Live Terminal):</label>
                <div id="found-list" class="w-full h-36 bg-slate-900 border border-slate-700 rounded-lg p-3 overflow-y-auto font-mono text-xs sm:text-sm text-green-300 space-y-1">
                    <span class="text-slate-500 italic">No matches found yet...</span>
                </div>
            </div>
        </div>
    </div>

    <script>
        const form = document.getElementById('checker-form');
        const submitBtn = document.getElementById('submit-btn');
        const progressContainer = document.getElementById('progress-container');
        const progressBar = document.getElementById('progress-bar');
        const lblTotal = document.getElementById('lbl-total');
        const lblChecked = document.getElementById('lbl-checked');
        const lblFound = document.getElementById('lbl-found');
        const lblErrors = document.getElementById('lbl-errors');
        const statusText = document.getElementById('status-text');
        const foundList = document.getElementById('found-list');

        let eventSource = null;
        let foundCount = 0;

        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const prefix = document.getElementById('roll_prefix').value.trim();
            if (!prefix) return;

            submitBtn.disabled = true;
            submitBtn.classList.add('opacity-50', 'cursor-not-allowed');
            progressContainer.classList.remove('hidden');
            foundList.innerHTML = '<span class="text-slate-500 italic">Scanning...</span>';
            foundCount = 0;

            if (eventSource) eventSource.close();

            eventSource = new EventSource(`/run?roll_prefix=${encodeURIComponent(prefix)}`);

            eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === 'start') {
                    lblTotal.textContent = data.total;
                    statusText.textContent = `Scanning range: ${data.start_roll} to ${data.end_roll}`;
                } else if (data.type === 'progress') {
                    lblChecked.textContent = data.checked;
                    lblFound.textContent = data.found;
                    lblErrors.textContent = data.errors;
                    const percent = (data.checked / data.total) * 100;
                    progressBar.style.width = `${percent}%`;
                    statusText.textContent = `Checking roll: ${data.roll}`;

                    if (data.status === 'found') {
                        if (foundCount === 0) foundList.innerHTML = '';
                        foundCount++;
                        const div = document.createElement('div');
                        div.textContent = `✓ ${data.roll}`;
                        foundList.appendChild(div);
                        foundList.scrollTop = foundList.scrollHeight;
                    }
                } else if (data.type === 'finish') {
                    statusText.textContent = `Completed in ${data.time}s`;
                    eventSource.close();
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
                } else if (data.type === 'error') {
                    statusText.textContent = `Error: ${data.message}`;
                    eventSource.close();
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
                }
            };

            eventSource.onerror = () => {
                statusText.textContent = 'Connection closed or finished.';
                eventSource.close();
                submitBtn.disabled = false;
                submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            };
        });
    </script>
</body>
</html>
"""

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
    return render_template_string(HTML_CONTENT)


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

            yield f"data: {json.dumps({'type': 'start', 'total': total, 'start_roll': start_roll, 'end_roll': end_roll - 1, 'prefix': prefix_str})}\n\n"

            start_time = time.time()
            checked = 0
            found = 0
            not_found = 0
            errors = 0
            blocked = 0

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
                        elif status == "not_found":
                            not_found += 1
                        elif status == "blocked":
                            blocked += 1
                        else:
                            errors += 1

                        yield f"data: {json.dumps({'type': 'progress', 'checked': checked, 'total': total, 'found': found, 'not_found': not_found, 'errors': errors, 'blocked': blocked, 'roll': roll, 'status': status})}\n\n"

            elapsed = time.time() - start_time
            yield f"data: {json.dumps({'type': 'finish', 'checked': checked, 'found': found, 'not_found': not_found, 'errors': errors, 'blocked': blocked, 'time': round(elapsed, 2)})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
