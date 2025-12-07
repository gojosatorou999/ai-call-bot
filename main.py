import os
import csv
import smtplib
import re
import google.generativeai as genai
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, request, session, render_template, jsonify, url_for
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client

# --- CONFIGURATION ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'any')

# Email Mapping
EMAILS = {
    "supervisor": "rishanthpatkar@gmail.com",
    "analyst": "mathematicsacademy007@gmail.com",
    "admin": "varunmax9989@gmail.com"
}

DB_FILE = "jalscan_data.csv"
call_context = {} 

# Configure Gemini
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"Gemini Error: {e}")

# Ensure CSV exists
if not os.path.exists(DB_FILE):
    with open(DB_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Time", "Role", "River Name", "River ID", "Water Level", "Submitted By", "AI Status"])

# --- HELPER FUNCTIONS ---
def send_email(to_email, subject, body, attachment_path=None):
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_password = os.environ.get('GMAIL_PASSWORD')

    if not gmail_user or not gmail_password:
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
        return True
    except: return False

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

    try:
        client = Client(account_sid, auth_token)
        callback_url = url_for('voice', _external=True)
        call = client.calls.create(to=to_number, from_=from_number, url=callback_url)
        return jsonify({"status": "success", "message": "Calling...", "sid": call.sid})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    resp = VoiceResponse()
    session.clear()
    session['step'] = 'welcome'
    user_number = request.values.get('To')
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
            # SKIP MENU: Jump to Agent Questions
            speak(resp, f"Hello Field Agent. Image verified. Gemini estimates water level is {level}. Please confirm the River Name.")
            session['step'] = 'ask_river_name' 
            gather = Gather(input='speech', action='/handle_input', speechTimeout='auto')
            resp.append(gather)
            return str(resp)

    # --- STANDARD FLOW ---
    speak(resp, "Hi! Welcome to the Jalscan reporting system.")
    gather = Gather(input='speech', action='/handle_input', speechTimeout='auto')
    speak(gather, "Would you like to log in as an Agent, Contact Support, or Raise an Issue?")
    resp.append(gather)
    resp.redirect('/voice')
    return str(resp)

@app.route("/handle_input", methods=['GET', 'POST'])
def handle_input():
    resp = VoiceResponse()
    user_input = request.values.get('SpeechResult', '').lower()
    step = session.get('step')

    # --- 1. WELCOME MENU ---
    if step == 'welcome':
        if 'agent' in user_input:
            session['step'] = 'select_role'
            gather = Gather(input='speech', action='/handle_input')
            speak(gather, "Please tell me your role. Field Agent, Supervisor, Analyst, or Admin?")
            resp.append(gather)
        elif 'support' in user_input:
            speak(resp, "Connecting to Support. Please hold.")
            resp.hangup()
        elif 'issue' in user_input:
             speak(resp, "Please state the issue.")
             resp.record(maxLength=30, action='/voice') 
        else:
            speak(resp, "I didn't catch that. Say Agent, Support, or Issue.")
            resp.redirect('/voice')

    # --- 2. ROLE SELECTION ---
    elif step == 'select_role':
        if 'field' in user_input:
            session['role'] = 'field_agent'
            session['step'] = 'ask_river_name'
            gather = Gather(input='speech', action='/handle_input')
            speak(gather, "Okay Field Agent. Please tell me the River Name.")
            resp.append(gather)
        elif 'supervisor' in user_input:
            session['role'] = 'supervisor'
            session['step'] = 'sup_ask_data'
            gather = Gather(input='speech', action='/handle_input')
            speak(gather, "Welcome Supervisor. Do you want data for a specific River ID, or All rivers?")
            resp.append(gather)
        elif 'analyst' in user_input:
            session['role'] = 'analyst'
            session['step'] = 'analyst_ask_data'
            gather = Gather(input='speech', action='/handle_input')
            speak(gather, "Hello Analyst. Do you want a particular Site Data or Everything?")
            resp.append(gather)
        elif 'admin' in user_input:
            session['role'] = 'admin'
            session['step'] = 'admin_menu'
            gather = Gather(input='speech', action='/handle_input')
            speak(gather, "Admin Access Granted. Sending system status.")
            # Admin Flow: Ask Confirmation
            session['admin_action'] = 'full_report'
            session['step'] = 'admin_confirm_email'
            gather = Gather(input='speech', action='/handle_input')
            speak(gather, f"I have prepared the master report. Should I email it to {EMAILS['admin']}? Say Yes or No.")
            resp.append(gather)
        else:
            speak(resp, "Invalid role.")
            resp.redirect('/handle_input') 

    # --- 3. FIELD AGENT FLOW (Ask Email Logic) ---
    elif step == 'ask_river_name':
        session['river_name'] = user_input
        session['step'] = 'ask_river_id'
        gather = Gather(input='speech', action='/handle_input')
        speak(gather, "Got it. Please tell me the River ID.")
        resp.append(gather)

    elif step == 'ask_river_id':
        numbers = re.findall(r'\d+', user_input)
        session['river_id'] = numbers[0] if numbers else user_input
        session['step'] = 'ask_water_level'
        gather = Gather(input='speech', action='/handle_input')
        speak(gather, "Okay. What is the water level?")
        resp.append(gather)

    elif step == 'ask_water_level':
        session['water_level'] = user_input
        report = f"River {session.get('river_name')}, Level {user_input}."
        session['final_report'] = report

        session['step'] = 'confirm_report'
        gather = Gather(input='speech', action='/handle_input')
        speak(gather, f"Here is your report: {report}. Say 'Confirm' to submit.")
        resp.append(gather)

    elif step == 'confirm_report':
        if 'confirm' in user_input or 'yes' in user_input:
            # Save Data
            with open(DB_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%H:%M:%S"), "Field Agent", session.get('river_name'), session.get('river_id'), session.get('water_level'), "Agent", session.get('ai_verified', 'Voice')])

            # ASK IF THEY WANT EMAIL
            session['step'] = 'ask_agent_email_perm'
            gather = Gather(input='speech', action='/handle_input')
            speak(gather, "Report Saved. Do you want a receipt sent to your email? Say Yes or No.")
            resp.append(gather)
        else:
            session['step'] = 'select_role'
            speak(resp, "Okay, let's start over.")
            resp.redirect('/voice')

    elif step == 'ask_agent_email_perm':
        if 'yes' in user_input:
            # ASK FOR EMAIL ADDRESS
            session['step'] = 'get_agent_email'
            gather = Gather(input='speech', action='/handle_input')
            speak(gather, "Please say your email address clearly.")
            resp.append(gather)
        else:
            speak(resp, "Okay. No email will be sent. Goodbye.")
            resp.hangup()

    elif step == 'get_agent_email':
        raw_email = user_input.replace(" at ", "@").replace(" dot ", ".").replace(" ", "")
        send_email(raw_email, "Jalscan Receipt", f"Report: {session.get('final_report')}")
        speak(resp, f"Sent to {raw_email}. Goodbye.")
        resp.hangup()

    # --- 4. SUPERVISOR FLOW (Confirm Registered Email) ---
    elif step == 'sup_ask_data':
        # Logic to determine WHAT to send
        if 'all' in user_input:
             session['sup_action'] = 'all'
             msg = "Full data logs"
        else:
             session['sup_action'] = 'site'
             msg = "River data"

        # ASK CONFIRMATION
        session['step'] = 'sup_confirm_email'
        gather = Gather(input='speech', action='/handle_input')
        target = EMAILS['supervisor']
        speak(gather, f"I have prepared the {msg}. Should I send it to your registered email {target}? Say Yes.")
        resp.append(gather)

    elif step == 'sup_confirm_email':
        if 'yes' in user_input or 'send' in user_input:
            send_email(EMAILS['supervisor'], "Jalscan Supervisor Report", "Data attached.", DB_FILE)
            speak(resp, "Email sent successfully. Goodbye.")
        else:
            speak(resp, "Okay, cancelled. Goodbye.")
        resp.hangup()

    # --- 5. ANALYST FLOW (Confirm Registered Email) ---
    elif step == 'analyst_ask_data':
        if 'everything' in user_input:
             session['analyst_action'] = 'full'
             msg = "Full dataset"
        else:
             session['analyst_action'] = 'site'
             msg = "Site report"

        # ASK CONFIRMATION
        session['step'] = 'analyst_confirm_email'
        gather = Gather(input='speech', action='/handle_input')
        target = EMAILS['analyst']
        speak(gather, f"I have the {msg}. Send to registered email {target}? Say Yes.")
        resp.append(gather)

    elif step == 'analyst_confirm_email':
        if 'yes' in user_input:
            send_email(EMAILS['analyst'], "Jalscan Analyst Data", "Data attached.", DB_FILE)
            speak(resp, "Email sent. Goodbye.")
        else:
            speak(resp, "Cancelled.")
        resp.hangup()

    # --- 6. ADMIN FLOW (Confirm Registered Email) ---
    elif step == 'admin_confirm_email':
        if 'yes' in user_input:
            send_email(EMAILS['admin'], "Jalscan Master Report", "Full logs attached.", DB_FILE)
            speak(resp, "Master report sent. Goodbye.")
        else:
            speak(resp, "Cancelled.")
        resp.hangup()

    else:
        speak(resp, "I didn't understand.")
        resp.redirect('/voice')

    return str(resp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)