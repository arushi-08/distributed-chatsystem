
from __future__ import print_function

import logging
import uuid
import grpc
import chat_system_pb2
import chat_system_pb2_grpc

from google.protobuf.json_format import MessageToJson
from datetime import datetime

from client import constants as C
from client.display_manager import display_manager

global state

state = {

}


def check_state(check_point):
    if check_point > C.SERVER_CONNECTION_CHECK:
        if not state.get(C.SERVER_ONLINE):
            raise Exception(C.NO_ACTIVE_SERVER)
    if check_point > C.USER_LOGIN_CHECK:
        if state.get(C.ACTIVE_USER_KEY) is None:
            raise Exception(C.NO_ACTIVE_USER)
    if check_point == C.JOIN_GROUP_CHECK:
        if state.get(C.ACTIVE_USER_KEY) is None:
            raise Exception(C.NO_ACTIVE_USER)


def manage_exits(stub=None, channel=None, user_id=None, group_id=None):
    if channel is not None:
        if state.get(C.ACTIVE_USER_KEY) is not None:
            manage_exits(stub=state.get(C.STUB), user_id=user_id)
        state[C.ACTIVE_CHANNEL] = None
        state[C.SERVER_ONLINE] = False
        state[C.SERVER_CONNECTION_STRING] = None
        state[C.STUB] = None
        channel.close()
        display_manager.info(
            f"terminated {state[C.SERVER_CONNECTION_STRING]} successfully")
    if user_id is not None and group_id is None:
        if state.get(C.ACTIVE_USER_KEY) is not None and state.get(C.ACTIVE_USER_KEY) == user_id:
            if state.get(C.ACTIVE_GROUP_KEY) is not None:
                manage_exits(stub, user_id=user_id,
                             group_id=state[C.ACTIVE_GROUP_KEY])
            stub.LogoutUser(chat_system_pb2.User(user_id=user_id))
            display_manager.info(f"Logout successful for user_id {user_id}")
            state[C.ACTIVE_USER_KEY] = None
    if user_id is not None and group_id is not None:
        if state.get(C.ACTIVE_USER_KEY) is not None and state.get(C.ACTIVE_USER_KEY) == user_id \
                and state.get(C.ACTIVE_GROUP_KEY) is not None and state.get(C.ACTIVE_GROUP_KEY) == group_id:
            stub.ExitGroup(chat_system_pb2.Group(
                group_id=group_id, user_id=user_id))
            display_manager.info(
                f"{user_id} successfully exited group {group_id}")
            state[C.ACTIVE_GROUP_KEY] = None


def join_server(server_string):
    if server_string == state.get(C.SERVER_CONNECTION_STRING):
        display_manager.info(f'Already connected to server {server_string}')
        return state.get(C.STUB)
    channel = state.get(C.ACTIVE_CHANNEL)
    manage_exits(channel)
    display_manager.info(f"Trying to connect to server: {server_string}")
    channel = grpc.insecure_channel(server_string)
    stub = chat_system_pb2_grpc.ChatServerStub(channel)
    server_status = stub.HealthCheck(chat_system_pb2.BlankMessage())
    if server_status.status is True:
        display_manager.info("Server connection active")
        state[C.ACTIVE_CHANNEL] = channel
        state[C.SERVER_ONLINE] = True
        state[C.SERVER_CONNECTION_STRING] = server_string
        state[C.STUB] = stub
    return stub


def get_user_connection(stub, user_id):
    try:
        check_state(C.USER_LOGIN_CHECK)
        if state.get(C.ACTIVE_USER_KEY) is not None:
            if state.get(C.ACTIVE_USER_KEY) != user_id:
                manage_exits(stub, user_id=state[C.ACTIVE_USER_KEY])
            else:
                display_manager.info(f"User {user_id} already logged in")
                return
        status = stub.GetUser(chat_system_pb2.User(user_id=user_id))
        if status.status is True:
            display_manager.info(f"Login successful with user_id {user_id}")
            state[C.ACTIVE_USER_KEY] = user_id
        else:
            raise Exception("Login not successful")
    except grpc.RpcError as rpcError:
        raise rpcError
    except Exception as ex:
        raise ex


def enter_group_chat(stub, group_id):
    try:
        check_state(C.JOIN_GROUP_CHECK)
        current_group_id = state.get(C.ACTIVE_GROUP_KEY)
        user_id = state.get(C.ACTIVE_USER_KEY)
        if current_group_id is not None and current_group_id != group_id:
            manage_exits(stub, user_id=user_id, group_id=current_group_id)
        elif current_group_id == group_id:
            display_manager.info(f"User {user_id} already in group {group_id}")
            return
        group_details = stub.GetGroup(
            chat_system_pb2.Group(group_id=group_id, user_id=user_id))
        group_data = MessageToJson(group_details)
        if group_details.status is True:
            display_manager.info(f"Successfully joined group {group_id}")
            state[C.ACTIVE_GROUP_KEY] = group_id
            state[C.GROUP_DATA] = group_data
        else:
            raise Exception("Entering group not successful")
    except Exception as ex:
        print(f"Error: {ex}. Please try again.")
        raise ex


def get_timestamp() -> int:
    """
    returns UTC timestamp in microseconds
    """
    return int(datetime.now().timestamp() * 1_000_000)


def get_unique_id() -> str:
    """
    returns unique string generated by MD5 hash
    """
    return str(uuid.uuid4())


def build_message(message_text):
    message = chat_system_pb2.Message(
        group_id=state.get(C.ACTIVE_GROUP_KEY),
        user_id=state.get(C.ACTIVE_USER_KEY),
        creation_time=get_timestamp(),
        text=message_text,
        message_id=get_unique_id()
    )

    return message


def post_message(stub, message_text):
    try:
        check_state(C.SENT_MESSAGE_CHECK)
        message = build_message(message_text)
        status = stub.PostMessage(message)
        if status.status is True:
            display_manager.info("Message sent successfuly")
        else:
            display_manager.error(
                f"Message senidng failed. Response from server: {status.statusMessage}")
    except Exception as ex:
        raise ex

    return C.EXIT_CODE


def run():
    status = None
    stub = None
    while True:
        # display_manager.write("hello", "world")
        user_input = display_manager.read()
        if ' ' in user_input:
            command = user_input.split(' ')[0].strip()
        else:
            command = user_input
        try:
            if command in C.CONNECTION_COMMANDS:
                server_string = user_input[2:].strip()
                if server_string == '':
                    server_string = C.DEFAULT_SERVER_CONNECTION_STRING
                stub = join_server(server_string)
            elif command in C.EXIT_APP_COMMANDS:
                manage_exits(channel=state.get(C.ACTIVE_CHANNEL))
                break
            elif command in C.LOGIN_COMMANDS:
                user_id = user_input[2:].strip()
                if len(user_id) < 1:
                    raise Exception("Invalide user_id")
                get_user_connection(stub, user_id)
            elif command in C.JOIN_GROUP_COMMANDS:
                group_id = user_input[2:].strip()
                if len(group_id) < 1:
                    raise Exception("Invalide group_id")
                enter_group_chat(stub, group_id)
            else:
                message_text = user_input
                post_message(stub, message_text)
        except grpc.RpcError as rpcError:
            display_manager.error(f"grpc exception: {rpcError}")
        except Exception as e:
            display_manager.error(
                f"Error: {e}")


if __name__ == "__main__":

    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)
    run()
