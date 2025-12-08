import os
import csv
import smtplib
import re
import google.generativeai as genai
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, request, render_template, jsonify, send_file, Response, make_response
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client

# --- CONFIGURATION ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'any')

# Get the public URL for Twilio callbacks (must be HTTPS)
# For Render: use RENDER_EXTERNAL_URL
# For Replit: use REPLIT_DEV_DOMAIN
# You can also set BASE_URL manually as an environment variable
BASE_URL = os.environ.get('BASE_URL') or os.environ.get('RENDER_EXTERNAL_URL') or os.environ.get('REPLIT_DEV_DOMAIN')
if BASE_URL and not BASE_URL.startswith('http'):
    BASE_URL = f"https://{BASE_URL}"
print(f"Base URL for callbacks: {BASE_URL}")

# Email Mapping
EMAILS = {
    "supervisor": "rishanthpatkar@gmail.com",
    "analyst": "mathematicsacademy007@gmail.com",
    "admin": "varunmax9989@gmail.com"
}

DB_FILE = "jalscan_data.csv"

# Server-side session storage (keyed by CallSid)
call_sessions = {}
call_context = {}

# Configure Gemini (check both possible env var names)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        print("Gemini API configured successfully")
    except Exception as e:
        print(f"Gemini Error: {e}")

# Ensure CSV exists
if not os.path.exists(DB_FILE):
    with open(DB_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Time", "Role", "River Name", "River ID", "Water Level", "Submitted By", "AI Status"])

# --- HELPER FUNCTIONS ---
def get_call_session(call_sid):
    """Get or create a session for this call"""
    if call_sid not in call_sessions:
        call_sessions[call_sid] = {'step': 'welcome'}
    return call_sessions[call_sid]

def send_email(to_email, subject, body, attachment_path=None):
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_password = os.environ.get('GMAIL_PASSWORD')

    if not gmail_user or not gmail_password:
        print(f"Email failed: Missing credentials (user: {bool(gmail_user)}, pass: {bool(gmail_password)})")
        return False

    msg = MIMEMultipart()
    msg['From'] = gmail_user
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "r") as f:
            attachment = MIMEText(f.read())
        attachment.add_header('Content-Disposition', 'attachment', filename="report.csv")
        msg.attach(attachment)

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()
        print(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def speak(response, text):
    response.say(text, voice='Polly.Joanna-Neural')

# --- JALVISION ROUTE ---
@app.route('/analyze_image', methods=['POST'])
def analyze_image():
    if not GEMINI_KEY: return jsonify({"error": "Gemini API Key missing"})
    try:
        if 'image' not in request.files: return jsonify({"error": "No image"})
        file = request.files['image']
        model = genai.GenerativeModel('gemini-1.5-flash-001')
        image_data = {"mime_type": "image/jpeg", "data": file.read()}
        prompt = """
        You are 'JalScan AI'. Analyze this LIVE CAPTURE.
        1. TAMPER CHECK: Is this a real river/water photo? 
        2. CONFIDENCE: Score 0-100.
        3. LEVEL: Estimate (Low/Normal/High/Flood).
        4. SUMMARY: 1 short sentence describing the scene.
        Format strictly as JSON: {"status": "Verified" or "Tampered", "confidence": 95, "level": "...", "summary": "..."}
        """
        response = model.generate_content([prompt, image_data])
        text = response.text.replace("```json", "").replace("```", "").strip()
        return text
    except Exception as e: return jsonify({"error": str(e)})

# --- CALL ROUTES ---
@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('index.html')

# --- LIVE CSV DATA ROUTES ---
@app.route('/data', methods=['GET'])
def download_csv():
    """Download the CSV file directly"""
    if os.path.exists(DB_FILE):
        response = make_response(send_file(DB_FILE, as_attachment=True, download_name='jalscan_data.csv'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    return "No data available", 404

@app.route('/data/live', methods=['GET'])
def view_csv():
    """View live CSV data as HTML table - auto-refreshes every 10 seconds"""
    if not os.path.exists(DB_FILE):
        return "No data available", 404
    
    with open(DB_FILE, 'r') as f:
        reader = csv.reader(f)
        rows = list(reader)
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>JalScan Live Data</title>
        <meta http-equiv="refresh" content="10">
        <style>
            body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0a192f; color: #ccd6f6; padding: 20px; }
            h1 { color: #64ffda; text-align: center; }
            .info { text-align: center; color: #8892b0; margin-bottom: 20px; }
            table { width: 100%; border-collapse: collapse; background: #112240; border-radius: 10px; overflow: hidden; }
            th { background: #64ffda; color: #0a192f; padding: 12px; text-align: left; }
            td { padding: 10px; border-bottom: 1px solid #233554; }
            tr:hover { background: #1d3a5c; }
            .timestamp { color: #64ffda; font-size: 0.9em; }
            .empty { text-align: center; padding: 40px; color: #8892b0; }
        </style>
    </head>
    <body>
        <h1>JalScan Live Data</h1>
        <p class="info">Auto-refreshes every 10 seconds | Last updated: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</p>
    """
    
    if len(rows) <= 1:
        html += '<div class="empty">No reports submitted yet.</div>'
    else:
        html += "<table><thead><tr>"
        for header in rows[0]:
            html += f"<th>{header}</th>"
        html += "</tr></thead><tbody>"
        for row in reversed(rows[1:]):
            html += "<tr>"
            for cell in row:
                html += f"<td>{cell}</td>"
            html += "</tr>"
        html += "</tbody></table>"
    
    html += "</body></html>"
    return html

@app.route('/data/json', methods=['GET'])
def json_csv():
    """Get CSV data as JSON API - always fresh"""
    if not os.path.exists(DB_FILE):
        return jsonify({"error": "No data", "records": []})
    
    with open(DB_FILE, 'r') as f:
        reader = csv.DictReader(f)
        records = list(reader)
    
    response = jsonify({
        "count": len(records),
        "last_updated": datetime.now().isoformat(),
        "records": records
    })
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

@app.route('/data/raw', methods=['GET'])
def raw_csv():
    """Get raw CSV content - for embedding in sheets/apps"""
    if not os.path.exists(DB_FILE):
        return "Date,Time,Role,River Name,River ID,Water Level,Submitted By,AI Status", 200
    
    with open(DB_FILE, 'r') as f:
        content = f.read()
    
    response = Response(content, mimetype='text/csv')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route('/initiate_call', methods=['POST'])
def initiate_call():
    data = request.json
    to_number = data.get('phone_number').strip()
    ai_data = data.get('ai_data')
    if ai_data: call_context[to_number] = ai_data

    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_number = os.environ.get('TWILIO_PHONE_NUMBER')

    if not all([account_sid, auth_token, from_number]):
         return jsonify({"status": "error", "message": "Twilio credentials missing"}), 500

    if not BASE_URL:
        return jsonify({"status": "error", "message": "Server URL not configured. Set BASE_URL env variable."}), 500

    try:
        client = Client(account_sid, auth_token)
        callback_url = f"{BASE_URL}/voice"
        print(f"Initiating call to {to_number} with callback: {callback_url}")
        call = client.calls.create(to=to_number, from_=from_number, url=callback_url)
        return jsonify({"status": "success", "message": "Calling...", "sid": call.sid})
    except Exception as e: 
        print(f"Call error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    resp = VoiceResponse()
    call_sid = request.values.get('CallSid')
    user_number = request.values.get('To')
    
    print(f"Voice webhook called - CallSid: {call_sid}, To: {user_number}")
    
    # Initialize session for this call
    session = get_call_session(call_sid)
    session['step'] = 'welcome'
    
    context = call_context.get(user_number)

    # --- VISION-ASSISTED FLOW ---
    if context:
        status = context.get('status', 'Unknown')
        confidence = context.get('confidence', 0)
        level = context.get('level', 'Unknown')

        session['ai_verified'] = f"{status} ({confidence}%)"
        session['role'] = 'field_agent' 

        if "Tampered" in status or int(confidence) < 70:
            speak(resp, f"Security Alert. JalScan AI detected tampering with only {confidence} percent confidence. Access Denied.")
            resp.hangup()
            return str(resp)
        else:
            speak(resp, f"Hello Field Agent. Image verified. Gemini estimates water level is {level}. Please confirm the River Name.")
            session['step'] = 'ask_river_name' 
            gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}', speechTimeout='auto')
            resp.append(gather)
            return str(resp)

    # --- STANDARD FLOW ---
    speak(resp, "Hi! Welcome to the Jalscan reporting system.")
    gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}', speechTimeout='auto')
    speak(gather, "Would you like to log in as an Agent, Contact Support, or Raise an Issue?")
    resp.append(gather)
    resp.redirect(f'{BASE_URL}/voice?CallSid={call_sid}')
    return str(resp)

@app.route("/handle_input", methods=['GET', 'POST'])
def handle_input():
    resp = VoiceResponse()
    call_sid = request.values.get('CallSid')
    user_input = request.values.get('SpeechResult', '').lower()
    
    print(f"Handle input - CallSid: {call_sid}, Input: {user_input}")
    
    # Get the session for this call
    session = get_call_session(call_sid)
    step = session.get('step', 'welcome')
    
    print(f"Current step: {step}")

    # --- 1. WELCOME MENU ---
    if step == 'welcome':
        if 'agent' in user_input:
            session['step'] = 'select_role'
            gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
            speak(gather, "Please tell me your role. Field Agent, Supervisor, Analyst, or Admin?")
            resp.append(gather)
        elif 'support' in user_input:
            speak(resp, "Connecting to Support. Please hold.")
            resp.hangup()
        elif 'issue' in user_input:
             speak(resp, "Please state the issue.")
             resp.record(maxLength=30, action=f'{BASE_URL}/voice?CallSid={call_sid}') 
        else:
            speak(resp, "I didn't catch that. Say Agent, Support, or Issue.")
            resp.redirect(f'{BASE_URL}/voice?CallSid={call_sid}')

    # --- 2. ROLE SELECTION ---
    elif step == 'select_role':
        if 'field' in user_input:
            session['role'] = 'field_agent'
            session['step'] = 'ask_river_name'
            gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
            speak(gather, "Okay Field Agent. Please tell me the River Name.")
            resp.append(gather)
        elif 'supervisor' in user_input:
            session['role'] = 'supervisor'
            session['step'] = 'sup_ask_data'
            gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
            speak(gather, "Welcome Supervisor. Do you want data for a specific River ID, or All rivers?")
            resp.append(gather)
        elif 'analyst' in user_input:
            session['role'] = 'analyst'
            session['step'] = 'analyst_ask_data'
            gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
            speak(gather, "Hello Analyst. Do you want a particular Site Data or Everything?")
            resp.append(gather)
        elif 'admin' in user_input:
            session['role'] = 'admin'
            session['step'] = 'admin_confirm_email'
            gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
            speak(gather, f"Admin Access Granted. I have prepared the master report. Should I email it to {EMAILS['admin']}? Say Yes or No.")
            resp.append(gather)
        else:
            speak(resp, "Invalid role. Say Field Agent, Supervisor, Analyst, or Admin.")
            resp.redirect(f'{BASE_URL}/handle_input?CallSid={call_sid}') 

    # --- 3. FIELD AGENT FLOW ---
    elif step == 'ask_river_name':
        session['river_name'] = user_input
        session['step'] = 'ask_river_id'
        gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
        speak(gather, "Got it. Please tell me the River ID.")
        resp.append(gather)

    elif step == 'ask_river_id':
        numbers = re.findall(r'\d+', user_input)
        session['river_id'] = numbers[0] if numbers else user_input
        session['step'] = 'ask_water_level'
        gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
        speak(gather, "Okay. What is the water level?")
        resp.append(gather)

    elif step == 'ask_water_level':
        session['water_level'] = user_input
        report = f"River {session.get('river_name')}, Level {user_input}."
        session['final_report'] = report

        session['step'] = 'confirm_report'
        gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
        speak(gather, f"Here is your report: {report}. Say 'Confirm' to submit.")
        resp.append(gather)

    elif step == 'confirm_report':
        if 'confirm' in user_input or 'yes' in user_input:
            # Save Data to CSV
            try:
                with open(DB_FILE, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        datetime.now().strftime("%Y-%m-%d"), 
                        datetime.now().strftime("%H:%M:%S"), 
                        "Field Agent", 
                        session.get('river_name', 'Unknown'), 
                        session.get('river_id', 'Unknown'), 
                        session.get('water_level', 'Unknown'), 
                        "Agent", 
                        session.get('ai_verified', 'Voice')
                    ])
                print(f"Data saved to CSV: {session.get('river_name')}")
            except Exception as e:
                print(f"CSV write error: {e}")

            # ASK IF THEY WANT EMAIL
            session['step'] = 'ask_agent_email_perm'
            gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
            speak(gather, "Report Saved. Do you want a receipt sent to your email? Say Yes or No.")
            resp.append(gather)
        else:
            session['step'] = 'welcome'
            speak(resp, "Okay, let's start over.")
            resp.redirect(f'{BASE_URL}/voice?CallSid={call_sid}')

    elif step == 'ask_agent_email_perm':
        if 'yes' in user_input:
            session['step'] = 'get_agent_email'
            gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
            speak(gather, "Please say your email address clearly.")
            resp.append(gather)
        else:
            speak(resp, "Okay. No email will be sent. Goodbye.")
            if call_sid in call_sessions:
                del call_sessions[call_sid]
            resp.hangup()

    elif step == 'get_agent_email':
        raw_email = user_input.replace(" at ", "@").replace(" dot ", ".").replace(" ", "")
        print(f"Sending email to: {raw_email}")
        email_sent = send_email(raw_email, "Jalscan Receipt", f"Report: {session.get('final_report', 'No report data')}")
        if email_sent:
            speak(resp, f"Email sent to {raw_email}. Goodbye.")
        else:
            speak(resp, f"Could not send email. Please check your email address. Goodbye.")
        if call_sid in call_sessions:
            del call_sessions[call_sid]
        resp.hangup()

    # --- 4. SUPERVISOR FLOW ---
    elif step == 'sup_ask_data':
        if 'all' in user_input:
             session['sup_action'] = 'all'
             msg = "Full data logs"
        else:
             session['sup_action'] = 'site'
             msg = "River data"

        session['step'] = 'sup_confirm_email'
        gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
        target = EMAILS['supervisor']
        speak(gather, f"I have prepared the {msg}. Should I send it to your registered email {target}? Say Yes.")
        resp.append(gather)

    elif step == 'sup_confirm_email':
        if 'yes' in user_input or 'send' in user_input:
            send_email(EMAILS['supervisor'], "Jalscan Supervisor Report", "Data attached.", DB_FILE)
            speak(resp, "Email sent successfully. Goodbye.")
        else:
            speak(resp, "Okay, cancelled. Goodbye.")
        if call_sid in call_sessions:
            del call_sessions[call_sid]
        resp.hangup()

    # --- 5. ANALYST FLOW ---
    elif step == 'analyst_ask_data':
        if 'everything' in user_input:
             session['analyst_action'] = 'full'
             msg = "Full dataset"
        else:
             session['analyst_action'] = 'site'
             msg = "Site report"

        session['step'] = 'analyst_confirm_email'
        gather = Gather(input='speech', action=f'{BASE_URL}/handle_input?CallSid={call_sid}')
        target = EMAILS['analyst']
        speak(gather, f"I have the {msg}. Send to registered email {target}? Say Yes.")
        resp.append(gather)

    elif step == 'analyst_confirm_email':
        if 'yes' in user_input:
            send_email(EMAILS['analyst'], "Jalscan Analyst Data", "Data attached.", DB_FILE)
            speak(resp, "Email sent. Goodbye.")
        else:
            speak(resp, "Cancelled.")
        if call_sid in call_sessions:
            del call_sessions[call_sid]
        resp.hangup()

    # --- 6. ADMIN FLOW ---
    elif step == 'admin_confirm_email':
        if 'yes' in user_input:
            send_email(EMAILS['admin'], "Jalscan Master Report", "Full logs attached.", DB_FILE)
            speak(resp, "Master report sent. Goodbye.")
        else:
            speak(resp, "Cancelled.")
        if call_sid in call_sessions:
            del call_sessions[call_sid]
        resp.hangup()

    else:
        speak(resp, "I didn't understand. Let me start over.")
        session['step'] = 'welcome'
        resp.redirect(f'{BASE_URL}/voice?CallSid={call_sid}')

    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

