
import argparse
import logging
import threading
from concurrent import futures

import chat_system_pb2
import chat_system_pb2_grpc
import grpc
import server.constants as C
from google.protobuf.json_format import MessageToDict
from server.storage.data_store import Datastore
from server.storage.utils import get_unique_id, get_timestamp
from server.server_pool_manager import ServerPoolManager

data_store = Datastore()


class ChatServerServicer(chat_system_pb2_grpc.ChatServerServicer):

    def __init__(self, data_store: Datastore, spm: ServerPoolManager) -> None:
        super().__init__()
        self.data_store = data_store
        self.new_message_event = threading.Event()
        self.spm = spm
        pass

    def get_group_details(self, group_id: str, user_id: str) -> chat_system_pb2.GroupDetails:

        group_created=False
        if not data_store.get_group(group_id):
            group = data_store.create_group(group_id)
            group_created = True
            
        data_store.add_user_to_group(group_id, user_id)

        if group_created:
            server_message = {
                "group_id": group_id,
                "users": group.get('users', []),
                "creation_time": group.get('creation_time')
            }
            self.spm.send_msg_to_connected_servers(server_message, event_type=C.GROUP_EVENT)

        group_details = chat_system_pb2.GroupDetails(
            group_id=group_id, 
            users=data_store.get_group(group_id)["users"], 
            status=True
            )
        return group_details

    def GetUser(self, request, context):
        user_id = request.user_id
        logging.info(f"Login request form user: {user_id}")
        session_id = get_unique_id()
        status = chat_system_pb2.Status(status=True, statusMessage=session_id)
        data_store.save_session_info(session_id, user_id)
        return status
    
    def LogoutUser(self, request, context):
        user_id = request.user_id
        logging.info(f"Logout request form user: {user_id}")
        status = chat_system_pb2.Status(status=True, statusMessage="")
        data_store.save_session_info(request.session_id, user_id, is_active=False)
        return status
    
    def GetGroup(self, request, context):
        group_id = request.group_id
        user_id = request.user_id
        group_details = self.get_group_details(group_id, user_id)
        # logging.info(f"{user_id} joined {group_id}")
        self.new_message({"group_id": group_id, 
        "user_id": user_id,
        "creation_time": get_timestamp(),
        "message_id": get_unique_id(),
        "text":[],
        "message_type": C.USER_JOIN})
        # self.new_message_event.set()
        data_store.save_session_info(request.session_id, user_id, group_id)
        return group_details

    def ExitGroup(self, request, context):
        group_id = request.group_id
        user_id = request.user_id
        session_id = request.session_id
        group = data_store.remove_user_from_group(group_id, user_id)
        status = chat_system_pb2.Status(status=True, statusMessage="")
        logging.info(f"{user_id} exited from group {group_id}")
        self.new_message({"group_id": group_id, 
        "user_id": user_id,
        "creation_time": get_timestamp(),
        "message_id": get_unique_id(),
        "text":[],
        "message_type": C.USER_LEFT})
        data_store.save_session_info(session_id, user_id, is_active=True)

        # server_message = {
        #     "group_id": group_id,
        #     "users": group.get('users', []),
        #     "creation_time": group.get('creation_time'),
        # }
        # self.spm.send_msg_to_connected_servers(server_message, event_type=C.GROUP_EVENT)
        

        self.new_message_event.set()
        data_store.save_session_info(request.session_id, user_id)
        return status

    def GetMessages(self, request, context):
        prev_messages = []
        last_msg_idx = request.message_start_idx
        updated_idx = None

        user_id = request.user_id
        group_id = request.group_id
        session_id = request.session_id

        data_store.save_session_info(session_id, user_id=user_id, group_id=group_id, context=context)

        while True:
            if not context.is_active():
                session_info = data_store.get_session_info(session_id)
                if session_info["group_id"] == group_id:
                    session_info = data_store.get_session_info(session_id)
                    if session_info.get('context') and not session_info.get('context').is_active():
                        data_store.remove_user_from_group(group_id, user_id)
                        data_store.save_session_info(session_id, user_id, is_active=False)
                        self.new_message_event.set()
                break
            last_msg_idx, new_messages, updated_idx = data_store.get_messages(group_id, start_index=last_msg_idx, updated_idx=updated_idx)
            
            for new_message in new_messages:
                
                message_grpc = chat_system_pb2.Message(
                    group_id=new_message["group_id"],
                    user_id=new_message["user_id"],
                    creation_time=new_message["creation_time"],
                    text=new_message.get("text", []),
                    message_id=new_message["message_id"],
                    likes=new_message.get("likes"),
                    message_type=new_message["message_type"]
                )

                yield message_grpc

            self.new_message_event.clear()
            self.new_message_event.wait()


    def new_message(self, message):
        server_message = data_store.save_message(message)
        self.spm.send_msg_to_connected_servers(server_message)
        self.new_message_event.set()

    def PostMessage(self, request, context):
        status = chat_system_pb2.Status(status=True, statusMessage = "")
        message = MessageToDict(request, preserving_proto_field_name=True)
        # add vector timestamp to message
        self.new_message(message)
        return status
    
    def HealthCheck(self, request_iter, context):
        status = chat_system_pb2.Status(status=True, statusMessage = "")
        session_id = None
        try:
            for request in request_iter:
                session_id = request.session_id
        except Exception:
            if session_id is not None:
                session_info = data_store.get_session_info(session_id)
                # if session_info.get('context') and not session_info.get('context').is_active():
                group_id, user_id = session_info.get('group_id'), session_info.get('user_id')
                if group_id is not None:
                    self.new_message({"group_id": group_id, 
                    "user_id": user_id,
                    "creation_time": get_timestamp(),
                    "message_id": get_unique_id(),
                    "text":[],
                    "message_type": C.USER_LEFT})
                    data_store.remove_user_from_group(group_id, user_id)
                    data_store.save_session_info(session_id, user_id, is_active=False)
                    self.new_message_event.set()
            pass
        return status
    
    def Ping(self, request, context):
        status = chat_system_pb2.Status(status=True, statusMessage = "")
        return status

    def GetServerView(self, request, context):
        status = chat_system_pb2.Status(
            status=True, 
            statusMessage = ", ".join(list(map(str, self.spm.get_connected_servers_view())))
            )
        return status
    
    def SyncMessagetoServer(self, request, context):
        """getting messages from other servers"""
        # whenever new message comes from client,
        # send it to spm, which is connected to other servers
        # then send
        status = chat_system_pb2.Status(status=True, statusMessage = "")
        message = MessageToDict(request, preserving_proto_field_name=True)
        event_type = message['event_type']
        message_type = message.get('message_type')
        group_id = message.get('group_id')
        user_id = message.get('user_id')

        if event_type == C.MESSAGE_EVENT:
            # add vector timestamp to message
            data_store.save_message(message)
            if message_type == C.USER_LEFT:
                data_store.remove_user_from_group(group_id, user_id)
            if message_type == C.USER_JOIN:
                data_store.add_user_to_group(group_id, user_id)
            # trigger new message event i.e. calling getmessages
            self.new_message_event.set()
        elif event_type == C.GROUP_EVENT:
            users = message.get('users', [])
            creation_time = message.get('creation_time')
            if not data_store.get_group(group_id):
                data_store.create_group(group_id, users, creation_time)
        return status

def get_args():
    parser = argparse.ArgumentParser(description="Script for running CS 2510 Project 2 servers")
    parser.add_argument('-id', type=int, help='Server Number', required=True)
    args = parser.parse_args()
    print(args)
    return args


def serve():
    data_store = None
    args = get_args()
    try:
        data_store = Datastore()
        spm = ServerPoolManager(id=args.id)
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10000))
        chat_system_pb2_grpc.add_ChatServerServicer_to_server(
            ChatServerServicer(data_store, spm), server
        )
        if C.USE_DIFFERENT_PORTS:
            id = args.id
            server.add_insecure_port(f'[::]:{(11999+id)}')
            print(f"Server [::]:{(11999+id)} started")
        else:
            server.add_insecure_port('[::]:12000')
            print("Server started")
        server.start()
        
        server.wait_for_termination()
    finally:
        if data_store is not None:
            data_store.save_on_file()


if __name__ == '__main__':
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)
    serve()
