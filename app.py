from pyngrok import ngrok
from flask import Flask, request, jsonify, render_template, flash, redirect, url_for
import dotenv
from talkToBox import getDataFromBox
from combineData import combineReports
from updateMonday import fillNewBoard, updateExistingBoard, getColumnValues, updateTriggerRow

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bagelTime'


def connect(port, protocol="http") -> str:
    """
    Create a new ngrok tunnel
    :param port: the tunnel local port
    :param protocol: the protocol to use
    :return: the ngrok url
    """
    return ngrok.connect(port, protocol)


@app.route('/', methods=['GET', 'POST'])
def index():
    # GET
    if request.method == 'GET':
        #return "<p>This is USU's QA update application. I don't do much here, try me out on monday.com!</p>", 200
        return render_template('index.html')

    if request.method == 'POST':
        title = request.form['board-id']
        content = request.form['content']

        if not title:
            flash('Title is required!')
        else:
            print(f"{title}: {content}")
            return redirect(url_for('index'))

    return render_template('index.html')

def otherThings():

    # POST
    data = request.get_json()
    # print(data)

    if 'challenge' in data:
        print("The challenge is here!!")
        challenge = data['challenge']
        return jsonify({'challenge': challenge}), 200

    if 'event' in data:
        print(f"Board id to update: {data['event']['boardId']}")

        print(data['event']['value']['label']['text'])
        triggerType = data['event']['value']['label']['text']

        boardId = data['event']['boardId']
        triggerRowId = data['event']['pulseId']

        ids = getColumnValues(triggerRowId, "ids")
        allyBoxId = ids[0]  # '1167467551435'
        crBoxId = ids[1]  # '1158649874756'

        if not allyBoxId.isnumeric() or not crBoxId.isnumeric():
            print("Triggered on incorrect row")
            updateTriggerRow(triggerRowId, boardId, "")
            return "Thank you!", 200

        allyData = getDataFromBox(allyBoxId, "csv")
        courseReportData = getDataFromBox(crBoxId, 'excel')

        completeReport = combineReports(courseReportData, allyData)

        if triggerType == "Fill whole board":
            fillNewBoard(completeReport, boardId)
            print("Fill in complete")
            updateTriggerRow(triggerRowId, boardId)
            return "Thank you!", 200

        updateExistingBoard(completeReport, boardId)
        updateTriggerRow(triggerRowId, boardId)
        print("Update complete")

    return "Thank you!", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
    connect(8080)

    dotenv.load_dotenv(dotenv.find_dotenv())
