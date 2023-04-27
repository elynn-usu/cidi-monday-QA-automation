from flask import Flask, request, jsonify, render_template, flash, redirect, url_for, session
import dotenv    # for dev
from boxsdk import Client, OAuth2
import os
from threading import Thread
import json
import pandas as pd
import smtplib, ssl
from email.message import EmailMessage
from datetime import datetime

from talkToBox import getDataFromBox
from combineData import combineReports
from updateMonday import fillNewBoard, updateExistingBoard
from getAllyData import getURL


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('CSRF')

link = "inactive"
status = "inactive"
allyDataFrame = None


@app.route('/', methods=['GET', 'POST'])
def initialLogin():

    if request.method == "GET":
        msg = request.args.get('msg')
        return render_template('login.html', msg=msg)

    if request.method == "POST":
        if request.form["check"]:
            print("Caught a bot!! Get out of here!")
            return redirect(url_for('initialLogin', msg="Error: please contact your site admin."))

        submittedCode = request.form["code"]

        authorizedUsers = json.loads(os.environ.get("AUTH_USERS"))

        if submittedCode in authorizedUsers:
            print(f"{authorizedUsers[submittedCode]} is trying to access the site with approved code {submittedCode}")
            session['activeUser'] = authorizedUsers[submittedCode]
            session['authorized'] = True
        else:
            return redirect(url_for('initialLogin', msg="Invalid credentials. Please contact your site admin."))

        return redirect(url_for("loginBox"))


#--------------------------


@app.route('/box-login', methods=['GET', 'POST'])
def loginBox():
    if not session.get('authorized'):
        return render_template('login.html', msg="Error: you must log in to access this application."), 403

    msg = request.args.get('msg')

    oauth = OAuth2(
        client_id=os.environ.get('BOX_CLIENT_ID'),
        client_secret=os.environ.get('BOX_SECRET'),
        store_tokens=store_tokens,
    )

    auth_url, csrf_token = oauth.get_authorization_url('http://localhost:8000/oauth/callback')
    session['csrf'] = csrf_token
    return render_template('loginBox.html', auth_url=auth_url, csrf_token=csrf_token, msg=msg)


def store_tokens(access_token: str, refresh_token: str) -> bool:
    """
    Store the access and refresh tokens for the current user
    """

    session["accessTok"] = access_token
    session["refreshTok"] = refresh_token

    print(f"Here is the access token!! {session['accessTok']}")

    return True


@app.route('/oauth/callback')
def oauth_callback():
    if not session.get('authorized'):
        return render_template('login.html', msg="Error: you must log in to access this application."), 403

    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    error_description = request.args.get('error_description')

    try:
        assert state == session['csrf']
    except AssertionError as e:
        print(e)
        msg = "CSRF verification failed."
        return redirect(url_for('loginBox', msg=msg))

    if error == 'access_denied':
        print("denial caught!")
        msg = 'You denied access to your Box account. You must authorize QA Update to access your ' \
              'account to use this application.'
    else:
        msg = error_description

    if msg is not None:
        print("rendering login page again")
        #return render_template('loginBox.html', msg=msg)
        return redirect(url_for('loginBox', msg=msg))

    oauth = OAuth2(
        client_id=os.environ.get('BOX_CLIENT_ID'),
        client_secret=os.environ.get('BOX_SECRET'),
        store_tokens=store_tokens
    )

    access_token, refresh_token = oauth.authenticate(code)

    return redirect(url_for('landing'))


#--------------------------


@app.route('/landing', methods=['GET', 'POST'])
def landing():
    if not session.get('authorized'):
        return render_template('login.html', msg="Error: you must log in to access this application."), 403

    # GET
    if request.method == 'GET':
        return render_template('index.html')

    if request.method == 'POST':
        return redirect(url_for('landing'))

    return render_template('index.html')


@app.route('/getAllyLink', methods=['POST'])
def getAllyLink():
    if not session.get('authorized'):
        return render_template('login.html', msg="Error: you must log in to access this application."), 403

    if request.method == 'POST':
        allyClientId = request.form['ally-client-id']
        allyConsumKey = request.form['ally-consum-key']
        allyConsumSec = request.form['ally-consum-sec']
        termCode = request.form['term-code']

        if not allyClientId or not allyConsumKey or not allyConsumSec or not termCode:
            flash('All fields are required!')
            return render_template('index.html')
        if not termCode.isdigit():
            flash('Invalid term code.')
            return render_template('index.html')

        global link
        link = ""

        t2 = Thread(target=getAllyURL, args=(allyClientId, allyConsumKey, allyConsumSec, termCode))

        print("Starting the thread")
        t2.start()

        return render_template('index.html', status=f"Loading....")

    return render_template('index.html')


def getAllyURL(allyClientId, allyConsumKey, allyConsumSec, termCode):
    result = getURL(allyClientId, allyConsumKey, allyConsumSec, termCode)
    global link
    if result == -1:
        link = -1
    else:
        link = f"http{result[5:-1]}"


@app.route('/processAllyFile', methods=['POST'])
def processAllyFile():
    if not session.get('authorized'):
        return render_template('login.html', msg="Error: you must log in to access this application."), 403

    if request.method == 'POST':
        if request.form["check"]:
            print("Caught a bot!! Get out of here!")
            return redirect(url_for('submitted', msg="Error: please contact your site admin."))

        try:
            uploadedFile = request.files["allyFile"]
            global allyDataFrame
            allyDataFrame = pd.read_csv(uploadedFile)

            return render_template('index.html', upload_status="Upload successful!")
        except Exception as e:
            uploadErr = "File is invalid or failed to upload. Please try again."
            print(e)
            return render_template('index.html', upload_err=uploadErr)

    return render_template('index.html')


@app.route('/linkStatus', methods=['GET'])
def getLinkStatus():
    if not session.get('authorized'):
        return render_template('login.html', msg="Error: you must log in to access this application."), 403

    statusList = {'status': link}
    return json.dumps(statusList)


#--------------------------


@app.route('/updating', methods=['GET', 'POST'])
def updating():
    if not session.get('authorized'):
        return render_template('login.html', msg="Error: you must log in to access this application."), 403

    # GET
    if request.method == 'GET':
        return render_template('updating.html')

    if request.method == 'POST':

        if request.form["check"]:
            print("Caught a bot!! Get out of here!")
            return redirect(url_for('submitted', msg="Error: please contact your site admin."))

        triggerType = request.form['trigger-type']
        boardId = request.form['board-id']
        crBoxId = request.form['cr-box-id']
        mondayAPIKey = request.form['mon-api-key']

        error = False

        if allyDataFrame is None:
            print("No ally file")
            flash("You must upload a valid Ally file to continue.")
            error = True

        print(f"triggerType: {triggerType}, boardID: {boardId}, crBoxID: {crBoxId}")

        if triggerType == "" or not boardId or not crBoxId or not mondayAPIKey:
            flash('All fields are required!')
            error = True
        else:
            if triggerType != "update" and triggerType != "new":
                flash('Invalid update type (stop messing with my dev tools!)')
                error = True
            if not boardId.isdigit() or int(boardId) <= 0:
                flash('Invalid monday board ID')
                error = True
            if not crBoxId.isdigit() or int(crBoxId) <= 0:
                flash('Invalid course report ID')
                error = True
        if error:
            return render_template('index.html')

        print(f"triggerType: {triggerType}, boardID: {boardId}, crBoxID: {crBoxId}")

        if not session.get('accessTok'):
            flash('Box authorization incomplete.')
            return render_template('index.html')

        allyData = allyDataFrame
        accessTokVal = session["accessTok"]

        t1 = Thread(target=doUpdate, args=(triggerType, boardId, crBoxId, mondayAPIKey, allyData, accessTokVal))
        t1.start()

        return redirect(url_for('updating'))

    return render_template('index.html')


def doUpdate(triggerType, boardId, crBoxId, mondayAPIKey, allyData, accessTok):
    global status
    status = 0

    print(f"doing the update {status}")

    status += 1

    try:
        courseReportData = getDataFromBox(crBoxId, 'excel', accessTok)
        print(f"gotten course report {status}")
        status += 1
    except Exception as e:
        print(e)
        status = "error1"
        return

    try:
        completeReport = combineReports(courseReportData, allyData)
        print(f"combined reports {status}")
        status += 1
    except Exception as e:
        print(e)
        status = "error2"
        return

    try:
        if triggerType == "new":
            fillNewBoard(completeReport, boardId, mondayAPIKey)
            print(f"Fill in complete {status}")
            status += 7
            return

        updateExistingBoard(completeReport, boardId, mondayAPIKey)
        print(f"Update complete: {status}")
        status += 7
    except Exception as e:
        print(e)
        status = "error3"


@app.route('/status', methods=['GET'])
def getStatus():
    if not session.get('authorized'):
        return render_template('login.html', msg="Error: you must log in to access this application."), 403

    statusList = {'status': status}

    return json.dumps(statusList)


#--------------------------


@app.route('/bug-report', methods=['GET', 'POST'])
def bugReport():
    if not session.get('authorized'):
        return render_template('login.html', msg="Error: you must log in to access this application."), 403

    supportedTools = ["QA Update"]

    # GET
    if request.method == 'GET':
        return render_template('bugReport.html')

    if request.method == 'POST':
        if request.form["check"]:
            print("Caught a bot!! Get out of here!")
            return redirect(url_for('submitted', msg="Error: please contact your site admin."))

        if not request.form["app-name"] in supportedTools:
            return redirect(url_for('submitted', msg='Invalid application name (stop messing with my dev tools!)'))

        reportInfo = {
            "App Name": request.form["app-name"],
            "Date and time": request.form["date-time"],
            "Expected Behavior": request.form["expected-behavior"],
            "Actual Behavior": request.form["actual-behavior"],
            "Errors": request.form["errors"],
            "Browser": request.form["browser"],
            "Other Info": request.form["other-info"],
            "Name": request.form["name"],
            "Email": request.form["email"],
        }

        message = f"Bug reported for {request.form['app-name']} submitted on {datetime.now()}" \
                  f"\n\n------Form Info------\n"

        for info in reportInfo:
            message += f"{info}: {reportInfo[info]}\n"

        message += "\n------Runtime Info------\n"

        message += f"status: {status}\n"
        message += f"link: {link}\n"
        message += f"allyDataframe: {allyDataFrame}\n"
        message += f"accessTok: {session['accessTok']}\n"
        message += f"refreshTok: {session['refreshTok']}\n"
        message += f"csrf: {session['csrf']}\n"
        message += f"active user: {session['activeUser']}\n"

        sendEmail(message, f"Bug Report - {request.form['app-name']}")
        return redirect(url_for('submitted'))

    return render_template('bugReport.html')


def sendEmail(message, subject):
    port = 465  # For SSL
    smtp_server = "smtp.gmail.com"
    sender_email = os.environ.get('DEV_EMAIL')
    receiver_email = os.environ.get('DEV_EMAIL')
    password = os.environ.get('EMAIL_PASS')

    msg = EmailMessage()
    msg.set_content(message)
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = receiver_email

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
        server.login(sender_email, password)
        server.send_message(msg, from_addr=sender_email, to_addrs=receiver_email)


#--------------------------

@app.route('/submitted', methods=['GET'])
def submitted():
    msg = request.args.get('msg')
    return render_template('submitted.html', msg=msg)


if __name__ == '__main__':
    app.run(port=8000, debug=True, host="localhost")
    dotenv.load_dotenv(dotenv.find_dotenv())
