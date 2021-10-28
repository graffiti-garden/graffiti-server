import json
from os import getenv
from asyncio import create_task
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .db import open_redis

ws_interval = int(getenv('ATTEND_WS_INTERVAL'))

router = APIRouter()

@router.websocket("/attend")
async def attend(ws: WebSocket):
    # Accept and create object
    await ws.accept()
    at = Attend()

    # Listen for updates
    while True:
        try:
            msg = await ws.receive_json()
        except WebSocketDisconnect:
            at.cancel()
            break

        # Send it to the object
        await at.receive(ws, msg)

class Attend:

    def __init__(self):
        self.stages = {}
        self.task  = None

    def cancel(self):
        if self.task:
            self.task.cancel()

    async def receive(self, ws: WebSocket, msg: dict):
        # Kill the task if it exists
        self.cancel()

        # Update the stage attendance and return an acknowledgment
        for stage in msg['stages']:
            if stage not in self.stages:
                self.stages[stage] = msg['stages'][stage]
        for stage in self.stages:
            if stage not in msg['stages']:
                del self.stages[stage]
        await ws.send_json({'stages': self.stages})

        # Start a background listening task if non-empty
        if self.stages:
            self.task = create_task(self.attend(ws))
        else:
            self.task = None

    async def attend(self, ws: WebSocket):
        # Connect to the database
        r = await open_redis()

        while True:
            # Wait for new events
            stages = {'stg' + stage: id_ for stage, id_ in self.stages.items()}
            events = await r.xread(stages,
                                   block=ws_interval)

            # Extract the actions
            actions = {}
            for stage, stageevents in events:
                stage = stage.decode()[3:]
                actions[stage] = []
                for id_, event in stageevents:
                    self.stages[stage] = id_.decode()
                    # Decode the binary to JSON
                    action = json.loads(event[b'action'])
                    actions[stage].append(action)

            # Send the output
            try:
                await ws.send_json({
                    'actions': actions,
                    'stages' : self.stages
                    })
            except:
                break
