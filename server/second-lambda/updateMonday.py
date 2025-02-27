# Copyright (C) 2023  Emma Lynn
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, version 3 of the License.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <https://www.gnu.org/licenses/>.

import requests
import json
import pandas as pd
from datetime import date
from databaseInteraction import checkRowExistence

API_URL = "https://api.monday.com/v2"
NUM_STU_INDEX = 9   # 9: number of students index - from Meghan's file
TERM_TABLE_NAME = 'QA_Terms'
COL_IDS = ["text8", "text67", "text83", "text", "text6", "status4", "status35", "status8", "__of_students",
           "__content_in_use",
           "files_total", "files_with_link", "files___in_use", "wysiwyg_content", "wysiwyg_in_use", "videos",
           "kaltura_vids", "youtube", "flash_content", "broken_links", "navigation_items", "status48",
           "overall_a11y_score",
           "files_ally_score", "wysiwyg_ally_score", "__of_pdf_files", "pdf_files_in_use", "pdf_scanned_not_ocr_d",
           "images", "images_wo_alt_text", "numbers"]
GROUP_IDS = {100: "new_group659", 50: "new_group84060", 20: "new_group63769", 10: "new_group69712", 1: "new_group",
             0: "new_group7956"}


def updateColIds(boardId):
    termData = checkRowExistence(TERM_TABLE_NAME, boardId, "id")
    if termData is None:
        raise Exception(f"{boardId} is not a recognized board ID. ")
    COL_IDS.append(termData["TriggerColID"])
    COL_IDS.append("date")


def findGroupID(numStu):
    for lowerLimit in GROUP_IDS:
        if int(numStu) >= lowerLimit:
            return GROUP_IDS[lowerLimit]
    return GROUP_IDS[0]


def createNewItem(rowInfo, boardId, headers):
    headers['API-Version'] = '2023-10'
    headers['Content-Type'] = 'application/json'

    groupID = findGroupID(rowInfo[NUM_STU_INDEX])
    query = f'mutation ($myItemName: String!, $columnVals: JSON!) ' \
            f'{{ create_item (board_id:{boardId}, group_id: "{groupID}", ' \
            f'item_name:$myItemName, column_values:$columnVals) {{ id }} }}'

    rowInfo.append("Done")
    rowInfo.append(date.today())

    colVals = dict(zip(COL_IDS, rowInfo[1:]))
    theVars = {
        'myItemName': rowInfo[0],
        'columnVals': json.dumps(colVals, default=str)
    }

    data = {'query': query, 'variables': theVars}
    r = requests.post(url=API_URL, json=data, headers=headers)  # make request

    try:
        return r.json()["data"]["create_item"]["id"]
    except Exception as e:
        # if e.contains('429'):
        #     print(f"Hit rate limit {e}")
        #     return 429
        print(f":( error when creating new row {e}")
        print(r.json())
        return None


def updateRow(itemID, rowInfo, boardId, headers):
    headers['API-Version'] = '2023-10'
    headers['Content-Type'] = 'application/json'

    query = f'mutation ($columnVals: JSON!) {{ change_multiple_column_values (board_id:{boardId}, ' \
            f'item_id: {itemID}, column_values:$columnVals) {{ name id }} }}'

    rowInfo.append("Done")
    rowInfo.append(date.today())

    colVals = dict(zip(COL_IDS, rowInfo[1:]))
    theVars = {
        'columnVals': json.dumps(colVals, default=str)
    }

    data = {'query': query, 'variables': theVars}

    r = requests.post(url=API_URL, json=data, headers=headers)  # make request
    try:
        return r.json()["data"]["change_multiple_column_values"]["id"]
    except Exception as e:
        # if e.contains('429'):
        #     print(f"Hit rate limit {e}")
        #     return 429
        print(f":(( Error updating row {e}")
        print(r.json())
        return None


def removeNaN(rowData):
    for item in range(len(rowData)):
        if pd.isna(rowData[item]):
            rowData[item] = ""
    return rowData


def doOneUpdate(courseDF, boardId, mondayAPIKey, currBoard):
    updateColIds(boardId)

    numUpdated = 0
    numNew = 0
    i = 0
    rowData = courseDF.iloc[i].values.tolist()
    rowData = removeNaN(rowData)
    if "Study Abroad" in rowData:
        print("Replacing 'Study Abroad' with 'Supervised'.")
        rowData[rowData.index("Study Abroad")] = "Supervised"
    if "Disability Resource Center" in rowData:
        print("Replacing 'Disability Resource Center' with 'University'.")
        rowData[rowData.index("Disability Resource Center")] = "University"
    if "Concurrent Enrollment" in rowData:
        print("Replacing 'Concurrent Enrollment' with 'Concurrent'.")
        rowData[rowData.index("Concurrent Enrollment")] = "Concurrent"
    print(str(rowData))

    HEADERS = {"Authorization": mondayAPIKey}

    newDF = courseDF.tail(-1)

    if rowData[0] in currBoard:
        itemID = currBoard[rowData[0]]
        updateAttempt = updateRow(itemID, rowData, boardId, HEADERS)

        if updateAttempt is None:
            print("Failed updating row")
            return [newDF, 0, 0, rowData[0]]

        if updateAttempt == 429:
            print("Needs to be retried")
            return [newDF, 0, 0, 429]

        numUpdated = 1
        print(f"{rowData[0]} matched and updated if needed")
    else:
        itemID = createNewItem(rowData, boardId, HEADERS)
        if itemID is None:
            print("Failed creating new")
            return [newDF, 0, 0, rowData[0]]
        if itemID == 429:
            print("Failed creating new")
            return [newDF, 0, 0, rowData[0]]
        numNew = 1
        print(f"{rowData[0]} added as new row")

    return [newDF, numUpdated, numNew, ""]


def getBoardContents(mondayAPIKey, boardId, currBoard):
    HEADERS = {'Content-Type': 'application/json', 'Authorization': mondayAPIKey, 'API-Version': '2023-10'}
    getIdsQuery = f'{{ boards(ids:{boardId}) {{ items_page(limit: 500) {{ cursor items {{ name id }} }} }} }}'
    data = {'query': getIdsQuery}

    r = requests.post(url=API_URL, json=data, headers=HEADERS)
    jsonObj = json.loads(r.content)

    for theRow in jsonObj['data']["boards"][0]["items_page"]['items']:
        currBoard[theRow["name"]] = theRow["id"]

    cursor = jsonObj['data']["boards"][0]["items_page"]['cursor']

    while cursor is not None:
        retryQuery = f'{{ next_items_page(limit: 500, cursor: "{cursor}") {{ cursor items {{ name id }} }} }}'
        data = {'query': retryQuery}

        r = requests.post(url=API_URL, json=data, headers=HEADERS)
        jsonObj = json.loads(r.content)

        for theRow in jsonObj["data"]["next_items_page"]['items']:
            currBoard[theRow["name"]] = theRow["id"]

        cursor = jsonObj["data"]["next_items_page"]['cursor']

    return currBoard
